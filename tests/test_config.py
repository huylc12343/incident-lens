import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models.incidents import VLMInputMode, VLMProvider


@pytest.mark.parametrize(
    ("provider", "input_mode"),
    [
        ("openai", "timestamped_frames"),
        ("gemini", "native_video"),
    ],
)
def test_supported_provider_mode_pairs(provider: str, input_mode: str) -> None:
    settings = Settings(_env_file=None, vlm_provider=provider, vlm_input_mode=input_mode)

    assert settings.vlm_provider == VLMProvider(provider)
    assert settings.vlm_input_mode == VLMInputMode(input_mode)


@pytest.mark.parametrize(
    ("provider", "input_mode"),
    [
        ("openai", "native_video"),
        ("gemini", "timestamped_frames"),
    ],
)
def test_unsupported_provider_mode_pairs_fail_bootstrap(provider: str, input_mode: str) -> None:
    with pytest.raises(ValidationError, match="unsupported VLM provider/input mode"):
        Settings(_env_file=None, vlm_provider=provider, vlm_input_mode=input_mode)


def test_rolling_batch_overlap_must_be_smaller_than_batch() -> None:
    with pytest.raises(ValidationError, match="overlap must be smaller"):
        Settings(_env_file=None, vlm_frame_batch_size=10, vlm_frame_batch_overlap=10)


def test_incident_clip_context_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.incident_clip_min_duration_s == 5
    assert settings.incident_clip_pre_roll_s == 1
    assert settings.incident_clip_post_roll_s == 2
