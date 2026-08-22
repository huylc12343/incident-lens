import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.agents.nodes.incident import (
    _incident_sampling_fps,
    _representative_timestamp,
    align_and_verify_claims_node,
    analyze_log_node,
    analyze_video_node,
    auto_reanalyze_node,
    build_draft_report_node,
    cut_incident_video_node,
    manual_reanalyze_node,
    map_canonical_evidence_node,
)
from src.models.incidents import (
    AnalysisMode,
    Claim,
    ClaimVerification,
    EvidenceReference,
    IncidentWindow,
    LogAnalysisResult,
    LogEvidenceSummary,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    PromptSource,
    RemoteMediaHandle,
    ReportModelOutput,
    TimelineEvent,
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
from src.services.log_analysis import LogAnalysisService
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
            provider=VLMProvider.QWEN,
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
    assert result["video_duration_s"] == 2
    media.sample_frames.assert_awaited_once()
    media.normalize_video.assert_not_awaited()
    request = service.analyze_video.await_args.args[0]
    assert request.prompt.context == {
        "input_mode": "timestamped_frames",
        "analyst_request": "Find the incident",
    }
    assert "INC_001" in result["artifact_uris"]["frames"]


@pytest.mark.asyncio
async def test_analyze_video_node_adds_qualitative_log_attention_hint(tmp_path: Path) -> None:
    log = tmp_path / "vehicle.csv"
    log.write_text(
        "timestamp_s,throttle,brake,steering_angle,acceleration_mps2\n"
        "0.0,0.1,0.0,0.0,0.0\n"
        "1.0,0.1,0.0,0.0,0.0\n"
        "2.0,0.1,0.0,0.0,0.0\n"
        "3.0,0.1,0.0,0.0,0.0\n"
        "4.0,0.1,0.0,0.0,0.0\n"
        "5.0,0.1,0.0,0.0,0.0\n"
        "6.0,0.5,0.6,-0.5,-6.0\n"
        "7.0,0.5,0.6,-0.5,-6.0\n",
        encoding="utf-8",
    )
    manifest = VideoSequenceManifest(
        frames=[
            TimestampedFrame(
                frame_id="frame-0",
                sequence_index=0,
                timestamp_s=0,
                delta_from_previous_s=0,
                image_uri="frame.jpg",
            )
        ],
        source_video_uri="video.mp4",
        duration_s=8,
    )
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest), normalize_video=AsyncMock())
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, _memory(AnalysisMode.SINGLE_REQUEST, 2))
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)))

    await analyze_video_node(
        {
            "incident_id": "INC-HINT",
            "video_uri": "video.mp4",
            "log_uri": str(log),
            "analysis_prompt": "Phân tích toàn bộ video",
        },
        media=media,
        workflow=workflow,
    )

    context = service.analyze_video.await_args.args[0].prompt.context
    hint = context["log_attention_hint"]
    assert "Tại giây thứ 6.0" in hint
    assert "ga tăng bất thường so với diễn biến gần đó" in hint
    assert "phanh tăng bất thường so với diễn biến gần đó" in hint
    assert "gia tốc giảm bất thường so với diễn biến gần đó" in hint
    assert "-6.0" not in hint
    assert "0.5" not in hint


