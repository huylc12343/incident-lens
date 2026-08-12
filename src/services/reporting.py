"""OpenAI structured-output adapter for incident report narrative fields."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from src.models.incidents import (
    PromptEnvelope,
    ReanalysisRequest,
    ReportModelOutput,
    ReportRequest,
    VideoMemoryPatch,
)
from src.prompts.reporting import build_report_prompt
from src.services.model_observability import ModelActivityRegistry


class ReportServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OpenAIReportService:
    def __init__(
        self,
        *,
        model: str,
        client: Any | None = None,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        prompt_version: str = "v1",
        observability: ModelActivityRegistry | None = None,
    ) -> None:
        if not model.strip() or not prompt_version.strip():
            raise ValueError("model and prompt_version must not be blank")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        self._client = client if client is not None else AsyncOpenAI(api_key=api_key)
        self._model = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._prompt_version = prompt_version
        self._observability = observability

    async def build_narrative(self, request: ReportRequest) -> ReportModelOutput:
        prompt = build_report_prompt(
            incident_id=request.incident_id,
            video_memory=request.video_memory,
            verification=request.verification,
            log_evidence_summary=request.log_evidence_summary,
            version=self._prompt_version,
        )
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=request.incident_id,
                step="report",
                operation="report_generation",
                description="Tổng hợp báo cáo sự cố bằng tiếng Việt từ VideoMemory và kết quả verification.",
                provider="openai",
                model=self._model,
                metadata={"claim_count": len(request.video_memory.claims)},
            )
        try:
            request_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": [
                    {"role": "system", "content": prompt.text},
                    {"role": "user", "content": _prompt_context_text(prompt)},
                ],
                "text_format": ReportModelOutput,
                "timeout": self._timeout_s,
            }
            if not self._model.startswith("gpt-5"):
                request_kwargs["temperature"] = self._temperature
            response = await self._client.responses.parse(**request_kwargs)
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = json.loads(getattr(response, "output_text", ""))
            narrative = ReportModelOutput.model_validate(parsed)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "REPORT_STRUCTURED_OUTPUT_INVALID", response)
            raise ReportServiceError(
                "REPORT_STRUCTURED_OUTPUT_INVALID",
                "report model returned invalid structured output",
            ) from exc
        except Exception as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_REPORT_FAILED", response)
            raise ReportServiceError(
                "OPENAI_REPORT_FAILED",
                "OpenAI report generation failed",
                retryable=True,
            ) from exc
        if activity_id is not None:
            self._observability.complete(activity_id, response)
        return narrative

    async def reanalyze_claims(self, request: ReanalysisRequest) -> VideoMemoryPatch:
        """Reanalyze reviewer-selected claims using text context only."""
        activity_id = None
        response = None
        if self._observability is not None:
            activity_id = self._observability.start(
                incident_id=request.incident_id,
                step="reanalysis",
                operation="memory_only_claim_reanalysis",
                description="Hiệu chỉnh claim từ VideoMemory và feedback, không gửi video/frame.",
                provider="openai",
                model=self._model,
                metadata={
                    "input_mode": "memory_only",
                    "target_claim_ids": request.target_claim_ids,
                },
            )
        try:
            request_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": [
                    {"role": "system", "content": request.prompt.text},
                    {"role": "user", "content": _prompt_context_text(request.prompt)},
                ],
                "text_format": VideoMemoryPatch,
                "timeout": self._timeout_s,
            }
            if not self._model.startswith("gpt-5"):
                request_kwargs["temperature"] = self._temperature
            response = await self._client.responses.parse(**request_kwargs)
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = json.loads(getattr(response, "output_text", ""))
            patch = VideoMemoryPatch.model_validate(parsed)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "REANALYSIS_STRUCTURED_OUTPUT_INVALID", response)
            raise ReportServiceError(
                "REANALYSIS_STRUCTURED_OUTPUT_INVALID",
                "reanalysis model returned invalid VideoMemoryPatch",
            ) from exc
        except Exception as exc:
            if activity_id is not None:
                self._observability.fail(activity_id, "OPENAI_REANALYSIS_FAILED", response)
            raise ReportServiceError(
                "OPENAI_REANALYSIS_FAILED",
                "OpenAI memory-only reanalysis failed",
                retryable=True,
            ) from exc
        if activity_id is not None:
            self._observability.complete(activity_id, response)
        return patch


def _prompt_context_text(prompt: PromptEnvelope) -> str:
    serialized = json.dumps(prompt.context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"<context>{serialized}</context>"
