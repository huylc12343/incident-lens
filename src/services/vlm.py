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
from urllib.parse import quote, urlparse

from google import genai
from google.genai import types
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
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
from src.services.model_observability import ModelActivityRegistry

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
        observability: ModelActivityRegistry | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if timeout_s <= 0 or max_images_per_request <= 0:
            raise ValueError("timeout and image limit must be positive")
        self._client = client if client is not None else AsyncOpenAI(api_key=api_key)
        self._model = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._observability = observability
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
        return await self._parse_response(
            content,
            VideoMemory,
            "OPENAI_VIDEO_ANALYSIS_FAILED",
            incident_id=request.incident_id,
            operation="video_analysis",
            description="Phân tích toàn bộ video và tạo VideoMemory có cấu trúc.",
            metadata={"image_count": len(request.manifest.frames), "input_mode": "timestamped_frames"},
        )

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        if request.frame_manifest is None:
            raise VLMServiceError(
                "OPENAI_REANALYSIS_FRAMES_REQUIRED",
                "OpenAI re-analysis requires a timestamped frame manifest",
            )
        content = await self._build_frame_content(request.prompt.text, request.frame_manifest.frames)
        patch = await self._parse_response(
            content,
            VideoMemoryPatch,
            "OPENAI_REANALYSIS_FAILED",
            incident_id=request.incident_id,
            operation="claim_reanalysis",
            description="Phân tích lại các claim được chọn trong cửa sổ sự cố.",
            metadata={
                "image_count": len(request.frame_manifest.frames),
                "target_claim_ids": request.target_claim_ids,
            },
        )
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
                    "detail": "low",
                }
            )
        return content

    async def _parse_response(
        self,
        content: list[dict[str, Any]],
        output_model: type[StructuredModel],
        error_code: str,
        *,
        incident_id: str,
        operation: str,
        description: str,
        metadata: dict[str, Any],
    ) -> StructuredModel:
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=incident_id,
                step="vlm",
                operation=operation,
                description=description,
                provider="openai",
                model=self._model,
                metadata=metadata,
            )
        try:
            request_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": [{"role": "user", "content": content}],
                "text_format": output_model,
                "timeout": self._timeout_s,
            }
            if not self._model.startswith("gpt-5"):
                request_kwargs["temperature"] = self._temperature
            response = await self._client.responses.parse(
                **request_kwargs,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                output_text = getattr(response, "output_text", "")
                parsed = json.loads(output_text)
            result = output_model.model_validate(parsed)
            if activity_id is not None:
                self._observability.complete(activity_id, response)
            return result
        except VLMServiceError:
            raise
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "VLM_STRUCTURED_OUTPUT_INVALID", response)
            raise VLMServiceError("VLM_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except AuthenticationError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_AUTHENTICATION_FAILED", response)
            raise VLMServiceError(
                "OPENAI_AUTHENTICATION_FAILED",
                "OpenAI authentication failed; check OPENAI_API_KEY",
            ) from exc
        except PermissionDeniedError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_PERMISSION_DENIED", response)
            raise VLMServiceError(
                "OPENAI_PERMISSION_DENIED",
                "OpenAI denied access to the configured video analysis model",
            ) from exc
        except RateLimitError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_RATE_LIMITED", response)
            raise VLMServiceError(
                "OPENAI_RATE_LIMITED",
                "OpenAI rate limit or quota was exceeded",
                retryable=True,
            ) from exc
        except APITimeoutError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_VIDEO_ANALYSIS_TIMEOUT", response)
            raise VLMServiceError(
                "OPENAI_VIDEO_ANALYSIS_TIMEOUT",
                "OpenAI video analysis timed out",
                retryable=True,
            ) from exc
        except APIConnectionError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_CONNECTION_FAILED", response)
            raise VLMServiceError(
                "OPENAI_CONNECTION_FAILED",
                "Could not connect to OpenAI",
                retryable=True,
            ) from exc
        except (BadRequestError, NotFoundError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_VIDEO_ANALYSIS_REQUEST_INVALID", response)
            raise VLMServiceError(
                "OPENAI_VIDEO_ANALYSIS_REQUEST_INVALID",
                "OpenAI rejected the configured video analysis model or structured request",
            ) from exc
        except Exception as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, error_code, response)
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
        observability: ModelActivityRegistry | None = None,
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
        self._observability = observability
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
                incident_id=request.incident_id,
                operation="video_analysis",
                description="Phân tích toàn bộ video native và tạo VideoMemory có cấu trúc.",
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
                incident_id=request.incident_id,
                operation="claim_reanalysis",
                description="Phân tích lại các claim được chọn trong cửa sổ sự cố.",
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
        incident_id: str,
        operation: str,
        description: str,
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
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=incident_id,
                step="vlm",
                operation=operation,
                description=description,
                provider="gemini",
                model=self._model,
                metadata={
                    "input_mode": "native_video",
                    "media_resolution": self._media_resolution,
                    "video_fps": self._video_fps,
                    "video_start_s": video_start_s,
                    "video_end_s": video_end_s,
                },
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
            result = output_model.model_validate(parsed)
            if activity_id is not None:
                self._observability.complete(activity_id, response)
            return result
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "VLM_STRUCTURED_OUTPUT_INVALID", response)
            raise VLMServiceError("VLM_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except Exception as exc:
            if isinstance(exc, VLMServiceError):
                raise
            if activity_id is not None:
                self._observability.fail(activity_id, "GEMINI_GENERATION_FAILED", response)
            raise VLMServiceError("GEMINI_GENERATION_FAILED", str(exc), retryable=True) from exc


class QwenNativeVideoVLMService:
    """DashScope OpenAI-compatible adapter for Qwen3-VL-Flash native video."""

    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        artifact_dir: str = "./data/artifacts",
        artifact_url_base: str = "",
        base64_max_video_bytes: int = 7_000_000,
        timeout_s: float = 120.0,
        temperature: float = 0.0,
        video_fps: float = 2.0,
        enable_thinking: bool = False,
        thinking_budget: int = 500,
        observability: ModelActivityRegistry | None = None,
    ) -> None:
        if not model.strip() or not base_url.strip():
            raise ValueError("model and base_url must not be blank")
        if timeout_s <= 0 or not 0 < video_fps <= 10 or min(thinking_budget, base64_max_video_bytes) <= 0:
            raise ValueError("timeout, video_fps, and thinking_budget must be positive")
        self._client = client if client is not None else AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._artifact_dir = Path(artifact_dir).resolve()
        self._artifact_url_base = artifact_url_base.rstrip("/")
        self._base64_max_video_bytes = base64_max_video_bytes
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._video_fps = video_fps
        self._enable_thinking = enable_thinking
        self._thinking_budget = thinking_budget
        self._observability = observability
        self._capabilities = VLMCapabilities(provider=VLMProvider.QWEN, input_mode=VLMInputMode.NATIVE_VIDEO)

    @property
    def capabilities(self) -> VLMCapabilities:
        return self._capabilities

    async def analyze_video(self, request: VideoAnalysisRequest) -> VideoMemory:
        if not isinstance(request, NativeVideoAnalysisRequest):
            raise VLMServiceError("QWEN_UNSUPPORTED_INPUT_MODE", "Qwen native VLM accepts normalized video only")
        memory = await self._generate(
            incident_id=request.incident_id,
            operation="video_analysis",
            description="Phân tích native video bằng Qwen3-VL-Flash và tạo VideoMemory có cấu trúc.",
            video_uri=request.normalized_video_uri,
            prompt=request.prompt.text,
            output_model=VideoMemory,
            model_defaults={"analysis_mode": AnalysisMode.NATIVE_VIDEO.value},
        )
        return memory

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        if not request.normalized_video_uri:
            raise VLMServiceError("QWEN_REANALYSIS_VIDEO_REQUIRED", "Qwen re-analysis requires normalized_video_uri")
        patch = await self._generate(
            incident_id=request.incident_id,
            operation="claim_reanalysis",
            description="Phân tích lại các claim được chọn bằng Qwen3-VL-Flash.",
            video_uri=request.normalized_video_uri,
            prompt=request.prompt.text,
            output_model=VideoMemoryPatch,
            model_defaults={
                "target_claim_ids": request.target_claim_ids,
                "base_revision": request.current_memory.revision,
            },
        )
        _validate_patch_targets(patch, request.target_claim_ids)
        return patch

    async def release_remote_resources(self, handles: list[RemoteMediaHandle]) -> None:
        return None

    async def _generate(
        self,
        *,
        incident_id: str,
        operation: str,
        description: str,
        video_uri: str,
        prompt: str,
        output_model: type[StructuredModel],
        model_defaults: dict[str, Any] | None = None,
    ) -> StructuredModel:
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=incident_id,
                step="vlm",
                operation=operation,
                description=description,
                provider="qwen",
                model=self._model,
                metadata={"input_mode": "native_video", "video_fps": self._video_fps},
            )
        try:
            output_schema = json.dumps(
                output_model.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            structured_prompt = (
                f"{prompt}\n"
                "Trả về đúng một JSON object, không kèm Markdown. "
                "JSON phải tuân thủ chính xác JSON Schema sau; không thêm trường ngoài schema:\n"
                f"<json_schema>{output_schema}</json_schema>"
            )
            request_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": self._public_video_url(video_uri)},
                                "fps": self._video_fps,
                            },
                            {"type": "text", "text": structured_prompt},
                        ],
                    }
                ],
                "temperature": self._temperature,
                "timeout": self._timeout_s,
                "response_format": {"type": "json_object"},
            }
            if self._enable_thinking:
                request_kwargs["extra_body"] = {
                    "enable_thinking": True,
                    "thinking_budget": self._thinking_budget,
                    "result_format": "message",
                }
            response = await self._client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content
            payload = _parse_json_content(content)
            if not isinstance(payload, dict):
                raise TypeError("Qwen structured output must be a JSON object")
            payload = {**payload, **(model_defaults or {})}
            result = output_model.model_validate(payload)
            if activity_id is not None:
                self._observability.complete(activity_id, response)
            return result
        except VLMServiceError:
            raise
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError, IndexError, AttributeError) as exc:
            if isinstance(exc, ValidationError):
                validation_details: object = [
                    {"location": ".".join(map(str, error["loc"])), "type": error["type"], "message": error["msg"]}
                    for error in exc.errors(include_input=False, include_url=False)
                ]
            else:
                validation_details = str(exc)
            logger.warning("Qwen structured output is invalid: %s", validation_details)
            if activity_id is not None:
                self._observability.fail(activity_id, "VLM_STRUCTURED_OUTPUT_INVALID", response)
            raise VLMServiceError("VLM_STRUCTURED_OUTPUT_INVALID", str(exc)) from exc
        except AuthenticationError as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "DASHSCOPE_AUTHENTICATION_FAILED", response)
            raise VLMServiceError("DASHSCOPE_AUTHENTICATION_FAILED", "DashScope authentication failed") from exc
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "QWEN_VIDEO_ANALYSIS_RETRYABLE", response)
            raise VLMServiceError("QWEN_VIDEO_ANALYSIS_RETRYABLE", str(exc), retryable=True) from exc
        except (BadRequestError, NotFoundError, PermissionDeniedError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "QWEN_VIDEO_ANALYSIS_REQUEST_INVALID", response)
            raise VLMServiceError("QWEN_VIDEO_ANALYSIS_REQUEST_INVALID", str(exc)) from exc
        except Exception as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "QWEN_VIDEO_ANALYSIS_FAILED", response)
            raise VLMServiceError("QWEN_VIDEO_ANALYSIS_FAILED", str(exc), retryable=True) from exc

    def _public_video_url(self, video_uri: str) -> str:
        if urlparse(video_uri).scheme in {"http", "https"}:
            return video_uri
        local_path = Path(video_uri).resolve()
        if not local_path.is_file():
            raise VLMServiceError("QWEN_LOCAL_VIDEO_MISSING", f"video does not exist: {video_uri}")
        try:
            relative_path = local_path.relative_to(self._artifact_dir)
        except ValueError as exc:
            raise VLMServiceError(
                "QWEN_VIDEO_OUTSIDE_ARTIFACT_DIR",
                "normalized video must be inside ARTIFACT_DIR or be a public HTTPS URL",
            ) from exc
        if self._artifact_url_base:
            return f"{self._artifact_url_base}/{quote(relative_path.as_posix())}"
        if local_path.stat().st_size > self._base64_max_video_bytes:
            raise VLMServiceError(
                "QWEN_PUBLIC_VIDEO_URL_REQUIRED",
                "normalized video is too large for Base64; configure QWEN_ARTIFACT_URL_BASE",
            )
        encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
        return f"data:video/mp4;base64,{encoded}"


async def _image_data_url(uri: str, mime_type: str) -> str:
    if uri.startswith("data:"):
        return uri
    path = Path(uri).resolve()
    if not path.is_file():
        raise VLMServiceError("OPENAI_FRAME_MISSING", f"frame does not exist: {uri}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_json_content(content: str | None) -> object:
    if not content:
        raise ValueError("Qwen returned empty content")
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(normalized)


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