@pytest.mark.asyncio
async def test_analyze_video_node_builds_native_request(tmp_path: Path) -> None:
    metadata = NativeVideoMetadata(
        duration_s=2,
        width=1280,
        height=720,
        fps=15,
        size_bytes=100,
    )
    normalized = NormalizedVideoArtifact(uri=str(tmp_path / "normalized_source.mp4"), metadata=metadata)
    redacted = NormalizedVideoArtifact(uri=str(tmp_path / "normalized.mp4"), metadata=metadata)
    media = SimpleNamespace(
        sample_frames=AsyncMock(),
        normalize_video=AsyncMock(return_value=normalized),
        redact_video=AsyncMock(return_value=redacted),
    )
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
    assert result["video_duration_s"] == 2
    media.normalize_video.assert_awaited_once_with(
        "video.mp4",
        str(tmp_path.resolve() / "INC-002" / "normalized_source.mp4"),
        width=1280,
        height=720,
        fps=15,
        codec="libx264",
        pixel_format="yuv420p",
        max_output_bytes=100_000_000,
        max_duration_s=60,
    )
    media.redact_video.assert_awaited_once_with(
        normalized.uri,
        str(tmp_path.resolve() / "INC-002" / "normalized.mp4"),
    )
    media.sample_frames.assert_not_awaited()
    request = service.analyze_video.await_args.args[0]
    assert request.normalized_video_uri == redacted.uri
    assert result["video_uri"] == redacted.uri
    assert result["artifact_uris"] == {"normalized_video": redacted.uri}


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
async def test_analyze_video_node_skips_redaction_when_disabled(tmp_path: Path) -> None:
    metadata = NativeVideoMetadata(duration_s=2, width=512, height=288, fps=10, size_bytes=100)
    normalized = NormalizedVideoArtifact(uri=str(tmp_path / "normalized.mp4"), metadata=metadata)
    media = SimpleNamespace(
        normalize_video=AsyncMock(return_value=normalized),
        redact_video=AsyncMock(),
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, _memory(AnalysisMode.NATIVE_VIDEO, 2))
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path), video_redaction_enabled=False),
    )

    result = await analyze_video_node(
        {"incident_id": "INC-NO-REDACTION", "video_uri": "video.mp4", "analysis_prompt": "Find incident"},
        media=media,
        workflow=workflow,
    )

    media.redact_video.assert_not_awaited()
    assert result["video_uri"] == normalized.uri


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
async def test_cut_incident_video_requires_a_representative_frame_before_review(tmp_path: Path) -> None:
    memory = _memory(AnalysisMode.SINGLE_REQUEST, 2)
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=2, width=160, height=90, fps=5, size_bytes=100),
    )
    media = SimpleNamespace(
        cut_incident_clip=AsyncMock(return_value=clip),
        sample_frames=AsyncMock(return_value=SimpleNamespace(frames=[])),
    )
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.TIMESTAMPED_FRAMES, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await cut_incident_video_node(
        {
            "incident_id": "INC-EMPTY-FRAMES",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "draft_report": Mock(),
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "INCIDENT_REVIEW_FRAMES_MISSING"


@pytest.mark.asyncio
async def test_native_cut_maps_fake_evidence_ids_to_sampled_artifacts(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[
            Claim(
                claim_id="claim-1",
                text="Vehicle brakes.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame_7", timestamp_s=1)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
    )
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=2, width=160, height=90, fps=5, size_bytes=100),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=2,
        frames=[
            TimestampedFrame(
                frame_id=f"frame-{index:06d}",
                sequence_index=index,
                timestamp_s=float(index),
                delta_from_previous_s=float(bool(index)),
                image_uri=str(tmp_path / f"frame-{index:06d}.jpg"),
            )
            for index in range(3)
        ],
    )
    media = SimpleNamespace(
        cut_incident_clip=AsyncMock(return_value=clip),
        sample_frames=AsyncMock(return_value=manifest),
    )
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.NATIVE_VIDEO, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await cut_incident_video_node(
        {
            "incident_id": "INC-NATIVE",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "verification": VerificationResult(
                results=[
                    ClaimVerification(
                        claim_id="claim-1",
                        status=VerificationStatus.SUPPORTED,
                        reason="Telemetry supports the claim.",
                    )
                ]
            ),
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    claim = result["video_memory"].claims[0]
    assert [item.evidence_id for item in claim.evidence] == ["frame-000001"]
    assert claim.verification_status == VerificationStatus.SUPPORTED
    assert "claims" not in result
    frame_artifacts = {Path(frame.image_uri).stem for frame in manifest.frames}
    assert {item.evidence_id for item in claim.evidence}.issubset(frame_artifacts)


@pytest.mark.asyncio
async def test_map_canonical_evidence_before_verification_preserves_claim_statuses(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=6, t0=7, t_end=12),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[TimelineEvent(timestamp_s=3, description="Vehicle starts moving.")],
        claims=[
            Claim(
                claim_id="claim-supported",
                text="Vehicle is moving.",
                timestamp_s=3,
                verification_status=VerificationStatus.SUPPORTED,
            ),
            Claim(
                claim_id="claim-pending",
                text="Vehicle changes direction.",
                timestamp_s=11,
            ),
        ],
    )
    timestamps = (3.0, 6.0, 7.0, 11.0, 12.0)
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=12,
        frames=[
            TimestampedFrame(
                frame_id=f"frame-{timestamp_s:06.1f}",
                sequence_index=index,
                timestamp_s=timestamp_s,
                delta_from_previous_s=0 if index == 0 else timestamp_s - timestamps[index - 1],
                image_uri=str(tmp_path / f"frame-{timestamp_s:06.1f}.jpg"),
            )
            for index, timestamp_s in enumerate(timestamps)
        ],
    )
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest))
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.NATIVE_VIDEO, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await map_canonical_evidence_node(
        {
            "incident_id": "INC-MAP-EVIDENCE",
            "video_uri": "video.mp4",
            "video_duration_s": 12,
            "video_memory": memory,
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    assert result["canonical_evidence_mapped"] is True
    mapped = result["video_memory"]
    assert [claim.evidence[0].evidence_id for claim in mapped.claims] == [
        "frame-0003.0",
        "frame-0011.0",
    ]
    assert [claim.verification_status for claim in mapped.claims] == [
        VerificationStatus.SUPPORTED,
        VerificationStatus.UNVERIFIED,
    ]
    assert mapped.timeline[0].evidence_ids == ["frame-0003.0"]
    assert media.sample_frames.await_args.kwargs["start_s"] == 3
    assert media.sample_frames.await_args.kwargs["end_s"] == 12
    assert "canonical_evidence_frames" in result["artifact_uris"]


@pytest.mark.asyncio
async def test_cut_after_early_mapping_keeps_canonical_evidence_and_samples_final_window(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=6, t0=7, t_end=8),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[
            Claim(
                claim_id="claim-early",
                text="Vehicle was moving.",
                timestamp_s=3,
                evidence=[EvidenceReference(evidence_id="frame-000003", timestamp_s=3)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
    )
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=2, width=160, height=90, fps=5, size_bytes=100),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=12,
        frames=[
            TimestampedFrame(
                frame_id=f"review-frame-{timestamp_s}",
                sequence_index=index,
                timestamp_s=float(timestamp_s),
                delta_from_previous_s=float(bool(index)),
                image_uri=str(tmp_path / f"review-frame-{timestamp_s}.jpg"),
            )
            for index, timestamp_s in enumerate((6, 7, 8))
        ],
    )
    media = SimpleNamespace(
        cut_incident_clip=AsyncMock(return_value=clip),
        sample_frames=AsyncMock(return_value=manifest),
    )
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.NATIVE_VIDEO, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await cut_incident_video_node(
        {
            "incident_id": "INC-CUT-FINAL-WINDOW",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "canonical_evidence_mapped": True,
        },
        media=media,
        workflow=workflow,
    )

    assert media.sample_frames.await_args.kwargs["start_s"] == 6
    assert media.sample_frames.await_args.kwargs["end_s"] == 8
    assert result["video_memory"].claims[0].evidence == memory.claims[0].evidence
    assert result["video_memory"].claims[0].verification_status == VerificationStatus.SUPPORTED
    assert "claims" not in result


@pytest.mark.asyncio
async def test_native_cut_samples_semantic_timestamps_outside_incident_window(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
        representative_timestamp_s=27,
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        timeline=[
            TimelineEvent(timestamp_s=0, description="Xe bắt đầu di chuyển."),
            TimelineEvent(timestamp_s=45, description="Video kết thúc."),
        ],
        claims=[
            Claim(claim_id="claim-start", text="Xe bắt đầu di chuyển.", timestamp_s=0),
            Claim(claim_id="claim-impact", text="Xe va chạm.", timestamp_s=27),
            Claim(claim_id="claim-end", text="Video kết thúc.", timestamp_s=45),
        ],
    )
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=4, width=160, height=90, fps=5, size_bytes=100),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=45,
        frames=[
            TimestampedFrame(
                frame_id=f"frame-{index:06d}",
                sequence_index=index,
                timestamp_s=timestamp_s,
                delta_from_previous_s=timestamp_s if index else 0,
                image_uri=str(tmp_path / f"frame-{index:06d}.jpg"),
            )
            for index, timestamp_s in enumerate((0.0, 27.0, 45.0))
        ],
    )
    media = SimpleNamespace(
        cut_incident_clip=AsyncMock(return_value=clip),
        sample_frames=AsyncMock(return_value=manifest),
    )
    workflow = VideoMemoryWorkflow(
        vlm=_service(VLMInputMode.NATIVE_VIDEO, memory),
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )

    result = await cut_incident_video_node(
        {"incident_id": "INC-NARROW", "video_uri": "video.mp4", "video_memory": memory},
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "running"
    assert media.cut_incident_clip.await_args.kwargs["window"] == memory.incident_window
    assert media.sample_frames.await_args.kwargs["start_s"] == 0
    assert media.sample_frames.await_args.kwargs["end_s"] == 45
    assert [claim.evidence[0].timestamp_s for claim in result["video_memory"].claims] == [0, 27, 45]


@pytest.mark.asyncio
async def test_analyze_log_node_exposes_verification_artifacts(tmp_path: Path) -> None:
    memory = _memory(AnalysisMode.SINGLE_REQUEST, 2)
    log_uri = tmp_path / "vehicle.csv"
    log_uri.write_text("timestamp_s,speed_kmh\n0,30\n1,20\n2,10\n", encoding="utf-8")
    analysis = LogAnalysisResult(
        log_artifact_uri=str(tmp_path / "log_full_video.csv"),
        summary=LogEvidenceSummary(metrics={"speed_start": 30}, warnings=["TAKEOVER"]),
        row_count=3,
        signal_names=["timestamp_s", "speed_kmh"],
    )
    log_analysis = SimpleNamespace(analyze=AsyncMock())
    log_analysis.analyze = lambda *args, **kwargs: analysis
    chart_uri = str(tmp_path / "charts" / "01.png")
    charts = SimpleNamespace(create_charts=Mock(return_value=[chart_uri]))

    result = await analyze_log_node(
        {
            "incident_id": "INC-004",
            "log_uri": str(log_uri),
            "video_memory": memory,
            "artifact_uris": {"incident_clip": "clip.mp4"},
            "warnings": ["existing warning"],
        },
        log_analysis=log_analysis,
        charts=charts,
        artifact_dir=str(tmp_path),
    )

    assert result["status"] == "running"
    assert result["log_evidence_summary"] == analysis.summary
    assert result["chart_uris"] == [chart_uri]
    assert result["artifact_uris"]["incident_clip"] == "clip.mp4"
    assert result["artifact_uris"]["log_full_video"] == analysis.log_artifact_uri
    assert Path(result["artifact_uris"]["verification_log"]).is_file()
    assert result["warnings"] == ["existing warning", "TAKEOVER"]
    assert charts.create_charts.call_args.args[0] == str(log_uri)


@pytest.mark.asyncio
async def test_analyze_log_uses_full_telemetry_for_evidence_and_charts(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=10.5, t0=13.7, t_end=15.5),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    log_uri = tmp_path / "vehicle.csv"
    log_uri.write_text(
        "timestamp_s,speed_kmh,acceleration_mps2\n"
        "0.0,30,0\n"
        "0.05,30,0\n"
        "0.1,30,0\n"
        "0.15,30,0\n"
        "0.2,30,0\n"
        "0.25,30,0\n"
        "0.35,30,-29.555\n"
        "9.5,30,0\n"
        "10.0,30,0\n"
        "10.5,30,0\n"
        "11.0,30,0\n"
        "12.0,30,0\n"
        "13.0,30,0\n"
        "13.8,30,-6\n"
        "14.0,30,0\n"
        "15.5,30,0\n"
        "16.5,30,0\n",
        encoding="utf-8",
    )
    charts = SimpleNamespace(create_charts=Mock(return_value=[]))

    result = await analyze_log_node(
        {
            "incident_id": "INC-LOG-SCOPE",
            "log_uri": str(log_uri),
            "video_memory": memory,
            "warnings": ["existing warning"],
        },
        log_analysis=LogAnalysisService(),
        charts=charts,
        artifact_dir=str(tmp_path),
    )

    with Path(result["artifact_uris"]["log_full_video"]).open(encoding="utf-8") as file:
        full_timestamps = [float(row["timestamp_s"]) for row in csv.DictReader(file)]

    assert 0.35 in full_timestamps
    assert result["log_evidence_summary"].metrics["max_deceleration_time"] == 0.35
    assert "Log toàn video" in result["log_evidence_summary"].summary
    assert result["warnings"] == ["existing warning", *result["log_evidence_summary"].warnings]
    assert any(event.timestamp_s == 0.35 for event in charts.create_charts.call_args.kwargs["events"])
    assert any(event.timestamp_s == 0.35 for event in result["log_events"])


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


def test_incident_sampling_fps_covers_long_window_within_frame_budget() -> None:
    memory = _memory(AnalysisMode.NATIVE_VIDEO, 60)
    config = VideoMemoryWorkflowConfig(incident_frame_fps=4, incident_max_frames=60)

    assert _incident_sampling_fps(memory, config) == 1


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
        sample_radius=1,
    )

    assert result["status"] == "running"
    assert result["verification"] == verification
    assert result["claim_log_summaries"][0].claim_id == "claim-1"
    assert result["video_memory"].claims[0].verification_status == VerificationStatus.CONTRADICTED
    assert "claims" not in result
    request = verifier.verify.await_args.args[0]
    assert request.claim_log_summaries[0].sample_count == 3
    assert request.claim_log_summaries[0].sample_start_s == 1.5
    assert request.claim_log_summaries[0].sample_end_s == 2.5
    assert request.claim_log_summaries[0].metrics["brake"]["max"] == 1
    assert request.claim_verification_contexts[0].raw_telemetry.at_claim.timestamp_s == 2.0
    assert len(request.claim_verification_contexts[0].allowed_evidence_ids) <= 5


