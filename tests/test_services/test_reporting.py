from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.incidents import (
    AccidentType,
    AnalysisMode,
    Claim,
    EvidenceReference,
    IncidentWindow,
    PromptEnvelope,
    ReanalysisRequest,
    ReportModelOutput,
    ReportRequest,
    VideoMemory,
    VideoMemoryPatch,
)
from src.services.reporting import OpenAIReportService, ReportServiceError


def _request() -> ReportRequest:
    return ReportRequest(
        incident_id="INC-REPORT",
        video_memory=VideoMemory(
            global_scene="Road scene",
            incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
            claims=[
                Claim(
                    claim_id="claim-1",
                    text="Vehicle brakes",
                    timestamp_s=2,
                    evidence=[EvidenceReference(evidence_id="frame-1", timestamp_s=2)],
                )
            ],
            analysis_mode=AnalysisMode.SINGLE_REQUEST,
        ),
    )


def _narrative() -> ReportModelOutput:
    return ReportModelOutput(
        type_of_accident=AccidentType.SIDE_COLLISION,
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        representative_timestamp_s=2,
        timeline="The event occurred near 2 seconds.",
        video_observations="The vehicle appears to brake.",
        hypothesized_causes="A possible cause remains unconfirmed.",
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
    call = client.responses.parse.await_args.kwargs
    assert call["text_format"] is ReportModelOutput
    assert [message["role"] for message in call["input"]] == ["system", "user"]
    assert "INC-REPORT" not in call["input"][0]["content"]
    assert "INC-REPORT" in call["input"][1]["content"]


@pytest.mark.asyncio
async def test_gpt5_report_omits_unsupported_temperature() -> None:
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=_narrative())))
    )

    await OpenAIReportService(model="gpt-5.6-luna", client=client).build_narrative(_request())

    call = client.responses.parse.await_args.kwargs
    assert "temperature" not in call
    assert [message["role"] for message in call["input"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_memory_reanalysis_uses_text_only_structured_request() -> None:
    memory = _request().video_memory
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[memory.claims[0].model_copy(update={"text": "Xe đã phanh."})],
        base_revision=memory.revision,
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=patch)))
    )
    service = OpenAIReportService(model="gpt-test", client=client)

    result = await service.reanalyze_claims(
        ReanalysisRequest(
            incident_id="INC-REPORT",
            prompt=PromptEnvelope(
                text="Memory-only rules",
                context={"reviewer_feedback": "Sửa claim"},
            ),
            target_claim_ids=["claim-1"],
            incident_window=memory.incident_window,
            current_memory=memory,
        )
    )

    assert result == patch
    call = client.responses.parse.await_args.kwargs
    assert call["text_format"] is VideoMemoryPatch
    assert [message["role"] for message in call["input"]] == ["system", "user"]
    assert "input_image" not in str(call["input"])
    assert "video_url" not in str(call["input"])


@pytest.mark.asyncio
async def test_report_rejects_backend_owned_fields() -> None:
    payload = _narrative().model_dump()
    payload["summary"] = "Model must not own this field"
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == "REPORT_STRUCTURED_OUTPUT_INVALID"


@pytest.mark.asyncio
async def test_report_accepts_new_accident_type_taxonomy() -> None:
    payload = _narrative().model_dump(mode="json")
    payload["type_of_accident"] = "side_collision"
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )

    result = await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert result.type_of_accident == AccidentType.SIDE_COLLISION


@pytest.mark.asyncio
async def test_report_requires_accident_type() -> None:
    payload = _narrative().model_dump(mode="json")
    del payload["type_of_accident"]
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == "REPORT_STRUCTURED_OUTPUT_INVALID"


@pytest.mark.asyncio
async def test_report_requires_incident_geometry() -> None:
    payload = _narrative().model_dump(mode="json")
    del payload["incident_window"]
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=payload)))
    )

    with pytest.raises(ReportServiceError) as exc_info:
        await OpenAIReportService(model="gpt-test", client=client).build_narrative(_request())

    assert exc_info.value.code == "REPORT_STRUCTURED_OUTPUT_INVALID"


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
