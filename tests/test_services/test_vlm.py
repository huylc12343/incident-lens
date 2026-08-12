from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AuthenticationError

from src.models.incidents import (
    AnalysisMode,
    IncidentWindow,
    PromptEnvelope,
    ReanalysisRequest,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
)
from src.services.model_observability import ModelActivityRegistry
from src.services.vlm import OpenAIVLMService, VLMServiceError


def _memory(mode: AnalysisMode) -> VideoMemory:
    return VideoMemory(
        global_scene="A road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        analysis_mode=mode,
    )


def _openai_request(tmp_path: Path) -> TimestampedFramesAnalysisRequest:
    frames = []
    for index in range(2):
        path = tmp_path / f"frame-{index}.jpg"
        path.write_bytes(f"image-{index}".encode())
        frames.append(
            TimestampedFrame(
                frame_id=f"frame-{index}",
                sequence_index=index,
                timestamp_s=float(index),
                delta_from_previous_s=0 if index == 0 else 1,
                image_uri=str(path),
            )
        )
    return TimestampedFramesAnalysisRequest(
        incident_id="INC-OPENAI",
        prompt=PromptEnvelope(text="Analyze frames"),
        manifest=VideoSequenceManifest(
            frames=frames,
            source_video_uri="video.mp4",
            duration_s=2,
        ),
    )


@pytest.mark.asyncio
async def test_openai_sends_all_ordered_frames_in_one_request(tmp_path: Path) -> None:
    observability = ModelActivityRegistry()
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(
                return_value=SimpleNamespace(
                    output_parsed=_memory(AnalysisMode.SINGLE_REQUEST),
                    usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120),
                )
            )
        )
    )
    service = OpenAIVLMService(
        model="gpt-test", client=client, max_images_per_request=10, observability=observability
    )

    result = await service.analyze_video(_openai_request(tmp_path))

    assert result.analysis_mode == AnalysisMode.SINGLE_REQUEST
    client.responses.parse.assert_awaited_once()
    call = client.responses.parse.await_args.kwargs
    assert [message["role"] for message in call["input"]] == ["system", "user"]
    assert call["input"][0]["content"] == "Analyze frames"
    content = call["input"][1]["content"]
    assert [item["type"] for item in content] == [
        "input_text",
        "input_text",
        "input_image",
        "input_text",
        "input_image",
    ]
    assert "sequence_index=0" in content[1]["text"]
    assert "sequence_index=1" in content[3]["text"]
    assert content[2]["image_url"].startswith("data:image/jpeg;base64,")
    assert call["text_format"] is VideoMemory
    activity = observability.list("INC-OPENAI")[0]
    assert activity.status == "completed"
    assert activity.model == "gpt-test"
    assert activity.metadata["image_count"] == 2
    assert activity.usage is not None
    assert activity.usage.total_tokens == 120


@pytest.mark.asyncio
async def test_openai_omits_temperature_for_gpt_5_models(tmp_path: Path) -> None:
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(return_value=SimpleNamespace(output_parsed=_memory(AnalysisMode.SINGLE_REQUEST)))
        )
    )

    await OpenAIVLMService(model="gpt-5.6-luna", client=client).analyze_video(_openai_request(tmp_path))

    assert "temperature" not in client.responses.parse.await_args.kwargs


@pytest.mark.asyncio
async def test_openai_rejects_frame_overflow_before_sdk_call(tmp_path: Path) -> None:
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock()))
    service = OpenAIVLMService(model="gpt-test", client=client, max_images_per_request=1)

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(_openai_request(tmp_path))

    assert exc_info.value.code == "OPENAI_FRAME_LIMIT_EXCEEDED"
    client.responses.parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_openai_reanalysis_uses_patch_schema_and_validates_targets(tmp_path: Path) -> None:
    request = _openai_request(tmp_path)
    patch = VideoMemoryPatch(target_claim_ids=["claim-1"], base_revision=1)
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock(return_value=SimpleNamespace(output_parsed=patch)))
    )
    service = OpenAIVLMService(model="gpt-test", client=client)
    reanalysis = ReanalysisRequest(
        incident_id="INC-OPENAI",
        prompt=PromptEnvelope(text="Review claim"),
        target_claim_ids=["claim-1"],
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        current_memory=_memory(AnalysisMode.SINGLE_REQUEST),
        frame_manifest=request.manifest,
    )

    result = await service.reanalyze_claims(reanalysis)

    assert result.target_claim_ids == ["claim-1"]
    assert client.responses.parse.await_args.kwargs["text_format"] is VideoMemoryPatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "side_effect", "expected_code"),
    [
        (SimpleNamespace(output_parsed={"invalid": "memory"}), None, "VLM_STRUCTURED_OUTPUT_INVALID"),
        (None, TimeoutError("provider timeout with sk-secret"), "OPENAI_VIDEO_ANALYSIS_FAILED"),
    ],
)
async def test_openai_maps_malformed_and_timeout_errors(
    tmp_path: Path,
    response: object | None,
    side_effect: Exception | None,
    expected_code: str,
) -> None:
    client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(return_value=response, side_effect=side_effect)))

    with pytest.raises(VLMServiceError) as exc_info:
        await OpenAIVLMService(model="gpt-test", client=client).analyze_video(_openai_request(tmp_path))

    assert exc_info.value.code == expected_code


@pytest.mark.asyncio
async def test_openai_maps_authentication_error_to_safe_code(tmp_path: Path) -> None:
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(side_effect=AuthenticationError("invalid API key", response=response, body={}))
        )
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await OpenAIVLMService(model="gpt-test", client=client).analyze_video(_openai_request(tmp_path))

    assert exc_info.value.code == "OPENAI_AUTHENTICATION_FAILED"