@pytest.mark.asyncio
async def test_align_and_verify_clips_claim_log_to_video_duration(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1.0, t0=1.5, t_end=2.0),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        claims=[Claim(claim_id="claim-end", text="Sự kiện cuối đoạn", timestamp_s=1.9)],
    )
    log = tmp_path / "vehicle.csv"
    log.write_text(
        "timestamp,speed_kmh,brake\n"
        "1.8,10,0\n"
        "2.0,9,0\n"
        "2.1,0,1\n",
        encoding="utf-8",
    )
    verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value=VerificationResult(
                results=[
                    ClaimVerification(
                        claim_id="claim-end",
                        status=VerificationStatus.SUPPORTED,
                        reason="Log phù hợp.",
                        evidence_ids=["log-row:2"],
                    )
                ]
            )
        )
    )

    await align_and_verify_claims_node(
        {
            "incident_id": "INC-WINDOW",
            "video_memory": memory,
            "video_duration_s": 2,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.25,
        sample_radius=3,
    )

    request = verifier.verify.await_args.args[0]
    evidence = request.claim_log_summaries[0].evidence
    assert [item.timestamp_s for item in evidence] == [1.8, 2.0]
    assert all(item.timestamp_s <= 2.0 for item in evidence)


@pytest.mark.asyncio
async def test_align_and_verify_uses_full_telemetry_for_claim_outside_incident_window(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        claims=[Claim(claim_id="claim-early", text="Xe bắt đầu di chuyển", timestamp_s=10)],
    )
    log = tmp_path / "vehicle.csv"
    log.write_text(
        "timestamp,speed_kmh,brake\n"
        "9.5,20,0\n"
        "10.0,18,0\n"
        "10.5,16,0\n"
        "45.1,0,1\n",
        encoding="utf-8",
    )
    verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value=VerificationResult(
                results=[
                    ClaimVerification(
                        claim_id="claim-early",
                        status=VerificationStatus.UNVERIFIED,
                        reason="Không đủ dữ liệu.",
                    )
                ]
            )
        )
    )

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-FULL-VIDEO-CLAIM",
            "video_memory": memory,
            "video_duration_s": 45,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
        sample_radius=10,
    )

    request = verifier.verify.await_args.args[0]
    assert result["status"] == "running"
    assert request.claim_log_summaries[0].within_tolerance is True
    assert [item.timestamp_s for item in request.claim_log_summaries[0].evidence] == [9.5, 10, 10.5]


