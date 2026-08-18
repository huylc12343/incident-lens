"""Production Qwen native-video VLM adapter."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote, urlparse

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
    IncidentWindow,
    NativeVideoAnalysisRequest,
    ReanalysisRequest,
    RemoteMediaHandle,
    VideoAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VLMCapabilities,
    VLMInputMode,
    VLMProvider,
)
from src.services.langsmith_tracing import LangSmithTracing
from src.services.model_observability import ModelActivityRegistry, ModelRequestBudgetError

logger = logging.getLogger(__name__)
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class VLMServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class QwenStructuredOutputValidationError(ValueError):
    def __init__(self, details: list[dict[str, str]], message: str = "Qwen structured output is invalid") -> None:
        super().__init__(message)
        self.details = details


class QwenNativeVideoVLMService:
    """DashScope adapter for Qwen3-VL-Flash native video."""

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
        max_structured_output_retries: int = 0,
        max_network_retries: int = 0,
        observability: ModelActivityRegistry | None = None,
        tracing: LangSmithTracing | None = None,
    ) -> None:
        if not model.strip() or not base_url.strip():
            raise ValueError("model and base_url must not be blank")
        if timeout_s <= 0 or not 0 < video_fps <= 10 or min(thinking_budget, base64_max_video_bytes) <= 0:
            raise ValueError("timeout, video_fps, and thinking_budget must be positive")
        if temperature != 0:
            raise ValueError("Qwen3-VL-Flash temperature must be 0")
        if min(max_structured_output_retries, max_network_retries) < 0:
            raise ValueError("structured output and network retries must be non-negative")
        provider_client = client if client is not None else AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = (
            tracing.wrap_openai_client(
                provider_client,
                name="Qwen VLM",
                provider="qwen",
                operation="vlm",
            )
            if tracing is not None
            else provider_client
        )
        self._model = model
        self._artifact_dir = Path(artifact_dir).resolve()
        self._artifact_url_base = artifact_url_base.rstrip("/")
        self._base64_max_video_bytes = base64_max_video_bytes
        self._timeout_s = timeout_s
        self._temperature = 0.0
        self._video_fps = video_fps
        self._enable_thinking = enable_thinking
        self._thinking_budget = thinking_budget
        self._max_structured_output_retries = max_structured_output_retries
        self._max_network_retries = max_network_retries
        self._observability = observability
        self._capabilities = VLMCapabilities(
            provider=VLMProvider.QWEN,
            input_mode=VLMInputMode.NATIVE_VIDEO,
            native_video_fps=video_fps,
        )

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
            system_prompt=request.prompt.text,
            user_prompt=_prompt_context_text(request.prompt.context),
            output_model=VideoMemory,
            model_defaults={"analysis_mode": AnalysisMode.NATIVE_VIDEO.value},
            timestamp_bounds=(0.0, request.metadata.duration_s),
        )
        return memory

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        if not request.normalized_video_uri:
            raise VLMServiceError("QWEN_REANALYSIS_VIDEO_REQUIRED", "Qwen re-analysis requires normalized_video_uri")
        timestamp_bounds = (
            (request.input_video_start_s, request.input_video_end_s)
            if request.input_video_start_s is not None and request.input_video_end_s is not None
            else (
                (0.0, request.source_duration_s)
                if request.source_duration_s is not None
                else (request.incident_window.t_start, request.incident_window.t_end)
            )
        )
        patch = await self._generate(
            incident_id=request.incident_id,
            operation="claim_reanalysis",
            description="Phân tích lại các claim được chọn bằng Qwen3-VL-Flash.",
            video_uri=request.normalized_video_uri,
            system_prompt=request.prompt.text,
            user_prompt=_prompt_context_text(request.prompt.context),
            output_model=VideoMemoryPatch,
            model_defaults={
                "target_claim_ids": request.target_claim_ids,
                "base_revision": request.current_memory.revision,
            },
            timestamp_bounds=timestamp_bounds,
            input_video_start_s=request.input_video_start_s,
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
        system_prompt: str,
        user_prompt: str,
        output_model: type[StructuredModel],
        model_defaults: dict[str, Any] | None = None,
        timestamp_bounds: tuple[float, float] | None = None,
        input_video_start_s: float | None = None,
    ) -> StructuredModel:
        activity_id = None
        response = None
        try:
            schema = output_model.model_json_schema()
            if output_model in {VideoMemory, VideoMemoryPatch}:
                definitions = schema.get("$defs", {})
                definitions.get("Claim", {}).get("properties", {}).pop("evidence", None)
                definitions.get("TimelineEvent", {}).get("properties", {}).pop("evidence_ids", None)
                definitions.pop("EvidenceReference", None)
                properties = schema.get("properties", {})
                for field_name in (
                    "revision",
                    "analysis_mode",
                    "sampling_metadata",
                    "remote_media_handles",
                ):
                    properties.pop(field_name, None)
                if "required" in schema:
                    schema["required"] = [field_name for field_name in schema["required"] if field_name in properties]
                definitions.pop("SamplingMetadata", None)
                definitions.pop("RemoteMediaHandle", None)
            output_schema = json.dumps(
                schema,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            structured_system_prompt = (
                f"{system_prompt}\n"
                "Trả về đúng một JSON object, không kèm Markdown. "
                "JSON phải tuân thủ chính xác JSON Schema sau; không thêm trường ngoài schema:\n"
                f"<json_schema>{output_schema}</json_schema>"
            )
            if timestamp_bounds is not None:
                if input_video_start_s is not None:
                    structured_system_prompt += (
                        "\nQUY TẮC TIMESTAMP BẮT BUỘC:\n"
                        "- Input là một clip con: mốc 0s của clip này tương ứng với "
                        f"{input_video_start_s:g}s của video gốc.\n"
                        f"- Clip phủ vùng {timestamp_bounds[0]:g}s đến {timestamp_bounds[1]:g}s của video gốc. "
                        "Mọi timestamp trả về phải là timestamp toàn cục của video gốc, không phải timestamp cục bộ của clip.\n"
                        f"- Không được trả timestamp ngoài [{timestamp_bounds[0]:g}, {timestamp_bounds[1]:g}]."
                    )
                else:
                    structured_system_prompt += (
                        "\nQUY TẮC TIMESTAMP BẮT BUỘC:\n"
                        f"- Video bắt đầu tại {timestamp_bounds[0]:g}s và kết thúc tại "
                        f"{timestamp_bounds[1]:g}s; không được trả timestamp ngoài khoảng này.\n"
                        "- Phải có t_start <= t0 <= t_end.\n"
                        "- representative_timestamp_s, mọi timeline.timestamp_s và claim.timestamp_s "
                        "phải nằm trong khoảng thời gian video đã nêu.\n"
                        "- Timestamp là số giây tính từ đầu video, không phải số frame hay chuỗi thời gian."
                    )
            validation_feedback = ""
            for attempt in range(self._max_structured_output_retries + 1):
                attempt_user_prompt = user_prompt
                if validation_feedback:
                    attempt_user_prompt += (
                        "\nJSON ở lần trước không hợp lệ. Hãy sửa đúng các lỗi validation sau và trả lại toàn bộ "
                        f"JSON object:\n<validation_errors>{validation_feedback}</validation_errors>"
                    )
                request_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "messages": [
                        {
                            "role": "system",
                            "content": structured_system_prompt,
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "video_url",
                                    "video_url": {"url": self._public_video_url(video_uri)},
                                    "fps": self._video_fps,
                                },
                                {"type": "text", "text": attempt_user_prompt},
                            ],
                        }
                    ],
                    "temperature": 0.0,
                    "timeout": self._timeout_s,
                    "response_format": {"type": "json_object"},
                }
                if self._enable_thinking:
                    request_kwargs["extra_body"] = {
                        "enable_thinking": True,
                        "thinking_budget": self._thinking_budget,
                        "result_format": "message",
                    }
                for network_attempt in range(self._max_network_retries + 1):
                    if self._observability is not None:
                        activity_id = self._observability.start(
                            incident_id=incident_id,
                            step="vlm",
                            operation=operation,
                            description=description,
                            provider="qwen",
                            model=self._model,
                            metadata={
                                "input_mode": "native_video",
                                "video_fps": self._video_fps,
                                "structured_output_attempt": attempt + 1,
                                "network_attempt": network_attempt + 1,
                                **(
                                    {"source_timestamp_window": list(timestamp_bounds)}
                                    if input_video_start_s is not None and timestamp_bounds is not None
                                    else {}
                                ),
                            },
                        )
                    try:
                        response = await self._client.chat.completions.create(**request_kwargs)
                        break
                    except (APITimeoutError, APIConnectionError, RateLimitError):
                        if activity_id is not None:
                            self._observability.fail(activity_id, "QWEN_VIDEO_ANALYSIS_RETRYABLE", response)
                            activity_id = None
                        if network_attempt >= self._max_network_retries:
                            raise
                try:
                    content = response.choices[0].message.content
                    payload = _parse_json_content(content)
                    if not isinstance(payload, dict):
                        raise TypeError("Qwen structured output must be a JSON object")
                    payload = _prepare_qwen_payload(payload, output_model, model_defaults)
                    result = output_model.model_validate(payload)
                    if timestamp_bounds is not None:
                        result = _stabilize_qwen_timestamps(
                            result,
                            *timestamp_bounds,
                            rounding_tolerance_s=1.0 / self._video_fps,
                        )
                        _validate_qwen_timestamp_bounds(result, *timestamp_bounds)
                    if isinstance(result, VideoMemory):
                        try:
                            _validate_qwen_incident_conclusion(result)
                        except QwenStructuredOutputValidationError as exc:
                            if self._max_structured_output_retries > 0:
                                raise
                            logger.warning(
                                "Qwen incident conclusion warning accepted because structured-output retries "
                                "are disabled: %s",
                                exc.details,
                            )
                    if activity_id is not None:
                        self._observability.complete(activity_id, response)
                        activity_id = None
                    break
                except (ValidationError, ValueError, TypeError, json.JSONDecodeError, IndexError, AttributeError) as exc:
                    validation_details = _structured_output_error_details(exc)
                    logger.warning(
                        "Qwen structured output is invalid (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_structured_output_retries + 1,
                        validation_details,
                    )
                    if attempt >= self._max_structured_output_retries:
                        raise
                    if activity_id is not None:
                        self._observability.fail(activity_id, "VLM_STRUCTURED_OUTPUT_INVALID", response)
                        activity_id = None
                    validation_feedback = json.dumps(validation_details, ensure_ascii=False, separators=(",", ":"))
            return result
        except VLMServiceError:
            raise
        except ModelRequestBudgetError:
            raise
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError, IndexError, AttributeError) as exc:
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
        except PermissionDeniedError as exc:
            error_code = (
                "QWEN_QUOTA_EXHAUSTED"
                if _is_dashscope_free_tier_exhausted(exc)
                else "QWEN_PERMISSION_DENIED"
            )
            if activity_id is not None:
                self._observability.fail(activity_id, error_code, response)
            message = (
                "DashScope free quota đã hết. Hãy bổ sung thông tin thanh toán hoặc tắt chế độ "
                "'use free tier only' trong DashScope console."
                if error_code == "QWEN_QUOTA_EXHAUSTED"
                else "DashScope API key không có quyền dùng model Qwen đã cấu hình."
            )
            raise VLMServiceError(error_code, message) from exc
        except (BadRequestError, NotFoundError) as exc:
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


def _parse_json_content(content: str | None) -> object:
    if not content:
        raise ValueError("Qwen returned empty content")
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(normalized)


def _prompt_context_text(context: dict[str, Any]) -> str:
    serialized = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"<context>{serialized}</context>"


def _is_dashscope_free_tier_exhausted(exc: PermissionDeniedError) -> bool:
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    provider_code = error.get("code", "") if isinstance(error, dict) else ""
    return provider_code == "AllocationQuota.FreeTierOnly" or "free quota has been exhausted" in str(exc).lower()


def _structured_output_error_details(exc: Exception) -> object:
    if isinstance(exc, QwenStructuredOutputValidationError):
        return exc.details
    if isinstance(exc, ValidationError):
        return [
            {"location": ".".join(map(str, error["loc"])), "type": error["type"], "message": error["msg"]}
            for error in exc.errors(include_input=False, include_url=False)
        ]
    return str(exc)


def _prepare_qwen_payload(
    payload: dict[str, Any],
    output_model: type[BaseModel],
    model_defaults: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply backend-owned values before strict Pydantic validation."""
    prepared = dict(payload)
    if output_model not in {VideoMemory, VideoMemoryPatch}:
        prepared.update(model_defaults or {})
        return prepared

    prepared.pop("evidence_id_counter", None)
    for field_name in ("revision", "analysis_mode", "sampling_metadata", "remote_media_handles"):
        prepared.pop(field_name, None)
    prepared.update(model_defaults or {})
    if output_model is VideoMemory:
        timeline = prepared.get("timeline")
        if isinstance(timeline, list):
            prepared["timeline"] = [
                {key: value for key, value in event.items() if key != "evidence_ids"}
                if isinstance(event, dict)
                else event
                for event in timeline
            ]
    claims = prepared.get("claims")
    if not isinstance(claims, list):
        return prepared
    prepared["claims"] = [
        {
            **{key: value for key, value in claim.items() if key != "evidence"},
            "verification_status": "unverified",
        }
        if isinstance(claim, dict)
        else claim
        for claim in claims
    ]
    return prepared


