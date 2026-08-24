"""Video-analysis node wired only to provider-neutral dependencies."""

from __future__ import annotations

import asyncio
import math
import re
import shutil
from pathlib import Path
from typing import Protocol

from src.agents.incident_state import IncidentState
from src.models.incidents import (
    AccidentType,
    Claim,
    ClaimVerification,
    DraftReport,
    IncidentWindow,
    LogAnalysisResult,
    LogEvent,
    LogEvidenceSummary,
    MemoryReanalysisService,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    ReanalysisRequest,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportModelOutput,
    ReportNarrative,
    ReportRequest,
    ReportService,
    ReportTimelineSection,
    ReportVideoObservationsSection,
    TimestampedFramesAnalysisRequest,
    VerificationRequest,
    VerificationResult,
    VerificationService,
    VerificationStatus,
    VideoMemory,
    VideoSequenceManifest,
    VLMInputMode,
)
from src.prompts.auto_reanalysis import build_auto_reanalysis_prompt_for_conflicts
from src.prompts.reanalysis import build_human_reanalysis_prompt
from src.prompts.video_analysis import build_video_analysis_prompt
from src.services.log_analysis import (
    LogAnalysisError,
    build_claim_verification_inputs,
    build_log_attention_hint,
    build_verification_log_artifact,
)
from src.services.media import NormalizedVideoArtifact
from src.services.video_memory import (
    VideoMemoryError,
    VideoMemoryWorkflow,
    VideoMemoryWorkflowConfig,
    merge_memory_only_patch,
    merge_video_memory_patch,
    reconcile_native_video_evidence,
    reconcile_video_memory_patch_evidence,
    validate_video_memory,
)

# Product requirement: each contradicted claim receives at most two seconds of
# visual context on either side unless its short windows overlap another claim.
REANALYSIS_CLIP_RADIUS_S = 2.0


class MediaWorkflowService(Protocol):
    async def redact_video(self, video_uri: str, output_uri: str) -> NormalizedVideoArtifact: ...

    async def cut_incident_clip(
        self,
        video_uri: str,
        output_uri: str,
        *,
        window: IncidentWindow,
        codec: str,
        pixel_format: str,
        min_duration_s: float,
        pre_roll_s: float,
        post_roll_s: float,
        output_fps: float | None = None,
    ) -> NormalizedVideoArtifact: ...

    async def sample_frames(
        self,
        video_uri: str,
        output_dir: str,
        *,
        fps: float,
        width: int,
        height: int,
        image_format: str,
        jpeg_quality: int,
        max_frames: int,
        start_s: float = 0.0,
        end_s: float | None = None,
    ) -> VideoSequenceManifest: ...

    async def normalize_video(
        self,
        video_uri: str,
        output_uri: str,
        *,
        width: int,
        height: int,
        fps: float,
        codec: str,
        pixel_format: str,
        max_output_bytes: int,
        max_duration_s: float = 60.0,
    ) -> NormalizedVideoArtifact: ...


class LogWorkflowService(Protocol):
    def analyze(
        self,
        log_uri: str,
        output_uri: str,
        *,
        video_duration_s: float | None = None,
    ) -> LogAnalysisResult: ...


class ChartWorkflowService(Protocol):
    def create_charts(
        self,
        log_uri: str,
        output_dir: str,
        *,
        window: IncidentWindow,
        events: list[LogEvent],
        claims: list[Claim],
    ) -> list[str]: ...


