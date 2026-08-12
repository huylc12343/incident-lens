from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

from src.models.incidents import (
    Claim,
    ClaimLogSummary,
    ClaimVerification,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from src.services.verification import OpenAIVerificationService, VerificationServiceError


def _request() -> VerificationRequest:
    return VerificationRequest(
        incident_id="INC-VERIFY",
        claims=[Claim(claim_id="claim-1", text="Vehicle brakes at 7.5 seconds", timestamp_s=7.5)],
        claim_log_summaries=[
            ClaimLogSummary(
                claim_id="claim-1",
                claim_timestamp_s=7.5,
                nearest_timestamp_s=7.5,
                timestamp_distance_s=0,
                within_tolerance=True,
                allowed_evidence_ids=["log-row:7.5"],
                summary="Brake tăng gần timestamp của claim.",
            )
        ],
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
                evidence_ids=["log-row:7.5"],
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
async def test_verification_marks_missing_claim_result_unverified() -> None:
    invalid = VerificationResult(results=[])
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=invalid)))
    )

    result = await OpenAIVerificationService(model="gpt-test", client=client).verify(_request())

    assert [item.claim_id for item in result.results] == ["claim-1"]
    assert result.results[0].status == VerificationStatus.UNVERIFIED
    assert result.results[0].evidence_ids == []
    assert "không trả về duy nhất một kết quả" in result.results[0].reason


@pytest.mark.asyncio
async def test_verification_restores_claim_order() -> None:
    request = _request().model_copy(
        update={
            "claims": [
                Claim(claim_id="claim-1", text="Xe phanh", timestamp_s=7.5),
                Claim(claim_id="claim-2", text="Xe dừng", timestamp_s=8.0),
            ],
            "claim_log_summaries": [
                _request().claim_log_summaries[0],
                ClaimLogSummary(
                    claim_id="claim-2",
                    claim_timestamp_s=8.0,
                    nearest_timestamp_s=8.0,
                    timestamp_distance_s=0,
                    within_tolerance=True,
                    allowed_evidence_ids=["log-row:8"],
                    summary="Xe gần như đứng yên.",
                ),
            ],
        }
    )
    reordered = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-2",
                status=VerificationStatus.SUPPORTED,
                reason="Tốc độ gần 0 km/h.",
                evidence_ids=["log-row:8"],
            ),
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Brake tăng.",
                evidence_ids=["log-row:7.5"],
            ),
        ]
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=reordered)))
    )

    result = await OpenAIVerificationService(model="gpt-test", client=client).verify(request)

    assert [item.claim_id for item in result.results] == ["claim-1", "claim-2"]
    assert all(item.status == VerificationStatus.SUPPORTED for item in result.results)


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

    assert result.results[0].status == VerificationStatus.UNVERIFIED
    assert result.results[0].evidence_ids == []


@pytest.mark.asyncio
async def test_verification_forces_unverified_when_log_is_outside_tolerance() -> None:
    request = _request().model_copy(
        update={
            "claim_log_summaries": [
                ClaimLogSummary(
                    claim_id="claim-1",
                    claim_timestamp_s=7.5,
                    nearest_timestamp_s=6,
                    timestamp_distance_s=1.5,
                    within_tolerance=False,
                    summary="Không có mẫu đủ gần.",
                )
            ]
        }
    )
    model_result = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Không thấy brake.",
            )
        ]
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=model_result)))
    )

    result = await OpenAIVerificationService(model="gpt-test", client=client).verify(request)

    assert result.results[0].status == VerificationStatus.UNVERIFIED
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
