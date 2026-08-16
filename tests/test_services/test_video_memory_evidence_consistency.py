from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.incidents import (
    AnalysisMode,
    Claim,
    EvidenceReference,
    IncidentWindow,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    TimelineEvent,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VerificationStatus,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)
from src.services.video_memory import (
    VideoMemoryError,
    VideoMemoryWorkflow,
    VideoMemoryWorkflowConfig,
    _reconcile_frame_evidence,
    merge_video_memory_patch,
    reconcile_native_video_evidence,
    reconcile_video_memory_patch_evidence,
    validate_video_memory,
)


def test_reconciliation_attaches_missing_timeline_evidence_to_a_claim() -> None:
    frames = [
        TimestampedFrame(
            frame_id=f"frame-{index:06d}",
            sequence_index=index,
            timestamp_s=float(index),
            delta_from_previous_s=float(bool(index)),
            image_uri=f"frame-{index}.jpg",
        )
        for index in range(3)
    ]
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        timeline=[TimelineEvent(timestamp_s=1, description="Diễn biến chính.", evidence_ids=["frame-000001"])],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Có diễn biến chính.",
                timestamp_s=0,
                evidence=[EvidenceReference(evidence_id="frame-000000", timestamp_s=0)],
            )
        ],
    )

    reconciled = _reconcile_frame_evidence(memory, frames)
    validate_video_memory(
        reconciled,
        source_duration_s=2,
        source_frame_ids={frame.frame_id for frame in frames},
    )

    assert [evidence.evidence_id for evidence in reconciled.claims[0].evidence] == [
        "frame-000000",
        "frame-000001",
    ]
    assert reconciled.timeline[0].evidence_ids == ["frame-000001"]


def test_native_video_reconciliation_attaches_timeline_evidence_by_timestamp() -> None:
    frames = [
        TimestampedFrame(
            frame_id=f"frame-{index:06d}",
            sequence_index=index,
            timestamp_s=float(index),
            delta_from_previous_s=float(bool(index)),
            image_uri=f"/artifacts/frame-{index:06d}.jpg",
        )
        for index in range(4)
    ]
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=3),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=2, description="Xe đổi hướng.", evidence_ids=["frame-000007"])],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe đổi hướng.",
                timestamp_s=2,
                evidence=[EvidenceReference(evidence_id="frame-000006", timestamp_s=1.5)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
    )

    reconciled = reconcile_native_video_evidence(memory, frames)
    validate_video_memory(
        reconciled,
        source_duration_s=3,
        source_frame_ids={frame.frame_id for frame in frames},
        expected_analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )

    evidence_ids = [item.evidence_id for item in reconciled.claims[0].evidence]
    assert evidence_ids == ["frame-000002"]
    assert reconciled.timeline[0].evidence_ids == ["frame-000002"]
    assert reconciled.claims[0].verification_status == VerificationStatus.UNVERIFIED
    assert set(evidence_ids).issubset({frame.frame_id for frame in frames})


def test_native_claims_may_share_the_same_real_frame_artifact() -> None:
    frame = TimestampedFrame(
        frame_id="frame-000001",
        sequence_index=0,
        timestamp_s=1,
        delta_from_previous_s=0,
        image_uri="/artifacts/frame-000001.jpg",
    )
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[
            Claim(claim_id="claim-1", text="Xe phanh.", timestamp_s=1),
            Claim(claim_id="claim-2", text="Xe dừng.", timestamp_s=1),
        ],
    )

    reconciled = reconcile_native_video_evidence(memory, [frame])
    validate_video_memory(reconciled, source_duration_s=2, source_frame_ids={frame.frame_id})

    assert [claim.evidence[0].evidence_id for claim in reconciled.claims] == [frame.frame_id, frame.frame_id]


