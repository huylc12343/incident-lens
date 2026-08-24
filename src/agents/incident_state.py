"""Serializable state shared by incident-workflow nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from src.models.api import AiGroundTruthEvaluation, GroundTruth, ModelActivity, ReviewAuditEntry
from src.models.incidents import (
    ClaimLogSummary,
    DraftReport,
    LogAnalysisResult,
    LogEvent,
    LogEvidenceSummary,
    RemoteMediaHandle,
    ReportNarrative,
    VerificationResult,
    VideoMemory,
)


class IncidentState(TypedDict, total=False):
    incident_id: str
    video_uri: str
    review_video_uri: str
    log_uri: str | None
    analysis_prompt: str
    video_duration_s: float
    metadata: dict[str, Any]
    status: Literal[
        "queued",
        "running",
        "awaiting_review",
        "approved",
        "not_incident",
        "failed",
        "cancelled",
    ]
    video_memory: VideoMemory
    canonical_evidence_mapped: bool
    canonical_evidence_phase: Literal["initial", "auto_reanalysis", "manual_reanalysis"]
    log_evidence_summary: LogEvidenceSummary
    claim_log_summaries: list[ClaimLogSummary]
    log_analysis: LogAnalysisResult
    log_events: list[LogEvent]
    chart_uris: list[str]
    verification: VerificationResult | None
    report_narrative: ReportNarrative
    draft_report: DraftReport
    remote_media_handles: list[RemoteMediaHandle]
    auto_reanalysis_count: int
    manual_reanalysis_count: int
    review_target_claim_ids: list[str]
    review_feedback: str
    auto_reanalysis_changed_claim_ids: list[str]
    manual_reanalysis_changed_claim_ids: list[str]
    last_review_action: Literal["approve", "edit", "reanalyze", "not_incident"]
    review_audit: list[ReviewAuditEntry]
    model_activities: list[ModelActivity]
    ground_truth: GroundTruth
    ai_evaluation: AiGroundTruthEvaluation
    artifact_uris: dict[str, str]
    warnings: list[str]
    error_code: str
    error_message: str
