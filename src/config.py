from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.incidents import VLMInputMode, VLMProvider


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

    # Video-language model
    vlm_provider: VLMProvider = VLMProvider.OPENAI
    vlm_input_mode: VLMInputMode = VLMInputMode.TIMESTAMPED_FRAMES
    openai_vlm_model_name: str = "gpt-5.6-luna"
    dashscope_api_key: str = ""
    qwen_vlm_model_name: str = "qwen3-vl-flash"
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_artifact_url_base: str = ""
    qwen_base64_max_video_bytes: int = Field(default=7_000_000, gt=0)
    qwen_video_fps: float = Field(default=2.0, gt=0, le=10)
    qwen_enable_thinking: bool = False
    qwen_thinking_budget: int = Field(default=500, gt=0)
    vlm_timeout_s: float = Field(default=120.0, gt=0)
    vlm_max_retries: int = Field(default=2, ge=0)
    vlm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # Native video preprocessing
    vlm_video_target_width: int = Field(default=1280, gt=0)
    vlm_video_target_height: int = Field(default=720, gt=0)
    vlm_video_target_fps: float = Field(default=15.0, gt=0)
    vlm_video_resize_mode: Literal["fit_pad"] = "fit_pad"
    vlm_video_codec: str = "libx264"
    vlm_video_pixel_format: str = "yuv420p"
    vlm_video_max_output_bytes: int = Field(default=100_000_000, gt=0)

    # Timestamped frames and memory limits
    vlm_frame_fps: float = Field(default=2.0, gt=0)
    vlm_frame_width: int = Field(default=1024, gt=0)
    vlm_frame_height: int = Field(default=576, gt=0)
    vlm_frame_format: Literal["jpeg", "png"] = "jpeg"
    vlm_frame_jpeg_quality: int = Field(default=85, ge=1, le=100)
    vlm_max_frames: int = Field(default=120, gt=0)
    vlm_max_frames_per_request: int = Field(default=120, gt=0)
    vlm_reanalysis_frame_fps: float = Field(default=4.0, gt=0)
    vlm_reanalysis_max_frames: int = Field(default=60, gt=0)
    vlm_frame_overflow_strategy: Literal["rolling_batches", "fail"] = "rolling_batches"
    vlm_frame_batch_size: int = Field(default=60, gt=0)
    vlm_frame_batch_overlap: int = Field(default=5, ge=0)
    vlm_frame_max_batches: int = Field(default=8, gt=0)
    video_memory_max_entities: int = Field(default=50, gt=0)
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
    incident_max_video_bytes: int = Field(default=250_000_000, gt=0)
    incident_max_log_bytes: int = Field(default=25_000_000, gt=0)
    incident_input_roots: str = "./data_mock"
    incident_upload_dir: str = "./data/uploads"
    incident_max_duration_s: float = Field(default=60.0, gt=0, le=60)
    incident_clip_min_duration_s: float = Field(default=5.0, gt=0)
    incident_clip_pre_roll_s: float = Field(default=1.0, ge=0)
    incident_clip_post_roll_s: float = Field(default=2.0, ge=0)
    log_timestamp_tolerance_s: float = Field(default=0.5, ge=0)
    log_brake_rise_threshold: float = Field(default=0.3, ge=0)
    log_steering_change_threshold: float = Field(default=10.0, ge=0)
    artifact_dir: str = "./data/artifacts"
    incident_database_path: str = "./data/incident_reports.sqlite3"
    incident_checkpoint_path: str = "./data/incident_checkpoints.sqlite3"
    background_concurrency: int = Field(default=2, gt=0)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"

    @model_validator(mode="after")
    def validate_provider_mode(self) -> Settings:
        supported_mode = {
            VLMProvider.OPENAI: VLMInputMode.TIMESTAMPED_FRAMES,
            VLMProvider.QWEN: VLMInputMode.NATIVE_VIDEO,
        }[self.vlm_provider]
        if self.vlm_input_mode != supported_mode:
            raise ValueError(
                f"unsupported VLM provider/input mode: {self.vlm_provider.value} + "
                f"{self.vlm_input_mode.value}; expected {supported_mode.value}"
            )
        if self.vlm_frame_batch_overlap >= self.vlm_frame_batch_size:
            raise ValueError("vlm_frame_batch_overlap must be smaller than vlm_frame_batch_size")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
