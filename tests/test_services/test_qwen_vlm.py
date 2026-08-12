import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import PermissionDeniedError

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
from src.services.model_observability import ModelActivityRegistry, ModelRequestBudgetError
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


@pytest.mark.asyncio
async def test_qwen_retries_invalid_structured_output_with_validation_feedback() -> None:
    invalid = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 0, "t_end": 0},
    }
    valid = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 1, "t_end": 2},
    }
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        for payload in (invalid, valid)
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses)))
    )
    observability = ModelActivityRegistry()
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
        observability=observability,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-RETRY",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.incident_window.t_end == 2
    assert client.chat.completions.create.await_count == 2
    retry_prompt = client.chat.completions.create.await_args_list[1].kwargs["messages"][0]["content"][1]["text"]
    assert "incident_window.t_end" in retry_prompt
    assert "greater_than" in retry_prompt
    activities = observability.list("INC-QWEN-RETRY")
    assert [item.metadata["structured_output_attempt"] for item in activities] == [1, 2]
    assert [item.status for item in activities] == ["failed", "completed"]


@pytest.mark.asyncio
async def test_qwen_reports_invalid_output_after_retry_budget_is_exhausted() -> None:
    invalid = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 0, "t_end": 0},
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(invalid)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-INVALID",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(request)

    assert exc_info.value.code == "VLM_STRUCTURED_OUTPUT_INVALID"
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_qwen_default_makes_only_one_request_for_invalid_structured_output() -> None:
    invalid = {"global_scene": "Đường giao thông.", "incident_window": {"t_start": 0, "t0": 0, "t_end": 0}}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(invalid)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-SINGLE-ATTEMPT",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(request)

    assert exc_info.value.code == "VLM_STRUCTURED_OUTPUT_INVALID"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_qwen_classifies_exhausted_free_tier_quota() -> None:
    response = httpx.Response(
        403,
        request=httpx.Request("POST", "https://dashscope.example.test/chat/completions"),
    )
    provider_error = PermissionDeniedError(
        "The free quota has been exhausted.",
        response=response,
        body={
            "error": {
                "type": "AllocationQuota.FreeTierOnly",
                "code": "AllocationQuota.FreeTierOnly",
            }
        },
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=provider_error)))
    )
    observability = ModelActivityRegistry()
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        observability=observability,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-QUOTA",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(request)

    assert exc_info.value.code == "QWEN_QUOTA_EXHAUSTED"
    assert exc_info.value.retryable is False
    assert "free quota" in str(exc_info.value)
    assert observability.list("INC-QWEN-QUOTA")[0].error_code == "QWEN_QUOTA_EXHAUSTED"


@pytest.mark.asyncio
@pytest.mark.parametrize("model_status", ["supported", "verified_by_video"])
async def test_qwen_forces_video_claims_to_unverified_before_schema_validation(model_status: str) -> None:
    payload = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 1, "t_end": 2},
        "claims": [
            {
                "claim_id": "claim-01",
                "text": "Xe ego dừng lại.",
                "timestamp_s": 1,
                "evidence": [],
                "verification_status": model_status,
            }
        ],
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-UNVERIFIED",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.claims[0].verification_status.value == "unverified"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_qwen_forces_reanalysis_claims_to_unverified_before_schema_validation() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        revision=3,
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )
    payload = {
        "claims": [
            {
                "claim_id": "claim-01",
                "text": "Xe ego dừng lại.",
                "timestamp_s": 1,
                "evidence": [],
                "verification_status": "verified_by_video",
            }
        ]
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = ReanalysisRequest(
        incident_id="INC-QWEN-REANALYSIS-UNVERIFIED",
        prompt=PromptEnvelope(text="Phân tích lại claim."),
        target_claim_ids=["claim-01"],
        incident_window=memory.incident_window,
        current_memory=memory,
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
    )

    result = await service.reanalyze_claims(request)

    assert result.claims[0].verification_status.value == "unverified"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_qwen_rejects_timeline_outside_its_incident_window_in_one_request() -> None:
    payload = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 1, "t0": 1.5, "t_end": 2},
        "timeline": [{"timestamp_s": 0.5, "description": "Ngoài cửa sổ", "evidence_ids": []}],
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    service = QwenNativeVideoVLMService(model="qwen3-vl-flash", client=client)
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-WINDOW",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(request)

    assert exc_info.value.code == "VLM_STRUCTURED_OUTPUT_INVALID"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_qwen_structured_retry_cannot_exceed_incident_request_budget() -> None:
    invalid = {"global_scene": "Đường giao thông.", "incident_window": {"t_start": 0, "t0": 0, "t_end": 0}}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(invalid)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    observability = ModelActivityRegistry(
        max_provider_requests_per_incident=1,
        max_activities_per_incident=1,
    )
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
        observability=observability,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-BUDGET",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    with pytest.raises(ModelRequestBudgetError) as exc_info:
        await service.analyze_video(request)

    assert exc_info.value.code == "PROVIDER_REQUEST_BUDGET_EXCEEDED"
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_qwen_retries_timestamps_that_exceed_video_duration() -> None:
    invalid = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 1, "t_end": 3},
        "timeline": [{"timestamp_s": 2.5, "description": "Ngoài video", "evidence_ids": []}],
    }
    valid = {
        "global_scene": "Đường giao thông.",
        "incident_window": {"t_start": 0, "t0": 1, "t_end": 2},
        "timeline": [{"timestamp_s": 1.5, "description": "Trong video", "evidence_ids": []}],
    }
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        for payload in (invalid, valid)
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses)))
    )
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-DURATION",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.incident_window.t_end == 2
    assert client.chat.completions.create.await_count == 2
    retry_prompt = client.chat.completions.create.await_args_list[1].kwargs["messages"][0]["content"][1]["text"]
    assert "incident_window.t_end" in retry_prompt
    assert "timeline.0.timestamp_s" in retry_prompt
    assert "timestamp_out_of_range" in retry_prompt


