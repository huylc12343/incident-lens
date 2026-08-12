"""Concrete dependency factory and lifecycle for the incident workflow."""

from __future__ import annotations

import re
import shutil
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from src.agents.incident_graph import IncidentGraphDependencies, LangGraphIncidentRunner, build_incident_graph
from src.config import Settings
from src.models.api import IncidentCreateRequest
from src.models.incidents import VLMProvider
from src.services.async_worker import AsyncWorker
from src.services.charts import ChartService
from src.services.log_analysis import LogAnalysisService
from src.services.media import MediaService
from src.services.model_observability import ModelActivityRegistry
from src.services.report_repository import SQLiteReportRepository
from src.services.reporting import OpenAIReportService
from src.services.verification import OpenAIVerificationService
from src.services.video_memory import VideoMemoryLimits, VideoMemoryWorkflow, VideoMemoryWorkflowConfig
from src.services.vlm import OpenAIVLMService, QwenNativeVideoVLMService
from src.services.workflow import WorkflowError, WorkflowService


@dataclass(frozen=True)
class ProviderClients:
    openai_vlm: Any | None = None
    openai_verification: Any | None = None
    openai_report: Any | None = None
    qwen: Any | None = None


class WorkerAsyncSqliteSaver(SqliteSaver):
    """LangGraph SQLite saver serialized on one dedicated daemon worker."""

    def __init__(self, connection: sqlite3.Connection, worker: AsyncWorker) -> None:
        super().__init__(connection)
        self._worker = worker

    async def aget_tuple(self, config):
        return await self._worker.call(self.get_tuple, config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        items = await self._worker.call(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._worker.call(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await self._worker.call(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        await self._worker.call(self.delete_thread, thread_id)


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
    observability = ModelActivityRegistry(
        max_provider_requests_per_incident=settings.provider_request_limit_per_incident,
        max_activities_per_incident=settings.model_activity_max_per_incident,
        retention_hours=settings.model_activity_retention_hours,
    )
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
                max_timeline_events=min(settings.video_memory_max_timeline_events, 6),
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
        claim_log_sample_radius=settings.log_claim_sample_radius,
        reanalysis_prompt_version=settings.reanalysis_prompt_version,
        auto_reanalysis_enabled=settings.auto_reanalysis_enabled,
        cleanup_remote_resources=True,
        observability=observability,
    )
    checkpoint_path = Path(settings.incident_checkpoint_path).resolve()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_worker = AsyncWorker(name="incident-checkpoint-sqlite")
    connection = await checkpoint_worker.call(sqlite3.connect, checkpoint_path, check_same_thread=False)
    checkpointer = WorkerAsyncSqliteSaver(connection, checkpoint_worker)
    try:
        await checkpoint_worker.call(checkpointer.setup)
        graph = build_incident_graph(dependencies=dependencies, checkpointer=checkpointer)
        runner = LangGraphIncidentRunner(graph)
        repository = SQLiteReportRepository(settings.incident_database_path, initialize=False)
        await repository.ainitialize()
        service = WorkflowService(
            runner=runner,
            repository=repository,
            input_validator=ConfiguredIncidentInputValidator(settings=settings, media=media),
            observability=observability,
            artifact_dir=settings.artifact_dir,
            upload_dir=settings.incident_upload_dir,
            remote_resource_releaser=vlm.release_remote_resources,
        )
        retained_incident_ids = {
            re.sub(r"[^A-Za-z0-9_.-]", "_", incident_id) for incident_id in await runner.list_incident_ids()
        }
        await _prune_expired_artifacts(
            Path(settings.artifact_dir).resolve(),
            retention_hours=settings.incident_artifact_retention_hours,
            retained_incident_ids=retained_incident_ids,
        )
        yield service
    finally:
        await checkpoint_worker.call(connection.close)
        checkpoint_worker.close()


def _build_vlm(
    settings: Settings,
    clients: ProviderClients,
    observability: ModelActivityRegistry | None = None,
) -> OpenAIVLMService | QwenNativeVideoVLMService:
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
    if settings.vlm_provider == VLMProvider.QWEN:
        if clients.qwen is None and not settings.dashscope_api_key.strip():
            raise ValueError("DASHSCOPE_API_KEY is required for the configured Qwen VLM provider")
        return QwenNativeVideoVLMService(
            model=settings.qwen_vlm_model_name,
            client=clients.qwen,
            api_key=settings.dashscope_api_key or None,
            base_url=settings.qwen_base_url,
            artifact_dir=settings.artifact_dir,
            artifact_url_base=settings.qwen_artifact_url_base,
            base64_max_video_bytes=settings.qwen_base64_max_video_bytes,
            timeout_s=settings.vlm_timeout_s,
            temperature=settings.vlm_temperature,
            video_fps=settings.qwen_video_fps,
            enable_thinking=settings.qwen_enable_thinking,
            thinking_budget=settings.qwen_thinking_budget,
            max_structured_output_retries=settings.vlm_structured_output_retries,
            max_network_retries=settings.provider_network_retries,
            observability=observability,
        )
    raise ValueError(f"unsupported VLM provider: {settings.vlm_provider.value}")


def _openai_key(settings: Settings, client: Any | None) -> str | None:
    if client is None and not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY is required for the configured workflow")
    return settings.openai_api_key or None


async def _prune_expired_artifacts(
    root: Path,
    *,
    retention_hours: float,
    retained_incident_ids: set[str],
) -> None:
    if not root.is_dir():
        return
    cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
    for path in root.iterdir():
        if path.name in retained_incident_ids:
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified_at >= cutoff:
            continue
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