@pytest.mark.asyncio
async def test_native_workflow_discards_provider_evidence_until_frames_are_sampled() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=1, description="Xe phanh.", evidence_ids=["frame-000007"])],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe phanh.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame_7", timestamp_s=1)],
                verification_status=VerificationStatus.CONTRADICTED,
            )
        ],
    )
    vlm = SimpleNamespace(
        capabilities=VLMCapabilities(provider=VLMProvider.QWEN, input_mode=VLMInputMode.NATIVE_VIDEO),
        analyze_video=AsyncMock(return_value=memory),
    )
    request = NativeVideoAnalysisRequest(
        incident_id="INC-NATIVE-EVIDENCE",
        prompt=PromptEnvelope(text="Phân tích video."),
        normalized_video_uri="normalized.mp4",
        metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
    )

    result = await VideoMemoryWorkflow(vlm=vlm, config=VideoMemoryWorkflowConfig()).analyze(request)

    assert result.claims[0].evidence == []
    assert result.timeline[0].evidence_ids == []
    assert result.claims[0].verification_status == VerificationStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_timestamped_workflow_resets_provider_verification_without_log() -> None:
    frame = TimestampedFrame(
        frame_id="frame-000001",
        sequence_index=0,
        timestamp_s=1,
        delta_from_previous_s=0,
        image_uri="/artifacts/frame-000001.jpg",
    )
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe phanh.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame_1", timestamp_s=1)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
    )
    vlm = SimpleNamespace(
        capabilities=VLMCapabilities(
            provider=VLMProvider.OPENAI,
            input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
            max_images_per_request=10,
        ),
        analyze_video=AsyncMock(return_value=memory),
    )
    request = TimestampedFramesAnalysisRequest(
        incident_id="INC-FRAME-TRUST",
        prompt=PromptEnvelope(text="Phân tích video."),
        manifest=VideoSequenceManifest(frames=[frame], source_video_uri="video.mp4", duration_s=2),
    )

    result = await VideoMemoryWorkflow(vlm=vlm, config=VideoMemoryWorkflowConfig()).analyze(request)

    assert result.claims[0].verification_status == VerificationStatus.UNVERIFIED
    assert result.claims[0].evidence[0].evidence_id == "frame-000001"


def test_native_video_reconciliation_does_not_relax_timestamped_frame_validation() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe đổi hướng.",
                evidence=[EvidenceReference(evidence_id="invented-frame", timestamp_s=1)],
            )
        ],
    )

    try:
        validate_video_memory(memory, source_duration_s=2, source_frame_ids={"frame-000001"})
    except Exception as exc:
        assert getattr(exc, "code", None) == "VLM_SOURCE_FRAME_INVALID"
    else:
        raise AssertionError("timestamped frame validation must remain strict")


def test_native_reanalysis_maps_patch_evidence_to_real_frames() -> None:
    frames = [
        TimestampedFrame(
            frame_id=f"frame-{index:06d}",
            sequence_index=index,
            timestamp_s=float(index),
            delta_from_previous_s=float(bool(index)),
            image_uri=f"/artifacts/frame-{index:06d}.jpg",
        )
        for index in range(3)
    ]
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=1, description="Xe phanh.", evidence_ids=["frame-000001"])],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe phanh.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame-000001", timestamp_s=1)],
            )
        ],
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe giảm tốc.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame_7", timestamp_s=1)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
        base_revision=1,
    )

    patch = reconcile_video_memory_patch_evidence(patch, frames, fallback_timestamp_s=1)
    merged = merge_video_memory_patch(memory, patch)

    assert merged.timeline[0].evidence_ids == ["frame-000001"]
    assert [item.evidence_id for item in merged.claims[0].evidence] == ["frame-000001"]
    assert merged.claims[0].verification_status == VerificationStatus.UNVERIFIED


def test_native_evidence_rejects_claim_when_no_frames_exist() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[Claim(claim_id="claim-1", text="Xe đổi hướng.")],
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        reconcile_native_video_evidence(memory, [])

    assert exc_info.value.code == "VLM_NATIVE_EVIDENCE_FRAMES_MISSING"


def test_native_evidence_rejects_timestamp_outside_sampled_frames() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=10, t_end=20),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[Claim(claim_id="claim-1", text="Xe đổi hướng.", timestamp_s=10)],
    )
    frames = [
        TimestampedFrame(
            frame_id=f"frame-{index:06d}",
            sequence_index=index,
            timestamp_s=float(index),
            delta_from_previous_s=float(bool(index)),
            image_uri=f"/artifacts/frame-{index:06d}.jpg",
        )
        for index in range(2)
    ]

    with pytest.raises(VideoMemoryError) as exc_info:
        reconcile_native_video_evidence(memory, frames)

    assert exc_info.value.code == "VLM_NATIVE_EVIDENCE_MAPPING_FAILED"


def test_validation_accepts_semantic_timestamps_outside_incident_window_within_video() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=2, t0=3, t_end=4),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        timeline=[
            TimelineEvent(
                timestamp_s=1,
                description="Xe bắt đầu di chuyển.",
                evidence_ids=["frame-000001"],
            )
        ],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Pre-roll observation.",
                timestamp_s=1.5,
                evidence=[EvidenceReference(evidence_id="frame-000001", timestamp_s=1.5)],
            )
        ],
    )

    result = validate_video_memory(memory, source_duration_s=5, source_frame_ids={"frame-000001"})

    assert result.incident_window == IncidentWindow(t_start=2, t0=3, t_end=4)
    assert result.timeline[0].timestamp_s == 1
    assert result.claims[0].timestamp_s == 1.5