@pytest.mark.asyncio
async def test_qwen_retries_ambiguous_collision_conclusion() -> None:
    ambiguous = {
        "global_scene": "Đường đô thị.",
        "video_summary": "Xe dừng trước bụi cây, cho thấy khả năng va chạm.",
        "incident_window": {"t_start": 1, "t0": 2, "t_end": 3},
    }
    definitive = {
        "global_scene": "Đường đô thị.",
        "video_summary": "Xe ego va chạm bụi cây và dừng lại.",
        "incident_window": {"t_start": 1, "t0": 2, "t_end": 3},
    }
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        for payload in (ambiguous, definitive)
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses)))
    )
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-COLLISION",
        prompt=PromptEnvelope(text="Xác định tai nạn."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.video_summary == "Xe ego va chạm bụi cây và dừng lại."
    assert client.chat.completions.create.await_count == 2
    retry_prompt = client.chat.completions.create.await_args_list[1].kwargs["messages"][0]["content"][1]["text"]
    assert "ambiguous_incident_conclusion" in retry_prompt
    assert "không dùng ngôn ngữ phỏng đoán" in retry_prompt


@pytest.mark.asyncio
async def test_qwen_accepts_valid_schema_with_ambiguous_conclusion_when_retries_are_disabled() -> None:
    payload = {
        "global_scene": "Đường đô thị.",
        "video_summary": "Xe dừng trước bụi cây, cho thấy khả năng va chạm.",
        "incident_window": {"t_start": 1, "t0": 2, "t_end": 3},
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    observability = ModelActivityRegistry()
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=0,
        observability=observability,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-AMBIGUOUS-SINGLE-ATTEMPT",
        prompt=PromptEnvelope(text="Xác định tai nạn."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.video_summary == payload["video_summary"]
    assert client.chat.completions.create.await_count == 1
    activities = observability.list("INC-QWEN-AMBIGUOUS-SINGLE-ATTEMPT")
    assert len(activities) == 1
    assert activities[0].status == "completed"


@pytest.mark.asyncio
async def test_qwen_retries_collision_denial_that_conflicts_with_its_observations() -> None:
    contradictory = {
        "global_scene": "Đường đô thị.",
        "video_summary": (
            "Xe ego tiến sát bụi cây, mặt trước bị che khuất và xe dừng đột ngột. "
            "Không có va chạm."
        ),
        "incident_window": {"t_start": 1, "t0": 2, "t_end": 3},
    }
    definitive = {
        "global_scene": "Đường đô thị.",
        "video_summary": "Xe ego va chạm bụi cây và dừng lại.",
        "incident_window": {"t_start": 1, "t0": 2, "t_end": 3},
    }
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        for payload in (contradictory, definitive)
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses)))
    )
    service = QwenNativeVideoVLMService(
        model="qwen3-vl-flash",
        client=client,
        max_structured_output_retries=1,
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-QWEN-CONTRADICTION",
        prompt=PromptEnvelope(text="Xác định tai nạn."),
        normalized_video_uri="https://cdn.example.test/artifacts/video.mp4",
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await service.analyze_video(request)

    assert result.video_summary == "Xe ego va chạm bụi cây và dừng lại."
    retry_prompt = client.chat.completions.create.await_args_list[1].kwargs["messages"][0]["content"][1]["text"]
    assert "incident_conclusion_conflicts_with_observed_sequence" in retry_prompt


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
