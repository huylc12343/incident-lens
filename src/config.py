from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for every tunable value in the service.

    Each field below is populated from the matching UPPERCASE key in `.env`.
    Because `extra="ignore"`, a key in `.env` with no field here is silently
    discarded — always add the field first, then document it in `.env.example`.
    `tests/test_config.py` enforces both halves of that rule.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- App ----
    # Service name reported by the startup banner.
    app_name: str = "AI20K Agent"
    # Selects the deployment profile. "production" additionally requires provider
    # credentials (see require_provider_credentials_in_production below).
    app_env: Literal["development", "production", "test"] = "development"
    # Minimum severity kept when logging is configured.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Comma-separated browser origin allowlist handed to CORSMiddleware.
    cors_origins: str = "http://localhost:3000"

    # ---- LLM (verification, reporting, and the eval judge) ----
    # OpenAI credential. Never used for video analysis; that is DashScope's job.
    openai_api_key: str = ""
    # Model behind src.services.llm.get_llm, used only by the eval semantic judge.
    model_name: str = "gpt-5.6-luna"
    # Sampling temperature for that judge. Higher means less repeatable answers.
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # ---- LangSmith tracing (optional; never changes routing or output) ----
    # Master switch. Everything below is inert while this is false.
    langsmith_tracing: bool = False
    # LangSmith credential; tracing silently stays off when blank.
    langsmith_api_key: str = ""
    # Project name traces are grouped under in the LangSmith UI.
    langsmith_project: str = "incident-analysis-dev"
    # LangSmith API host. Change only for a self-hosted instance.
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    # Needed only when the API key belongs to more than one workspace.
    langsmith_workspace_id: str = ""
    # Fraction of runs traced: 1.0 traces every run, 0.1 traces one in ten.
    langsmith_tracing_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    # ---- Video-language model (Qwen native video via DashScope) ----
    # DashScope credential. Required for any real video analysis.
    dashscope_api_key: str = ""
    # Qwen model id used for video analysis and focused re-analysis.
    qwen_vlm_model_name: str = "qwen3-vl-flash"
    # DashScope OpenAI-compatible endpoint.
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    # Public URL mapped onto artifact_dir. Required only for videos too large to
    # inline as Base64; leave blank to keep every upload machine-local.
    qwen_artifact_url_base: str = ""
    # Videos at or below this size are inlined as a Base64 data URL. Larger ones
    # need qwen_artifact_url_base, otherwise analysis fails.
    qwen_base64_max_video_bytes: int = Field(default=7_000_000, gt=0)
    # Frame rate Qwen samples the video at on its side. Higher costs more tokens.
    qwen_video_fps: float = Field(default=2.0, gt=0, le=10)
    # Enables Qwen's extended reasoning mode. Slower and more expensive per call.
    qwen_enable_thinking: bool = False
    # Token ceiling for that reasoning when it is enabled.
    qwen_thinking_budget: int = Field(default=500, gt=0)
    # Per-request deadline for any VLM call.
    vlm_timeout_s: float = Field(default=120.0, gt=0)
    # Retries when the model returns JSON that fails schema validation.
    # 0 means one malformed reply discards an incident that already cost a call.
    vlm_structured_output_retries: int = Field(default=0, ge=0)
    # Retries for transport-level provider failures. Same caveat as above.
    provider_network_retries: int = Field(default=0, ge=0)
    # Hard ceiling on provider calls for one incident; the cost circuit breaker.
    provider_request_limit_per_incident: int = Field(default=12, gt=0)
    # Sampling temperature for the VLM. Keep at 0 so analysis is reproducible.
    vlm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # ---- Native video preprocessing (before upload) ----
    # Target resolution the source video is resized and padded to.
    vlm_video_target_width: int = Field(default=1280, gt=0)
    vlm_video_target_height: int = Field(default=720, gt=0)
    # Normalized frame rate, so timestamps mean the same thing across sources.
    vlm_video_target_fps: float = Field(default=15.0, gt=0)
    # Preserves aspect ratio and pads the remainder rather than stretching.
    vlm_video_resize_mode: Literal["fit_pad"] = "fit_pad"
    # FFmpeg encoder settings for the normalized copy.
    vlm_video_codec: str = "libx264"
    vlm_video_pixel_format: str = "yuv420p"
    # Ceiling on the normalized file. Without qwen_artifact_url_base the runtime
    # takes min(this, qwen_base64_max_video_bytes).
    vlm_video_max_output_bytes: int = Field(default=100_000_000, gt=0)
    # Blurs faces and licence plates locally before anything leaves the machine.
    # Turning this off sends unredacted footage to a third-party provider.
    video_redaction_enabled: bool = True
    # YOLO inference resolution for that redaction pass. Lower is faster and
    # misses more; higher is slower and catches more.
    redaction_image_size: int = Field(default=512, gt=0)
    # Detector runs per second of footage. The tracker bridges the frames in
    # between, so every frame is still blurred, but an object that appears and
    # leaves inside one gap is never localized and never blurred.
    # Redaction runs on the normalized copy, so this is compared against
    # vlm_video_target_fps, not the uploaded file's frame rate. At or above that
    # value the stride collapses to 1 and every frame pays full inference, so
    # keep it well below.
    redaction_detection_fps: float = Field(default=5.0, gt=0)

    # ---- Frame artifacts used to canonicalize Qwen timestamps after analysis ----
    # Size and quality of the stills each claim and timeline event is pinned to.
    vlm_frame_width: int = Field(default=1024, gt=0)
    vlm_frame_height: int = Field(default=576, gt=0)
    vlm_frame_format: Literal["jpeg", "png"] = "jpeg"
    vlm_frame_jpeg_quality: int = Field(default=85, ge=1, le=100)
    # Sampling density and cap for the focused clip during re-analysis.
    vlm_reanalysis_frame_fps: float = Field(default=4.0, gt=0)
    vlm_reanalysis_max_frames: int = Field(default=60, gt=0)
    # Upper bounds the model output must respect, rejected beyond these.
    video_memory_max_timeline_events: int = Field(default=6, gt=0)
    video_memory_max_claims: int = Field(default=100, gt=0)

    # ---- Prompt and downstream service settings ----
    # Labels stamped onto PromptEnvelope for traceability. They do NOT select a
    # different prompt; there is no branching on version anywhere.
    video_analysis_prompt_version: str = "v1"
    reanalysis_prompt_version: str = "v1"
    verification_prompt_version: str = "v1"
    reporting_prompt_version: str = "v1"
    # Model that checks each claim against the vehicle log.
    verification_model_name: str = "gpt-4o-mini"
    verification_timeout_s: float = Field(default=60.0, gt=0)
    verification_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # Model that writes the narrative sections of the report.
    report_model_name: str = "gpt-4o-mini"
    report_timeout_s: float = Field(default=60.0, gt=0)
    report_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # When a claim contradicts the log, re-ask the VLM once on a focused clip.
    # Set false to surface the contradiction without spending another call.
    auto_reanalysis_enabled: bool = True
    # Seconds kept each side of the claim when cutting that focused clip.
    auto_reanalysis_clip_radius_s: float = Field(default=2.0, gt=0)

    # ---- Workflow and incident inputs ----
    # Longest analyst instruction accepted on incident creation.
    human_prompt_max_length: int = Field(default=5000, gt=0)
    # Largest accepted telemetry CSV. Video size is not capped here.
    incident_max_log_bytes: int = Field(default=25_000_000, gt=0)
    # Comma-separated directories inputs may be read from. This is the path
    # traversal boundary; incident_upload_dir is always added to it.
    incident_input_roots: str = "./data_mock"
    # Where multipart uploads land.
    incident_upload_dir: str = "./data/uploads"
    # Videos longer than this are rejected before any provider call.
    incident_max_duration_s: float = Field(default=60.0, gt=0, le=60)
    # Shape of the incident clip cut for the reviewer: a floor on total length,
    # plus lead-in and lead-out around the window the VLM identified.
    incident_clip_min_duration_s: float = Field(default=5.0, gt=0)
    incident_clip_pre_roll_s: float = Field(default=1.0, ge=0)
    incident_clip_post_roll_s: float = Field(default=2.0, ge=0)
    # How far from a claim's timestamp a log row may sit and still count.
    log_timestamp_tolerance_s: float = Field(default=0.5, ge=0)
    # Log rows kept each side of the nearest sample: 3 yields at most 7 rows.
    # Raising this multiplies verification prompt size for every claim.
    log_claim_sample_radius: int = Field(default=3, ge=0)
    # Generated media: normalized video, clips, frames, charts.
    artifact_dir: str = "./data/artifacts"
    # Terminal reports (approved / not_incident).
    incident_database_path: str = "./data/incident_reports.sqlite3"
    # LangGraph checkpoints backing resume and human review.
    incident_checkpoint_path: str = "./data/incident_checkpoints.sqlite3"
    # Age at which artifacts of finished incidents are pruned on startup.
    incident_artifact_retention_hours: float = Field(default=168, gt=0)
    # Retention and per-incident cap for recorded model activity and token usage.
    model_activity_retention_hours: float = Field(default=168, gt=0)
    model_activity_max_per_incident: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def require_provider_credentials_in_production(self) -> Settings:
        """Fail fast on a misconfigured production boot instead of erroring per incident.

        Development and test stay permissive: they run against stubbed provider clients.
        """
        if self.app_env != "production":
            return self
        missing = [
            name
            for name, value in (
                ("OPENAI_API_KEY", self.openai_api_key),
                ("DASHSCOPE_API_KEY", self.dashscope_api_key),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} must be set when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
