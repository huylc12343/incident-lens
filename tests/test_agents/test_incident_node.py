from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.nodes.incident import (
    _representative_timestamp,
    align_and_verify_claims_node,
    analyze_log_node,
    analyze_video_node,
    auto_reanalyze_node,
    build_draft_report_node,
    cut_incident_video_node,
    manual_reanalyze_node,
)
from src.models.incidents import (
    AnalysisMode,
    Claim,
    ClaimVerification,
    IncidentWindow,
    LogAnalysisResult,
    LogEvidenceSummary,
    NativeVideoMetadata,
    PromptSource,
    RemoteMediaHandle,
    ReportNarrative,
    TimestampedFrame,
    VerificationResult,
    VerificationStatus,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)
from src.services.media import NormalizedVideoArtifact
from src.services.video_memory import VideoMemoryWorkflow, VideoMemoryWorkflowConfig


def _memory(mode: AnalysisMode, duration_s: float) -> VideoMemory:
    return VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=duration_s),
        analysis_mode=mode,
    )


def _service(mode: VLMInputMode, result: VideoMemory) -> SimpleNamespace:
    return SimpleNamespace(
        capabilities=VLMCapabilities(
            provider=VLMProvider.OPENAI if mode == VLMInputMode.TIMESTAMPED_FRAMES else VLMProvider.QWEN,
            input_mode=mode,
            max_images_per_request=10 if mode == VLMInputMode.TIMESTAMPED_FRAMES else None,
        ),
        analyze_video=AsyncMock(return_value=result),
        reanalyze_claims=AsyncMock(),
        release_remote_resources=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_analyze_video_node_builds_frame_request(tmp_path: Path) -> None:
    frame = TimestampedFrame(
        frame_id="frame-0",
        sequence_index=0,
        timestamp_s=0,
        delta_from_previous_s=0,
        image_uri="frame.jpg",
    )
    manifest = VideoSequenceManifest(frames=[frame], source_video_uri="video.mp4", duration_s=2)
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest), normalize_video=AsyncMock())
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, _memory(AnalysisMode.SINGLE_REQUEST, 2))
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await analyze_video_node(
        {
            "incident_id": "INC 001",
            "video_uri": "video.mp4",
            "analysis_prompt": "Find the incident",
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    assert isinstance(result["video_memory"], VideoMemory)
    media.sample_frames.assert_awaited_once()
    media.normalize_video.assert_not_awaited()
    request = service.analyze_video.await_args.args[0]
    assert request.prompt.context == {"input_mode": "timestamped_frames"}
    assert "INC_001" in result["artifact_uris"]["frames"]


@pytest.mark.asyncio
async def test_analyze_video_node_builds_native_request(tmp_path: Path) -> None:
    metadata = NativeVideoMetadata(
        duration_s=2,
        width=1280,
        height=720,
        fps=15,
        size_bytes=100,
    )
    normalized = NormalizedVideoArtifact(uri=str(tmp_path / "normalized.mp4"), metadata=metadata)
    media = SimpleNamespace(sample_frames=AsyncMock(), normalize_video=AsyncMock(return_value=normalized))
    service = _service(VLMInputMode.NATIVE_VIDEO, _memory(AnalysisMode.NATIVE_VIDEO, 2))
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await analyze_video_node(
        {
            "incident_id": "INC-002",
            "video_uri": "video.mp4",
            "analysis_prompt": "Find the incident",
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    media.normalize_video.assert_awaited_once_with(
        "video.mp4",
        str(tmp_path.resolve() / "INC-002" / "normalized.mp4"),
        width=1280,
        height=720,
        fps=15,
        codec="libx264",
        pixel_format="yuv420p",
        max_output_bytes=100_000_000,
        max_duration_s=60,
    )
    media.sample_frames.assert_not_awaited()
    assert result["artifact_uris"] == {"normalized_video": normalized.uri}


@pytest.mark.asyncio
async def test_analyze_video_node_rejects_missing_input_without_dependencies() -> None:
    media = SimpleNamespace(sample_frames=AsyncMock(), normalize_video=AsyncMock())
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, _memory(AnalysisMode.SINGLE_REQUEST, 2))
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig())

    result = await analyze_video_node({}, media=media, workflow=workflow)

    assert result["status"] == "failed"
    assert result["error_code"] == "VIDEO_ANALYSIS_INPUT_INVALID"
    media.sample_frames.assert_not_awaited()
    service.analyze_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_cut_incident_video_node_creates_clip_and_frames(tmp_path: Path) -> None:
    memory = _memory(AnalysisMode.SINGLE_REQUEST, 2)
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "INC_003" / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=2, width=160, height=90, fps=5, size_bytes=100),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=2,
        frames=[
            TimestampedFrame(
                frame_id="incident-frame-0",
                sequence_index=0,
                timestamp_s=0,
                delta_from_previous_s=0,
                image_uri=str(tmp_path / "frame-start.jpg"),
            ),
            TimestampedFrame(
                frame_id="incident-frame-1",
                sequence_index=1,
                timestamp_s=1,
                delta_from_previous_s=1,
                image_uri=str(tmp_path / "frame-peak.jpg"),
            ),
            TimestampedFrame(
                frame_id="incident-frame-2",
                sequence_index=2,
                timestamp_s=1.75,
                delta_from_previous_s=0.75,
                image_uri=str(tmp_path / "frame-end.jpg"),
            ),
        ],
    )
    media = SimpleNamespace(
        cut_incident_clip=AsyncMock(return_value=clip),
        sample_frames=AsyncMock(return_value=manifest),
    )
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.TIMESTAMPED_FRAMES, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await cut_incident_video_node(
        {"incident_id": "INC 003", "video_uri": "video.mp4", "video_memory": memory},
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    assert result["artifact_uris"]["incident_clip"] == clip.uri
    assert result["artifact_uris"]["representative_frame"] == str(tmp_path / "frame-peak.jpg")
    assert media.cut_incident_clip.await_args.kwargs == {
        "window": memory.incident_window,
        "codec": workflow.config.video_codec,
        "pixel_format": workflow.config.video_pixel_format,
        "min_duration_s": workflow.config.incident_clip_min_duration_s,
        "pre_roll_s": workflow.config.incident_clip_pre_roll_s,
        "post_roll_s": workflow.config.incident_clip_post_roll_s,
    }
    assert media.sample_frames.await_args.kwargs["start_s"] == memory.incident_window.t_start
    assert media.sample_frames.await_args.kwargs["end_s"] == memory.incident_window.t_end


@pytest.mark.asyncio
async def test_analyze_log_node_exposes_verification_artifacts(tmp_path: Path) -> None:
    memory = _memory(AnalysisMode.SINGLE_REQUEST, 2)
    analysis = LogAnalysisResult(
        log_slice_uri=str(tmp_path / "log_slice.csv"),
        summary=LogEvidenceSummary(metrics={"speed_start": 30}),
        row_count=3,
        signal_names=["timestamp_s", "speed_kmh"],
    )
    log_analysis = SimpleNamespace(analyze=AsyncMock())
    log_analysis.analyze = lambda *args, **kwargs: analysis
    chart_uri = str(tmp_path / "charts" / "01.png")
    charts = SimpleNamespace(create_charts=lambda *args, **kwargs: [chart_uri])

    result = await analyze_log_node(
        {
            "incident_id": "INC-004",
            "log_uri": "vehicle.csv",
            "video_memory": memory,
            "artifact_uris": {"incident_clip": "clip.mp4"},
        },
        log_analysis=log_analysis,
        charts=charts,
        artifact_dir=str(tmp_path),
    )

    assert result["status"] == "running"
    assert result["log_evidence_summary"] == analysis.summary
    assert result["chart_uris"] == [chart_uri]
    assert result["artifact_uris"]["incident_clip"] == "clip.mp4"
    assert result["artifact_uris"]["log_slice"] == analysis.log_slice_uri


def _claim_memory(mode: AnalysisMode) -> VideoMemory:
    return VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        claims=[Claim(claim_id="claim-1", text="Vehicle brakes", timestamp_s=2)],
        analysis_mode=mode,
    )


