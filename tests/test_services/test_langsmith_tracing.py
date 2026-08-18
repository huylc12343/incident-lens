from unittest.mock import Mock, patch

from src.config import Settings
from src.services.langsmith_tracing import (
    LangSmithTracing,
    build_langsmith_tracing,
    sanitize_trace_payload,
)


def test_sanitizer_removes_media_payloads_secrets_and_signed_urls() -> None:
    sanitized = sanitize_trace_payload(
        {
            "openai_api_key": "sk-secret",
            "input": [
                {"image_url": "data:image/jpeg;base64,raw-image"},
                {"video_url": "https://example.test/private/clip.mp4?signature=secret"},
            ],
            "result": {
                "video_uri": "/tmp/incidents/front-camera.mp4",
                "artifact_uris": {
                    "incident_clip": "/tmp/incidents/private/incident.mp4",
                    "chart": "/tmp/incidents/private/speed.png",
                },
            },
        }
    )

    assert sanitized == {
        "openai_api_key": "[REDACTED_SECRET]",
        "input": [
            {"image_url": "[REDACTED_MEDIA_DATA]"},
            {"video_url": "[MEDIA:clip.mp4]"},
        ],
        "result": {
            "video_uri": "[MEDIA:front-camera.mp4]",
            "artifact_uris": {
                "incident_clip": "[MEDIA:incident.mp4]",
                "chart": "[MEDIA:speed.png]",
            },
        },
    }


def test_disabled_tracing_does_not_wrap_provider_client() -> None:
    provider_client = object()

    result = LangSmithTracing().wrap_openai_client(
        provider_client,
        name="Qwen VLM",
        provider="qwen",
        operation="video_analysis",
    )

    assert result is provider_client


def test_enabled_tracing_wraps_provider_client_with_metadata() -> None:
    provider_client = object()
    langsmith_client = Mock()
    tracing = LangSmithTracing(enabled=True, client=langsmith_client)
    wrapped_client = object()

    with patch("src.services.langsmith_tracing.wrap_openai", return_value=wrapped_client) as wrapper:
        result = tracing.wrap_openai_client(
            provider_client,
            name="Qwen VLM",
            provider="qwen",
            operation="vlm",
        )

    assert result is wrapped_client
    wrapper.assert_called_once_with(
        provider_client,
        chat_name="Qwen VLM",
        completions_name="Qwen VLM",
        tracing_extra={
            "client": langsmith_client,
            "tags": ["provider:qwen", "operation:vlm"],
            "metadata": {"provider": "qwen", "operation": "vlm"},
        },
    )


def test_wrapper_failure_keeps_original_provider_client() -> None:
    provider_client = object()
    tracing = LangSmithTracing(enabled=True, client=Mock())

    with patch("src.services.langsmith_tracing.wrap_openai", side_effect=TypeError("unsupported client")):
        result = tracing.wrap_openai_client(
            provider_client,
            name="Injected test client",
            provider="qwen",
            operation="vlm",
        )

    assert result is provider_client


def test_missing_api_key_disables_requested_tracing() -> None:
    settings = Settings(_env_file=None, langsmith_tracing=True, langsmith_api_key="")

    tracing = build_langsmith_tracing(settings)

    assert tracing.enabled is False
    assert tracing.client is None


def test_enabled_tracing_builds_sanitizing_client() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        langsmith_tracing=True,
        langsmith_api_key="lsv2_test",
        langsmith_project="incident-production",
        langsmith_tracing_sampling_rate=0.25,
    )
    client = Mock()

    with patch("src.services.langsmith_tracing.Client", return_value=client) as client_type:
        tracing = build_langsmith_tracing(settings)

    assert tracing.enabled is True
    assert tracing.client is client
    assert tracing.project_name == "incident-production"
    client_type.assert_called_once_with(
        api_url="https://api.smith.langchain.com",
        api_key="lsv2_test",
        workspace_id=None,
        tracing_sampling_rate=0.25,
        hide_inputs=sanitize_trace_payload,
        hide_outputs=sanitize_trace_payload,
        tracing_error_callback=client_type.call_args.kwargs["tracing_error_callback"],
    )