def _validate_qwen_timestamp_bounds(result: BaseModel, minimum_s: float, maximum_s: float) -> None:
    timestamps: list[tuple[str, float | None]] = []
    if isinstance(result, VideoMemory):
        timestamps.extend(
            [
                ("incident_window.t_start", result.incident_window.t_start),
                ("incident_window.t0", result.incident_window.t0),
                ("incident_window.t_end", result.incident_window.t_end),
                ("representative_timestamp_s", result.representative_timestamp_s),
            ]
        )
        timestamps.extend((f"timeline.{index}.timestamp_s", item.timestamp_s) for index, item in enumerate(result.timeline))
        timestamps.extend((f"claims.{index}.timestamp_s", item.timestamp_s) for index, item in enumerate(result.claims))
        timestamps.extend(
            (f"claims.{claim_index}.evidence.{evidence_index}.timestamp_s", evidence.timestamp_s)
            for claim_index, claim in enumerate(result.claims)
            for evidence_index, evidence in enumerate(claim.evidence)
        )
    elif isinstance(result, VideoMemoryPatch):
        timestamps.extend((f"claims.{index}.timestamp_s", item.timestamp_s) for index, item in enumerate(result.claims))
        timestamps.extend(
            (f"claims.{claim_index}.evidence.{evidence_index}.timestamp_s", evidence.timestamp_s)
            for claim_index, claim in enumerate(result.claims)
            for evidence_index, evidence in enumerate(claim.evidence)
        )
    errors = [
        {
            "location": location,
            "type": "timestamp_out_of_range",
            "message": f"Timestamp must be between {minimum_s:g} and {maximum_s:g} seconds",
        }
        for location, timestamp_s in timestamps
        if timestamp_s is not None and not minimum_s <= timestamp_s <= maximum_s
    ]
    if isinstance(result, VideoMemory) and result.representative_timestamp_s is not None:
        if not result.incident_window.t_start <= result.representative_timestamp_s <= result.incident_window.t_end:
            errors.append(
                {
                    "location": "representative_timestamp_s",
                    "type": "timestamp_outside_incident_window",
                    "message": "Representative timestamp must be inside incident_window",
                }
            )
    if errors:
        raise QwenStructuredOutputValidationError(errors, "Qwen output violates video timestamp bounds")


