"""Video-analysis node wired only to provider-neutral dependencies."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from src.agents.incident_state import IncidentState
from src.models.incidents import (
    DraftReport,
    IncidentWindow,
    LogAnalysisResult,
    LogEvent,
    NativeVideoAnalysisRequest,
    NativeVideoMetadata,
    PromptEnvelope,
    ReanalysisRequest,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportNarrative,
    ReportRequest,
    ReportService,
    ReportTimelineSection,
    ReportVideoObservationsSection,
    TimestampedFramesAnalysisRequest,
    VerificationRequest,
    VerificationService,
    VerificationStatus,
    VideoMemory,
    VideoSequenceManifest,
    VLMInputMode,
)
from src.prompts.reanalysis import build_auto_reanalysis_prompt_for_conflicts, build_human_reanalysis_prompt
from src.prompts.video_analysis import build_video_analysis_prompt
from src.services.media import NormalizedVideoArtifact
from src.services.video_memory import VideoMemoryWorkflow, merge_video_memory_patch


class MediaWorkflowService(Protocol):
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
        window: IncidentWindow,
    ) -> LogAnalysisResult: ...


class ChartWorkflowService(Protocol):
    def create_charts(
        self,
        log_slice_uri: str,
        output_dir: str,
        *,
        window: IncidentWindow,
        events: list[LogEvent],
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
        version=config.prompt_version,
    )
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
            artifact_uris = {"frames": str(artifact_root / "frames")}
        else:
            normalized = await media.normalize_video(
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
                normalized_video_uri=normalized.uri,
                metadata=NativeVideoMetadata.model_validate(normalized.metadata),
            )
            artifact_uris = {"normalized_video": normalized.uri}

        memory = await workflow.analyze(request)
        return {
            "status": "running",
            "video_memory": memory,
            "claims": memory.claims,
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
        clip = await media.cut_incident_clip(
            video_uri,
            str(artifact_root / "incident_clip.mp4"),
            window=memory.incident_window,
            codec=config.video_codec,
            pixel_format=config.video_pixel_format,
            min_duration_s=config.incident_clip_min_duration_s,
            pre_roll_s=config.incident_clip_pre_roll_s,
            post_roll_s=config.incident_clip_post_roll_s,
        )
        frames = await media.sample_frames(
            video_uri,
            str(frame_dir),
            fps=config.incident_frame_fps,
            width=config.frame_width,
            height=config.frame_height,
            image_format=config.frame_format,
            jpeg_quality=config.frame_jpeg_quality,
            max_frames=config.incident_max_frames,
            start_s=memory.incident_window.t_start,
            end_s=memory.incident_window.t_end,
        )
        artifact_uris = {
            **state.get("artifact_uris", {}),
            "incident_clip": clip.uri,
            "incident_frames": str(frame_dir),
        }
        if frames.frames:
            target_timestamp_s = _representative_timestamp(memory)
            representative = min(frames.frames, key=lambda frame: abs(frame.timestamp_s - target_timestamp_s))
            artifact_uris["representative_frame"] = representative.image_uri
        return {"status": "running", "artifact_uris": artifact_uris}
    except Exception as exc:
        return {
            "status": "failed",
            "error_code": getattr(exc, "code", "INCIDENT_CLIP_FAILED"),
            "error_message": str(exc),
        }


async def analyze_log_node(
    state: IncidentState,
    *,
    log_analysis: LogWorkflowService,
    charts: ChartWorkflowService,
    artifact_dir: str,
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
    try:
        result = log_analysis.analyze(
            log_uri,
            str(artifact_root / "log_slice.csv"),
            window=memory.incident_window,
        )
        chart_uris = charts.create_charts(
            result.log_slice_uri,
            str(artifact_root / "charts"),
            window=memory.incident_window,
            events=result.events,
        )
        artifact_uris = {
            **state.get("artifact_uris", {}),
            "log_slice": result.log_slice_uri,
            **{f"chart_{index}": uri for index, uri in enumerate(chart_uris, start=1)},
        }
        return {
            "status": "running",
            "log_analysis": result,
            "log_evidence_summary": result.summary,
            "log_events": result.events,
            "chart_uris": chart_uris,
            "artifact_uris": artifact_uris,
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
) -> dict[str, object]:
    incident_id = state.get("incident_id", "").strip()
    memory = state.get("video_memory")
    log_summary = state.get("log_evidence_summary")
    if not incident_id or memory is None or log_summary is None:
        return {
            "status": "failed",
            "error_code": "VERIFICATION_INPUT_INVALID",
            "error_message": "incident_id, video_memory, and log_evidence_summary are required",
        }
    try:
        result = await verification.verify(
            VerificationRequest(
                incident_id=incident_id,
                claims=memory.claims,
                log_evidence_summary=log_summary,
                timestamp_tolerance_s=timestamp_tolerance_s,
            )
        )
        statuses = {item.claim_id: item.status for item in result.results}
        claims = [claim.model_copy(update={"verification_status": statuses[claim.claim_id]}) for claim in memory.claims]
        updated_memory = memory.model_copy(update={"claims": claims})
        return {
            "status": "running",
            "verification": result,
            "video_memory": updated_memory,
            "claims": claims,
        }
    except Exception as exc:
        claims = [
            claim.model_copy(update={"verification_status": VerificationStatus.UNVERIFIED}) for claim in memory.claims
        ]
        warning = (
            f"{getattr(exc, 'code', 'CLAIM_VERIFICATION_FAILED')}: verification unavailable; "
            "claims remain unverified and processing continued."
        )
        return {
            "status": "running",
            "verification": None,
            "video_memory": memory.model_copy(update={"claims": claims}),
            "claims": claims,
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
    log_summary = state.get("log_evidence_summary")
    if memory is None or verification is None or log_summary is None:
        return _failure("AUTO_REANALYSIS_INPUT_INVALID", "video memory, verification, and log summary are required")
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
        prompt = build_auto_reanalysis_prompt_for_conflicts(
            conflict_claims=[claims[claim_id] for claim_id in target_ids],
            verification_reasons={conflict.claim_id: conflict.reason for conflict in conflicts},
            log_evidence_summary=log_summary,
            timestamp_window=memory.incident_window,
            version=prompt_version,
        )
        merged, artifact_uris = await _reanalyze(
            state,
            media=media,
            workflow=workflow,
            prompt=prompt,
            target_claim_ids=target_ids,
        )
        return {
            "status": "running",
            "video_memory": merged,
            "claims": merged.claims,
            "remote_media_handles": merged.remote_media_handles,
            "artifact_uris": artifact_uris,
            "auto_reanalysis_count": state.get("auto_reanalysis_count", 0) + 1,
        }
    except Exception as exc:
        return _failure(getattr(exc, "code", "AUTO_REANALYSIS_FAILED"), str(exc))


async def manual_reanalyze_node(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
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
            current_claims=memory.claims,
            current_evidence=memory.evidence,
            version=prompt_version,
        )
        merged, artifact_uris = await _reanalyze(
            state,
            media=media,
            workflow=workflow,
            prompt=prompt,
            target_claim_ids=target_ids,
        )
        return {
            "status": "running",
            "video_memory": merged,
            "claims": merged.claims,
            "remote_media_handles": merged.remote_media_handles,
            "artifact_uris": artifact_uris,
            "manual_reanalysis_count": state.get("manual_reanalysis_count", 0) + 1,
        }
    except Exception as exc:
        return _failure(getattr(exc, "code", "MANUAL_REANALYSIS_FAILED"), str(exc))


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
            narrative = ReportNarrative.model_validate(narrative)
        except Exception as exc:
            warning = (
                f"{getattr(exc, 'code', 'REPORT_GENERATION_FAILED')}: report model unavailable; "
                "the backend used the VLM video summary and structured evidence."
            )
            warnings = list(dict.fromkeys([*warnings, warning]))
            narrative = _fallback_report_narrative(memory, has_log=state.get("log_evidence_summary") is not None)

    if state.get("log_evidence_summary") is None:
        narrative = narrative.model_copy(update={"log_findings": "Không có dữ liệu log."})
    conflict_ids = [
        claim.claim_id for claim in memory.claims if claim.verification_status == VerificationStatus.CONTRADICTED
    ]
    warnings.extend(f"Unresolved contradicted claim: {claim_id}" for claim_id in conflict_ids)
    warnings = list(dict.fromkeys(warnings))
    draft_report = DraftReport(
        general_information=ReportGeneralInformation(
            incident_id=incident_id,
            video_uri=state["video_uri"],
            has_log=state.get("log_evidence_summary") is not None,
            log_uri=state.get("log_uri"),
        ),
        incident_window=memory.incident_window,
        summary=narrative.summary,
        timeline=ReportTimelineSection(
            narrative=narrative.timeline,
            events=memory.timeline,
        ),
        video_observations=ReportVideoObservationsSection(
            narrative=narrative.video_observations,
            observations=memory.observations,
        ),
        log_findings=ReportLogSection(
            narrative=narrative.log_findings,
            summary=state.get("log_evidence_summary"),
        ),
        alignment=ReportAlignmentSection(
            narrative=narrative.alignment,
            verification=state.get("verification"),
        ),
        hypothesized_causes=narrative.hypothesized_causes,
        evidence_and_warnings=ReportEvidenceAndWarnings(
            evidence=memory.evidence,
            artifact_uris=state.get("artifact_uris", {}),
            warnings=warnings,
        ),
        review_status="pending",
    )
    return {
        "status": "awaiting_review",
        "report_narrative": narrative,
        "draft_report": draft_report,
        "warnings": warnings,
    }


async def _reanalyze(
    state: IncidentState,
    *,
    media: MediaWorkflowService,
    workflow: VideoMemoryWorkflow,
    prompt: PromptEnvelope,
    target_claim_ids: list[str],
) -> tuple[VideoMemory, dict[str, str]]:
    incident_id = state.get("incident_id", "").strip()
    video_uri = state.get("video_uri", "").strip()
    memory = state.get("video_memory")
    if not incident_id or not video_uri or memory is None:
        raise ValueError("incident_id, video_uri, and video_memory are required")

    config = workflow.config
    artifacts = dict(state.get("artifact_uris", {}))
    frame_manifest = None
    normalized_video_uri = None
    if workflow.vlm.capabilities.input_mode == VLMInputMode.TIMESTAMPED_FRAMES:
        frame_dir = Path(config.artifact_dir).resolve() / _safe_incident_id(incident_id) / "reanalysis_frames"
        frame_manifest = await media.sample_frames(
            video_uri,
            str(frame_dir),
            fps=config.incident_frame_fps,
            width=config.frame_width,
            height=config.frame_height,
            image_format=config.frame_format,
            jpeg_quality=config.frame_jpeg_quality,
            max_frames=config.incident_max_frames,
            start_s=memory.incident_window.t_start,
            end_s=memory.incident_window.t_end,
        )
        artifacts["reanalysis_frames"] = str(frame_dir)
    else:
        normalized_video_uri = artifacts.get("normalized_video")

    patch = await workflow.vlm.reanalyze_claims(
        ReanalysisRequest(
            incident_id=incident_id,
            prompt=prompt,
            target_claim_ids=target_claim_ids,
            incident_window=memory.incident_window,
            current_memory=memory,
            frame_manifest=frame_manifest,
            normalized_video_uri=normalized_video_uri,
            remote_media_handles=state.get("remote_media_handles", memory.remote_media_handles),
        )
    )
    return merge_video_memory_patch(memory, patch), artifacts


def _failure(code: str, message: str) -> dict[str, object]:
    return {"status": "failed", "error_code": code, "error_message": message}


def _safe_incident_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _representative_timestamp(memory: VideoMemory) -> float:
    collision_pattern = re.compile(r"\b(collid\w*|collision|impact|crash\w*)\b", re.IGNORECASE)
    aftermath_pattern = re.compile(r"\b(aftermath|debris|water|after the incident)\b", re.IGNORECASE)
    candidates: list[float] = []
    text_and_timestamps = [
        *((item.text, item.timestamp_s) for item in memory.claims),
        *((item.description, item.timestamp_s) for item in memory.timeline),
        *((item.text, item.timestamp_s) for item in memory.observations),
        *((item.description, item.timestamp_s) for item in memory.evidence),
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
    observations = " ".join(item.text for item in memory.observations)
    return ReportNarrative(
        summary=memory.video_summary or memory.global_scene,
        timeline=timeline or "Phân tích video không trả về sự kiện timeline có timestamp.",
        video_observations=observations or memory.global_scene,
        log_findings=(
            "Bằng chứng log phương tiện có cấu trúc được cung cấp trong phần kết quả log."
            if has_log
            else "Không có dữ liệu log."
        ),
        alignment="Không thể thực hiện bước kiểm chứng claim; tất cả claim vẫn ở trạng thái unverified.",
        hypothesized_causes=(
            " ".join(memory.uncertainties)
            or "Chưa thể xác định nguyên nhân từ bằng chứng hiện có nếu chưa được chuyên viên xem xét thêm."
        ),
        evidence_ids=[item.evidence_id for item in memory.evidence],
    )
