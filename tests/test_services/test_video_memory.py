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
    Observation,
    PromptEnvelope,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VerificationStatus,
    VideoMemory,
    VideoMemoryPatch,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)
from src.services.video_memory import (
    VideoMemoryError,
    VideoMemoryWorkflow,
    VideoMemoryWorkflowConfig,
    analyze_rolling_batches,
    build_sequence_manifest,
    merge_memory_only_patch,
    merge_video_memory_patch,
    reconcile_video_memory_patch_evidence,
    validate_video_memory,
)


def _frames(count: int) -> list[TimestampedFrame]:
    return [
        TimestampedFrame(
            frame_id=f"frame-{index}",
            sequence_index=index,
            timestamp_s=float(index),
            delta_from_previous_s=0 if index == 0 else 1,
            image_uri=f"data:image/jpeg;base64,{index}",
        )
        for index in range(count)
    ]


def _frame_request(count: int) -> TimestampedFramesAnalysisRequest:
    return TimestampedFramesAnalysisRequest(
        incident_id="INC-001",
        prompt=PromptEnvelope(text="Analyze the video"),
        manifest=build_sequence_manifest(
            frames=_frames(count),
            source_video_uri="video.mp4",
            duration_s=float(max(count, 1)),
        ),
    )


def _memory(
    *,
    duration_s: float,
    mode: AnalysisMode = AnalysisMode.SINGLE_REQUEST,
) -> VideoMemory:
    return VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=min(1, duration_s), t_end=duration_s),
        analysis_mode=mode,
    )


def _vlm(*, input_mode: VLMInputMode, max_images: int | None, side_effect: object) -> SimpleNamespace:
    provider = VLMProvider.QWEN
    analyze_video = AsyncMock()
    if callable(side_effect):
        analyze_video.side_effect = side_effect
    else:
        analyze_video.return_value = side_effect
    return SimpleNamespace(
        capabilities=VLMCapabilities(
            provider=provider,
            input_mode=input_mode,
            max_images_per_request=max_images,
        ),
        analyze_video=analyze_video,
        reanalyze_claims=AsyncMock(),
        release_remote_resources=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_frames_within_limit_use_exactly_one_request() -> None:
    request = _frame_request(3)
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=_memory(duration_s=3),
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(
            max_frames_per_request=3,
            frame_batch_size=3,
            frame_batch_overlap=1,
        ),
    )

    result = await workflow.analyze(request)

    service.analyze_video.assert_awaited_once_with(request)
    assert result.analysis_mode == AnalysisMode.SINGLE_REQUEST
    assert result.sampling_metadata is not None
    assert result.sampling_metadata.batch_count == 1


@pytest.mark.asyncio
async def test_video_analysis_cannot_preverify_claims() -> None:
    request = _frame_request(3)
    memory = _memory(duration_s=3)
    memory = memory.model_copy(
        update={
            "claims": [
                Claim(
                    claim_id="claim-1",
                    text="Model says this is already verified",
                    timestamp_s=1,
                    verification_status=VerificationStatus.SUPPORTED,
                )
            ]
        }
    )
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=memory,
    )
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig(max_frames_per_request=3))

    result = await workflow.analyze(request)

    assert result.claims[0].verification_status == VerificationStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_video_analysis_recovers_and_canonicalizes_supplied_frame_evidence() -> None:
    request = _frame_request(3)
    memory = _memory(duration_s=3)
    memory = memory.model_copy(
        update={
            "claims": [
                Claim(
                    claim_id="claim-1",
                    text="Visible event",
                    timestamp_s=2,
                    evidence=[EvidenceReference(evidence_id="frame-1", timestamp_s=2)],
                )
            ],
        }
    )
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=memory,
    )
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig(max_frames_per_request=3))

    result = await workflow.analyze(request)

    evidence = {item.evidence_id: item for item in result.claims[0].evidence}
    assert set(evidence) == {"frame-2"}
    assert evidence["frame-2"].timestamp_s == request.manifest.frames[2].timestamp_s


@pytest.mark.asyncio
async def test_video_analysis_maps_model_evidence_alias_to_nearest_real_frame() -> None:
    request = _frame_request(3)
    memory = _memory(duration_s=3)
    memory = memory.model_copy(
        update={
            "claims": [
                Claim(
                    claim_id="claim-1",
                    text="Hai xe va chạm",
                    timestamp_s=1.8,
                    evidence=[EvidenceReference(evidence_id="collision-evidence", timestamp_s=1.8)],
                )
            ],
        }
    )
    workflow = VideoMemoryWorkflow(
        vlm=_vlm(input_mode=VLMInputMode.TIMESTAMPED_FRAMES, max_images=3, side_effect=memory),
        config=VideoMemoryWorkflowConfig(max_frames_per_request=3),
    )

    result = await workflow.analyze(request)

    assert [item.evidence_id for item in result.claims[0].evidence] == ["frame-2"]
    assert result.claims[0].evidence[0].timestamp_s == request.manifest.frames[2].timestamp_s


