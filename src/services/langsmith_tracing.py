"""LangSmith tracing configuration with incident-data sanitization."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import langsmith as ls
from langsmith import Client
from langsmith.wrappers import wrap_openai

logger = logging.getLogger(__name__)

_MEDIA_KEYS = {
    "artifact_uri",
    "image_uri",
    "image_url",
    "local_artifact_uri",
    "log_uri",
    "normalized_video_uri",
    "source_video_uri",
    "video_uri",
    "video_url",
}
_SECRET_KEYS = {
    "api_key",
    "authorization",
    "dashscope_api_key",
    "langsmith_api_key",
    "openai_api_key",
}


@dataclass(frozen=True)
class LangSmithTracing:
    """Optional tracing dependency; disabled instances are deliberate no-ops."""

    enabled: bool = False
    project_name: str = "incident-analysis-dev"
    environment: str = "development"
    client: Client | None = None

    @contextmanager
    def incident_context(self, incident_id: str, phase: str) -> Iterator[None]:
        metadata = {
            "thread_id": incident_id,
            "incident_id": incident_id,
            "environment": self.environment,
            "workflow_phase": phase,
        }
        tags = [
            "workflow:incident-analysis",
            f"env:{self.environment}",
            f"phase:{phase}",
        ]
        with ls.tracing_context(
            enabled=self.enabled,
            client=self.client,
            project_name=self.project_name,
            metadata=metadata,
            tags=tags,
        ):
            yield

    def wrap_openai_client(
        self,
        client: Any,
        *,
        name: str,
        provider: str,
        operation: str,
    ) -> Any:
        if not self.enabled or self.client is None:
            return client
        try:
            return wrap_openai(
                client,
                chat_name=name,
                completions_name=name,
                tracing_extra={
                    "client": self.client,
                    "tags": [f"provider:{provider}", f"operation:{operation}"],
                    "metadata": {"provider": provider, "operation": operation},
                },
            )
        except Exception:
            logger.exception("Could not instrument %s; provider client remains unmodified", name)
            return client


def build_langsmith_tracing(settings: Any) -> LangSmithTracing:
    """Build tracing without making LangSmith availability an app dependency."""
    disabled = LangSmithTracing(
        project_name=settings.langsmith_project,
        environment=settings.app_env,
    )
    if not settings.langsmith_tracing:
        return disabled
    if not settings.langsmith_api_key.strip():
        logger.warning("LangSmith tracing is enabled but LANGSMITH_API_KEY is empty; tracing is disabled")
        return disabled
    try:
        client = Client(
            api_url=settings.langsmith_endpoint,
            api_key=settings.langsmith_api_key,
            workspace_id=settings.langsmith_workspace_id or None,
            tracing_sampling_rate=settings.langsmith_tracing_sampling_rate,
            hide_inputs=sanitize_trace_payload,
            hide_outputs=sanitize_trace_payload,
            tracing_error_callback=lambda exc: logger.warning("LangSmith tracing error: %s", exc),
        )
    except Exception:
        logger.exception("LangSmith client initialization failed; tracing is disabled")
        return disabled
    return LangSmithTracing(
        enabled=True,
        project_name=settings.langsmith_project,
        environment=settings.app_env,
        client=client,
    )


def sanitize_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove secrets and raw media while retaining useful trace structure."""
    return _sanitize(payload)


def _sanitize(value: Any, key: str = "") -> Any:
    normalized_key = key.lower()
    if normalized_key in _SECRET_KEYS:
        return "[REDACTED_SECRET]"
    if normalized_key == "artifact_uris" and isinstance(value, dict):
        return {item_key: _media_reference(item) for item_key, item in value.items()}
    if normalized_key in _MEDIA_KEYS:
        return _media_reference(value)
    if isinstance(value, dict):
        return {item_key: _sanitize(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, key) for item in value)
    if isinstance(value, str):
        if value.startswith("data:image/") or value.startswith("data:video/"):
            return "[REDACTED_MEDIA_DATA]"
        if value.startswith("sk-") or value.startswith("lsv2_"):
            return "[REDACTED_SECRET]"
    return value


def _media_reference(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "[REDACTED_MEDIA]"
    if value.startswith("data:"):
        return "[REDACTED_MEDIA_DATA]"
    parsed = urlsplit(value)
    name = Path(parsed.path).name
    return f"[MEDIA:{name}]" if name else "[REDACTED_MEDIA]"
