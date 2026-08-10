"""Provider-neutral contracts for the incident analysis workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VLMProvider(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    QWEN = "qwen"


class VLMInputMode(StrEnum):
    TIMESTAMPED_FRAMES = "timestamped_frames"
    NATIVE_VIDEO = "native_video"


class AnalysisMode(StrEnum):
    SINGLE_REQUEST = "single_request"
    ROLLING_BATCHES = "rolling_batches"
    NATIVE_VIDEO = "native_video"


class VerificationStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"


class PromptSource(StrEnum):
    SYSTEM = "system"
    AGENT_GENERATED = "agent_generated"
    HUMAN_PROVIDED = "human_provided"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentWindow(ContractModel):
    t_start: float = Field(ge=0)
    t0: float = Field(ge=0)
    t_end: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> IncidentWindow:
        if not self.t_start <= self.t0 <= self.t_end:
            raise ValueError("incident timestamps must satisfy t_start <= t0 <= t_end")
        return self


class PromptEnvelope(ContractModel):
    text: str = Field(min_length=1)
    source: PromptSource = PromptSource.SYSTEM
    version: str = Field(default="v1", min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class TimestampedFrame(ContractModel):
    frame_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    timestamp_s: float = Field(ge=0)
    delta_from_previous_s: float = Field(ge=0)
    image_uri: str = Field(min_length=1)
    mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"


class VideoSequenceManifest(ContractModel):
    frames: list[TimestampedFrame] = Field(min_length=1)
    source_video_uri: str = Field(min_length=1)
    duration_s: float = Field(gt=0, le=60)

    @model_validator(mode="after")
    def validate_frame_order(self) -> VideoSequenceManifest:
        indexes = [frame.sequence_index for frame in self.frames]
        timestamps = [frame.timestamp_s for frame in self.frames]
        if indexes != list(range(len(self.frames))):
            raise ValueError("frame sequence_index values must be contiguous and start at zero")
        if timestamps != sorted(timestamps):
            raise ValueError("frames must be ordered by timestamp")
        if timestamps[-1] > self.duration_s:
            raise ValueError("frame timestamp cannot exceed video duration")
        return self


class NativeVideoMetadata(ContractModel):
    duration_s: float = Field(gt=0, le=60)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    mime_type: Literal["video/mp4"] = "video/mp4"
    size_bytes: int = Field(gt=0)


class RemoteMediaHandle(ContractModel):
    provider: VLMProvider
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    local_artifact_uri: str = Field(min_length=1)


class TrackedEntity(ContractModel):
    entity_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""


class TimelineEvent(ContractModel):
    timestamp_s: float = Field(ge=0)
    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class Observation(ContractModel):
    observation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp_s: float | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)


class Claim(ContractModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp_s: float | None = Field(default=None, ge=0)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class EvidenceReference(ContractModel):
    evidence_id: str = Field(min_length=1)
    timestamp_s: float = Field(ge=0)


class SamplingMetadata(ContractModel):
    requested_fps: float = Field(gt=0)
    sampled_frame_count: int = Field(ge=0)
    source_duration_s: float = Field(gt=0, le=60)
    batch_count: int = Field(default=1, ge=1)


class VideoMemory(ContractModel):
    global_scene: str = Field(min_length=1)
    video_summary: str | None = Field(default=None, min_length=1)
    tracked_entities: list[TrackedEntity] = Field(default_factory=list)
    incident_window: IncidentWindow
    representative_timestamp_s: float | None = Field(default=None, ge=0)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    analysis_mode: AnalysisMode
    sampling_metadata: SamplingMetadata | None = None
    remote_media_handles: list[RemoteMediaHandle] = Field(default_factory=list)


class VideoMemoryPatch(ContractModel):
    target_claim_ids: list[str] = Field(min_length=1)
    claims: list[Claim] = Field(default_factory=list)
    remote_media_handles: list[RemoteMediaHandle] = Field(default_factory=list)
    base_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_claim_scope(self) -> VideoMemoryPatch:
        target_ids = set(self.target_claim_ids)
        returned_ids = {claim.claim_id for claim in self.claims}
        if len(target_ids) != len(self.target_claim_ids):
            raise ValueError("target_claim_ids must be unique")
        if not returned_ids.issubset(target_ids):
            raise ValueError("memory patch cannot modify claims outside target_claim_ids")
        return self


class TimestampedFramesAnalysisRequest(ContractModel):
    input_mode: Literal[VLMInputMode.TIMESTAMPED_FRAMES] = VLMInputMode.TIMESTAMPED_FRAMES
    incident_id: str = Field(min_length=1)
    prompt: PromptEnvelope
    manifest: VideoSequenceManifest


class NativeVideoAnalysisRequest(ContractModel):
    input_mode: Literal[VLMInputMode.NATIVE_VIDEO] = VLMInputMode.NATIVE_VIDEO
    incident_id: str = Field(min_length=1)
    prompt: PromptEnvelope
    normalized_video_uri: str = Field(min_length=1)
    metadata: NativeVideoMetadata
    remote_media_handle: RemoteMediaHandle | None = None


VideoAnalysisRequest: TypeAlias = Annotated[
    TimestampedFramesAnalysisRequest | NativeVideoAnalysisRequest,
    Field(discriminator="input_mode"),
]


class ReanalysisRequest(ContractModel):
    incident_id: str = Field(min_length=1)
    prompt: PromptEnvelope
    target_claim_ids: list[str] = Field(min_length=1)
    incident_window: IncidentWindow
    current_memory: VideoMemory
    frame_manifest: VideoSequenceManifest | None = None
    normalized_video_uri: str | None = None
    remote_media_handles: list[RemoteMediaHandle] = Field(default_factory=list)


class LogEvidenceSummary(ContractModel):
    summary: str = ""
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class LogEvent(ContractModel):
    event_id: str = Field(min_length=1)
    event_type: Literal["brake_rise", "steering_change", "disengagement", "warning", "error"]
    timestamp_s: float = Field(ge=0)
    signal: str = Field(min_length=1)
    value: float | int | str | bool | None = None
    previous_value: float | int | str | bool | None = None
    details: str = ""
    evidence_id: str = Field(min_length=1)


class LogAnalysisResult(ContractModel):
    log_slice_uri: str = Field(min_length=1)
    summary: LogEvidenceSummary
    events: list[LogEvent] = Field(default_factory=list)
    row_count: int = Field(gt=0)
    signal_names: list[str] = Field(default_factory=list)


class ClaimLogEvidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    timestamp_s: float = Field(ge=0)
    camera_frame: str | int | float | None = None


class ClaimLogSummary(ContractModel):
    claim_id: str = Field(min_length=1)
    claim_timestamp_s: float | None = Field(default=None, ge=0)
    nearest_timestamp_s: float | None = Field(default=None, ge=0)
    timestamp_distance_s: float | None = Field(default=None, ge=0)
    within_tolerance: bool = False
    sample_start_s: float | None = Field(default=None, ge=0)
    sample_end_s: float | None = Field(default=None, ge=0)
    sample_count: int = Field(default=0, ge=0)
    available_signals: list[str] = Field(default_factory=list)
    metrics: dict[str, dict[str, float | int | str | bool | None]] = Field(default_factory=dict)
    evidence: list[ClaimLogEvidence] = Field(default_factory=list)
    allowed_evidence_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class VerificationRequest(ContractModel):
    incident_id: str = Field(min_length=1)
    claims: list[Claim]
    claim_log_summaries: list[ClaimLogSummary]
    timestamp_tolerance_s: float = Field(ge=0)


class ClaimVerification(ContractModel):
    claim_id: str = Field(min_length=1)
    status: Literal[
        VerificationStatus.SUPPORTED,
        VerificationStatus.CONTRADICTED,
        VerificationStatus.UNVERIFIED,
    ]
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationResult(ContractModel):
    results: list[ClaimVerification]


class ReportRequest(ContractModel):
    incident_id: str = Field(min_length=1)
    video_memory: VideoMemory
    verification: VerificationResult | None = None
    log_evidence_summary: LogEvidenceSummary | None = None


class ReportNarrative(ContractModel):
    summary: str = Field(min_length=1)
    timeline: str = Field(min_length=1)
    video_observations: str = Field(min_length=1)
    log_findings: str = Field(min_length=1)
    alignment: str = Field(min_length=1)
    hypothesized_causes: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ReportGeneralInformation(ContractModel):
    incident_id: str = Field(min_length=1)
    video_uri: str = Field(min_length=1)
    has_log: bool
    log_uri: str | None = None


class ReportEvidenceAndWarnings(ContractModel):
    evidence: list[EvidenceReference] = Field(default_factory=list)
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ReportTimelineSection(ContractModel):
    narrative: str = Field(min_length=1)
    events: list[TimelineEvent] = Field(default_factory=list)


class ReportVideoObservationsSection(ContractModel):
    narrative: str = Field(min_length=1)
    observations: list[Observation] = Field(default_factory=list)


class ReportLogSection(ContractModel):
    narrative: str = Field(min_length=1)
    summary: LogEvidenceSummary | None = None
    claim_summaries: list[ClaimLogSummary] = Field(default_factory=list)


class ReportAlignmentSection(ContractModel):
    narrative: str = Field(min_length=1)
    verification: VerificationResult | None = None


class DraftReport(ContractModel):
    """Backend-owned ten-section incident report.

    The language model supplies only the six narrative strings. All source facts,
    artifacts, warnings, and lifecycle fields are assembled by the backend.
    """

    general_information: ReportGeneralInformation
    incident_window: IncidentWindow
    summary: str = Field(min_length=1)
    timeline: ReportTimelineSection
    video_observations: ReportVideoObservationsSection
    log_findings: ReportLogSection
    alignment: ReportAlignmentSection
    hypothesized_causes: str = Field(min_length=1)
    evidence_and_warnings: ReportEvidenceAndWarnings
    review_status: Literal["pending", "approved", "edited", "not_incident"] = "pending"


class VLMCapabilities(ContractModel):
    provider: VLMProvider
    input_mode: VLMInputMode
    supports_reanalysis: bool = True
    max_images_per_request: int | None = Field(default=None, gt=0)


@runtime_checkable
class VLMService(Protocol):
    @property
    def capabilities(self) -> VLMCapabilities: ...

    async def analyze_video(self, request: VideoAnalysisRequest) -> VideoMemory: ...

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch: ...

    async def release_remote_resources(self, handles: list[RemoteMediaHandle]) -> None: ...


@runtime_checkable
class VerificationService(Protocol):
    async def verify(self, request: VerificationRequest) -> VerificationResult: ...


@runtime_checkable
class ReportService(Protocol):
    async def build_narrative(self, request: ReportRequest) -> ReportNarrative: ...