@pytest.mark.asyncio
async def test_rolling_batches_only_on_overflow_and_finish_with_synthesis() -> None:
    request = _frame_request(6)

    async def response_for(batch_request: TimestampedFramesAnalysisRequest) -> VideoMemory:
        return _memory(
            duration_s=request.manifest.duration_s,
        )

    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=response_for,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(
            max_frames_per_request=3,
            frame_batch_size=3,
            frame_batch_overlap=1,
            frame_max_batches=3,
        ),
    )

    result = await workflow.analyze(request)

    assert service.analyze_video.await_count == 4  # 3 chronological batches + 1 synthesis
    calls = [call.args[0] for call in service.analyze_video.await_args_list]
    assert [len(call.manifest.frames) for call in calls] == [3, 3, 2, 3]
    assert calls[0].manifest.frames[-1].frame_id == calls[1].manifest.frames[0].frame_id
    assert "prior_compact_memory" in calls[1].prompt.text
    assert "Synthesize one final VideoMemory" in calls[-1].prompt.text
    assert "nội dung mô tả phải được viết bằng tiếng Việt rõ ràng, chuyên nghiệp" in calls[-1].prompt.text
    assert result.analysis_mode == AnalysisMode.ROLLING_BATCHES
    assert result.sampling_metadata is not None
    assert result.sampling_metadata.batch_count == 3


@pytest.mark.asyncio
async def test_rolling_is_not_used_when_frame_count_equals_limit() -> None:
    request = _frame_request(3)
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=_memory(duration_s=3),
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(
            max_frames_per_request=3,
            frame_batch_size=3,
            frame_batch_overlap=1,
        ),
    )

    await workflow.analyze(request)

    assert service.analyze_video.await_count == 1


@pytest.mark.asyncio
async def test_overflow_strategy_fail_stops_before_vlm_call() -> None:
    request = _frame_request(4)
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=_memory(duration_s=4),
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(max_frames_per_request=3, frame_overflow_strategy="fail"),
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        await workflow.analyze(request)

    assert exc_info.value.code == "FRAME_LIMIT_EXCEEDED"
    service.analyze_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_video_produces_same_video_memory_contract() -> None:
    request = NativeVideoAnalysisRequest(
        incident_id="INC-NATIVE",
        prompt=PromptEnvelope(text="Analyze native video"),
        normalized_video_uri="normalized.mp4",
        metadata=NativeVideoMetadata(
            duration_s=4,
            width=1280,
            height=720,
            fps=15,
            size_bytes=100,
        ),
    )
    service = _vlm(
        input_mode=VLMInputMode.NATIVE_VIDEO,
        max_images=None,
        side_effect=_memory(duration_s=4, mode=AnalysisMode.NATIVE_VIDEO),
    )
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig())

    result = await workflow.analyze(request)

    service.analyze_video.assert_awaited_once_with(request)
    assert isinstance(result, VideoMemory)
    assert result.analysis_mode == AnalysisMode.NATIVE_VIDEO
    assert result.sampling_metadata is None


def test_validate_video_memory_rejects_out_of_range_timestamp() -> None:
    memory = _memory(duration_s=5)

    with pytest.raises(VideoMemoryError) as exc_info:
        validate_video_memory(memory, source_duration_s=4)

    assert exc_info.value.code == "VLM_TIMESTAMP_OUT_OF_RANGE"
    assert memory.incident_window.t_end == 5  # rejected, not clamped


def test_validate_video_memory_rejects_unknown_evidence_reference() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Claim",
                evidence=[EvidenceReference(evidence_id="missing", timestamp_s=1)],
            )
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        validate_video_memory(memory, source_duration_s=2, source_frame_ids=set())

    assert exc_info.value.code == "VLM_SOURCE_FRAME_INVALID"


def test_validate_video_memory_rejects_representative_timestamp_outside_incident() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        representative_timestamp_s=4,
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        validate_video_memory(memory, source_duration_s=5)

    assert exc_info.value.code == "VLM_REPRESENTATIVE_TIMESTAMP_INVALID"


def test_reanalysis_patch_maps_evidence_alias_to_real_frame() -> None:
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Va chạm được xác nhận lại",
                timestamp_s=1.9,
                evidence=[EvidenceReference(evidence_id="model-collision-proof", timestamp_s=1.9)],
            )
        ],
        base_revision=1,
    )

    result = reconcile_video_memory_patch_evidence(patch, _frames(3), fallback_timestamp_s=1)

    assert [item.evidence_id for item in result.claims[0].evidence] == ["frame-2"]
    assert result.claims[0].evidence[0].timestamp_s == 2


