"""One-shot live Qwen trace for the incident graph.

The script permits exactly one external model request. Verification and report
provider responses are deterministic local doubles so every main graph node can
still be exercised without silently spending more than the approved API call.
All runtime artifacts and SQLite files are created below /tmp.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI

from src.config import Settings
from src.models.api import IncidentCreateRequest
from src.models.incidents import ClaimVerification, ReportNarrative, VerificationResult
from src.services.incident_runtime import ProviderClients, incident_workflow_service

INCIDENT_ID = "TRACE-LIVE-ONE-SHOT-20260811"
VIDEO_URI = "data_mock/data1/front_camera.mp4"
LOG_URI = "data_mock/data1/vehicle_state.csv"
ANALYSIS_PROMPT = (
    "Phân tích sự cố giao thông trong toàn bộ video. Xác định t_start, t0, t_end, "
    "timeline và các claim chỉ dựa trên bằng chứng quan sát được; không dùng các file ground truth."
)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items() if not str(key).startswith("__")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _context_from_prompt(prompt: str) -> dict[str, Any]:
    start = prompt.index("<context>") + len("<context>")
    end = prompt.index("</context>", start)
    return json.loads(prompt[start:end])


class LocalResponses:
    """Deterministic downstream response double; never accesses the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        prompt = kwargs["input"][0]["content"]
        context = _context_from_prompt(prompt)
        output_type = kwargs["text_format"].__name__
        self.calls.append(
            {
                "output_type": output_type,
                "model": kwargs["model"],
                "prompt": prompt,
                "timeout": kwargs.get("timeout"),
                "temperature": kwargs.get("temperature"),
            }
        )
        if output_type == "VerificationResult":
            parsed = VerificationResult(
                results=[
                    ClaimVerification(
                        claim_id=item["claim"]["claim_id"],
                        status="unverified",
                        reason="Provider verification được thay bằng response cục bộ trong one-shot trace.",
                        evidence_ids=[],
                    )
                    for item in context["verification_items"]
                ]
            )
        elif output_type == "ReportNarrative":
            memory_summary = context.get("video_summary") or context.get("global_scene") or "Không có tóm tắt."
            parsed = ReportNarrative(
                summary=memory_summary,
                timeline="Narrative report được tạo cục bộ trong one-shot trace.",
                video_observations=memory_summary,
                log_findings="Kết quả log có cấu trúc được backend cung cấp.",
                alignment="Verification provider được thay bằng response cục bộ trong one-shot trace.",
                hypothesized_causes="Chưa kết luận nguyên nhân nếu chưa có human review.",
                evidence_ids=[],
            )
        else:
            raise AssertionError(f"unexpected local output type: {output_type}")
        return SimpleNamespace(output_parsed=parsed, usage=None)


class OneShotCompletions:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.count = 0
        self.request: dict[str, Any] | None = None
        self.response: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.count += 1
        if self.count > 1:
            raise RuntimeError("one-shot guard blocked a second external Qwen request")

        content = kwargs["messages"][0]["content"]
        video_url = content[0]["video_url"]["url"]
        if video_url.startswith("data:"):
            header, encoded = video_url.split(",", 1)
            decoded = base64.b64decode(encoded)
            video_descriptor = {
                "transport": header,
                "decoded_bytes": len(decoded),
                "sha256": hashlib.sha256(decoded).hexdigest(),
            }
        else:
            video_descriptor = {"transport": "public_url", "url": video_url}
        self.request = {
            "model": kwargs["model"],
            "role": kwargs["messages"][0]["role"],
            "video": video_descriptor,
            "video_fps": content[0].get("fps"),
            "prompt": content[1]["text"],
            "prompt_chars": len(content[1]["text"]),
            "temperature": kwargs.get("temperature"),
            "timeout": kwargs.get("timeout"),
            "response_format": kwargs.get("response_format"),
            "extra_body": kwargs.get("extra_body"),
        }
        response = await self._delegate.create(**kwargs)
        raw_content = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        self.response = {
            "content": raw_content,
            "content_chars": len(raw_content or ""),
            "finish_reason": getattr(response.choices[0], "finish_reason", None),
            "usage": _jsonable(usage),
            "response_id": getattr(response, "id", None),
        }
        return response


