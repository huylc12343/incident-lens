import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import Settings
from src.models.incidents import (
    AnalysisMode,
    IncidentWindow,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    ReanalysisRequest,
    VideoMemory,
)
from src.services.incident_runtime import ProviderClients, _build_vlm
from src.services.vlm import QwenNativeVideoVLMService, VLMServiceError


@pytest.mark.asyncio
async def test_qwen_sends_native_video_to_dashscope_chat_completions() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )
    qwen_payload = memory.model_dump()
    qwen_payload.pop("analysis_mode")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(qwen_payload)))],
                    )
                )
            )
        )
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.analysis_mode == AnalysisMode.NATIVE_VIDEO
    call = client.chat.completions.create.await_args.kwargs
    assert call["model"] == "qwen3-vl-flash"
    assert call["messages"][0]["content"][0] == {
        "type": "video_url",
        "video_url": {"url": request.normalized_video_uri},
        "fps": 2.0,
    }
    assert call["response_format"] == {"type": "json_object"}
    structured_prompt = call["messages"][0]["content"][1]["text"]
    assert "<json_schema>" in structured_prompt
    assert '"analysis_mode"' in structured_prompt
    assert "extra_body" not in call


@pytest.mark.asyncio
async def test_qwen_reanalysis_injects_backend_owned_patch_fields() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        revision=3,
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"claims": []})))],
                    )
                )
            )
        )
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = ReanalysisRequest(
        incident_id="INC-QWEN",
        prompt=PromptEnvelope(text="Phân tích lại claim."),
        target_claim_ids=["claim-01"],
        incident_window=memory.incident_window,
        current_memory=memory,
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
    )

    result = await service.reanalyze_claims(request)

    assert result.target_claim_ids == ["claim-01"]
    assert result.base_revision == 3


def test_qwen_runtime_allows_base64_mode_without_public_artifact_url() -> None:
    settings = Settings(
        vlm_provider="qwen",
        vlm_input_mode="native_video",
        dashscope_api_key="test-key",
        qwen_artifact_url_base="",
    )

    service = _build_vlm(settings, ProviderClients(qwen=SimpleNamespace()))

    assert isinstance(service, QwenNativeVideoVLMService)


def test_qwen_encodes_small_local_video_as_data_url(tmp_path) -> None:
    video = tmp_path / "incident" / "normalized.mp4"
    video.parent.mkdir()
    video.write_bytes(b"small-video")
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=SimpleNamespace(),
        artifact_dir=str(tmp_path),
    )

    assert service._public_video_url(str(video)).startswith("data:video/mp4;base64,")


def test_qwen_requires_public_url_for_large_local_video(tmp_path) -> None:
    video = tmp_path / "normalized.mp4"
    video.write_bytes(b"too-large")
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=SimpleNamespace(),
        artifact_dir=str(tmp_path),
        base64_max_video_bytes=1,
    )

    with pytest.raises(VLMServiceError) as exc_info:
        service._public_video_url(str(video))

    assert exc_info.value.code == "QWEN_PUBLIC_VIDEO_URL_REQUIRED"
