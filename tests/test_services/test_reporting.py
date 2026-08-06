from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.incidents import (
    AnalysisMode,
    Claim,
    EvidenceReference,
    IncidentWindow,
    ReportNarrative,
    ReportRequest,
    VideoMemory,
)
from src.services.reporting import OpenAIReportService, ReportServiceError


def _request() -> ReportRequest:
    return ReportRequest(
        incident_id="INC-REPORT",
        video_memory=VideoMemory(
            global_scene="Road scene",
            incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
            claims=[Claim(claim_id="claim-1", text="Vehicle brakes", evidence_ids=["frame-1"])],
            evidence=[
                EvidenceReference(
                    evidence_id="frame-1",
                    kind="frame",
                    artifact_uri="private://frame.jpg",
                    timestamp_s=2,
                )
            ],
            analysis_mode=AnalysisMode.SINGLE_REQUEST,
        ),
    )


def _narrative(evidence_ids: list[str] | None = None) -> ReportNarrative:
    return ReportNarrative(
        summary="A vehicle event occurred.",
        timeline="The event occurred near 2 seconds.",
        video_observations="The vehicle appears to brake.",
        log_findings="No log data was supplied.",
        alignment="The claim is unverified.",
        hypothesized_causes="A possible cause remains unconfirmed.",
        evidence_ids=evidence_ids or ["frame-1"],
    )


@pytest.mark.asyncio
async def test_openai_report_uses_one_structured_output_call() -> None:
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=_narrative())))
    )
    service = OpenAIReportService(model="gpt-test", client=client)

    result = await service.build_narrative(_request())

    assert result == _narrative()
    client.responses.parse.assert_awaited_once()
    assert client.responses.parse.await_args.kwargs["text_format"] is ReportNarrative


@pytest.mark.asyncio
async def test_report_rejects_invented_evidence_id() -> None:
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=_narrative(["invented"]))))
    )

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == "REPORT_EVIDENCE_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "side_effect", "expected_code"),
    [
        (SimpleNamespace(output_parsed=None, output_text="not-json"), None, "REPORT_STRUCTURED_OUTPUT_INVALID"),
        (None, TimeoutError("model timeout"), "OPENAI_REPORT_FAILED"),
    ],
)
async def test_report_maps_malformed_and_timeout_errors(
    response: object | None,
    side_effect: Exception | None,
    expected_code: str,
) -> None:
    parse = AsyncMock(return_value=response, side_effect=side_effect)
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == expected_code
    assert "model timeout" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_report_cannot_overwrite_backend_timestamp() -> None:
    payload = _narrative().model_dump()
    payload["t_start"] = 999
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == "REPORT_STRUCTURED_OUTPUT_INVALID"