def _stabilize_qwen_timestamps(
    result: StructuredModel,
    minimum_s: float,
    maximum_s: float,
    *,
    rounding_tolerance_s: float,
) -> StructuredModel:
    """Repair sampling-rounding drift without accepting materially out-of-range timestamps."""

    def normalize(timestamp_s: float | None) -> float | None:
        if timestamp_s is None:
            return None
        if minimum_s - rounding_tolerance_s <= timestamp_s < minimum_s:
            return minimum_s
        if maximum_s < timestamp_s <= maximum_s + rounding_tolerance_s:
            return maximum_s
        return timestamp_s

    if isinstance(result, VideoMemoryPatch):
        claims = [
            claim.model_copy(
                update={
                    "timestamp_s": normalize(claim.timestamp_s),
                    "evidence": [
                        evidence.model_copy(update={"timestamp_s": normalize(evidence.timestamp_s)})
                        for evidence in claim.evidence
                    ],
                }
            )
            for claim in result.claims
        ]
        return result.model_copy(update={"claims": claims})

    if not isinstance(result, VideoMemory):
        return result

    timeline = [
        item.model_copy(update={"timestamp_s": normalize(item.timestamp_s)}) for item in result.timeline
    ]
    claims = [
        claim.model_copy(
            update={
                "timestamp_s": normalize(claim.timestamp_s),
                "evidence": [
                    evidence.model_copy(update={"timestamp_s": normalize(evidence.timestamp_s)})
                    for evidence in claim.evidence
                ],
            }
        )
        for claim in result.claims
    ]
    representative_timestamp_s = normalize(result.representative_timestamp_s)
    window = result.incident_window
    normalized_window = IncidentWindow(
        t_start=normalize(window.t_start),
        t0=normalize(window.t0),
        t_end=normalize(window.t_end),
    )
    return result.model_copy(
        update={
            "incident_window": normalized_window,
            "representative_timestamp_s": representative_timestamp_s,
            "timeline": timeline,
            "claims": claims,
        }
    )