def _state_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_json = _jsonable(before)
    after_json = _jsonable(after)
    return {key: value for key, value in after_json.items() if key not in before_json or before_json[key] != value}


async def main() -> None:
    logging.getLogger("langgraph").setLevel(logging.ERROR)
    base_settings = Settings()
    if not base_settings.dashscope_api_key.strip():
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    runtime_dir = Path(tempfile.mkdtemp(prefix="incident-one-shot-", dir="/tmp"))
    settings = Settings(
        vlm_provider="qwen",
        vlm_input_mode="native_video",
        dashscope_api_key=base_settings.dashscope_api_key,
        qwen_vlm_model_name=base_settings.qwen_vlm_model_name,
        qwen_base_url=base_settings.qwen_base_url,
        qwen_base64_max_video_bytes=base_settings.qwen_base64_max_video_bytes,
        qwen_video_fps=base_settings.qwen_video_fps,
        qwen_enable_thinking=base_settings.qwen_enable_thinking,
        qwen_thinking_budget=base_settings.qwen_thinking_budget,
        vlm_max_retries=0,
        auto_reanalysis_enabled=False,
        incident_input_roots=str(Path("data_mock").resolve()),
        artifact_dir=str(runtime_dir / "artifacts"),
        incident_database_path=str(runtime_dir / "reports.sqlite3"),
        incident_checkpoint_path=str(runtime_dir / "checkpoints.sqlite3"),
    )

    real_client = AsyncOpenAI(api_key=settings.dashscope_api_key, base_url=settings.qwen_base_url)
    one_shot = OneShotCompletions(real_client.chat.completions)
    qwen_client = SimpleNamespace(chat=SimpleNamespace(completions=one_shot))
    local_responses = LocalResponses()
    local_openai = SimpleNamespace(responses=local_responses)
    clients = ProviderClients(
        qwen=qwen_client,
        openai_verification=local_openai,
        openai_report=local_openai,
    )

    try:
        async with incident_workflow_service(settings, clients=clients) as service:
            snapshot = await service.create(
                IncidentCreateRequest(
                    incident_id=INCIDENT_ID,
                    video_uri=VIDEO_URI,
                    log_uri=LOG_URI,
                    analysis_prompt=ANALYSIS_PROMPT,
                    metadata={"trace": "one-shot-live-qwen", "ground_truth_supplied_to_model": False},
                )
            )
            graph = service._runner._graph
            history = [item async for item in graph.aget_state_history({"configurable": {"thread_id": INCIDENT_ID}})]
    finally:
        await real_client.close()

    ordered = sorted(
        (item for item in history if item.metadata.get("step", -1) >= 0),
        key=lambda item: item.metadata["step"],
    )
    node_traces: list[dict[str, Any]] = []
    for index, item in enumerate(ordered):
        node_name = item.next[0] if item.next else "END"
        before = dict(item.values)
        trace: dict[str, Any] = {
            "step": item.metadata["step"],
            "node": node_name,
            "input_state": _jsonable(before),
        }
        if index + 1 < len(ordered):
            after = dict(ordered[index + 1].values)
            trace["output_delta"] = _state_delta(before, after)
        else:
            interrupts = [
                _jsonable(interrupt.value) for task in item.tasks for interrupt in getattr(task, "interrupts", ())
            ]
            trace["output"] = {"interrupt_payload": interrupts, "status": "suspended"}
        node_traces.append(trace)

    result = {
        "run": {
            "incident_id": INCIDENT_ID,
            "video_uri": VIDEO_URI,
            "log_uri": LOG_URI,
            "analysis_prompt": ANALYSIS_PROMPT,
            "runtime_dir": str(runtime_dir),
            "external_request_policy": "exactly_one_qwen_request; downstream providers local",
        },
        "external_qwen": {
            "request_count": one_shot.count,
            "request": one_shot.request,
            "response": one_shot.response,
        },
        "local_provider_calls": local_responses.calls,
        "node_traces": node_traces,
        "public_snapshot": snapshot.model_dump(mode="json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
