import pytest
from pydantic import ValidationError

from src.config import Settings


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
    assert not hasattr(settings, "log_strong_deceleration_threshold_mps2")
    assert not hasattr(settings, "log_brake_rise_threshold")


def test_claim_log_sample_radius_is_configurable() -> None:
    settings = Settings(_env_file=None, log_claim_sample_radius=5)

    assert settings.log_claim_sample_radius == 5


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
