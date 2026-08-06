"""OpenAI structured-output adapter for incident report narrative fields."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from src.models.incidents import ReportNarrative, ReportRequest
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

    async def build_narrative(self, request: ReportRequest) -> ReportNarrative:
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
            response = await self._client.responses.parse(
                model=self._model,
                input=[{"role": "user", "content": prompt.text}],
                text_format=ReportNarrative,
                temperature=self._temperature,
                timeout=self._timeout_s,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                parsed = json.loads(getattr(response, "output_text", ""))
            narrative = ReportNarrative.model_validate(parsed)
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
        allowed_evidence = {item.evidence_id for item in request.video_memory.evidence}
        if request.log_evidence_summary is not None:
            allowed_evidence.update(request.log_evidence_summary.evidence_ids)
        if not set(narrative.evidence_ids).issubset(allowed_evidence):
            if activity_id is not None:
                self._observability.fail(activity_id, "REPORT_EVIDENCE_INVALID", response)
            raise ReportServiceError(
                "REPORT_EVIDENCE_INVALID",
                "report references evidence not supplied by the workflow",
            )
        if activity_id is not None:
            self._observability.complete(activity_id, response)
        return narrative