@pytest.mark.asyncio
async def test_verification_uses_only_the_saved_full_video_log_artifact(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=6, t0=9, t_end=12),
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
        claims=[
            Claim(claim_id="claim-early", text="Xe đang di chuyển", timestamp_s=3),
            Claim(claim_id="claim-end", text="Xe tiếp tục di chuyển", timestamp_s=12),
        ],
    )
    log_uri = tmp_path / "vehicle.csv"
    log_uri.write_text(
        "timestamp_s,speed_kmh,brake\n"
        "2.5,30,0\n"
        "3.0,30,0\n"
        "3.5,30,0\n"
        "5.0,30,0\n"
        "6.0,30,0\n"
        "12.0,20,0\n"
        "12.5,20,0\n"
        "13.0,20,0\n"
        "14.0,20,0\n",
        encoding="utf-8",
    )
    charts = SimpleNamespace(create_charts=Mock(return_value=[]))
    analyzed = await analyze_log_node(
        {
            "incident_id": "INC-VERIFY-ARTIFACT",
            "log_uri": str(log_uri),
            "video_memory": memory,
            "video_duration_s": 14,
        },
        log_analysis=LogAnalysisService(),
        charts=charts,
        artifact_dir=str(tmp_path),
        timestamp_tolerance_s=0.5,
    )
    verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value=VerificationResult(
                results=[
                    ClaimVerification(
                        claim_id="claim-early",
                        status=VerificationStatus.SUPPORTED,
                        reason="Log phù hợp.",
                    ),
                    ClaimVerification(
                        claim_id="claim-end",
                        status=VerificationStatus.SUPPORTED,
                        reason="Log phù hợp.",
                    ),
                ]
            )
        )
    )

    await align_and_verify_claims_node(
        {
            "incident_id": "INC-VERIFY-ARTIFACT",
            "log_uri": str(log_uri),
            "video_memory": memory,
            "video_duration_s": 14,
            "log_evidence_summary": analyzed["log_evidence_summary"],
            "artifact_uris": analyzed["artifact_uris"],
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    with Path(analyzed["artifact_uris"]["verification_log"]).open(encoding="utf-8") as file:
        saved_timestamps = {float(row["timestamp_s"]) for row in csv.DictReader(file)}
    with Path(analyzed["artifact_uris"]["log_full_video"]).open(encoding="utf-8") as file:
        full_video_timestamps = [float(row["timestamp_s"]) for row in csv.DictReader(file)]
    request = verifier.verify.await_args.args[0]
    evidence_timestamps = [
        evidence.timestamp_s
        for summary in request.claim_log_summaries
        for evidence in summary.evidence
    ]
    assert saved_timestamps == {2.5, 3.0, 3.5, 5.0, 6.0, 12.0, 12.5, 13.0, 14.0}
    assert full_video_timestamps == [2.5, 3.0, 3.5, 5.0, 6.0, 12.0, 12.5, 13.0, 14.0]
    assert set(evidence_timestamps) <= saved_timestamps
    assert [item.timestamp_s for item in request.claim_log_summaries[0].evidence] == [2.5, 3.0, 3.5, 5.0, 6.0]
    assert [item.timestamp_s for item in request.claim_log_summaries[1].evidence] == [3.5, 5.0, 6.0, 12.0, 12.5, 13.0, 14.0]


@pytest.mark.asyncio
async def test_video_claim_becomes_supported_only_after_log_verification(tmp_path: Path) -> None:
    provider_memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        claims=[
            Claim(
                claim_id="claim-1",
                text="Vehicle brakes.",
                timestamp_s=1,
                evidence=[EvidenceReference(evidence_id="frame_7", timestamp_s=1)],
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, provider_memory)
    workflow = VideoMemoryWorkflow(vlm=service, config=VideoMemoryWorkflowConfig())
    analyzed = await workflow.analyze(
        NativeVideoAnalysisRequest(
            incident_id="INC-TRUST",
            prompt=PromptEnvelope(text="Analyze."),
            normalized_video_uri="normalized.mp4",
            metadata=NativeVideoMetadata(duration_s=2, width=1280, height=720, fps=15, size_bytes=100),
        )
    )
    assert analyzed.claims[0].verification_status == VerificationStatus.UNVERIFIED

    log = tmp_path / "vehicle.csv"
    log.write_text("timestamp,brake\n1.0,1\n", encoding="utf-8")
    verification_result = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Brake signal supports the claim.",
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock(return_value=verification_result))

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-TRUST",
            "video_memory": analyzed,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    assert result["video_memory"].claims[0].verification_status == VerificationStatus.SUPPORTED


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
async def test_auto_reanalysis_resamples_claim_window_once(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.NATIVE_VIDEO).model_copy(
        update={
            "video_summary": "Vehicle drives straight before braking.",
            "timeline": [TimelineEvent(timestamp_s=0, description="Vehicle drives straight.")],
        }
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Vehicle does not brake", timestamp_s=2)],
        video_summary="Vehicle drives before braking.",
        timeline=[TimelineEvent(timestamp_s=0, description="Vehicle drives.")],
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
    short_clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "reanalysis-claim-1.mp4"),
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )
    media = SimpleNamespace(
        sample_frames=AsyncMock(return_value=manifest),
        cut_incident_clip=AsyncMock(return_value=short_clip),
    )
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
            "artifact_uris": {"normalized_video": str(tmp_path / "normalized.mp4")},
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    assert result["status"] == "running"
    assert result["auto_reanalysis_count"] == 1
    assert result["video_memory"].claims[0].text == "Vehicle does not brake"
    assert result["video_memory"].video_summary == "Vehicle drives before braking."
    assert result["video_memory"].timeline[0].description == "Vehicle drives."
    media.sample_frames.assert_awaited_once()
    assert media.sample_frames.await_args.kwargs["start_s"] == 0
    assert media.sample_frames.await_args.kwargs["end_s"] == 3
    assert media.cut_incident_clip.await_args.kwargs["window"] == IncidentWindow(t_start=0, t0=1.5, t_end=3)
    request = service.reanalyze_claims.await_args.args[0]
    assert request.prompt.source == PromptSource.AGENT_GENERATED
    assert request.frame_manifest == manifest
    assert request.normalized_video_uri == short_clip.uri
    assert request.input_video_start_s == 0
    assert request.input_video_end_s == 3
    assert request.prompt.context == {
        "target_claims": [{"claim_id": "claim-1", "text": "Vehicle brakes", "timestamp_s": 2}],
        "verification_reasons": {"claim-1": "Log has no brake rise"},
        "reanalysis_window": [0, 3],
    }
    assert "max_brake" not in str(request.prompt.context)


@pytest.mark.asyncio
async def test_auto_reanalysis_allows_pre_cut_native_claims_without_evidence(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        claims=[
            Claim(claim_id="claim-1", text="Vehicle moves", timestamp_s=1),
            Claim(claim_id="claim-2", text="Vehicle brakes", timestamp_s=2),
        ],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-2"],
        claims=[Claim(claim_id="claim-2", text="Vehicle slows down", timestamp_s=2)],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    manifest = VideoSequenceManifest(
        frames=[
            TimestampedFrame(
                frame_id=f"frame-{index}",
                sequence_index=index,
                timestamp_s=float(index + 1),
                delta_from_previous_s=float(bool(index)),
                image_uri=f"frame-{index}.jpg",
            )
            for index in range(3)
        ],
        source_video_uri="video.mp4",
        duration_s=3,
    )
    short_clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "reanalysis-claim-2.mp4"),
        metadata=NativeVideoMetadata(duration_s=3, width=1280, height=720, fps=15, size_bytes=100),
    )
    media = SimpleNamespace(
        sample_frames=AsyncMock(return_value=manifest),
        cut_incident_clip=AsyncMock(return_value=short_clip),
    )
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-2",
                status=VerificationStatus.CONTRADICTED,
                reason="Log does not support braking.",
            )
        ]
    )

    result = await auto_reanalyze_node(
        {
            "incident_id": "INC-AUTO-PRE-CUT",
            "video_uri": "video.mp4",
            "video_memory": memory,
            "verification": verification,
            "log_evidence_summary": LogEvidenceSummary(),
            "artifact_uris": {"normalized_video": str(tmp_path / "normalized.mp4")},
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    assert result["status"] == "running"
    assert result["video_memory"].claims[0].evidence == []
    assert [item.evidence_id for item in result["video_memory"].claims[1].evidence] == ["frame-1"]
    assert service.reanalyze_claims.await_args.args[0].normalized_video_uri == short_clip.uri


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
async def test_manual_reanalysis_uses_memory_only_without_video_or_frames(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.NATIVE_VIDEO)
    handle = RemoteMediaHandle(
        provider=VLMProvider.QWEN,
        name="files/one",
        uri="provider://one",
        mime_type="video/mp4",
        local_artifact_uri=str(tmp_path / "normalized.mp4"),
    )
    reanalysis = SimpleNamespace(reanalyze_claims=AsyncMock(return_value=VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Human-reviewed claim", timestamp_s=2)],
        base_revision=1,
    )))

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
        reanalysis=reanalysis,
        prompt_version="v1",
    )

    assert result["status"] == "running"
    assert result["manual_reanalysis_count"] == 1
    assert result["manual_reanalysis_changed_claim_ids"] == ["claim-1"]
    request = reanalysis.reanalyze_claims.await_args.args[0]
    assert request.prompt.source == PromptSource.HUMAN_PROVIDED
    assert request.frame_manifest is None
    assert request.normalized_video_uri is None
    assert request.remote_media_handles == []


