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

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        prompt = build_verification_prompt(
            claims=request.claims,
            log_evidence_summary=request.log_evidence_summary,
            timestamp_tolerance_s=request.timestamp_tolerance_s,
            version=self._prompt_version,
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
            raise VerificationServiceError("VERIFICATION_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except AuthenticationError as exc:
            raise VerificationServiceError(
                "OPENAI_AUTHENTICATION_FAILED",
                "OpenAI authentication failed; check OPENAI_API_KEY",
            ) from exc
        except PermissionDeniedError as exc:
            raise VerificationServiceError(
                "OPENAI_PERMISSION_DENIED",
                "OpenAI denied access to the configured verification model",
            ) from exc
        except RateLimitError as exc:
            raise VerificationServiceError(
                "OPENAI_RATE_LIMITED",
                "OpenAI rate limit or quota was exceeded",
                retryable=True,
            ) from exc
        except APITimeoutError as exc:
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_TIMEOUT",
                "OpenAI verification timed out",
                retryable=True,
            ) from exc
        except APIConnectionError as exc:
            raise VerificationServiceError(
                "OPENAI_CONNECTION_FAILED",
                "Could not connect to OpenAI",
                retryable=True,
            ) from exc
        except (BadRequestError, NotFoundError) as exc:
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_REQUEST_INVALID",
                "OpenAI rejected the verification model or structured request",
            ) from exc
        except Exception as exc:
            raise VerificationServiceError(
                "OPENAI_VERIFICATION_FAILED",
                "OpenAI verification failed unexpectedly",
                retryable=True,
            ) from exc
        _validate_verification_result(request, result)
        return result


def _validate_verification_result(request: VerificationRequest, result: VerificationResult) -> None:
    expected_ids = [claim.claim_id for claim in request.claims]
    returned_ids = [item.claim_id for item in result.results]
    if returned_ids != expected_ids:
        raise VerificationServiceError(
            "VERIFICATION_RESULT_MISMATCH",
            "verification must return exactly one ordered result for every claim",
        )
    allowed_evidence = set(request.log_evidence_summary.evidence_ids)
    returned_evidence = {evidence_id for item in result.results for evidence_id in item.evidence_ids}
    if not returned_evidence.issubset(allowed_evidence):
        raise VerificationServiceError(
            "VERIFICATION_EVIDENCE_INVALID",
            "verification references evidence not supplied in the log summary",
        )
