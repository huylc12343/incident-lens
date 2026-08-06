"""Concrete dependency factory and lifecycle for the incident workflow."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from src.agents.incident_graph import IncidentGraphDependencies, LangGraphIncidentRunner, build_incident_graph
from src.config import Settings
from src.models.api import IncidentCreateRequest
from src.models.incidents import VLMProvider
from src.services.charts import ChartService
from src.services.log_analysis import LogAnalysisService
from src.services.media import MediaService
from src.services.model_observability import ModelActivityRegistry
from src.services.report_repository import SQLiteReportRepository
from src.services.reporting import OpenAIReportService
from src.services.verification import OpenAIVerificationService
from src.services.video_memory import VideoMemoryLimits, VideoMemoryWorkflow, VideoMemoryWorkflowConfig
from src.services.vlm import GeminiNativeVideoVLMService, OpenAIVLMService
from src.services.workflow import WorkflowError, WorkflowService


@dataclass(frozen=True)
class ProviderClients:
    openai_vlm: Any | None = None
    openai_verification: Any | None = None
    openai_report: Any | None = None
    gemini: Any | None = None


class DirectAsyncSqliteSaver(SqliteSaver):
    """SQLite saver with async methods that avoid a thread-executor dependency."""

    async def aget_tuple(self, config):
        return self.get_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        self.delete_thread(thread_id)


class ConfiguredIncidentInputValidator:
    def __init__(self, *, settings: Settings, media: MediaService) -> None:
        self._settings = settings
        self._media = media
        roots = [item.strip() for item in settings.incident_input_roots.split(",") if item.strip()]
        if not roots:
            raise ValueError("incident_input_roots must contain at least one path")
        self._roots = [Path(item).resolve() for item in roots]
        upload_root = Path(settings.incident_upload_dir).resolve()
        if upload_root not in self._roots:
            self._roots.append(upload_root)

    async def validate(self, request: IncidentCreateRequest) -> None:
        if len(request.analysis_prompt) > self._settings.human_prompt_max_length:
            raise WorkflowError("ANALYSIS_PROMPT_TOO_LONG", "analysis prompt exceeds the configured limit")
        video = self._validated_path(request.video_uri, "video", self._settings.incident_max_video_bytes)
        if request.log_uri is not None:
            self._validated_path(request.log_uri, "log", self._settings.incident_max_log_bytes)
        try:
            metadata = await self._media.probe_video(str(video))
        except Exception as exc:
            raise WorkflowError("VIDEO_INPUT_INVALID", "video input could not be validated") from exc
        if metadata.duration_s > self._settings.incident_max_duration_s:
            raise WorkflowError("VIDEO_DURATION_EXCEEDED", "video duration exceeds 60 seconds")

    def _validated_path(self, value: str, label: str, max_bytes: int) -> Path:
        path = Path(value).resolve()
        if not any(path.is_relative_to(root) for root in self._roots):
            raise WorkflowError("INCIDENT_INPUT_OUTSIDE_ROOT", f"{label} input is outside configured roots")
        if not path.is_file():
            raise WorkflowError("INCIDENT_INPUT_NOT_FOUND", f"{label} input does not exist")
        if path.stat().st_size > max_bytes:
            raise WorkflowError("INCIDENT_INPUT_TOO_LARGE", f"{label} input exceeds the configured size limit")
        return path


@asynccontextmanager
async def incident_workflow_service(
    settings: Settings,
    *,
    clients: ProviderClients | None = None,
) -> AsyncIterator[WorkflowService]:
    clients = clients or ProviderClients()
    media = MediaService()
    observability = ModelActivityRegistry()
    vlm = _build_vlm(settings, clients, observability)
    video_workflow = VideoMemoryWorkflow(
        vlm=vlm,
        config=VideoMemoryWorkflowConfig(
            artifact_dir=settings.artifact_dir,
            frame_fps=settings.vlm_frame_fps,
            frame_width=settings.vlm_frame_width,
            frame_height=settings.vlm_frame_height,
            frame_format=settings.vlm_frame_format,
            frame_jpeg_quality=settings.vlm_frame_jpeg_quality,
            max_frames=settings.vlm_max_frames,
            max_frames_per_request=settings.vlm_max_frames_per_request,
            frame_overflow_strategy=settings.vlm_frame_overflow_strategy,
            frame_batch_size=settings.vlm_frame_batch_size,
            frame_batch_overlap=settings.vlm_frame_batch_overlap,
            frame_max_batches=settings.vlm_frame_max_batches,
            incident_frame_fps=settings.vlm_reanalysis_frame_fps,
            incident_max_frames=settings.vlm_reanalysis_max_frames,
            incident_clip_min_duration_s=settings.incident_clip_min_duration_s,
            incident_clip_pre_roll_s=settings.incident_clip_pre_roll_s,
            incident_clip_post_roll_s=settings.incident_clip_post_roll_s,
            video_target_width=settings.vlm_video_target_width,
            video_target_height=settings.vlm_video_target_height,
            video_target_fps=settings.vlm_video_target_fps,
            video_codec=settings.vlm_video_codec,
            video_pixel_format=settings.vlm_video_pixel_format,
            video_max_output_bytes=settings.vlm_video_max_output_bytes,
            max_duration_s=settings.incident_max_duration_s,
            prompt_version=settings.video_analysis_prompt_version,
            limits=VideoMemoryLimits(
                max_entities=settings.video_memory_max_entities,
                max_timeline_events=settings.video_memory_max_timeline_events,
                max_claims=settings.video_memory_max_claims,
            ),
        ),
    )
    verification = OpenAIVerificationService(
        model=settings.verification_model_name,
        client=clients.openai_verification,
        api_key=_openai_key(settings, clients.openai_verification),
        timeout_s=settings.verification_timeout_s,
        temperature=settings.verification_temperature,
        prompt_version=settings.verification_prompt_version,
        observability=observability,
    )
    report = OpenAIReportService(
        model=settings.report_model_name,
        client=clients.openai_report,
        api_key=_openai_key(settings, clients.openai_report),
        timeout_s=settings.report_timeout_s,
        temperature=settings.report_temperature,
        prompt_version=settings.reporting_prompt_version,
        observability=observability,
    )
    dependencies = IncidentGraphDependencies(
        media=media,
        video_workflow=video_workflow,
        log_analysis=LogAnalysisService(
            brake_rise_threshold=settings.log_brake_rise_threshold,
            steering_change_threshold=settings.log_steering_change_threshold,
        ),
        charts=ChartService(),
        verification=verification,
        report=report,
        artifact_dir=settings.artifact_dir,
        timestamp_tolerance_s=settings.log_timestamp_tolerance_s,
        reanalysis_prompt_version=settings.reanalysis_prompt_version,
        cleanup_remote_resources=settings.gemini_delete_remote_file_on_terminal,
        observability=observability,
    )
    checkpoint_path = Path(settings.incident_checkpoint_path).resolve()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    checkpointer = DirectAsyncSqliteSaver(connection)
    try:
        checkpointer.setup()
        graph = build_incident_graph(dependencies=dependencies, checkpointer=checkpointer)
        service = WorkflowService(
            runner=LangGraphIncidentRunner(graph),
            repository=SQLiteReportRepository(settings.incident_database_path),
            input_validator=ConfiguredIncidentInputValidator(settings=settings, media=media),
            observability=observability,
        )
        yield service
    finally:
        connection.close()


def _build_vlm(
    settings: Settings,
    clients: ProviderClients,
    observability: ModelActivityRegistry | None = None,
) -> OpenAIVLMService | GeminiNativeVideoVLMService:
    if settings.vlm_provider == VLMProvider.OPENAI:
        return OpenAIVLMService(
            model=settings.openai_vlm_model_name,
            client=clients.openai_vlm,
            api_key=_openai_key(settings, clients.openai_vlm),
            timeout_s=settings.vlm_timeout_s,
            temperature=settings.vlm_temperature,
            max_images_per_request=settings.vlm_max_frames_per_request,
            observability=observability,
        )
    if clients.gemini is None and not settings.gemini_api_key.strip():
        raise ValueError("GEMINI_API_KEY is required for the configured VLM provider")
    return GeminiNativeVideoVLMService(
        model=settings.gemini_vlm_model_name,
        client=clients.gemini,
        api_key=settings.gemini_api_key or None,
        poll_interval_s=settings.gemini_file_poll_interval_s,
        processing_timeout_s=settings.gemini_file_processing_timeout_s,
        max_poll_attempts=settings.gemini_file_max_poll_attempts,
        timeout_s=settings.vlm_timeout_s,
        temperature=settings.vlm_temperature,
        media_resolution=settings.gemini_media_resolution,
        video_fps=settings.gemini_video_fps,
        reupload_missing_file=settings.gemini_reupload_missing_file,
        observability=observability,
    )


def _openai_key(settings: Settings, client: Any | None) -> str | None:
    if client is None and not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY is required for the configured workflow")
    return settings.openai_api_key or None