def test_merge_video_memory_patch_updates_only_targets_and_revision() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Original target",
                evidence=[EvidenceReference(evidence_id="frame-1", timestamp_s=1)],
            ),
            Claim(
                claim_id="claim-2",
                text="Unrelated",
                evidence=[EvidenceReference(evidence_id="frame-3", timestamp_s=1.5)],
            ),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        revision=2,
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Revised target",
                evidence=[EvidenceReference(evidence_id="frame-2", timestamp_s=1.2)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
        base_revision=2,
    )

    merged = merge_video_memory_patch(memory, patch)

    assert merged.revision == 3
    assert {claim.claim_id: claim.text for claim in merged.claims} == {
        "claim-1": "Revised target",
        "claim-2": "Unrelated",
    }
    assert [item.evidence_id for item in merged.claims[0].evidence] == ["frame-2"]
    assert [item.evidence_id for item in merged.claims[1].evidence] == ["frame-3"]
    assert merged.claims[0].verification_status == VerificationStatus.UNVERIFIED
    assert memory.revision == 2


def test_merge_video_memory_patch_rejects_stale_revision() -> None:
    memory = _memory(duration_s=2)
    patch = VideoMemoryPatch(target_claim_ids=["claim-1"], base_revision=2)

    with pytest.raises(VideoMemoryError) as exc_info:
        merge_video_memory_patch(memory, patch)

    assert exc_info.value.code == "VLM_PATCH_REVISION_CONFLICT"


def test_memory_only_patch_preserves_unselected_claim_and_reuses_existing_evidence() -> None:
    evidence = EvidenceReference(evidence_id="frame-1", timestamp_s=1)
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=2, t0=3, t_end=4),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Original target",
                timestamp_s=1,
                evidence=[evidence],
                verification_status=VerificationStatus.SUPPORTED,
            ),
            Claim(
                claim_id="claim-2",
                text="Unselected",
                timestamp_s=1.5,
                verification_status=VerificationStatus.CONTRADICTED,
            ),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Revised target",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame-1", timestamp_s=1.1)],
            )
        ],
        base_revision=1,
    )

    merged = merge_memory_only_patch(memory, patch, ["claim-1"])

    assert merged.global_scene == memory.global_scene
    assert merged.incident_window == memory.incident_window
    assert merged.claims[0].text == "Revised target"
    assert merged.claims[0].evidence == [evidence]
    assert merged.claims[0].verification_status == VerificationStatus.UNVERIFIED
    assert merged.claims[1] == memory.claims[1]


def test_memory_only_patch_rejects_new_evidence() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[Claim(claim_id="claim-1", text="Original", timestamp_s=1)],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[
            Claim(
                claim_id="claim-1",
                text="Revised",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="invented", timestamp_s=1)],
            )
        ],
        base_revision=1,
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        merge_memory_only_patch(memory, patch, ["claim-1"])

    assert exc_info.value.code == "MEMORY_PATCH_EVIDENCE_INVALID"


def test_memory_only_patch_keeps_verification_when_claim_content_is_unchanged() -> None:
    original = Claim(
        claim_id="claim-1",
        text="Unchanged",
        timestamp_s=1,
        verification_status=VerificationStatus.SUPPORTED,
    )
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[original],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[original.model_copy(update={"verification_status": VerificationStatus.UNVERIFIED})],
        base_revision=1,
    )

    merged = merge_memory_only_patch(memory, patch, ["claim-1"])

    assert merged.claims[0].verification_status == VerificationStatus.SUPPORTED


def test_video_memory_patch_keeps_an_omitted_target_visible_with_its_prior_status() -> None:
    """An omitted focused-reanalysis target must never disappear from user-visible state."""
    target_evidence = EvidenceReference(evidence_id="frame-target", timestamp_s=1)
    supported_evidence = EvidenceReference(evidence_id="frame-supported", timestamp_s=2)
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(
                claim_id="claim-target",
                text="Target no longer has enough evidence.",
                timestamp_s=1,
                evidence=[target_evidence],
                verification_status=VerificationStatus.CONTRADICTED,
            ),
            Claim(
                claim_id="claim-supported",
                text="Unrelated supported event.",
                timestamp_s=2,
                evidence=[supported_evidence],
                verification_status=VerificationStatus.SUPPORTED,
            ),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    patch = VideoMemoryPatch(
        target_claim_ids=["claim-target"],
        claims=[],
        base_revision=1,
    )

    merged = merge_video_memory_patch(memory, patch)

    assert merged.revision == 2
    assert [claim.claim_id for claim in merged.claims] == ["claim-target", "claim-supported"]
    assert merged.claims[0].verification_status == VerificationStatus.CONTRADICTED
    assert merged.claims[0].evidence == [target_evidence]
    assert merged.claims[1].verification_status == VerificationStatus.SUPPORTED
    assert merged.claims[1].evidence == [supported_evidence]


@pytest.mark.asyncio
async def test_rolling_batch_limit_rejects_before_any_request() -> None:
    request = _frame_request(8)
    service = _vlm(
        input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
        max_images=3,
        side_effect=_memory(duration_s=8),
    )

    with pytest.raises(VideoMemoryError) as exc_info:
        await analyze_rolling_batches(
            vlm=service,
            request=request,
            batch_size=3,
            overlap=1,
            max_batches=2,
            final_frame_limit=3,
        )

    assert exc_info.value.code == "ROLLING_BATCH_LIMIT_EXCEEDED"
    service.analyze_video.assert_not_awaited()
