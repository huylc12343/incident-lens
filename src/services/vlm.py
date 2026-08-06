"""Production OpenAI-frames and Gemini-native-video VLM adapters."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from src.models.incidents import (
    AnalysisMode,
    NativeVideoAnalysisRequest,
    ReanalysisRequest,
    RemoteMediaHandle,
    TimestampedFramesAnalysisRequest,
    VideoAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)

logger = logging.getLogger(__name__)
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class VLMServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OpenAIVLMService:
    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        temperature: float = 0.0,
        max_images_per_request: int = 120,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if timeout_s <= 0 or max_images_per_request <= 0:
            raise ValueError("timeout and image limit must be positive")
        self._client = client if client is not None else AsyncOpenAI(api_key=api_key)
        self._model = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._capabilities = VLMCapabilities(
            provider=VLMProvider.OPENAI,
            input_mode=VLMInputMode.TIMESTAMPED_FRAMES,
            max_images_per_request=max_images_per_request,
        )

    @property
    def capabilities(self) -> VLMCapabilities:
        return self._capabilities

    async def analyze_video(self, request: VideoAnalysisRequest) -> VideoMemory:
        if not isinstance(request, TimestampedFramesAnalysisRequest):
            raise VLMServiceError("OPENAI_UNSUPPORTED_INPUT_MODE", "OpenAI VLM accepts timestamped frames only")
        content = await self._build_frame_content(request.prompt.text, request.manifest.frames)
        return await self._parse_response(content, VideoMemory, "OPENAI_VIDEO_ANALYSIS_FAILED")

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        if request.frame_manifest is None:
            raise VLMServiceError(
                "OPENAI_REANALYSIS_FRAMES_REQUIRED",
                "OpenAI re-analysis requires a timestamped frame manifest",
            )
        content = await self._build_frame_content(request.prompt.text, request.frame_manifest.frames)
        patch = await self._parse_response(content, VideoMemoryPatch, "OPENAI_REANALYSIS_FAILED")
        _validate_patch_targets(patch, request.target_claim_ids)
        return patch

    async def release_remote_resources(self, handles: list[RemoteMediaHandle]) -> None:
        return None

    async def _build_frame_content(self, prompt: str, frames: list[Any]) -> list[dict[str, Any]]:
        image_limit = self._capabilities.max_images_per_request or 0
        if len(frames) > image_limit:
            raise VLMServiceError(
                "OPENAI_FRAME_LIMIT_EXCEEDED",
                f"received {len(frames)} frames; maximum is {image_limit}",
            )
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for frame in frames:
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        f"frame_id={frame.frame_id}; sequence_index={frame.sequence_index}; "
                        f"timestamp_s={frame.timestamp_s}; delta_from_previous_s={frame.delta_from_previous_s}"
                    ),
                }
            )
            content.append(
                {
                    "type": "input_image",
                    "image_url": await _image_data_url(frame.image_uri, frame.mime_type),
                    "detail": "high",
                }
            )
        return content

    async def _parse_response(
        self,
        content: list[dict[str, Any]],
        output_model: type[StructuredModel],
        error_code: str,
    ) -> StructuredModel:
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[{"role": "user", "content": content}],
                text_format=output_model,
                temperature=self._temperature,
                timeout=self._timeout_s,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                output_text = getattr(response, "output_text", "")
                parsed = json.loads(output_text)
            return output_model.model_validate(parsed)
        except VLMServiceError:
            raise
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VLMServiceError("VLM_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except Exception as exc:
            raise VLMServiceError(error_code, str(exc), retryable=True) from exc


class GeminiNativeVideoVLMService:
    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        poll_interval_s: float = 2.0,
        processing_timeout_s: float = 300.0,
        max_poll_attempts: int = 150,
        timeout_s: float = 120.0,
        temperature: float = 0.0,
        media_resolution: str = "medium",
        video_fps: float = 2.0,
        reupload_missing_file: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if min(poll_interval_s, processing_timeout_s, max_poll_attempts, timeout_s, video_fps) <= 0:
            raise ValueError("Gemini timeout, polling, and FPS settings must be positive")
        if media_resolution not in {"low", "medium", "high"}:
            raise ValueError("media_resolution must be low, medium, or high")
        self._client = client if client is not None else genai.Client(api_key=api_key)
        self._model = model
        self._poll_interval_s = poll_interval_s
        self._processing_timeout_s = processing_timeout_s
        self._max_poll_attempts = max_poll_attempts
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._media_resolution = media_resolution
        self._video_fps = video_fps
        self._reupload_missing_file = reupload_missing_file
        self._sleep = sleep
        self._monotonic = monotonic
        self._capabilities = VLMCapabilities(
            provider=VLMProvider.GEMINI,
            input_mode=VLMInputMode.NATIVE_VIDEO,
        )

    @property
    def capabilities(self) -> VLMCapabilities:
        return self._capabilities

    async def analyze_video(self, request: VideoAnalysisRequest) -> VideoMemory:
        if not isinstance(request, NativeVideoAnalysisRequest):
            raise VLMServiceError("GEMINI_UNSUPPORTED_INPUT_MODE", "Gemini native VLM accepts normalized video only")
        handle = await self._upload_and_wait(request.normalized_video_uri)
        try:
            memory = await self._generate(
                handle=handle,
                prompt=request.prompt.text,
                output_model=VideoMemory,
                video_start_s=None,
                video_end_s=None,
            )
        except Exception:
            await self.release_remote_resources([handle])
            raise
        return memory.model_copy(
            update={
                "analysis_mode": AnalysisMode.NATIVE_VIDEO,
                "remote_media_handles": [handle],
            }
        )

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        handle = await self._resolve_reanalysis_handle(request)
        try:
            patch = await self._generate(
                handle=handle,
                prompt=request.prompt.text,
                output_model=VideoMemoryPatch,
                video_start_s=request.incident_window.t_start,
                video_end_s=request.incident_window.t_end,
            )
            _validate_patch_targets(patch, request.target_claim_ids)
        except Exception:
            await self.release_remote_resources([handle])
            raise
        return patch.model_copy(update={"remote_media_handles": [handle]})

    async def release_remote_resources(self, handles: list[RemoteMediaHandle]) -> None:
        for handle in handles:
            if handle.provider != VLMProvider.GEMINI:
                continue
            try:
                await self._client.aio.files.delete(name=handle.name)
            except Exception as exc:
                logger.warning("Failed to delete Gemini remote file %s: %s", handle.name, exc)

    async def _upload_and_wait(self, local_video_uri: str) -> RemoteMediaHandle:
        local_path = Path(local_video_uri).resolve()
        if not local_path.is_file():
            raise VLMServiceError("GEMINI_LOCAL_VIDEO_MISSING", f"video does not exist: {local_video_uri}")
        try:
            remote_file = await self._client.aio.files.upload(
                file=str(local_path),
                config={"mime_type": "video/mp4"},
            )
        except Exception as exc:
            raise VLMServiceError("GEMINI_VIDEO_UPLOAD_FAILED", str(exc), retryable=True) from exc

        deadline = self._monotonic() + self._processing_timeout_s
        for attempt in range(self._max_poll_attempts):
            state = _file_state_name(remote_file)
            if state == "ACTIVE":
                return _remote_handle(remote_file, str(local_path))
            if state == "FAILED":
                await self._delete_remote_name(getattr(remote_file, "name", None))
                raise VLMServiceError("GEMINI_VIDEO_PROCESSING_FAILED", "Gemini file processing failed")
            if self._monotonic() >= deadline or attempt == self._max_poll_attempts - 1:
                await self._delete_remote_name(getattr(remote_file, "name", None))
                raise VLMServiceError("GEMINI_VIDEO_PROCESSING_TIMEOUT", "Gemini file processing timed out")
            await self._sleep(self._poll_interval_s)
            try:
                remote_file = await self._client.aio.files.get(name=remote_file.name)
            except Exception as exc:
                await self._delete_remote_name(getattr(remote_file, "name", None))
                raise VLMServiceError("GEMINI_VIDEO_POLL_FAILED", str(exc), retryable=True) from exc
        raise VLMServiceError("GEMINI_VIDEO_PROCESSING_TIMEOUT", "Gemini file processing timed out")

    async def _resolve_reanalysis_handle(self, request: ReanalysisRequest) -> RemoteMediaHandle:
        handle = next(
            (item for item in request.remote_media_handles if item.provider == VLMProvider.GEMINI),
            None,
        )
        if handle is not None:
            try:
                remote_file = await self._client.aio.files.get(name=handle.name)
                if _file_state_name(remote_file) == "ACTIVE":
                    return _remote_handle(remote_file, handle.local_artifact_uri)
            except Exception:
                pass
            if not self._reupload_missing_file:
                raise VLMServiceError("GEMINI_REMOTE_FILE_MISSING", "Gemini remote video is not active")
            return await self._upload_and_wait(handle.local_artifact_uri)
        if request.normalized_video_uri:
            return await self._upload_and_wait(request.normalized_video_uri)
        raise VLMServiceError("GEMINI_REMOTE_FILE_MISSING", "re-analysis has no reusable or local video")

    async def _delete_remote_name(self, name: str | None) -> None:
        if not name:
            return
        try:
            await self._client.aio.files.delete(name=name)
        except Exception as exc:
            logger.warning("Failed to delete Gemini remote file %s: %s", name, exc)

    async def _generate(
        self,
        *,
        handle: RemoteMediaHandle,
        prompt: str,
        output_model: type[StructuredModel],
        video_start_s: float | None,
        video_end_s: float | None,
    ) -> StructuredModel:
        video_part = types.Part.from_uri(
            file_uri=handle.uri,
            mime_type=handle.mime_type,
            media_resolution={
                "low": types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW,
                "medium": types.PartMediaResolutionLevel.MEDIA_RESOLUTION_MEDIUM,
                "high": types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH,
            }[self._media_resolution],
        )
        video_part.video_metadata = types.VideoMetadata(
            start_offset=f"{video_start_s}s" if video_start_s is not None else None,
            end_offset=f"{video_end_s}s" if video_end_s is not None else None,
            fps=self._video_fps,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[video_part, prompt],
                config=types.GenerateContentConfig(
                    temperature=self._temperature,
                    response_mime_type="application/json",
                    response_schema=output_model,
                    http_options=types.HttpOptions(timeout=int(self._timeout_s * 1000)),
                ),
            )
            parsed = getattr(response, "parsed", None)
            if parsed is None:
                parsed = json.loads(getattr(response, "text", ""))
            return output_model.model_validate(parsed)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VLMServiceError("VLM_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except Exception as exc:
            if isinstance(exc, VLMServiceError):
                raise
            raise VLMServiceError("GEMINI_GENERATION_FAILED", str(exc), retryable=True) from exc


async def _image_data_url(uri: str, mime_type: str) -> str:
    if uri.startswith("data:"):
        return uri
    path = Path(uri).resolve()
    if not path.is_file():
        raise VLMServiceError("OPENAI_FRAME_MISSING", f"frame does not exist: {uri}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _file_state_name(remote_file: Any) -> str:
    state = getattr(remote_file, "state", None)
    return str(getattr(state, "name", state) or "PROCESSING").upper()


def _remote_handle(remote_file: Any, local_artifact_uri: str) -> RemoteMediaHandle:
    name = getattr(remote_file, "name", None)
    uri = getattr(remote_file, "uri", None)
    mime_type = getattr(remote_file, "mime_type", None) or "video/mp4"
    if not name or not uri:
        raise VLMServiceError("GEMINI_FILE_HANDLE_INVALID", "Gemini returned an incomplete file handle")
    return RemoteMediaHandle(
        provider=VLMProvider.GEMINI,
        name=name,
        uri=uri,
        mime_type=mime_type,
        local_artifact_uri=local_artifact_uri,
    )


def _validate_patch_targets(patch: VideoMemoryPatch, requested_ids: list[str]) -> None:
    if set(patch.target_claim_ids) != set(requested_ids):
        raise VLMServiceError(
            "VLM_PATCH_TARGET_MISMATCH",
            "structured patch target IDs do not match the re-analysis request",
        )