def test_representative_timestamp_avoids_late_aftermath() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=6, t0=11, t_end=16.5),
        claims=[
            Claim(claim_id="claim-1", text="Vehicle collision", timestamp_s=11),
            Claim(claim_id="claim-2", text="Car swerved just before collision", timestamp_s=6),
            Claim(claim_id="claim-3", text="Debris in water after the collision", timestamp_s=16.5),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )

    assert _representative_timestamp(memory) == 6


@pytest.mark.asyncio
async def test_align_and_verify_claims_builds_per_claim_log_summary(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    log = tmp_path / "vehicle.csv"
    log.write_text(
        "timestamp,camera_frame,speed_kmh,brake,steer\n"
        "1.5,10,30,0,0\n"
        "2.0,11,20,1,0.5\n"
        "2.5,12,10,1,0.2\n",
        encoding="utf-8",
    )
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="No matching brake rise",
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock(return_value=verification))

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-VERIFY",
            "video_memory": memory,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    assert result["status"] == "running"
    assert result["verification"] == verification
    assert result["claim_log_summaries"][0].claim_id == "claim-1"
    assert result["claims"][0].verification_status == VerificationStatus.CONTRADICTED
    assert result["video_memory"].claims[0].verification_status == VerificationStatus.CONTRADICTED
    request = verifier.verify.await_args.args[0]
    assert request.claim_log_summaries[0].metrics["brake"]["max"] == 1


