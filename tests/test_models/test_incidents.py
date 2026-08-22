import pytest
from pydantic import TypeAdapter, ValidationError

from src.models.incidents import (
    AnalysisMode,
    Claim,
    IncidentWindow,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VideoAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
    VLMInputMode,
)


def test_timestamped_frames_request_validates() -> None:
    request = TypeAdapter(VideoAnalysisRequest).validate_python(
        {
            "input_mode": "timestamped_frames",
            "incident_id": "INC-001",
            "prompt": {"text": "Analyze the incident."},
            "manifest": {
                "source_video_uri": "data_mock/front_camera.mp4",
                "duration_s": 17,
                "frames": [
                    {
                        "frame_id": "frame-0",
                        "sequence_index": 0,
                        "timestamp_s": 0,
                        "delta_from_previous_s": 0,
                        "image_uri": "data:image/jpeg;base64,abc",
                    }
                ],
            },
        }
    )

    assert isinstance(request, TimestampedFramesAnalysisRequest)
    assert request.input_mode == VLMInputMode.TIMESTAMPED_FRAMES


def test_native_video_request_validates() -> None:
    request = TypeAdapter(VideoAnalysisRequest).validate_python(
        {
            "input_mode": "native_video",
            "incident_id": "INC-002",
            "prompt": {"text": "Analyze the incident."},
            "normalized_video_uri": "data/artifacts/INC-002/normalized.mp4",
            "metadata": {
                "duration_s": 17,
                "width": 1280,
                "height": 720,
                "fps": 15,
                "size_bytes": 1024,
            },
        }
    )

    assert isinstance(request, NativeVideoAnalysisRequest)
    assert request.input_mode == VLMInputMode.NATIVE_VIDEO


def test_incident_window_rejects_invalid_timestamp_order() -> None:
    with pytest.raises(ValidationError, match="t_start <= t0 <= t_end"):
        IncidentWindow(t_start=3, t0=2, t_end=4)


def test_manifest_rejects_out_of_order_frames() -> None:
    frames = [
        TimestampedFrame(
            frame_id="frame-0",
            sequence_index=0,
            timestamp_s=2,
            delta_from_previous_s=0,
            image_uri="frame-0.jpg",
        ),
        TimestampedFrame(
            frame_id="frame-1",
            sequence_index=1,
            timestamp_s=1,
            delta_from_previous_s=1,
            image_uri="frame-1.jpg",
        ),
    ]

    with pytest.raises(ValidationError, match="ordered by timestamp"):
        VideoSequenceManifest(frames=frames, source_video_uri="video.mp4", duration_s=3)


def test_video_memory_patch_cannot_modify_unrequested_claim() -> None:
    with pytest.raises(ValidationError, match="outside target_claim_ids"):
        VideoMemoryPatch(
            target_claim_ids=["claim-1"],
            claims=[Claim(claim_id="claim-2", text="Different claim")],
            base_revision=1,
        )


def test_video_memory_contract_is_provider_neutral() -> None:
    memory = VideoMemory(
        global_scene="A road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )

    assert memory.remote_media_handles == []
    assert memory.revision == 1


def test_video_memory_contract_has_no_tracked_entities() -> None:
    assert "tracked_entities" not in VideoMemory.model_json_schema()["properties"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VideoMemory(
            global_scene="A road scene",
            tracked_entities=[],  # type: ignore[call-arg]
            incident_window=IncidentWindow(t_start=0, t0=0, t_end=3),
            analysis_mode=AnalysisMode.NATIVE_VIDEO,
        )


def test_request_models_forbid_unknown_provider_payload_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NativeVideoAnalysisRequest(
            incident_id="INC-003",
            prompt=PromptEnvelope(text="Analyze"),
            normalized_video_uri="video.mp4",
            metadata=NativeVideoMetadata(
                duration_s=10,
                width=1280,
                height=720,
                fps=15,
                size_bytes=1024,
            ),
            api_key="must-not-enter-contract",  # type: ignore[call-arg]
        )
