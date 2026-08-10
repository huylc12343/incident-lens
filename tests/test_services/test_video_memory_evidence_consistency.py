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
    VideoMemory,
    VideoMemoryPatch,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)
from src.services.video_memory import (
    VideoMemoryWorkflow,
    VideoMemoryWorkflowConfig,
    _reconcile_frame_evidence,
    merge_video_memory_patch,
    reconcile_native_video_evidence,
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
            )
        ],
    )

    reconciled = reconcile_native_video_evidence(memory)
    validate_video_memory(
        reconciled,
        source_duration_s=3,
        expected_analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )

    assert [item.evidence_id for item in reconciled.claims[0].evidence] == [
        "frame-000006",
        "frame-000007",
    ]
    assert reconciled.claims[0].evidence[1].timestamp_s == 2


@pytest.mark.asyncio
async def test_native_workflow_reconciles_evidence_before_validation() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=1, description="Xe phanh.", evidence_ids=["frame-000007"])],
        claims=[Claim(claim_id="claim-1", text="Xe phanh.", timestamp_s=1)],
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

    assert "frame-000007" in [item.evidence_id for item in result.claims[0].evidence]


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


def test_native_reanalysis_preserves_timeline_evidence_references() -> None:
    memory = VideoMemory(
        global_scene="Đường giao thông.",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=1, description="Xe phanh.", evidence_ids=["old-evidence"])],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Xe phanh.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="old-evidence", timestamp_s=1)],
            )
        ],
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Xe giảm tốc.", timestamp_s=1)],
        base_revision=1,
    )

    merged = merge_video_memory_patch(memory, patch, reconcile_native_evidence=True)

    assert merged.timeline[0].evidence_ids == ["old-evidence"]
    assert "old-evidence" in [item.evidence_id for item in merged.claims[0].evidence]