async def analyze_video_node(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    video_uri = state.get("video_uri", "").strip()
    analysis_prompt = state.get("analysis_prompt", "").strip()
    if not incident_id or not video_uri or not analysis_prompt:
        return {
            "status": "failed",
            "error_code": "VIDEO_ANALYSIS_INPUT_INVALID",
            "error_message": "incident_id, video_uri, and analysis_prompt are required",
        }

    config = workflow.config
    artifact_root = Path(config.artifact_dir).resolve() / _safe_incident_id(incident_id)
    mode = workflow.vlm.capabilities.input_mode
    prompt = build_video_analysis_prompt(
        analysis_prompt=analysis_prompt,
        input_mode=mode,
        log_attention_hint="",
        version=config.prompt_version,
    )
    processed_video_uri = video_uri
    try:
        if mode == VLMInputMode.TIMESTAMPED_FRAMES:
            manifest = await media.sample_frames(
                video_uri,
                str(artifact_root / "frames"),
                fps=config.frame_fps,
                width=config.frame_width,
                height=config.frame_height,
                image_format=config.frame_format,
                jpeg_quality=config.frame_jpeg_quality,
                max_frames=config.max_frames,
            )
            request = TimestampedFramesAnalysisRequest(
                incident_id=incident_id,
                prompt=prompt,
                manifest=manifest,
            )
            video_duration_s = manifest.duration_s
            artifact_uris = {"frames": str(artifact_root / "frames")}
        else:
            if config.video_redaction_enabled:
                normalized_source = artifact_root / "normalized_source.mp4"
                normalized = await media.normalize_video(
                    video_uri,
                    str(normalized_source),
                    width=config.video_target_width,
                    height=config.video_target_height,
                    fps=config.video_target_fps,
                    codec=config.video_codec,
                    pixel_format=config.video_pixel_format,
                    max_output_bytes=config.video_max_output_bytes,
                    max_duration_s=config.max_duration_s,
                )
                try:
                    processed_video = await media.redact_video(
                        normalized.uri,
                        str(artifact_root / "normalized.mp4"),
                    )
                finally:
                    normalized_source.unlink(missing_ok=True)
            else:
                processed_video = await media.normalize_video(
                    video_uri,
                    str(artifact_root / "normalized.mp4"),
                    width=config.video_target_width,
                    height=config.video_target_height,
                    fps=config.video_target_fps,
                    codec=config.video_codec,
                    pixel_format=config.video_pixel_format,
                    max_output_bytes=config.video_max_output_bytes,
                    max_duration_s=config.max_duration_s,
                )
            request = NativeVideoAnalysisRequest(
                incident_id=incident_id,
                prompt=prompt,
                normalized_video_uri=processed_video.uri,
                metadata=NativeVideoMetadata.model_validate(processed_video.metadata),
            )
            video_duration_s = request.metadata.duration_s
            artifact_uris = {"normalized_video": processed_video.uri}
            processed_video_uri = processed_video.uri

        log_attention_hint = ""
        log_uri = (state.get("log_uri") or "").strip()
        if log_uri:
            try:
                log_attention_hint = build_log_attention_hint(log_uri, video_duration_s=video_duration_s)
            except LogAnalysisError:
                # Log validation still runs in its existing workflow node; a hint must never block video analysis.
                pass
        prompt = build_video_analysis_prompt(
            analysis_prompt=analysis_prompt,
            input_mode=mode,
            log_attention_hint=log_attention_hint,
            version=config.prompt_version,
        )
        request = request.model_copy(update={"prompt": prompt})
        memory = await workflow.analyze(request)
        return {
            "status": "running",
            "video_uri": processed_video_uri,
            "review_video_uri": state.get("review_video_uri") or video_uri,
            "video_memory": memory,
            "video_duration_s": video_duration_s,
            "remote_media_handles": memory.remote_media_handles,
            "artifact_uris": {**state.get("artifact_uris", {}), **artifact_uris},
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error_code": getattr(exc, "code", "VIDEO_ANALYSIS_FAILED"),
            "error_message": str(exc),
        }


async def cut_incident_video_node(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    video_uri = state.get("video_uri", "").strip()
    memory = state.get("video_memory")
    if not incident_id or not video_uri or memory is None:
        return {
            "status": "failed",
            "error_code": "INCIDENT_CLIP_INPUT_INVALID",
            "error_message": "incident_id, video_uri, and video_memory are required",
        }

    config = workflow.config
    artifact_root = Path(config.artifact_dir).resolve() / _safe_incident_id(incident_id)
    frame_dir = artifact_root / "incident_frames"
    try:
        review_video_uri = state.get("review_video_uri", "").strip()
        review_source_uri = review_video_uri or video_uri
        clip_options = {
            "codec": config.video_codec,
            "pixel_format": config.video_pixel_format,
            "min_duration_s": config.incident_clip_min_duration_s,
            "pre_roll_s": config.incident_clip_pre_roll_s,
            "post_roll_s": config.incident_clip_post_roll_s,
        }
        final_clip_uri = str(artifact_root / "incident_clip.mp4")
        if review_video_uri and config.video_redaction_enabled:
            raw_clip_path = artifact_root / "incident_clip_source.mp4"
            redacted_clip_path = artifact_root / "incident_clip_redacted.mp4"
            try:
                raw_clip = await media.cut_incident_clip(
                    review_source_uri,
                    str(raw_clip_path),
                    window=memory.incident_window,
                    **clip_options,
                )
                redacted_clip = await media.redact_video(raw_clip.uri, str(redacted_clip_path))
                redacted_duration = redacted_clip.metadata.duration_s
                clip = await media.cut_incident_clip(
                    redacted_clip.uri,
                    final_clip_uri,
                    window=IncidentWindow(
                        t_start=0,
                        t0=redacted_duration / 2,
                        t_end=redacted_duration,
                    ),
                    codec=config.video_codec,
                    pixel_format=config.video_pixel_format,
                    min_duration_s=redacted_duration,
                    pre_roll_s=0,
                    post_roll_s=0,
                    output_fps=config.incident_clip_display_fps,
                )
            finally:
                raw_clip_path.unlink(missing_ok=True)
                redacted_clip_path.unlink(missing_ok=True)
        else:
            clip = await media.cut_incident_clip(
                review_source_uri,
                final_clip_uri,
                window=memory.incident_window,
                output_fps=config.incident_clip_display_fps,
                **clip_options,
            )
        # Canonical evidence is mapped before log verification.  The late cut is
        # intentionally only a review artifact built from the final report window.
        # Keep the legacy semantic sampling fallback for direct callers that have
        # not yet passed through the mapping node.
        canonical_evidence_mapped = state.get("canonical_evidence_mapped", False)
        sample_start_s, sample_end_s = (
            (memory.incident_window.t_start, memory.incident_window.t_end)
            if canonical_evidence_mapped or workflow.vlm.capabilities.input_mode != VLMInputMode.NATIVE_VIDEO
            else _semantic_sampling_bounds(memory)
        )
        frames = await media.sample_frames(
            video_uri,
            str(frame_dir),
            fps=_incident_sampling_fps(
                memory,
                config,
                start_s=sample_start_s,
                end_s=sample_end_s,
            ),
            width=config.frame_width,
            height=config.frame_height,
            image_format=config.frame_format,
            jpeg_quality=config.frame_jpeg_quality,
            max_frames=config.incident_max_frames,
            start_s=sample_start_s,
            end_s=sample_end_s,
        )
        if not frames.frames:
            raise VideoMemoryError(
                "INCIDENT_REVIEW_FRAMES_MISSING",
                "review artifacts require at least one sampled incident frame",
            )
        if workflow.vlm.capabilities.input_mode == VLMInputMode.NATIVE_VIDEO and not canonical_evidence_mapped:
            memory = reconcile_native_video_evidence(memory, frames.frames)
            memory = _restore_claim_verification_statuses(memory, state.get("video_memory"))
            validate_video_memory(
                memory,
                source_duration_s=frames.duration_s,
                source_frame_ids={frame.frame_id for frame in frames.frames},
                expected_analysis_mode=memory.analysis_mode,
                limits=config.limits,
            )
        artifact_uris = {
            **state.get("artifact_uris", {}),
            "incident_clip": clip.uri,
            "incident_frames": str(frame_dir),
        }
        await _materialize_canonical_evidence_frames(
            memory,
            canonical_frame_dir=state.get("artifact_uris", {}).get("canonical_evidence_frames"),
            incident_frame_dir=frame_dir,
        )
        target_timestamp_s = _representative_timestamp(memory)
        representative = min(frames.frames, key=lambda frame: abs(frame.timestamp_s - target_timestamp_s))
        artifact_uris["representative_frame"] = representative.image_uri
        output: dict[str, object] = {
            "status": "awaiting_review" if state.get("draft_report") is not None else "running",
            "artifact_uris": artifact_uris,
            "video_memory": memory,
        }
        output.update(_refresh_report_after_cut(state, memory=memory, artifact_uris=artifact_uris))
        return output
    except Exception as exc:
        return {
            "status": "failed",
            "error_code": getattr(exc, "code", "INCIDENT_CLIP_FAILED"),
            "error_message": str(exc),
        }


async def map_canonical_evidence_node(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
) -> dict[str, object]:
    """Map native VLM timestamps to real frames before verification/reporting.

    Native VLM output intentionally has no provider-owned frame IDs.  This node
    samples the semantic span of the source video and establishes canonical frame
    evidence before telemetry verification.  The later cut node remains solely
    responsible for the user-facing incident clip using the final report window.
    """
    incident_id = state.get("incident_id", "").strip()
    video_uri = state.get("video_uri", "").strip()
    memory = state.get("video_memory")
    if not incident_id or not video_uri or memory is None:
        return _failure(
            "CANONICAL_EVIDENCE_INPUT_INVALID",
            "incident_id, video_uri, and video_memory are required",
        )

    if workflow.vlm.capabilities.input_mode != VLMInputMode.NATIVE_VIDEO:
        return {
            "status": "running",
            "video_memory": memory,
            "canonical_evidence_mapped": True,
        }
    if not memory.claims and not memory.timeline:
        return {
            "status": "running",
            "video_memory": memory,
            "canonical_evidence_mapped": True,
        }

    config = workflow.config
    artifact_root = Path(config.artifact_dir).resolve() / _safe_incident_id(incident_id)
    frame_dir = artifact_root / "canonical_evidence_frames"
    sample_start_s, sample_end_s = _semantic_sampling_bounds(memory)
    # Native analysis may intentionally use a low-FPS normalized video. Pad by
    # one real source frame so an event on the exclusive FFmpeg end boundary is
    # still available for canonical evidence mapping.
    source_fps = config.video_target_fps
    source_frame_interval_s = 1.0 / source_fps
    duration_s = _video_duration_s(state, memory)
    sample_start_s = max(0.0, math.floor(sample_start_s * source_fps) / source_fps)
    sample_end_s = min(
        duration_s,
        math.ceil(sample_end_s * source_fps) / source_fps + source_frame_interval_s,
    )
    try:
        frames = await media.sample_frames(
            video_uri,
            str(frame_dir),
            fps=_incident_sampling_fps(
                memory,
                config,
                start_s=sample_start_s,
                end_s=sample_end_s,
            ),
            width=config.frame_width,
            height=config.frame_height,
            image_format=config.frame_format,
            jpeg_quality=config.frame_jpeg_quality,
            max_frames=config.incident_max_frames,
            start_s=sample_start_s,
            end_s=sample_end_s,
        )
        mapped = reconcile_native_video_evidence(memory, frames.frames)
        mapped = _restore_claim_verification_statuses(mapped, memory)
        validate_video_memory(
            mapped,
            source_duration_s=_video_duration_s(state, memory),
            source_frame_ids={frame.frame_id for frame in frames.frames},
            expected_analysis_mode=mapped.analysis_mode,
            limits=config.limits,
        )
        return {
            "status": "running",
            "video_memory": mapped,
            "canonical_evidence_mapped": True,
            "artifact_uris": {
                **state.get("artifact_uris", {}),
                "canonical_evidence_frames": str(frame_dir),
            },
        }
    except Exception as exc:
        return _failure(getattr(exc, "code", "CANONICAL_EVIDENCE_MAPPING_FAILED"), str(exc))


async def _materialize_canonical_evidence_frames(
    memory: VideoMemory,
    *,
    canonical_frame_dir: str | None,
    incident_frame_dir: Path,
) -> None:
    """Copy canonical evidence under stable IDs into the review-frame directory."""
    if not canonical_frame_dir:
        return
    source_dir = Path(canonical_frame_dir)
    if not source_dir.is_dir():
        return
    evidence_ids = {evidence.evidence_id for claim in memory.claims for evidence in claim.evidence} | {
        evidence_id for event in memory.timeline for evidence_id in event.evidence_ids
    }
    for evidence_id in evidence_ids:
        for extension in (".jpg", ".png"):
            source = source_dir / f"{evidence_id}{extension}"
            if source.is_file():
                destination = incident_frame_dir / source.name
                if source.resolve() != destination.resolve():
                    await asyncio.to_thread(shutil.copy2, source, destination)
                break


def _restore_claim_verification_statuses(
    mapped: VideoMemory,
    original: VideoMemory | object | None,
) -> VideoMemory:
    """Reconciliation changes evidence only; it must not invalidate verification."""
    if not isinstance(original, VideoMemory):
        return mapped
    status_by_claim_id = {claim.claim_id: claim.verification_status for claim in original.claims}
    return mapped.model_copy(
        update={
            "claims": [
                claim.model_copy(
                    update={
                        "verification_status": status_by_claim_id.get(
                            claim.claim_id,
                            claim.verification_status,
                        )
                    }
                )
                for claim in mapped.claims
            ]
        }
    )


def _project_verification_statuses(memory: VideoMemory, verification: VerificationResult) -> VideoMemory:
    """Mirror the canonical verification result into UI-facing claim status."""
    status_by_claim_id = {item.claim_id: item.status for item in verification.results}
    return memory.model_copy(
        update={
            "claims": [
                claim.model_copy(
                    update={"verification_status": status_by_claim_id.get(claim.claim_id, claim.verification_status)}
                )
                for claim in memory.claims
            ]
        }
    )


async def analyze_log_node(
    state: IncidentState,
    *,
    log_analysis: LogWorkflowService,
    charts: ChartWorkflowService,
    artifact_dir: str,
    timestamp_tolerance_s: float = 0.5,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    log_uri = (state.get("log_uri") or "").strip()
    memory = state.get("video_memory")
    if not incident_id or not log_uri or memory is None:
        return {
            "status": "failed",
            "error_code": "LOG_ANALYSIS_INPUT_INVALID",
            "error_message": "incident_id, log_uri, and video_memory are required",
        }

    artifact_root = Path(artifact_dir).resolve() / _safe_incident_id(incident_id)
    telemetry_duration_s = _telemetry_duration_s(state, memory)
    try:
        result = log_analysis.analyze(
            log_uri,
            str(artifact_root / "log_full_video.csv"),
            video_duration_s=telemetry_duration_s,
        )
        verification_log_uri = build_verification_log_artifact(
            log_uri,
            str(artifact_root / "verification_log.csv"),
            video_duration_s=telemetry_duration_s,
        )
        chart_uris = charts.create_charts(
            log_uri,
            str(artifact_root / "charts"),
            window=memory.incident_window,
            events=result.events,
            claims=memory.claims,
        )
        artifact_uris = {
            **state.get("artifact_uris", {}),
            "log_full_video": result.log_artifact_uri,
            "verification_log": verification_log_uri,
            **{f"chart_{index}": uri for index, uri in enumerate(chart_uris, start=1)},
        }
        return {
            "status": "running",
            "log_analysis": result,
            "log_evidence_summary": result.summary,
            "log_events": result.events,
            "chart_uris": chart_uris,
            "artifact_uris": artifact_uris,
            "warnings": list(dict.fromkeys([*state.get("warnings", []), *result.summary.warnings])),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error_code": getattr(exc, "code", "LOG_ANALYSIS_FAILED"),
            "error_message": str(exc),
        }


async def align_and_verify_claims_node(
    state: IncidentState,
    *,
    verification: VerificationService,
    timestamp_tolerance_s: float,
    sample_radius: int = 3,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    memory = state.get("video_memory")
    log_summary = state.get("log_evidence_summary")
    log_uri = (state.get("log_uri") or "").strip()
    if not incident_id or memory is None or log_summary is None or not log_uri:
        return {
            "status": "failed",
            "error_code": "VERIFICATION_INPUT_INVALID",
            "error_message": "incident_id, video_memory, log_uri, and log_evidence_summary are required",
        }
    changed_ids = _reanalysis_changed_claim_ids(state)
    telemetry_duration_s = _telemetry_duration_s(state, memory)
    try:
        artifact_uris = dict(state.get("artifact_uris", {}))
        verification_log_uri = artifact_uris.get("verification_log")
        verification_input_uri = log_uri
        if verification_log_uri:
            verification_input_uri = build_verification_log_artifact(
                log_uri,
                verification_log_uri,
                video_duration_s=telemetry_duration_s,
            )
            artifact_uris["verification_log"] = verification_input_uri
        if changed_ids == []:
            return {
                "status": "running",
                "verification": state.get("verification"),
                "video_memory": memory,
                "claim_log_summaries": state.get("claim_log_summaries", []),
            }
        claims_to_verify = (
            [claim for claim in memory.claims if claim.claim_id in set(changed_ids)]
            if changed_ids is not None
            else memory.claims
        )
        if claims_to_verify:
            claim_log_summaries, claim_verification_contexts = build_claim_verification_inputs(
                verification_input_uri,
                claims_to_verify,
                timestamp_tolerance_s=timestamp_tolerance_s,
                sample_radius=sample_radius,
                video_duration_s=telemetry_duration_s,
            )
            result = await verification.verify(
                VerificationRequest(
                    incident_id=incident_id,
                    claims=claims_to_verify,
                    claim_log_summaries=claim_log_summaries,
                    claim_verification_contexts=claim_verification_contexts,
                    timestamp_tolerance_s=timestamp_tolerance_s,
                )
            )
        else:
            claim_log_summaries = []
            result = VerificationResult(results=[])
        if changed_ids is not None:
            result, claim_log_summaries = _merge_selective_verification(
                memory,
                previous_verification=state.get("verification"),
                next_verification=result,
                previous_summaries=state.get("claim_log_summaries", []),
                next_summaries=claim_log_summaries,
                changed_claim_ids=set(changed_ids),
            )
        memory = _project_verification_statuses(memory, result)
        output: dict[str, object] = {
            "status": "running",
            "verification": result,
            "claim_log_summaries": claim_log_summaries,
            "video_memory": memory,
        }
        if verification_log_uri:
            output["artifact_uris"] = artifact_uris
        return output
    except Exception as exc:
        warning = (
            f"{getattr(exc, 'code', 'CLAIM_VERIFICATION_FAILED')}: verification unavailable; "
            "processing continued without a verification result."
        )
        if changed_ids is not None:
            changed_id_set = set(changed_ids)
            previous = state.get("verification")
            preserved = [
                item
                for item in (previous.results if previous is not None else [])
                if item.claim_id not in changed_id_set
                and any(claim.claim_id == item.claim_id for claim in memory.claims)
            ]
            preserved.extend(
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=VerificationStatus.UNVERIFIED,
                    reason="Không thể xác thực lại claim sau reanalysis.",
                    evidence_ids=[],
                )
                for claim in memory.claims
                if claim.claim_id in changed_id_set
            )
            fallback_verification = VerificationResult(results=preserved)
            return {
                "status": "running",
                "verification": fallback_verification,
                "video_memory": _project_verification_statuses(memory, fallback_verification),
                "warnings": list(dict.fromkeys([*state.get("warnings", []), warning])),
            }
        return {
            "status": "running",
            "verification": None,
            "video_memory": memory,
            "warnings": list(dict.fromkeys([*state.get("warnings", []), warning])),
        }


async def auto_reanalyze_node(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
    prompt_version: str,
) -> dict[str, object]:
    memory = state.get("video_memory")
    verification = state.get("verification")
    if memory is None or verification is None:
        return _failure("AUTO_REANALYSIS_INPUT_INVALID", "video memory and verification are required")
    if state.get("auto_reanalysis_count", 0) >= 1:
        return _failure("AUTO_REANALYSIS_LIMIT_REACHED", "automatic re-analysis is limited to one attempt")
    conflicts = [item for item in verification.results if item.status == VerificationStatus.CONTRADICTED]
    if not conflicts:
        return _failure("AUTO_REANALYSIS_NO_CONFLICT", "automatic re-analysis requires a contradicted claim")
    claims = {claim.claim_id: claim for claim in memory.claims}
    if any(conflict.claim_id not in claims for conflict in conflicts):
        return _failure("AUTO_REANALYSIS_CLAIM_MISSING", "contradicted claim is absent from video memory")
    try:
        target_ids = [conflict.claim_id for conflict in conflicts]
        reasons = {conflict.claim_id: conflict.reason for conflict in conflicts}
        duration_s = _video_duration_s(state, memory)
        groups = _reanalysis_claim_groups(memory, target_ids, duration_s=duration_s)
        merged = memory
        artifact_uris = dict(state.get("artifact_uris", {}))
        changed_claim_ids: list[str] = []
        for group_ids, reanalysis_window in groups:
            current_claims = {claim.claim_id: claim for claim in merged.claims}
            target_claims = [current_claims[claim_id] for claim_id in group_ids]
            prompt = build_auto_reanalysis_prompt_for_conflicts(
                conflict_claims=target_claims,
                verification_reasons={claim_id: reasons[claim_id] for claim_id in group_ids},
                reanalysis_window=reanalysis_window,
                version=prompt_version,
            )
            before = {claim_id: current_claims[claim_id] for claim_id in group_ids}
            merged, artifact_uris = await _reanalyze(
                state,
                media=media,
                workflow=workflow,
                prompt=prompt,
                target_claim_ids=group_ids,
                memory=merged,
                artifact_uris=artifact_uris,
                reanalysis_window=reanalysis_window,
            )
            after = {claim.claim_id: claim for claim in merged.claims}
            changed_claim_ids.extend(
                claim_id
                for claim_id, previous_claim in before.items()
                if claim_id not in after or _claim_content_changed(previous_claim, after[claim_id])
            )
        return {
            "status": "running",
            "video_memory": merged,
            "remote_media_handles": merged.remote_media_handles,
            "artifact_uris": artifact_uris,
            "auto_reanalysis_count": state.get("auto_reanalysis_count", 0) + 1,
            "auto_reanalysis_changed_claim_ids": list(dict.fromkeys(changed_claim_ids)),
        }
    except Exception as exc:
        return _failure(getattr(exc, "code", "AUTO_REANALYSIS_FAILED"), str(exc))


async def manual_reanalyze_node(
    state: IncidentState,
    *,
    reanalysis: MemoryReanalysisService,
    prompt_version: str,
) -> dict[str, object]:
    memory = state.get("video_memory")
    target_ids = state.get("review_target_claim_ids", [])
    feedback = state.get("review_feedback", "")
    if memory is None:
        return _failure("MANUAL_REANALYSIS_INPUT_INVALID", "video_memory is required")
    try:
        prompt = build_human_reanalysis_prompt(
            target_claim_ids=target_ids,
            feedback=feedback,
            current_memory=memory,
            current_verification=state.get("verification"),
            version=prompt_version,
        )
        patch = await reanalysis.reanalyze_claims(
            ReanalysisRequest(
                incident_id=state.get("incident_id", ""),
                prompt=prompt,
                target_claim_ids=target_ids,
                incident_window=memory.incident_window,
                current_memory=memory,
            )
        )
        merged = merge_memory_only_patch(memory, patch, target_ids)
        previous_claims = {claim.claim_id: claim for claim in memory.claims}
        changed_claim_ids = [
            claim_id
            for claim_id in target_ids
            if _claim_content_changed(
                previous_claims[claim_id],
                next(claim for claim in merged.claims if claim.claim_id == claim_id),
            )
        ]
        return {
            "status": "running",
            "video_memory": merged,
            "manual_reanalysis_changed_claim_ids": changed_claim_ids,
            "manual_reanalysis_count": state.get("manual_reanalysis_count", 0) + 1,
        }
    except Exception as exc:
        return _failure(getattr(exc, "code", "MANUAL_REANALYSIS_FAILED"), str(exc))


def _claim_content_changed(previous: Claim, current: Claim) -> bool:
    return previous.model_dump(exclude={"verification_status", "evidence"}) != current.model_dump(
        exclude={"verification_status", "evidence"}
    )


def _reanalysis_changed_claim_ids(state: IncidentState) -> list[str] | None:
    """Return the one re-analysis patch that must be re-verified, if any."""
    if state.get("last_review_action") == "reanalyze":
        return state.get("manual_reanalysis_changed_claim_ids", [])
    if "auto_reanalysis_changed_claim_ids" in state:
        return state.get("auto_reanalysis_changed_claim_ids", [])
    return None


def _merge_selective_verification(
    memory: VideoMemory,
    *,
    previous_verification: VerificationResult | None,
    next_verification: VerificationResult,
    previous_summaries: list,
    next_summaries: list,
    changed_claim_ids: set[str],
) -> tuple[VerificationResult, list]:
    """Replace results for changed claims while retaining all unchanged results exactly."""
    active_claim_ids = {claim.claim_id for claim in memory.claims}
    result_by_claim_id = {
        item.claim_id: item
        for item in (previous_verification.results if previous_verification is not None else [])
        if item.claim_id not in changed_claim_ids and item.claim_id in active_claim_ids
    }
    result_by_claim_id.update({item.claim_id: item for item in next_verification.results})
    merged_result = VerificationResult(
        has_accident=(
            previous_verification.has_accident
            if previous_verification is not None and previous_verification.has_accident is not None
            else next_verification.has_accident
        ),
        results=[result_by_claim_id[claim.claim_id] for claim in memory.claims if claim.claim_id in result_by_claim_id],
    )
    summary_by_claim_id = {
        summary.claim_id: summary
        for summary in previous_summaries
        if summary.claim_id not in changed_claim_ids and summary.claim_id in active_claim_ids
    }
    summary_by_claim_id.update({summary.claim_id: summary for summary in next_summaries})
    return (
        merged_result,
        [summary_by_claim_id[claim.claim_id] for claim in memory.claims if claim.claim_id in summary_by_claim_id],
    )


async def build_draft_report_node(
    state: IncidentState,
    *,
    report: ReportService,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    memory = state.get("video_memory")
    if not incident_id or memory is None:
        return _failure("REPORT_INPUT_INVALID", "incident_id and video_memory are required")
    warnings = list(state.get("warnings", []))
    verification_unavailable = state.get("log_evidence_summary") is not None and state.get("verification") is None
    if verification_unavailable:
        warnings = list(
            dict.fromkeys(
                [
                    *warnings,
                    "Report model skipped because verification was unavailable; the backend used the VLM video "
                    "summary and structured evidence.",
                ]
            )
        )
        narrative = _fallback_report_narrative(memory, has_log=state.get("log_evidence_summary") is not None)
    else:
        try:
            narrative = await report.build_narrative(
                ReportRequest(
                    incident_id=incident_id,
                    video_memory=memory,
                    verification=state.get("verification"),
                    log_evidence_summary=state.get("log_evidence_summary"),
                )
            )
            model_output = ReportModelOutput.model_validate(narrative)
            memory, geometry_warning = _apply_report_incident_geometry(state, memory, model_output)
            if geometry_warning is not None:
                warnings.append(geometry_warning)
            has_log = state.get("log_evidence_summary") is not None
            narrative = ReportNarrative(
                type_of_accident=model_output.type_of_accident,
                summary=memory.video_summary or memory.global_scene,
                timeline=model_output.timeline,
                video_observations=model_output.video_observations,
                log_findings=_backend_log_findings(state.get("log_evidence_summary")),
                alignment=_verification_alignment(state.get("verification")) if has_log else "Không có dữ liệu log.",
                hypothesized_causes=model_output.hypothesized_causes,
                evidence_ids=[evidence.evidence_id for claim in memory.claims for evidence in claim.evidence],
            )
        except Exception as exc:
            warning = (
                f"{getattr(exc, 'code', 'REPORT_GENERATION_FAILED')}: report model unavailable; "
                "the backend used the VLM video summary and structured evidence."
            )
            warnings = list(dict.fromkeys([*warnings, warning]))
            narrative = _fallback_report_narrative(memory, has_log=state.get("log_evidence_summary") is not None)

    conflict_ids = list(
        dict.fromkeys(
            [
                item.claim_id
                for item in (state.get("verification").results if state.get("verification") else [])
                if item.status == VerificationStatus.CONTRADICTED
            ]
            + [
                claim.claim_id
                for claim in memory.claims
                if claim.verification_status == VerificationStatus.CONTRADICTED
            ]
        )
    )
    warnings.extend(f"Unresolved contradicted claim: {claim_id}" for claim_id in conflict_ids)
    warnings = list(dict.fromkeys(warnings))
    draft_report = DraftReport(
        general_information=ReportGeneralInformation(
            incident_id=incident_id,
            video_uri=state["video_uri"],
            has_log=state.get("log_evidence_summary") is not None,
            log_uri=state.get("log_uri"),
        ),
        type_of_accident=narrative.type_of_accident,
        incident_window=memory.incident_window,
        representative_timestamp_s=memory.representative_timestamp_s,
        summary=narrative.summary,
        timeline=ReportTimelineSection(
            narrative=narrative.timeline,
            events=memory.timeline,
        ),
        video_observations=ReportVideoObservationsSection(
            narrative=narrative.video_observations,
        ),
        log_findings=ReportLogSection(
            narrative=narrative.log_findings,
            summary=state.get("log_evidence_summary"),
            claim_summaries=state.get("claim_log_summaries", []),
        ),
        alignment=ReportAlignmentSection(
            narrative=narrative.alignment,
            verification=state.get("verification"),
        ),
        hypothesized_causes=narrative.hypothesized_causes,
        evidence_and_warnings=ReportEvidenceAndWarnings(
            evidence=[evidence for claim in memory.claims for evidence in claim.evidence],
            artifact_uris=state.get("artifact_uris", {}),
            warnings=warnings,
        ),
        review_status="pending",
    )
    return {
        "status": "running",
        "video_memory": memory,
        "report_narrative": narrative,
        "draft_report": draft_report,
        "warnings": warnings,
    }


def _apply_report_incident_geometry(
    state: IncidentState,
    memory: VideoMemory,
    model_output: ReportModelOutput,
) -> tuple[VideoMemory, str | None]:
    """Accept a report correction only when it describes an in-bounds incident."""
    if model_output.type_of_accident == AccidentType.NO_INCIDENT:
        return memory, None

    window = model_output.incident_window
    representative_timestamp_s = model_output.representative_timestamp_s
    duration_s = _video_duration_s(state, memory)
    if window.t_end > duration_s:
        return memory, (
            "REPORT_INCIDENT_WINDOW_INVALID: report incident_window exceeds the source video duration; "
            "the VLM incident window was retained."
        )
    if not window.t_start <= representative_timestamp_s <= window.t_end:
        return memory, (
            "REPORT_REPRESENTATIVE_TIMESTAMP_INVALID: report representative_timestamp_s is outside its "
            "incident_window; the VLM incident window was retained."
        )
    return memory.model_copy(
        update={
            "incident_window": window,
            "representative_timestamp_s": representative_timestamp_s,
        }
    ), None


def _refresh_report_after_cut(
    state: IncidentState,
    *,
    memory: VideoMemory,
    artifact_uris: dict[str, str],
) -> dict[str, object]:
    """Attach clip/frame artifacts and canonical visual evidence after report generation."""
    draft_report = state.get("draft_report")
    if not isinstance(draft_report, DraftReport):
        return {}

    evidence = [evidence for claim in memory.claims for evidence in claim.evidence]
    output: dict[str, object] = {
        "draft_report": draft_report.model_copy(
            update={
                "incident_window": memory.incident_window,
                "representative_timestamp_s": memory.representative_timestamp_s,
                "timeline": draft_report.timeline.model_copy(update={"events": memory.timeline}),
                "evidence_and_warnings": draft_report.evidence_and_warnings.model_copy(
                    update={
                        "evidence": evidence,
                        "artifact_uris": artifact_uris,
                        "warnings": state.get("warnings", []),
                    }
                ),
            }
        )
    }
    narrative = state.get("report_narrative")
    if isinstance(narrative, ReportNarrative):
        output["report_narrative"] = narrative.model_copy(
            update={"evidence_ids": [item.evidence_id for item in evidence]}
        )
    return output


async def _reanalyze(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
    prompt: PromptEnvelope,
    target_claim_ids: list[str],
    memory: VideoMemory,
    artifact_uris: dict[str, str],
    reanalysis_window: IncidentWindow,
) -> tuple[VideoMemory, dict[str, str]]:
    incident_id = state.get("incident_id", "").strip()
    video_uri = state.get("video_uri", "").strip()
    if not incident_id or not video_uri:
        raise ValueError("incident_id and video_uri are required")

    config = workflow.config
    artifacts = dict(artifact_uris)
    group_key = "_".join(_safe_incident_id(claim_id) for claim_id in target_claim_ids)
    artifact_root = Path(config.artifact_dir).resolve() / _safe_incident_id(incident_id)
    frame_dir = artifact_root / "reanalysis_frames" / group_key
    sample_start_s, sample_end_s = reanalysis_window.t_start, reanalysis_window.t_end
    frame_manifest = await media.sample_frames(
        video_uri,
        str(frame_dir),
        fps=_incident_sampling_fps(
            memory,
            config,
            start_s=sample_start_s,
            end_s=sample_end_s,
        ),
        width=config.frame_width,
        height=config.frame_height,
        image_format=config.frame_format,
        jpeg_quality=config.frame_jpeg_quality,
        max_frames=config.incident_max_frames,
        start_s=sample_start_s,
        end_s=sample_end_s,
    )
    artifacts[f"reanalysis_frames_{group_key}"] = str(frame_dir)
    normalized_video_uri = None
    if workflow.vlm.capabilities.input_mode == VLMInputMode.NATIVE_VIDEO:
        normalized_source_uri = artifacts.get("normalized_video")
        if not normalized_source_uri:
            raise ValueError("normalized_video artifact is required for native re-analysis")
        clip = await media.cut_incident_clip(
            normalized_source_uri,
            str(artifact_root / "reanalysis_clips" / f"{group_key}.mp4"),
            window=reanalysis_window,
            codec=config.video_codec,
            pixel_format=config.video_pixel_format,
            min_duration_s=reanalysis_window.t_end - reanalysis_window.t_start,
            pre_roll_s=0.0,
            post_roll_s=0.0,
        )
        normalized_video_uri = clip.uri
        artifacts[f"reanalysis_clip_{group_key}"] = clip.uri

    patch = await workflow.vlm.reanalyze_claims(
        ReanalysisRequest(
            incident_id=incident_id,
            prompt=prompt,
            target_claim_ids=target_claim_ids,
            incident_window=memory.incident_window,
            current_memory=memory,
            source_duration_s=_video_duration_s(state, memory),
            frame_manifest=frame_manifest,
            normalized_video_uri=normalized_video_uri,
            input_video_start_s=reanalysis_window.t_start,
            input_video_end_s=reanalysis_window.t_end,
            remote_media_handles=state.get("remote_media_handles", memory.remote_media_handles),
        )
    )
    if any(
        claim.timestamp_s is None or not reanalysis_window.t_start <= claim.timestamp_s <= reanalysis_window.t_end
        for claim in patch.claims
    ):
        raise ValueError("reanalysis claims must use a timestamp inside the submitted clip window")
    original_timestamp_by_claim_id = {
        claim.claim_id: claim.timestamp_s for claim in memory.claims if claim.claim_id in set(target_claim_ids)
    }
    if any(
        abs(claim.timestamp_s - original_timestamp_by_claim_id[claim.claim_id]) > REANALYSIS_CLIP_RADIUS_S
        for claim in patch.claims
    ):
        raise ValueError("reanalysis claim timestamp cannot move more than two seconds from its original claim")
    patch = reconcile_video_memory_patch_evidence(
        patch,
        frame_manifest.frames,
        fallback_timestamp_s=reanalysis_window.t0,
    )
    return merge_video_memory_patch(memory, patch), artifacts


def _failure(code: str, message: str) -> dict[str, object]:
    return {"status": "failed", "error_code": code, "error_message": message}


def _safe_incident_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _incident_sampling_fps(
    memory: VideoMemory,
    config: VideoMemoryWorkflowConfig,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
) -> float:
    """Cover the requested sampling span without exceeding the frame budget."""
    sample_start_s = memory.incident_window.t_start if start_s is None else start_s
    sample_end_s = memory.incident_window.t_end if end_s is None else end_s
    duration_s = sample_end_s - sample_start_s
    if duration_s <= 0:
        return config.incident_frame_fps
    return min(config.incident_frame_fps, config.incident_max_frames / duration_s)


def _semantic_sampling_bounds(memory: VideoMemory) -> tuple[float, float]:
    timestamps = [
        memory.incident_window.t_start,
        memory.incident_window.t_end,
        *(item.timestamp_s for item in memory.timeline),
        *(claim.timestamp_s for claim in memory.claims if claim.timestamp_s is not None),
        *(evidence.timestamp_s for claim in memory.claims for evidence in claim.evidence),
    ]
    return min(timestamps), max(timestamps)


def _reanalysis_claim_groups(
    memory: VideoMemory,
    target_claim_ids: list[str],
    *,
    duration_s: float,
) -> list[tuple[list[str], IncidentWindow]]:
    """Group only overlapping ±2s claim clips, preserving short visual input by default."""
    claims = {claim.claim_id: claim for claim in memory.claims}
    windows: list[tuple[str, float, float]] = []
    for claim_id in target_claim_ids:
        claim = claims[claim_id]
        if claim.timestamp_s is None:
            raise ValueError(f"claim {claim_id} must have timestamp_s for automatic re-analysis")
        windows.append(
            (
                claim_id,
                max(0.0, claim.timestamp_s - REANALYSIS_CLIP_RADIUS_S),
                min(duration_s, claim.timestamp_s + REANALYSIS_CLIP_RADIUS_S),
            )
        )
    windows.sort(key=lambda item: (item[1], item[2], item[0]))
    groups: list[tuple[list[str], float, float]] = []
    for claim_id, start_s, end_s in windows:
        if groups and start_s < groups[-1][2]:
            group_ids, group_start_s, group_end_s = groups[-1]
            groups[-1] = (group_ids + [claim_id], group_start_s, max(group_end_s, end_s))
        else:
            groups.append(([claim_id], start_s, end_s))
    return [
        (
            group_ids,
            IncidentWindow(
                t_start=start_s,
                t0=(start_s + end_s) / 2,
                t_end=end_s,
            ),
        )
        for group_ids, start_s, end_s in groups
    ]


def _video_duration_s(state: IncidentState, memory: VideoMemory) -> float:
    duration_s = state.get("video_duration_s")
    if duration_s is not None:
        return duration_s
    if memory.sampling_metadata is not None:
        return memory.sampling_metadata.source_duration_s
    timestamps = [
        memory.incident_window.t_end,
        *(item.timestamp_s for item in memory.timeline),
        *(claim.timestamp_s for claim in memory.claims if claim.timestamp_s is not None),
        *(evidence.timestamp_s for claim in memory.claims for evidence in claim.evidence),
    ]
    return max(timestamps)


def _telemetry_duration_s(state: IncidentState, memory: VideoMemory) -> float | None:
    """Return a known video bound without inferring one from the incident window."""
    duration_s = state.get("video_duration_s")
    if duration_s is not None:
        return duration_s
    if memory.sampling_metadata is not None:
        return memory.sampling_metadata.source_duration_s
    return None


def _representative_timestamp(memory: VideoMemory) -> float:
    collision_pattern = re.compile(r"\b(collid\w*|collision|impact|crash\w*)\b", re.IGNORECASE)
    aftermath_pattern = re.compile(r"\b(aftermath|debris|water|after the incident)\b", re.IGNORECASE)
    candidates: list[float] = []
    text_and_timestamps = [
        *((item.text, item.timestamp_s) for item in memory.claims),
        *((item.description, item.timestamp_s) for item in memory.timeline),
    ]
    for text, timestamp_s in text_and_timestamps:
        if timestamp_s is not None and collision_pattern.search(text) and not aftermath_pattern.search(text):
            candidates.append(timestamp_s)

    earliest_collision_s = min(candidates) if candidates else None
    model_choice_s = memory.representative_timestamp_s
    if model_choice_s is None:
        return earliest_collision_s if earliest_collision_s is not None else memory.incident_window.t0
    if earliest_collision_s is not None and model_choice_s - earliest_collision_s > 2:
        return earliest_collision_s
    return model_choice_s


def _fallback_report_narrative(memory: VideoMemory, *, has_log: bool) -> ReportNarrative:
    timeline = " ".join(f"Tại {item.timestamp_s:g} giây: {item.description}" for item in memory.timeline)
    claims = " ".join(item.text for item in memory.claims)
    return ReportNarrative(
        type_of_accident=_fallback_accident_type(memory),
        summary=memory.video_summary or memory.global_scene,
        timeline=timeline or "Phân tích video không trả về sự kiện timeline có timestamp.",
        video_observations=claims or memory.global_scene,
        log_findings=(
            "Bằng chứng log phương tiện có cấu trúc được cung cấp trong phần kết quả log."
            if has_log
            else "Không có dữ liệu log."
        ),
        alignment="Không thể thực hiện bước kiểm chứng claim vì verification không trả về kết quả.",
        hypothesized_causes=(
            "Chưa thể xác định nguyên nhân từ bằng chứng hiện có nếu chưa được chuyên viên xem xét thêm."
        ),
        evidence_ids=[evidence.evidence_id for claim in memory.claims for evidence in claim.evidence],
    )


def _fallback_accident_type(memory: VideoMemory) -> AccidentType:
    text = " ".join(
        [
            memory.global_scene,
            memory.video_summary or "",
            *(event.description for event in memory.timeline),
            *(claim.text for claim in memory.claims),
        ]
    ).lower()
    no_incident_phrases = (
        "không có tai nạn",
        "không quan sát được tai nạn",
        "không xảy ra va chạm",
        "không có va chạm",
        "no accident",
        "no collision",
    )
    if any(phrase in text for phrase in no_incident_phrases):
        return AccidentType.NO_INCIDENT

    collision_terms = ("tai nạn", "va chạm", "đâm", "collision", "crash", "impact")
    if not any(term in text for term in collision_terms):
        return AccidentType.NO_INCIDENT
    if any(term in text for term in ("cắt ngang", "crossing collision")):
        return AccidentType.CROSSING_COLLISION
    if any(term in text for term in ("người đi bộ", "pedestrian")):
        return AccidentType.PEDESTRIAN_COLLISION
    if any(
        term in text for term in ("lan can", "guardrail", "hàng rào", "tường", "cây", "cột", "rời đường", "roadside")
    ):
        return AccidentType.ROADSIDE_COLLISION
    if any(term in text for term in ("barrier", "vật cản", "static object")):
        return AccidentType.STATIC_OBJECT_COLLISION
    if any(term in text for term in ("đối đầu", "ngược chiều", "head-on", "head on")):
        return AccidentType.HEAD_ON_COLLISION
    if any(term in text for term in ("nhập làn", "đổi làn", "cùng hướng", "bên hông", "cut-in", "cut in")):
        return AccidentType.SIDE_COLLISION
    if any(term in text for term in ("đâm đuôi", "phía sau", "rear-end", "rear end")):
        return AccidentType.REAR_END_COLLISION
    if any(term in text for term in ("xe", "phương tiện", "vehicle", "car", "truck", "motorcycle")):
        return AccidentType.OTHER_UNKNOWN
    return AccidentType.OTHER_UNKNOWN


def _verification_alignment(verification: VerificationResult | None) -> str:
    if verification is None:
        return "Không thể đối chiếu claim vì bước verification không trả về kết quả."
    statements = []
    for item in verification.results:
        conclusion = {
            VerificationStatus.SUPPORTED: "được log hỗ trợ",
            VerificationStatus.CONTRADICTED: "mâu thuẫn với log",
            VerificationStatus.UNVERIFIED: "chưa thể xác minh từ log",
        }[item.status]
        evidence = f" Bằng chứng: {', '.join(item.evidence_ids)}." if item.evidence_ids else ""
        statements.append(f"{item.claim_id} {conclusion}: {item.reason.rstrip('.')}.{evidence}")
    return " ".join(statements) or "Không có claim để đối chiếu với log."


def _backend_log_findings(summary: LogEvidenceSummary | None) -> str:
    if summary is None:
        return "Không có dữ liệu log."
    return summary.summary or "Không có dữ liệu log có thể tổng hợp trong toàn bộ video."