@pytest.mark.asyncio
async def test_manual_reanalysis_verifies_only_changed_claims_and_merges_old_results(tmp_path: Path) -> None:
    log = tmp_path / "vehicle.csv"
    log.write_text("timestamp,speed_kmh\n1.0,10\n2.0,0\n", encoding="utf-8")
    memory = VideoMemory(
        global_scene="Road",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(claim_id="claim-1", text="Changed", timestamp_s=1),
            Claim(
                claim_id="claim-2",
                text="Unchanged",
                timestamp_s=2,
                verification_status=VerificationStatus.SUPPORTED,
            ),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    previous = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Old result",
            ),
            ClaimVerification(
                claim_id="claim-2",
                status=VerificationStatus.SUPPORTED,
                reason="Keep this result",
                evidence_ids=["log-row:2"],
            ),
        ]
    )
    updated = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="New result",
                evidence_ids=["log-row:1"],
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock(return_value=updated))

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-MEMORY-VERIFY",
            "video_memory": memory,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": previous,
            "last_review_action": "reanalyze",
            "manual_reanalysis_changed_claim_ids": ["claim-1"],
        },
        verification=verifier,
        timestamp_tolerance_s=0.1,
    )

    request = verifier.verify.await_args.args[0]
    assert [claim.claim_id for claim in request.claims] == ["claim-1"]
    assert [item.claim_id for item in result["verification"].results] == ["claim-1", "claim-2"]
    assert result["verification"].results[1].reason == "Keep this result"
    assert result["video_memory"].claims[1].verification_status == VerificationStatus.SUPPORTED
    assert "claims" not in result


