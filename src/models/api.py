"""Public API contracts for the incident workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.incidents import AccidentType, Claim, ClaimLogSummary, DraftReport, VerificationStatus

IncidentStatus = Literal[
    "queued",
    "running",
    "awaiting_review",
    "approved",
    "not_incident",
    "failed",
    "cancelled",
]
ReviewAction = Literal["approve", "edit", "reanalyze", "not_incident"]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentCreateRequest(APIModel):
    incident_id: str = Field(min_length=1, max_length=128)
    video_uri: str = Field(min_length=1)
    log_uri: str | None = None
    analysis_prompt: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("incident_id", "video_uri", "analysis_prompt")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("log_uri")
    @classmethod
    def strip_optional_log_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("log_uri must not be blank")
        return value


class IncidentUploadResponse(APIModel):
    video_uri: str
    log_uri: str | None = None
    ground_truth_uri: str | None = None


class ClaimEdit(APIModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp_s: float | None = Field(default=None, ge=0)
    verification_status: VerificationStatus | None = None
    evidence_ids: list[str] | None = None

    @field_validator("claim_id", "text")
    @classmethod
    def strip_claim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("claim edit text must not be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("evidence IDs must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence IDs must be unique")
        return normalized


class ReportEdits(APIModel):
    type_of_accident: AccidentType | None = None
    t_start: float | None = Field(default=None, ge=0)
    t0: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, gt=0)
    claims: list[ClaimEdit] | None = None
    summary: str | None = None
    timeline: str | None = None
    video_observations: str | None = None
    log_findings: str | None = None
    alignment: str | None = None
    hypothesized_causes: str | None = None
    warnings: list[str] | None = None

    @field_validator(
        "summary",
        "timeline",
        "video_observations",
        "log_findings",
        "alignment",
        "hypothesized_causes",
    )
    @classmethod
    def strip_optional_narrative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("edited report text must not be blank")
        return value

    @field_validator("warnings")
    @classmethod
    def normalize_warnings(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("warnings must not contain blank values")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_edit_payload(self) -> ReportEdits:
        if not self.model_fields_set:
            raise ValueError("at least one report edit is required")
        claim_ids = [claim.claim_id for claim in self.claims or []]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("edited claim IDs must be unique")
        return self


class ReviewDecision(APIModel):
    action: ReviewAction
    reviewer: str = Field(min_length=1)
    reason: str | None = None
    feedback: str | None = None
    target_claim_ids: list[str] = Field(default_factory=list)
    edits: ReportEdits | None = None

    @field_validator("reviewer")
    @classmethod
    def strip_reviewer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reviewer must not be blank")
        return value

    @model_validator(mode="after")
    def validate_action_payload(self) -> ReviewDecision:
        if self.action == "not_incident" and not (self.reason or "").strip():
            raise ValueError("not_incident requires a non-empty reason")
        if self.action == "reanalyze":
            if not (self.feedback or "").strip() or not self.target_claim_ids:
                raise ValueError("reanalyze requires feedback and target_claim_ids")
            if any(not item.strip() for item in self.target_claim_ids):
                raise ValueError("target_claim_ids must not contain blank values")
            if len(set(self.target_claim_ids)) != len(self.target_claim_ids):
                raise ValueError("target_claim_ids must be unique")
        if self.action == "edit":
            if self.edits is None:
                raise ValueError("edit requires at least one report field")
        elif self.edits is not None:
            raise ValueError("edits are only allowed for the edit action")
        return self


class ReviewAuditEntry(APIModel):
    action: ReviewAction
    reviewer: str
    reason: str | None = None
    feedback: str | None = None
    target_claim_ids: list[str] = Field(default_factory=list)


class TokenUsage(APIModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)


class ModelActivity(APIModel):
    activity_id: str
    incident_id: str
    step: str
    operation: str
    description: str
    provider: str
    model: str
    status: Literal["running", "completed", "failed", "skipped"]
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    usage: TokenUsage | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroundTruthTimeline(APIModel):
    t_start: float | None = Field(default=None, ge=0)
    t0: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_known_timestamps(self) -> GroundTruthTimeline:
        known = [value for value in (self.t_start, self.t0, self.t_end) if value is not None]
        if known != sorted(known):
            raise ValueError("known ground-truth timestamps must be ordered")
        return self


class GroundTruth(APIModel):
    source: Literal["CARLA Incident", "Human annotation", "Reviewer verified"]
    incident_type: AccidentType | None = None
    severity: str | None = None
    timeline: GroundTruthTimeline | None = None


class AiIncidentPrediction(APIModel):
    incident_type: AccidentType | None = None
    severity: str | None = None
    timeline: GroundTruthTimeline | None = None


class AiGroundTruthEvaluation(APIModel):
    overall_accuracy: float | None = Field(default=None, ge=0, le=1)
    incident_type_match: bool | None = None
    severity_match: bool | None = None
    t0_delta_s: float | None = Field(default=None, ge=0)
    timeline_iou: float | None = Field(default=None, ge=0, le=1)
    prediction: AiIncidentPrediction


class IncidentSnapshot(APIModel):
    incident_id: str
    status: IncidentStatus
    has_log: bool
    video_summary: str = ""
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    claim_log_summaries: list[ClaimLogSummary] = Field(default_factory=list)
    conflict_claim_ids: list[str] = Field(default_factory=list)
    auto_reanalysis_count: int = Field(default=0, ge=0)
    manual_reanalysis_count: int = Field(default=0, ge=0)
    draft_report: DraftReport | None = None
    final_report: DraftReport | None = None
    review_audit: list[ReviewAuditEntry] = Field(default_factory=list)
    model_activities: list[ModelActivity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ground_truth: GroundTruth | None = None
    ai_evaluation: AiGroundTruthEvaluation | None = None
    error_code: str | None = None
    error_message: str | None = None
    stored_at: datetime | None = None


class StoredReport(APIModel):
    incident_id: str
    status: Literal["approved", "not_incident"]
    has_log: bool = False
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_audit: list[ReviewAuditEntry] = Field(default_factory=list)
    model_activities: list[ModelActivity] = Field(default_factory=list)
    ground_truth: GroundTruth | None = None
    ai_evaluation: AiGroundTruthEvaluation | None = None
    final_report: DraftReport | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reviewer: str
    decision: Literal["approve", "edit", "not_incident"]
    reason: str | None = None
    stored_at: datetime | None = None

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> StoredReport:
        if self.status == "approved" and self.final_report is None:
            raise ValueError("approved outcome requires a final report")
        if self.status == "not_incident" and not (self.reason or "").strip():
            raise ValueError("not_incident outcome requires a reason")
        if self.status == "not_incident" and self.decision != "not_incident":
            raise ValueError("not_incident status requires the matching decision")
        if self.status == "approved" and self.decision not in {"approve", "edit"}:
            raise ValueError("approved status requires approve or edit decision")
        return self


class StoredReportsResponse(APIModel):
    reports: list[StoredReport] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class IncidentHistoryResponse(APIModel):
    incident_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class IncidentDeleteResponse(APIModel):
    incident_id: str
    deleted: bool
