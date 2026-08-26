from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings

# Read by scripts/log_hook.py rather than by Settings, so they are documented in
# .env.example on purpose and must not be treated as orphaned keys.
NON_SETTINGS_ENV_KEYS = {"AI_LOG_SERVER", "AI_LOG_API_KEY", "AI_LOG_DIR"}


def _env_example_keys() -> set[str]:
    keys = set()
    for line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_every_documented_env_key_maps_to_a_settings_field() -> None:
    """Settings uses extra="ignore", so an unmapped key is silently dead config."""
    orphaned = _env_example_keys() - {name.upper() for name in Settings.model_fields} - NON_SETTINGS_ENV_KEYS

    assert orphaned == set(), f"keys in .env.example that Settings never reads: {sorted(orphaned)}"


def test_documented_env_values_match_settings_defaults() -> None:
    """.env.example mirrors src/config.py so the two can never drift apart again."""
    defaults = {name.upper(): field.default for name, field in Settings.model_fields.items()}
    settings = Settings(_env_file=".env.example")

    mismatched = {
        key: (defaults[key], getattr(settings, key.lower()))
        for key in _env_example_keys() - NON_SETTINGS_ENV_KEYS
        if defaults[key] != getattr(settings, key.lower())
    }

    assert mismatched == {}, f"'.env.example' contradicts Settings defaults: {mismatched}"


def test_settings_exposes_qwen_as_the_only_vlm_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.qwen_vlm_model_name == "qwen3-vl-flash"
    assert not hasattr(settings, "openai_vlm_model_name")
    assert not hasattr(settings, "vlm_provider")
    assert not hasattr(settings, "vlm_input_mode")


def test_incident_clip_context_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.incident_clip_min_duration_s == 5
    assert settings.incident_clip_pre_roll_s == 1
    assert settings.incident_clip_post_roll_s == 2
    assert settings.log_claim_sample_radius == 3
    assert settings.vlm_structured_output_retries == 0
    assert settings.provider_network_retries == 0
    assert settings.video_redaction_enabled is True
    assert settings.redaction_image_size == 512
    assert not hasattr(settings, "log_strong_deceleration_threshold_mps2")
    assert not hasattr(settings, "log_brake_rise_threshold")


def test_claim_log_sample_radius_is_configurable() -> None:
    settings = Settings(_env_file=None, log_claim_sample_radius=5)

    assert settings.log_claim_sample_radius == 5


def test_redaction_image_size_is_configurable() -> None:
    settings = Settings(_env_file=None, redaction_image_size=640)

    assert settings.redaction_image_size == 640


def test_video_redaction_can_be_disabled() -> None:
    settings = Settings(_env_file=None, video_redaction_enabled=False)

    assert settings.video_redaction_enabled is False


def test_claim_log_sample_radius_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_claim_sample_radius=-1)


def test_langsmith_tracing_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.langsmith_tracing is False
    assert settings.langsmith_project == "incident-analysis-dev"
    assert settings.langsmith_tracing_sampling_rate == 1.0


@pytest.mark.parametrize("sampling_rate", [-0.01, 1.01])
def test_langsmith_sampling_rate_must_be_between_zero_and_one(sampling_rate: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, langsmith_tracing_sampling_rate=sampling_rate)


@pytest.mark.parametrize("missing", ["openai_api_key", "dashscope_api_key"])
def test_production_refuses_to_boot_without_provider_credentials(missing: str) -> None:
    keys = {"openai_api_key": "set", "dashscope_api_key": "set"} | {missing: ""}

    with pytest.raises(ValidationError, match=missing.upper()):
        Settings(_env_file=None, app_env="production", **keys)


def test_production_boots_once_provider_credentials_are_present() -> None:
    settings = Settings(_env_file=None, app_env="production", openai_api_key="a", dashscope_api_key="b")

    assert settings.app_env == "production"


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_non_production_stays_permissive_about_credentials(app_env: str) -> None:
    """Dev and test run against stubbed provider clients and need no real keys."""
    assert Settings(_env_file=None, app_env=app_env).openai_api_key == ""


def test_dead_configuration_fields_stay_removed() -> None:
    settings = Settings(_env_file=None)

    for removed in ("database_url", "chroma_persist_dir", "app_host", "app_port", "background_concurrency"):
        assert not hasattr(settings, removed)