@pytest.mark.asyncio
async def test_manual_reanalysis_skips_verifier_when_no_claim_changed() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    previous = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Keep result",
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock())

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-NO-CHANGE",
            "video_memory": memory,
            "log_uri": "unused.csv",
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": previous,
            "last_review_action": "reanalyze",
            "manual_reanalysis_changed_claim_ids": [],
        },
        verification=verifier,
        timestamp_tolerance_s=0.1,
    )

    verifier.verify.assert_not_awaited()
    assert result["verification"] == previous


@pytest.mark.asyncio
async def test_draft_report_marks_video_only_and_unresolved_conflict() -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    contradicted = memory.claims[0].model_copy(update={"verification_status": VerificationStatus.CONTRADICTED})
    memory = memory.model_copy(update={"claims": [contradicted]})
    narrative = ReportModelOutput(
        type_of_accident="other_unknown",
        incident_window=memory.incident_window,
        representative_timestamp_s=memory.incident_window.t0,
        timeline="Timeline",
        video_observations="Video findings",
        hypothesized_causes="Possible cause",
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

    assert result["status"] == "running"
    assert result["report_narrative"].log_findings == "Không có dữ liệu log."
    assert result["draft_report"].log_findings.narrative == "Không có dữ liệu log."
    assert len(type(result["draft_report"]).model_fields) == 12
    assert result["draft_report"].type_of_accident == "other_unknown"
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

    assert result["status"] == "running"
    assert result["draft_report"].summary == memory.video_summary
    assert result["draft_report"].type_of_accident == "other_unknown"
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

    assert result["status"] == "running"
    assert result["draft_report"].summary == "Whole-video VLM summary."
    assert result["draft_report"].type_of_accident == "no_incident"
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
        warnings=["TAKEOVER"],
    )
    narrative = ReportModelOutput(
        type_of_accident="rear_end_collision",
        incident_window=memory.incident_window,
        representative_timestamp_s=memory.incident_window.t0,
        timeline="Timeline.",
        video_observations="Quan sát.",
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
            "warnings": log_summary.warnings,
        },
        report=report,
    )

    draft = result["draft_report"]
    assert draft.type_of_accident == "rear_end_collision"
    assert draft.summary == memory.global_scene
    assert draft.log_findings.narrative == log_summary.summary
    assert "claim-1 được log hỗ trợ" in draft.alignment.narrative
    assert "log-evidence:2:brake_rise" in draft.alignment.narrative
    assert draft.evidence_and_warnings.warnings == ["TAKEOVER"]


@pytest.mark.asyncio
async def test_draft_report_can_correct_default_vlm_incident_window() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=0, t_end=45),
        representative_timestamp_s=0,
        timeline=[
            TimelineEvent(timestamp_s=25, description="Xe tiến gần chướng ngại vật."),
            TimelineEvent(timestamp_s=27, description="Xe va chạm."),
            TimelineEvent(timestamp_s=29, description="Xe dừng sau va chạm."),
        ],
        claims=[Claim(claim_id="claim-impact", text="Xe va chạm tại 27 giây.", timestamp_s=27)],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    narrative = ReportModelOutput(
        type_of_accident="static_object_collision",
        incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
        representative_timestamp_s=27,
        timeline="Xe tiếp cận, va chạm rồi dừng lại.",
        video_observations="Ego va chạm vật thể tĩnh.",
        hypothesized_causes="Chưa đủ dữ liệu xác định nguyên nhân.",
    )
    report = SimpleNamespace(build_narrative=AsyncMock(return_value=narrative))

    result = await build_draft_report_node(
        {
            "incident_id": "INC-REPORT-CORRECTION",
            "video_uri": "video.mp4",
            "video_memory": memory,
        },
        report=report,
    )

    corrected = result["video_memory"]
    assert corrected.incident_window == IncidentWindow(t_start=25, t0=27, t_end=29)
    assert corrected.representative_timestamp_s == 27
    assert result["draft_report"].incident_window == corrected.incident_window
    assert result["draft_report"].representative_timestamp_s == 27


@pytest.mark.asyncio
async def test_draft_report_keeps_vlm_geometry_for_no_incident() -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=0, t_end=45),
        representative_timestamp_s=0,
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    narrative = ReportModelOutput(
        type_of_accident="no_incident",
        incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
        representative_timestamp_s=27,
        timeline="Xe tiếp tục di chuyển bình thường.",
        video_observations="Không phát hiện tai nạn.",
        hypothesized_causes="Không áp dụng phân tích nguyên nhân tai nạn.",
    )
    report = SimpleNamespace(build_narrative=AsyncMock(return_value=narrative))

    result = await build_draft_report_node(
        {
            "incident_id": "INC-REPORT-NO-INCIDENT",
            "video_uri": "video.mp4",
            "video_memory": memory,
        },
        report=report,
    )

    assert result["video_memory"].incident_window == memory.incident_window
    assert result["video_memory"].representative_timestamp_s == 0


