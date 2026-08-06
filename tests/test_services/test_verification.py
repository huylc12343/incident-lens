from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

from src.models.incidents import (
    Claim,
    ClaimVerification,
    LogEvidenceSummary,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from src.services.verification import OpenAIVerificationService, VerificationServiceError


def _request() -> VerificationRequest:
    return VerificationRequest(
        incident_id="INC-VERIFY",
        claims=[Claim(claim_id="claim-1", text="Vehicle brakes at 7.5 seconds", timestamp_s=7.5)],
        log_evidence_summary=LogEvidenceSummary(
            metrics={"brake_rise_time": 7.5},
            evidence_ids=["log-evidence:7.5:brake_rise"],
        ),
        timestamp_tolerance_s=0.5,
    )


@pytest.mark.asyncio
async def test_openai_verification_uses_structured_output() -> None:
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Brake rise matches the claim timestamp.",
                evidence_ids=["log-evidence:7.5:brake_rise"],
            )
        ]
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=verification)))
    )
    service = OpenAIVerificationService(model="gpt-test", client=client)

    result = await service.verify(_request())

    assert result == verification
    call = client.responses.parse.await_args.kwargs
    assert call["text_format"] is VerificationResult
    assert "claim-1" in call["input"][0]["content"]


@pytest.mark.asyncio
async def test_verification_rejects_missing_or_reordered_claim_results() -> None:
    invalid = VerificationResult(results=[])
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=invalid)))
    )

    with pytest.raises(VerificationServiceError) as exc_info:
        await OpenAIVerificationService(model="gpt-test", client=client).verify(_request())

    assert exc_info.value.code == "VERIFICATION_RESULT_MISMATCH"


@pytest.mark.asyncio
async def test_verification_removes_invented_log_evidence_without_discarding_result() -> None:
    invalid = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Unsupported evidence reference.",
                evidence_ids=["invented-evidence"],
            )
        ]
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=invalid)))
    )

    result = await OpenAIVerificationService(model="gpt-test", client=client).verify(_request())

    assert result.results[0].status == VerificationStatus.SUPPORTED
    assert result.results[0].evidence_ids == []


@pytest.mark.asyncio
async def test_verification_maps_openai_sdk_failure() -> None:
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(side_effect=OSError("offline"))))

    with pytest.raises(VerificationServiceError) as exc_info:
        await OpenAIVerificationService(model="gpt-test", client=client).verify(_request())

    assert exc_info.value.code == "OPENAI_VERIFICATION_FAILED"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            AuthenticationError(
                "invalid key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "OPENAI_AUTHENTICATION_FAILED",
        ),
        (
            RateLimitError(
                "quota",
                response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "OPENAI_RATE_LIMITED",
        ),
        (APITimeoutError(httpx.Request("POST", "https://api.openai.com")), "OPENAI_VERIFICATION_TIMEOUT"),
        (
            APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
            "OPENAI_CONNECTION_FAILED",
        ),
    ],
)
async def test_verification_classifies_common_openai_failures(error: Exception, expected_code: str) -> None:
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(side_effect=error)))

    with pytest.raises(VerificationServiceError) as exc_info:
        await OpenAIVerificationService(model="gpt-test", client=client).verify(_request())

    assert exc_info.value.code == expected_code