def _validate_qwen_incident_conclusion(memory: VideoMemory) -> None:
    hedging_pattern = re.compile(
        r"(?:khả năng(?: xảy ra)? va chạm|có thể(?: đã)? va chạm|nghi(?: ngờ)? va chạm|"
        r"không (?:có|thấy) dấu hiệu va chạm rõ(?: ràng)?|possible collision|may have collided|"
        r"no clear (?:signs? of )?collision)",
        re.IGNORECASE,
    )
    candidates = [("video_summary", memory.video_summary or "")]
    candidates.extend((f"claims.{index}.text", claim.text) for index, claim in enumerate(memory.claims))
    errors = [
        {
            "location": location,
            "type": "ambiguous_incident_conclusion",
            "message": (
                "Kết luận tai nạn phải dứt khoát là có va chạm hoặc không có va chạm theo "
                "quy tắc camera trước xe ego; không dùng ngôn ngữ phỏng đoán."
            ),
        }
        for location, text in candidates
        if hedging_pattern.search(text)
    ]
    combined_text = " ".join(text for _, text in candidates)
    describes_obstacle = re.search(
        r"(?:bụi cây|hàng cây|hàng rào|vật cản|tree|hedge|fence|obstacle)",
        combined_text,
        re.IGNORECASE,
    )
    describes_abrupt_end = re.search(
        r"(?:dừng đột ngột|che khuất|che phủ|mặt trước bị che|abrupt(?:ly)? stop|obscur)",
        combined_text,
        re.IGNORECASE,
    )
    denies_incident = re.search(
        r"(?:không (?:có|xảy ra|phát hiện)[^.]{0,80}(?:va chạm|tai nạn)|no (?:collision|accident))",
        combined_text,
        re.IGNORECASE,
    )
    if describes_obstacle and describes_abrupt_end and denies_incident:
        errors.append(
            {
                "location": "video_summary",
                "type": "incident_conclusion_conflicts_with_observed_sequence",
                "message": (
                    "Output đã mô tả xe ego tiến sát vật cản, bị che khuất và dừng đột ngột; "
                    "theo quy tắc camera trước, phải kết luận xe ego va chạm vật cản."
                ),
            }
        )
    if errors:
        raise QwenStructuredOutputValidationError(errors, "Qwen incident conclusion is ambiguous")


def _validate_patch_targets(patch: VideoMemoryPatch, requested_ids: list[str]) -> None:
    if set(patch.target_claim_ids) != set(requested_ids):
        raise VLMServiceError(
            "VLM_PATCH_TARGET_MISMATCH",
            "structured patch target IDs do not match the re-analysis request",
        )
