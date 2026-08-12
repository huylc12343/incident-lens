"""OpenAI-backed structured verification of video claims against log evidence."""

from __future__ import annotations

import json
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from src.models.incidents import ClaimVerification, VerificationRequest, VerificationResult, VerificationStatus
from src.prompts.verification import build_verification_prompt
from src.services.model_observability import ModelActivityRegistry


class VerificationServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OpenAIVerificationService:
    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        prompt_version: str = "v1",
        observability: ModelActivityRegistry | None = None,
    ) -> None:
        if not model.strip() or not prompt_version.strip():
            raise ValueError("model and prompt_version must not be blank")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        self._client = client if client is not None else AsyncOpenAI(api_key=api_key)
        self._model = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._prompt_version = prompt_version
        self._observability = observability

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        prompt = build_verification_prompt(
            claims=request.claims,
            claim_log_summaries=request.claim_log_summaries,
            timestamp_tolerance_s=request.timestamp_tolerance_s,
            version=self._prompt_version,
        )
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=request.incident_id,
                step="verification",
                operation="claim_verification",
                description="Đối chiếu các claim từ video với bằng chứng log.",
                provider="openai",
                model=self._model,
                metadata={"claim_count": len(request.claims)},
            )
        try:
            request_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": [
                    {"role": "system", "content": prompt.text},
                    {"role": "user", "content": _prompt_context_text(prompt.context)},
                ],
                "text_format": VerificationResult,
                "timeout": self._timeout_s,
            }
            if not self._model.startswith("gpt-5"):
                request_kwargs["temperature"] = self._temperature
            response = await self._client.responses.parse(**request_kwargs)
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = json.loads(getattr(response, "output_text", ""))
            result = VerificationResult.model_validate(parsed)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "VERIFICATION_STRUCTURED_OUTPUT_INVALID", response)
            raise VerificationServiceError("VERIFICATION_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except AuthenticationError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_AUTHENTICATION_FAILED", response)
            raise VerificationServiceError(
                "OPENAI_AUTHENTICATION_FAILED",
                "OpenAI authentication failed; check OPENAI_API_KEY",
            ) from exc
        except PermissionDeniedError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_PERMISSION_DENIED", response)
            raise VerificationServiceError(
                "OPENAI_PERMISSION_DENIED",
                "OpenAI denied access to the configured verification model",
            ) from exc
        except RateLimitError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_RATE_LIMITED", response)
            raise VerificationServiceError(
                "OPENAI_RATE_LIMITED",
                "OpenAI rate limit or quota was exceeded",
                retryable=True,
            ) from exc
        except APITimeoutError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_VERIFICATION_TIMEOUT", response)
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_TIMEOUT",
                "OpenAI verification timed out",
                retryable=True,
            ) from exc
        except APIConnectionError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_CONNECTION_FAILED", response)
            raise VerificationServiceError(
                "OPENAI_CONNECTION_FAILED",
                "Could not connect to OpenAI",
                retryable=True,
            ) from exc
        except (BadRequestError, NotFoundError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_VERIFICATION_REQUEST_INVALID", response)
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_REQUEST_INVALID",
                "OpenAI rejected the verification model or structured request",
            ) from exc
        except Exception as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_VERIFICATION_FAILED", response)
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_FAILED",
                "OpenAI verification failed unexpectedly",
                retryable=True,
            ) from exc
        try:
            result = _validate_verification_result(request, result)
        except VerificationServiceError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, exc.code, response)
            raise
        if activity_id is not None:
            self._observability.complete(activity_id, response)
        return result


def _validate_verification_result(request: VerificationRequest, result: VerificationResult) -> VerificationResult:
    expected_ids = [claim.claim_id for claim in request.claims]
    summaries = {summary.claim_id: summary for summary in request.claim_log_summaries}
    if list(summaries) != expected_ids:
        raise VerificationServiceError(
            "VERIFICATION_SUMMARY_MISMATCH",
            "verification requires exactly one ordered log summary for every claim",
        )

    returned_by_id: dict[str, list[ClaimVerification]] = {}
    for item in result.results:
        returned_by_id.setdefault(item.claim_id, []).append(item)
    ordered_results = []
    for claim_id in expected_ids:
        matches = returned_by_id.get(claim_id, [])
        if len(matches) == 1:
            ordered_results.append(matches[0])
        else:
            ordered_results.append(
                ClaimVerification(
                    claim_id=claim_id,
                    status=VerificationStatus.UNVERIFIED,
                    reason="Verifier không trả về duy nhất một kết quả hợp lệ cho claim này.",
                    evidence_ids=[],
                )
            )

    normalized_results = []
    for item in ordered_results:
        summary = summaries[item.claim_id]
        if not summary.within_tolerance:
            normalized_results.append(
                item.model_copy(
                    update={
                        "status": VerificationStatus.UNVERIFIED,
                        "reason": "Không có evidence log đủ gần timestamp của claim.",
                        "evidence_ids": [],
                    }
                )
            )
            continue
        allowed_evidence = set(summary.allowed_evidence_ids)
        evidence_ids = list(dict.fromkeys(eid for eid in item.evidence_ids if eid in allowed_evidence))
        if item.status == VerificationStatus.UNVERIFIED or not evidence_ids:
            normalized_results.append(
                item.model_copy(
                    update={
                        "status": VerificationStatus.UNVERIFIED,
                        "reason": (
                            item.reason
                            if item.status == VerificationStatus.UNVERIFIED
                            else "Không có evidence log trực tiếp hợp lệ để xác nhận hoặc bác bỏ claim."
                        ),
                        "evidence_ids": [],
                    }
                )
            )
            continue
        normalized_results.append(
            item.model_copy(update={"evidence_ids": evidence_ids})
        )
    return result.model_copy(update={"results": normalized_results})


def _prompt_context_text(context: dict[str, Any]) -> str:
    serialized = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"<context>{serialized}</context>"
