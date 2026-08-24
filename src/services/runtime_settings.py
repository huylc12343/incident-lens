"""Persisted, restart-applied AI provider settings.

Secrets are written only to the backend data volume and are never returned by
the API.  Docker restarts load this file after .env, so explicit runtime
settings take precedence without modifying the repository checkout.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field


class AiRuntimeSettingsUpdate(BaseModel):
    openai_api_key: str | None = Field(default=None, max_length=500)
    dashscope_api_key: str | None = Field(default=None, max_length=500)
    langsmith_api_key: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=120)
    qwen_vlm_model_name: str | None = Field(default=None, min_length=1, max_length=120)
    verification_model_name: str | None = Field(default=None, min_length=1, max_length=120)
    report_model_name: str | None = Field(default=None, min_length=1, max_length=120)
    langsmith_project: str | None = Field(default=None, min_length=1, max_length=120)
    langsmith_tracing: bool | None = None


_ENV_NAMES = {
    "openai_api_key": "OPENAI_API_KEY",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "langsmith_api_key": "LANGSMITH_API_KEY",
    "model_name": "MODEL_NAME",
    "qwen_vlm_model_name": "QWEN_VLM_MODEL_NAME",
    "verification_model_name": "VERIFICATION_MODEL_NAME",
    "report_model_name": "REPORT_MODEL_NAME",
    "langsmith_project": "LANGSMITH_PROJECT",
    "langsmith_tracing": "LANGSMITH_TRACING",
}


def runtime_settings_path() -> Path:
    return Path("./data/runtime-settings.env")


def save_ai_runtime_settings(update: AiRuntimeSettingsUpdate, path: Path | None = None) -> None:
    """Merge non-empty submitted values into a mode-0600 dotenv file."""
    destination = path or runtime_settings_path()
    values = _read_dotenv(destination)
    for field, env_name in _ENV_NAMES.items():
        value = getattr(update, field)
        if isinstance(value, bool):
            values[env_name] = str(value).lower()
        elif value is not None and value.strip():
            values[env_name] = value.strip()

    destination.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{name}={_quote(value)}\n" for name, value in sorted(values.items()))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        if name in _ENV_NAMES.values():
            result[name] = value.strip().strip('"')
    return result


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