@pytest.mark.asyncio
async def test_verification_failure_continues_without_result(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    log = tmp_path / "vehicle.csv"
    log.write_text("timestamp,brake\n2.0,1\n", encoding="utf-8")

    class RateLimitedError(RuntimeError):
        code = "OPENAI_RATE_LIMITED"

    verifier = SimpleNamespace(verify=AsyncMock(side_effect=RateLimitedError("quota")))

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-VERIFY-FALLBACK",
            "video_memory": memory,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    assert result["status"] == "running"
    assert result["verification"] is None
    assert "OPENAI_RATE_LIMITED" in result["warnings"][0]


@pytest.mark.asyncio
async def test_auto_reanalysis_resamples_openai_window_once(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Vehicle does not brake")],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    manifest = VideoSequenceManifest(
        frames=[
            TimestampedFrame(
                frame_id="frame-0",
                sequence_index=0,
                timestamp_s=1,
                delta_from_previous_s=0,
                image_uri="frame.jpg",
            )
        ],
        source_video_uri="video.mp4",
        duration_s=3,
    )
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest))
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Log has no brake rise",
            )
        ]
    )

    result = await auto_reanalyze_node(
        {
            "incident_id": "INC-AUTO",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "verification": verification,
            "log_evidence_summary": LogEvidenceSummary(),
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    assert result["status"] == "running"
    assert result["auto_reanalysis_count"] == 1
    assert result["video_memory"].claims[0].text == "Vehicle does not brake"
    media.sample_frames.assert_awaited_once()
    assert media.sample_frames.await_args.kwargs["start_s"] == 1
    assert media.sample_frames.await_args.kwargs["end_s"] == 3
    request = service.reanalyze_claims.await_args.args[0]
    assert request.prompt.source == PromptSource.AGENT_GENERATED
    assert request.frame_manifest == manifest


@pytest.mark.asyncio
async def test_auto_reanalysis_stops_after_one_attempt(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, memory)
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    media = SimpleNamespace(sample_frames=AsyncMock())
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Still contradicted",
            )
        ]
    )

    result = await auto_reanalyze_node(
        {
            "incident_id": "INC-AUTO",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "verification": verification,
            "log_evidence_summary": LogEvidenceSummary(),
            "auto_reanalysis_count": 1,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "AUTO_REANALYSIS_LIMIT_REACHED"
    media.sample_frames.assert_not_awaited()
    service.reanalyze_claims.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_native_reanalysis_reuses_remote_handle(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.NATIVE_VIDEO)
    handle = RemoteMediaHandle(
        provider=VLMProvider.QWEN,
        name="files/one",
        uri="provider://one",
        mime_type="video/mp4",
        local_artifact_uri=str(tmp_path / "normalized.mp4"),
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Human-reviewed claim")],
        remote_media_handles=[handle],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    media = SimpleNamespace(sample_frames=AsyncMock())

    result = await manual_reanalyze_node(
        {
            "incident_id": "INC-HUMAN",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "remote_media_handles": [handle],
            "artifact_uris": {"normalized_video": str(tmp_path / "normalized.mp4")},
            "review_target_claim_ids": ["claim-1"],
            "review_feedback": "Inspect the braking claim again",
            "manual_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    assert result["status"] == "running"
    assert result["manual_reanalysis_count"] == 1
    media.sample_frames.assert_not_awaited()
    request = service.reanalyze_claims.await_args.args[0]
    assert request.prompt.source == PromptSource.HUMAN_PROVIDED
    assert request.remote_media_handles == [handle]
    assert request.normalized_video_uri == str(tmp_path / "normalized.mp4")


@pytest.mark.asyncio
async def test_draft_report_marks_video_only_and_unresolved_conflict() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    contradicted = memory.claims[0].model_copy(update={"verification_status": VerificationStatus.CONTRADICTED})
    memory = memory.model_copy(update={"claims": [contradicted]})
    narrative = ReportNarrative(
        summary="Summary",
        timeline="Timeline",
        video_observations="Video findings",
        log_findings="Invented log findings",
        alignment="Conflict remains",
        hypothesized_causes="Possible cause",
        evidence_ids=[],
    )
    report = SimpleNamespace(build_narrative=AsyncMock(return_value=narrative))

    result = await build_draft_report_node(
        {
            "incident_id": "INC-REPORT",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "auto_reanalysis_count": 1,
            "warnings": [],
        },
        report=report,
    )

    assert result["status"] == "awaiting_review"
    assert result["report_narrative"].log_findings == "Không có dữ liệu log."
    assert result["draft_report"].log_findings.narrative == "Không có dữ liệu log."
    assert len(type(result["draft_report"]).model_fields) == 10
    assert "claim-1" in result["warnings"][0]
    report.build_narrative.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_report_falls_back_to_vlm_video_summary() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST).model_copy(
        update={"video_summary": "The vehicle approached a hazard, crashed, and came to rest."}
    )
    report = SimpleNamespace(build_narrative=AsyncMock(side_effect=RuntimeError("quota")))

    result = await build_draft_report_node(
        {
            "incident_id": "INC-REPORT-FALLBACK",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "warnings": ["verification unavailable"],
        },
        report=report,
    )

    assert result["status"] == "awaiting_review"
    assert result["draft_report"].summary == memory.video_summary
    assert result["draft_report"].alignment.verification is None
    assert any("report model unavailable" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_draft_report_skips_model_when_log_verification_is_unavailable() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST).model_copy(update={"video_summary": "Whole-video VLM summary."})
    report = SimpleNamespace(build_narrative=AsyncMock())

    result = await build_draft_report_node(
        {
            "incident_id": "INC-REPORT-SKIP",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": None,
            "warnings": ["verification unavailable"],
        },
        report=report,
    )

    assert result["status"] == "awaiting_review"
    assert result["draft_report"].summary == "Whole-video VLM summary."
    assert any("Report model skipped" in warning for warning in result["warnings"])
    report.build_narrative.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_report_uses_code_log_summary_and_verification_alignment() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Brake tăng mạnh gần timestamp của claim",
                evidence_ids=["log-evidence:2:brake_rise"],
            )
        ]
    )
    log_summary = LogEvidenceSummary(
        summary="Tốc độ giảm và brake tăng mạnh tại 2 giây.",
        evidence_ids=["log-evidence:2:brake_rise"],
    )
    narrative = ReportNarrative(
        summary="Tóm tắt video.",
        timeline="Timeline.",
        video_observations="Quan sát.",
        log_findings="Nội dung model không được dùng.",
        alignment="Đối chiếu model không được dùng.",
        hypothesized_causes="Chưa xác định.",
    )
    report = SimpleNamespace(build_narrative=AsyncMock(return_value=narrative))

    result = await build_draft_report_node(
        {
            "incident_id": "INC-DETERMINISTIC-REPORT",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "log_evidence_summary": log_summary,
            "verification": verification,
        },
        report=report,
    )

    draft = result["draft_report"]
    assert draft.log_findings.narrative == log_summary.summary
    assert "claim-1 được log hỗ trợ" in draft.alignment.narrative
    assert "log-evidence:2:brake_rise" in draft.alignment.narrative


@pytest.mark.asyncio
async def test_conflict_can_be_reanalyzed_once_then_verified_supported(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Revised braking claim")],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    manifest = VideoSequenceManifest(
        frames=[
            TimestampedFrame(
                frame_id="frame-0",
                sequence_index=0,
                timestamp_s=1,
                delta_from_previous_s=0,
                image_uri="frame.jpg",
            )
        ],
        source_video_uri="video.mp4",
        duration_s=3,
    )
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest))
    conflict = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Log conflicts with video",
            )
        ]
    )
    reanalyzed = await auto_reanalyze_node(
        {
            "incident_id": "INC-RESOLVED",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "verification": conflict,
            "log_evidence_summary": LogEvidenceSummary(),
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )
    supported = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Revised claim matches log",
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock(return_value=supported))

    verified = await align_and_verify_claims_node(
        {
            "incident_id": "INC-RESOLVED",
            "video_memory": reanalyzed["video_memory"],
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    assert reanalyzed["auto_reanalysis_count"] == 1
    assert verified["claims"][0].verification_status == VerificationStatus.SUPPORTED
    service.reanalyze_claims.assert_awaited_once()
