from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Telemetry event thresholds are deliberately separate from the lower thresholds
# used only to build qualitative VLM attention hints.
LOG_STRONG_DECELERATION_THRESHOLD_MPS2_DEFAULT = -5.0
LOG_STRONG_ACCELERATION_THRESHOLD_MPS2_DEFAULT = 4.0
LOG_EXTREME_ACCELERATION_THRESHOLD_MPS2_DEFAULT = 8.0
LOG_STRONG_STEERING_DELTA_THRESHOLD_DEFAULT = 0.3


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM
    openai_api_key: str = ""
    model_name: str = "gpt-5.6-luna"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # LangSmith tracing
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "incident-analysis-dev"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str = ""
    langsmith_tracing_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    # Video-language model
    dashscope_api_key: str = ""
    qwen_vlm_model_name: str = "qwen3-vl-flash"
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_artifact_url_base: str = ""
    qwen_base64_max_video_bytes: int = Field(default=7_000_000, gt=0)
    qwen_video_fps: float = Field(default=2.0, gt=0, le=10)
    qwen_enable_thinking: bool = False
    qwen_thinking_budget: int = Field(default=500, gt=0)
    vlm_timeout_s: float = Field(default=120.0, gt=0)
    vlm_structured_output_retries: int = Field(default=0, ge=0)
    provider_network_retries: int = Field(default=0, ge=0)
    provider_request_limit_per_incident: int = Field(default=12, gt=0)
    vlm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # Native video preprocessing
    vlm_video_target_width: int = Field(default=1280, gt=0)
    vlm_video_target_height: int = Field(default=720, gt=0)
    vlm_video_target_fps: float = Field(default=15.0, gt=0)
    vlm_video_resize_mode: Literal["fit_pad"] = "fit_pad"
    vlm_video_codec: str = "libx264"
    vlm_video_pixel_format: str = "yuv420p"
    vlm_video_max_output_bytes: int = Field(default=100_000_000, gt=0)

    # Frame artifacts used to canonicalize Qwen timestamps after analysis.
    vlm_frame_width: int = Field(default=1024, gt=0)
    vlm_frame_height: int = Field(default=576, gt=0)
    vlm_frame_format: Literal["jpeg", "png"] = "jpeg"
    vlm_frame_jpeg_quality: int = Field(default=85, ge=1, le=100)
    vlm_reanalysis_frame_fps: float = Field(default=4.0, gt=0)
    vlm_reanalysis_max_frames: int = Field(default=60, gt=0)
    video_memory_max_timeline_events: int = Field(default=6, gt=0)
    video_memory_max_claims: int = Field(default=100, gt=0)

    # Prompt and downstream service settings
    video_analysis_prompt_version: str = "v1"
    reanalysis_prompt_version: str = "v1"
    verification_prompt_version: str = "v1"
    reporting_prompt_version: str = "v1"
    verification_model_name: str = "gpt-4o-mini"
    verification_timeout_s: float = Field(default=60.0, gt=0)
    verification_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    report_model_name: str = "gpt-4o-mini"
    report_timeout_s: float = Field(default=60.0, gt=0)
    report_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    auto_reanalysis_enabled: bool = True

    # Workflow and incident inputs
    human_prompt_max_length: int = Field(default=5000, gt=0)
    incident_max_log_bytes: int = Field(default=25_000_000, gt=0)
    incident_input_roots: str = "./data_mock"
    incident_upload_dir: str = "./data/uploads"
    incident_max_duration_s: float = Field(default=60.0, gt=0, le=60)
    incident_clip_min_duration_s: float = Field(default=5.0, gt=0)
    incident_clip_pre_roll_s: float = Field(default=1.0, ge=0)
    incident_clip_post_roll_s: float = Field(default=2.0, ge=0)
    log_timestamp_tolerance_s: float = Field(default=0.5, ge=0)
    log_claim_sample_radius: int = Field(default=3, ge=0)
    log_brake_rise_threshold: float = Field(default=0.3, ge=0)
    log_steering_change_threshold: float = Field(default=10.0, ge=0)
    log_strong_deceleration_threshold_mps2: float = Field(
        default=LOG_STRONG_DECELERATION_THRESHOLD_MPS2_DEFAULT,
        lt=0,
    )
    log_strong_acceleration_threshold_mps2: float = Field(
        default=LOG_STRONG_ACCELERATION_THRESHOLD_MPS2_DEFAULT,
        gt=0,
    )
    log_extreme_acceleration_threshold_mps2: float = Field(
        default=LOG_EXTREME_ACCELERATION_THRESHOLD_MPS2_DEFAULT,
        gt=0,
    )
    log_strong_steering_delta_threshold: float = Field(
        default=LOG_STRONG_STEERING_DELTA_THRESHOLD_DEFAULT,
        gt=0,
    )
    artifact_dir: str = "./data/artifacts"
    incident_database_path: str = "./data/incident_reports.sqlite3"
    incident_checkpoint_path: str = "./data/incident_checkpoints.sqlite3"
    background_concurrency: int = Field(default=2, gt=0)
    incident_artifact_retention_hours: float = Field(default=168, gt=0)
    model_activity_retention_hours: float = Field(default=168, gt=0)
    model_activity_max_per_incident: int = Field(default=100, gt=0)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"

@lru_cache
def get_settings() -> Settings:
    return Settings()
