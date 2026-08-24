import os

from src.services.runtime_settings import AiRuntimeSettingsUpdate, save_ai_runtime_settings


def test_save_ai_runtime_settings_merges_values_without_erasing_existing_secret(tmp_path):
    path = tmp_path / "runtime-settings.env"
    save_ai_runtime_settings(
        AiRuntimeSettingsUpdate(openai_api_key="openai-secret", model_name="gpt-4o-mini"), path
    )
    save_ai_runtime_settings(
        AiRuntimeSettingsUpdate(report_model_name="gpt-4.1-mini", langsmith_tracing=True), path
    )

    content = path.read_text(encoding="utf-8")
    assert 'OPENAI_API_KEY="openai-secret"' in content
    assert 'MODEL_NAME="gpt-4o-mini"' in content
    assert 'REPORT_MODEL_NAME="gpt-4.1-mini"' in content
    assert 'LANGSMITH_TRACING="true"' in content
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
