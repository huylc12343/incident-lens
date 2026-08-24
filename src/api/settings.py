"""Admin-only API for AI provider configuration."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.config import Settings
from src.services.runtime_settings import AiRuntimeSettingsUpdate, save_ai_runtime_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class AiRuntimeSettingsResponse(BaseModel):
    openai_api_key_configured: bool
    dashscope_api_key_configured: bool
    langsmith_api_key_configured: bool
    model_name: str
    qwen_vlm_model_name: str
    verification_model_name: str
    report_model_name: str
    langsmith_project: str
    langsmith_tracing: bool
    restart_required: bool = False


def _response(settings: Settings, *, restart_required: bool = False) -> AiRuntimeSettingsResponse:
    return AiRuntimeSettingsResponse(
        openai_api_key_configured=bool(settings.openai_api_key.strip()),
        dashscope_api_key_configured=bool(settings.dashscope_api_key.strip()),
        langsmith_api_key_configured=bool(settings.langsmith_api_key.strip()),
        model_name=settings.model_name,
        qwen_vlm_model_name=settings.qwen_vlm_model_name,
        verification_model_name=settings.verification_model_name,
        report_model_name=settings.report_model_name,
        langsmith_project=settings.langsmith_project,
        langsmith_tracing=settings.langsmith_tracing,
        restart_required=restart_required,
    )


@router.get("/ai", response_model=AiRuntimeSettingsResponse)
async def get_ai_runtime_settings() -> AiRuntimeSettingsResponse:
    return _response(Settings())


@router.put("/ai", response_model=AiRuntimeSettingsResponse)
async def update_ai_runtime_settings(
    payload: AiRuntimeSettingsUpdate,
) -> AiRuntimeSettingsResponse:
    settings = Settings()
    save_ai_runtime_settings(payload)
    # The running workflow owns provider clients created at startup. A restart
    # avoids mixing credentials/models within a single incident execution.
    return _response(settings, restart_required=True)