@pytest.mark.asyncio
async def test_cut_after_report_uses_report_corrected_incident_window(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=0, t0=0, t_end=45),
        representative_timestamp_s=0,
        timeline=[TimelineEvent(timestamp_s=27, description="Xe va chạm.")],
        claims=[Claim(claim_id="claim-impact", text="Xe va chạm tại 27 giây.", timestamp_s=27)],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    report = SimpleNamespace(
        build_narrative=AsyncMock(
            return_value=ReportModelOutput(
                type_of_accident="static_object_collision",
                incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
                representative_timestamp_s=27,
                timeline="Xe va chạm rồi dừng lại.",
                video_observations="Ego va chạm vật thể tĩnh.",
                hypothesized_causes="Chưa đủ dữ liệu xác định nguyên nhân.",
            )
        )
    )
    report_result = await build_draft_report_node(
        {
            "incident_id": "INC-CUT-AFTER-REPORT",
            "video_uri": "video.mp4",
            "video_memory": memory,
        },
        report=report,
    )
    clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "incident_clip.mp4"),
        metadata=NativeVideoMetadata(duration_s=4, width=160, height=90, fps=5, size_bytes=100),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=45,
        frames=[
            TimestampedFrame(
                frame_id="frame-000027",
                sequence_index=0,
                timestamp_s=27,
                delta_from_previous_s=0,
                image_uri=str(tmp_path / "frame-000027.jpg"),
            )
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
        {
            "incident_id": "INC-CUT-AFTER-REPORT",
            "video_uri": "video.mp4",
            "video_memory": report_result["video_memory"],
            "draft_report": report_result["draft_report"],
            "report_narrative": report_result["report_narrative"],
            "warnings": report_result["warnings"],
        },
        media=media,
        workflow=workflow,
    )

    assert result["status"] == "awaiting_review"
    assert media.cut_incident_clip.await_args.kwargs["window"] == IncidentWindow(t_start=25, t0=27, t_end=29)
    assert result["draft_report"].evidence_and_warnings.artifact_uris["incident_clip"] == clip.uri
    assert result["draft_report"].representative_timestamp_s == 27


@pytest.mark.asyncio
async def test_conflict_can_be_reanalyzed_once_then_verified_supported(tmp_path: Path) -> None:
    memory = _claim_memory(AnalysisMode.SINGLE_REQUEST)
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Revised braking claim", timestamp_s=2)],
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
    log = tmp_path / "vehicle.csv"
    log.write_text("timestamp,brake\n2.0,1\n", encoding="utf-8")

    verified = await align_and_verify_claims_node(
        {
            "incident_id": "INC-RESOLVED",
            "video_memory": reanalyzed["video_memory"],
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": conflict,
            "auto_reanalysis_changed_claim_ids": reanalyzed["auto_reanalysis_changed_claim_ids"],
        },
        verification=verifier,
        timestamp_tolerance_s=0.5,
    )

    assert reanalyzed["auto_reanalysis_count"] == 1
    assert verified["video_memory"].claims[0].verification_status == VerificationStatus.SUPPORTED
    assert "claims" not in verified
    service.reanalyze_claims.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_reanalysis_reverifies_only_changed_claim_and_keeps_supported_result(tmp_path: Path) -> None:
    """A retry for one conflict must not degrade an unrelated verified claim."""
    log = tmp_path / "vehicle.csv"
    log.write_text(
        "timestamp,speed_kmh\n"
        "1.0,20\n"
        "2.0,18\n",
        encoding="utf-8",
    )
    memory = VideoMemory(
        global_scene="Road",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Corrected target claim",
                timestamp_s=1,
                verification_status=VerificationStatus.UNVERIFIED,
            ),
            Claim(
                claim_id="claim-4",
                text="Unchanged supported claim",
                timestamp_s=2,
                verification_status=VerificationStatus.SUPPORTED,
            ),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    prior = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Old contradiction",
            ),
            ClaimVerification(
                claim_id="claim-4",
                status=VerificationStatus.SUPPORTED,
                reason="Keep this prior result",
                evidence_ids=["log-row:2"],
            ),
        ]
    )
    reverified = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.SUPPORTED,
                reason="Corrected claim matches telemetry",
                evidence_ids=["log-row:1"],
            )
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock(return_value=reverified))

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-AUTO-SELECTIVE-VERIFY",
            "video_memory": memory,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": prior,
            "auto_reanalysis_changed_claim_ids": ["claim-1"],
        },
        verification=verifier,
        timestamp_tolerance_s=0.1,
    )

    request = verifier.verify.await_args.args[0]
    assert [claim.claim_id for claim in request.claims] == ["claim-1"]
    assert [item.claim_id for item in result["verification"].results] == ["claim-1", "claim-4"]
    assert result["verification"].results[1].reason == "Keep this prior result"
    assert result["video_memory"].claims[1].verification_status == VerificationStatus.SUPPORTED


@pytest.mark.asyncio
async def test_auto_reanalysis_drop_removes_old_result_without_rechecking_untouched_claim(tmp_path: Path) -> None:
    """When a focused clip cannot support a target, only that target is removed."""
    log = tmp_path / "vehicle.csv"
    log.write_text("timestamp,speed_kmh\n2.0,18\n", encoding="utf-8")
    memory = VideoMemory(
        global_scene="Road",
        incident_window=IncidentWindow(t_start=0, t0=1, t_end=2),
        claims=[
            Claim(
                claim_id="claim-4",
                text="Unchanged supported claim",
                timestamp_s=2,
                verification_status=VerificationStatus.SUPPORTED,
            )
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    prior = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Target was contradicted before focused reanalysis",
            ),
            ClaimVerification(
                claim_id="claim-4",
                status=VerificationStatus.SUPPORTED,
                reason="Keep this prior result",
                evidence_ids=["log-row:1"],
            ),
        ]
    )
    verifier = SimpleNamespace(verify=AsyncMock())

    result = await align_and_verify_claims_node(
        {
            "incident_id": "INC-AUTO-DROPPED-TARGET",
            "video_memory": memory,
            "log_uri": str(log),
            "log_evidence_summary": LogEvidenceSummary(),
            "verification": prior,
            "auto_reanalysis_changed_claim_ids": ["claim-1"],
        },
        verification=verifier,
        timestamp_tolerance_s=0.1,
    )

    verifier.verify.assert_not_awaited()
    assert [item.claim_id for item in result["verification"].results] == ["claim-4"]
    assert result["verification"].results[0].reason == "Keep this prior result"
    assert result["video_memory"].claims[0].verification_status == VerificationStatus.SUPPORTED


