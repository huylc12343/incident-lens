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

from src.models.incidents import VerificationRequest, VerificationResult
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
            log_evidence_summary=request.log_evidence_summary,
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
            response = await self._client.responses.parse(
                model=self._model,
                input=[{"role": "user", "content": prompt.text}],
                text_format=VerificationResult,
                temperature=self._temperature,
                timeout=self._timeout_s,
            )
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
    returned_ids = [item.claim_id for item in result.results]
    if returned_ids != expected_ids:
        raise VerificationServiceError(
            "VERIFICATION_RESULT_MISMATCH",
            "verification must return exactly one ordered result for every claim",
        )
    allowed_evidence = set(request.log_evidence_summary.evidence_ids)
    normalized_results = [
        item.model_copy(
            update={"evidence_ids": list(dict.fromkeys(eid for eid in item.evidence_ids if eid in allowed_evidence))}
        )
        for item in result.results
    ]
    return result.model_copy(update={"results": normalized_results})
