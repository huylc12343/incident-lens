"""Per-incident model activity and provider token-usage tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from src.models.api import ModelActivity, TokenUsage


class ModelActivityRegistry:
    def __init__(self) -> None:
        self._activities: dict[str, list[ModelActivity]] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        incident_id: str,
        step: str,
        operation: str,
        description: str,
        provider: str,
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        activity = ModelActivity(
            activity_id=str(uuid4()),
            incident_id=incident_id,
            step=step,
            operation=operation,
            description=description,
            provider=provider,
            model=model,
            status="running",
            started_at=datetime.now(UTC),
            metadata=metadata or {},
        )
        with self._lock:
            self._activities.setdefault(incident_id, []).append(activity)
        return activity.activity_id

    def complete(self, activity_id: str, response: Any) -> None:
        self._finish(activity_id, status="completed", usage=extract_token_usage(response))

    def fail(self, activity_id: str, error_code: str, response: Any | None = None) -> None:
        self._finish(
            activity_id,
            status="failed",
            error_code=error_code,
            usage=extract_token_usage(response) if response is not None else None,
        )

    def list(self, incident_id: str) -> list[ModelActivity]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._activities.get(incident_id, [])]

    def restore(self, incident_id: str, activities: list[ModelActivity]) -> None:
        with self._lock:
            if incident_id not in self._activities:
                self._activities[incident_id] = [item.model_copy(deep=True) for item in activities]

    def _finish(
        self,
        activity_id: str,
        *,
        status: str,
        usage: TokenUsage | None = None,
        error_code: str | None = None,
    ) -> None:
        completed_at = datetime.now(UTC)
        with self._lock:
            for incident_id, activities in self._activities.items():
                for index, activity in enumerate(activities):
                    if activity.activity_id != activity_id:
                        continue
                    elapsed = max(int((completed_at - activity.started_at).total_seconds() * 1000), 0)
                    activities[index] = activity.model_copy(
                        update={
                            "status": status,
                            "completed_at": completed_at,
                            "duration_ms": elapsed,
                            "usage": usage,
                            "error_code": error_code,
                        }
                    )
                    return


def extract_token_usage(response: Any) -> TokenUsage | None:
    """Normalize common provider usage metadata without SDK coupling."""
    usage = _value(response, "usage")
    if usage is not None:
        input_details = _value(usage, "input_tokens_details")
        output_details = _value(usage, "output_tokens_details")
        return _usage(
            input_tokens=_integer(usage, "input_tokens") or _integer(usage, "prompt_tokens"),
            output_tokens=_integer(usage, "output_tokens") or _integer(usage, "completion_tokens"),
            total_tokens=_integer(usage, "total_tokens"),
            cached_tokens=_integer(input_details, "cached_tokens"),
            reasoning_tokens=_integer(output_details, "reasoning_tokens"),
        )

    usage = _value(response, "usage_metadata")
    if usage is not None:
        return _usage(
            input_tokens=_integer(usage, "prompt_token_count"),
            output_tokens=_integer(usage, "candidates_token_count"),
            total_tokens=_integer(usage, "total_token_count"),
            cached_tokens=_integer(usage, "cached_content_token_count"),
            reasoning_tokens=_integer(usage, "thoughts_token_count"),
        )
    return None


def _usage(**values: int) -> TokenUsage:
    if values["total_tokens"] == 0:
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    return TokenUsage(**values)


def _integer(value: Any, key: str) -> int:
    raw = _value(value, key)
    return int(raw) if isinstance(raw, (int, float)) and raw >= 0 else 0


def _value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