@pytest.mark.asyncio
async def test_auto_reanalysis_uses_short_native_clip_with_global_source_window(tmp_path: Path) -> None:
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=25, t0=27, t_end=29),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Vehicle begins turning.",
                timestamp_s=26.5,
                evidence=[EvidenceReference(evidence_id="frame-before", timestamp_s=26.5)],
                verification_status=VerificationStatus.CONTRADICTED,
            )
        ],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )
    service = _service(VLMInputMode.NATIVE_VIDEO, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1"],
        claims=[Claim(claim_id="claim-1", text="Vehicle turns right.", timestamp_s=26.5)],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=45,
        frames=[
            TimestampedFrame(
                frame_id="frame-000001",
                sequence_index=0,
                timestamp_s=26.5,
                delta_from_previous_s=0,
                image_uri=str(tmp_path / "frame-000001.jpg"),
            )
        ],
    )
    short_clip = NormalizedVideoArtifact(
        uri=str(tmp_path / "INC-SHORT" / "reanalysis_clips" / "claim-1.mp4"),
        metadata=NativeVideoMetadata(duration_s=4, width=1280, height=720, fps=15, size_bytes=100),
    )
    media = SimpleNamespace(
        sample_frames=AsyncMock(return_value=manifest),
        cut_incident_clip=AsyncMock(return_value=short_clip),
    )
    prior = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Telemetry does not support the original turn claim.",
            )
        ]
    )
    normalized_video_uri = str(tmp_path / "INC-SHORT" / "normalized.mp4")

    result = await auto_reanalyze_node(
        {
            "incident_id": "INC-SHORT",
            "video_uri": "video.mp4",
            "video_duration_s": 45,
            "video_memory": memory,
            "verification": prior,
            "log_evidence_summary": LogEvidenceSummary(),
            "artifact_uris": {"normalized_video": normalized_video_uri},
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    expected_window = IncidentWindow(t_start=24.5, t0=26.5, t_end=28.5)
    clip_call = media.cut_incident_clip.await_args
    assert clip_call.args[0] == normalized_video_uri
    assert clip_call.kwargs["window"] == expected_window
    assert clip_call.kwargs["min_duration_s"] == 4
    assert clip_call.kwargs["pre_roll_s"] == 0
    assert clip_call.kwargs["post_roll_s"] == 0
    assert media.sample_frames.await_args.kwargs["start_s"] == 24.5
    assert media.sample_frames.await_args.kwargs["end_s"] == 28.5
    request = service.reanalyze_claims.await_args.args[0]
    assert request.normalized_video_uri == short_clip.uri
    assert request.input_video_start_s == 24.5
    assert request.input_video_end_s == 28.5
    assert "automatic reanalysis, không phải phân tích video ban đầu" in request.prompt.text
    assert request.prompt.context == {
        "target_claims": [{"claim_id": "claim-1", "text": "Vehicle begins turning.", "timestamp_s": 26.5}],
        "verification_reasons": {"claim-1": "Telemetry does not support the original turn claim."},
        "reanalysis_window": [24.5, 28.5],
    }
    assert result["auto_reanalysis_changed_claim_ids"] == ["claim-1"]


@pytest.mark.asyncio
async def test_auto_reanalysis_never_accepts_target_timestamp_more_than_two_seconds_from_original(
    tmp_path: Path,
) -> None:
    """An overlap group cannot widen the allowed correction range of an individual claim."""
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=8, t0=11, t_end=14),
        claims=[
            Claim(claim_id="claim-1", text="First event", timestamp_s=10),
            Claim(claim_id="claim-2", text="Second event", timestamp_s=12),
        ],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    service = _service(VLMInputMode.TIMESTAMPED_FRAMES, memory)
    service.reanalyze_claims.return_value = VideoMemoryPatch(
        target_claim_ids=["claim-1", "claim-2"],
        claims=[
            Claim(claim_id="claim-1", text="Incorrectly moved event", timestamp_s=12.5),
            Claim(claim_id="claim-2", text="Second event", timestamp_s=12),
        ],
        base_revision=1,
    )
    workflow = VideoMemoryWorkflow(
        vlm=service,
        config=VideoMemoryWorkflowConfig(artifact_dir=str(tmp_path)),
    )
    manifest = VideoSequenceManifest(
        source_video_uri="video.mp4",
        duration_s=20,
        frames=[
            TimestampedFrame(
                frame_id=f"frame-{index}",
                sequence_index=index,
                timestamp_s=timestamp_s,
                delta_from_previous_s=0 if index == 0 else timestamp_s - (10 if index == 1 else 12),
                image_uri=str(tmp_path / f"frame-{index}.jpg"),
            )
            for index, timestamp_s in enumerate((10.0, 12.0, 12.5))
        ],
    )
    media = SimpleNamespace(sample_frames=AsyncMock(return_value=manifest))
    conflicts = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="First event conflicts with telemetry.",
            ),
            ClaimVerification(
                claim_id="claim-2",
                status=VerificationStatus.CONTRADICTED,
                reason="Second event conflicts with telemetry.",
            ),
        ]
    )

    result = await auto_reanalyze_node(
        {
            "incident_id": "INC-PER-CLAIM-BOUND",
            "video_uri": "video.mp4",
            "video_duration_s": 20,
            "video_memory": memory,
            "verification": conflicts,
            "log_evidence_summary": LogEvidenceSummary(),
            "auto_reanalysis_count": 0,
        },
        media=media,
        workflow=workflow,
        prompt_version="v1",
    )

    request = service.reanalyze_claims.await_args.args[0]
    assert request.input_video_start_s == 8
    assert request.input_video_end_s == 14
    assert result["status"] == "failed"
    assert result["error_code"] == "AUTO_REANALYSIS_FAILED"
    assert "more than two seconds" in result["error_message"]
