from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.incidents import (
    AnalysisMode,
    Claim,
    IncidentWindow,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    ReanalysisRequest,
    RemoteMediaHandle,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
    VLMProvider,
)
from src.services.model_observability import ModelActivityRegistry
from src.services.vlm import GeminiNativeVideoVLMService, OpenAIVLMService, VLMServiceError


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


def _gemini_request(video_path: Path) -> NativeVideoAnalysisRequest:
    return NativeVideoAnalysisRequest(
        incident_id="INC-GEMINI",
        prompt=PromptEnvelope(text="Analyze video"),
        normalized_video_uri=str(video_path),
        metadata=NativeVideoMetadata(
            duration_s=3,
            width=160,
            height=90,
            fps=5,
            size_bytes=video_path.stat().st_size,
        ),
    )


def _gemini_client(
    *,
    uploaded: object,
    polled: object | None = None,
    parsed: object | None = None,
) -> SimpleNamespace:
    files = SimpleNamespace(
        upload=AsyncMock(return_value=uploaded),
        get=AsyncMock(return_value=polled or uploaded),
        delete=AsyncMock(),
    )
    models = SimpleNamespace(
        generate_content=AsyncMock(
            return_value=SimpleNamespace(parsed=parsed or _memory(AnalysisMode.NATIVE_VIDEO), text="")
        )
    )
    return SimpleNamespace(aio=SimpleNamespace(files=files, models=models))


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
    content = call["input"][0]["content"]
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
async def test_gemini_uploads_polls_active_and_generates_structured_result(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    processing = SimpleNamespace(
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        state=SimpleNamespace(name="PROCESSING"),
    )
    active = SimpleNamespace(
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        state=SimpleNamespace(name="ACTIVE"),
    )
    client = _gemini_client(uploaded=processing, polled=active)
    sleep = AsyncMock()
    service = GeminiNativeVideoVLMService(model="gemini-test", client=client, sleep=sleep)

    result = await service.analyze_video(_gemini_request(video))

    client.aio.files.upload.assert_awaited_once_with(
        file=str(video.resolve()),
        config={"mime_type": "video/mp4"},
    )
    client.aio.files.get.assert_awaited_once_with(name="files/one")
    sleep.assert_awaited_once()
    client.aio.models.generate_content.assert_awaited_once()
    generation = client.aio.models.generate_content.await_args.kwargs
    assert generation["contents"][0].file_data.file_uri == "gemini://one"
    assert generation["contents"][1] == "Analyze video"
    assert generation["config"].response_schema is VideoMemory
    assert result.remote_media_handles[0].name == "files/one"
    assert result.analysis_mode == AnalysisMode.NATIVE_VIDEO


@pytest.mark.asyncio
async def test_gemini_failed_processing_maps_domain_error(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    failed = SimpleNamespace(
        name="files/failed",
        uri="gemini://failed",
        mime_type="video/mp4",
        state=SimpleNamespace(name="FAILED"),
    )
    client = _gemini_client(uploaded=failed)
    service = GeminiNativeVideoVLMService(model="gemini-test", client=client)

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(_gemini_request(video))

    assert exc_info.value.code == "GEMINI_VIDEO_PROCESSING_FAILED"
    client.aio.models.generate_content.assert_not_awaited()
    client.aio.files.delete.assert_awaited_once_with(name="files/failed")


@pytest.mark.asyncio
async def test_gemini_upload_failure_maps_domain_error(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    active = SimpleNamespace(
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        state=SimpleNamespace(name="ACTIVE"),
    )
    client = _gemini_client(uploaded=active)
    client.aio.files.upload.side_effect = OSError("upload unavailable")
    service = GeminiNativeVideoVLMService(model="gemini-test", client=client)

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(_gemini_request(video))

    assert exc_info.value.code == "GEMINI_VIDEO_UPLOAD_FAILED"
    assert exc_info.value.retryable is True
    client.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_processing_timeout_has_no_blocking_sleep(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    processing = SimpleNamespace(
        name="files/processing",
        uri="gemini://processing",
        mime_type="video/mp4",
        state=SimpleNamespace(name="PROCESSING"),
    )
    client = _gemini_client(uploaded=processing)
    sleep = AsyncMock()
    service = GeminiNativeVideoVLMService(
        model="gemini-test",
        client=client,
        max_poll_attempts=2,
        sleep=sleep,
    )

    with pytest.raises(VLMServiceError) as exc_info:
        await service.analyze_video(_gemini_request(video))

    assert exc_info.value.code == "GEMINI_VIDEO_PROCESSING_TIMEOUT"
    sleep.assert_awaited_once()
    client.aio.files.delete.assert_awaited_once_with(name="files/processing")


@pytest.mark.asyncio
async def test_gemini_reanalysis_reuses_handle_and_applies_video_window(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    active = SimpleNamespace(
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        state=SimpleNamespace(name="ACTIVE"),
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Revised claim")],
        base_revision=1,
    )
    client = _gemini_client(uploaded=active, parsed=patch)
    service = GeminiNativeVideoVLMService(model="gemini-test", client=client)
    handle = RemoteMediaHandle(
        provider=VLMProvider.GEMINI,
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        local_artifact_uri=str(video),
    )
    request = ReanalysisRequest(
        incident_id="INC-GEMINI",
        prompt=PromptEnvelope(text="Review claim"),
        target_claim_ids=["claim-1"],
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        current_memory=_memory(AnalysisMode.NATIVE_VIDEO),
        remote_media_handles=[handle],
    )

    result = await service.reanalyze_claims(request)

    client.aio.files.upload.assert_not_awaited()
    client.aio.files.get.assert_awaited_once_with(name="files/one")
    video_part = client.aio.models.generate_content.await_args.kwargs["contents"][0]
    assert video_part.video_metadata.start_offset == "1.0s"
    assert video_part.video_metadata.end_offset == "3.0s"
    assert result.remote_media_handles[0].uri == "gemini://one"


@pytest.mark.asyncio
async def test_gemini_cleanup_is_idempotent() -> None:
    active = SimpleNamespace(
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        state=SimpleNamespace(name="ACTIVE"),
    )
    client = _gemini_client(uploaded=active)
    client.aio.files.delete.side_effect = FileNotFoundError("already deleted")
    service = GeminiNativeVideoVLMService(model="gemini-test", client=client)
    handle = RemoteMediaHandle(
        provider=VLMProvider.GEMINI,
        name="files/one",
        uri="gemini://one",
        mime_type="video/mp4",
        local_artifact_uri="video.mp4",
    )

    await service.release_remote_resources([handle])

    client.aio.files.delete.assert_awaited_once_with(name="files/one")
