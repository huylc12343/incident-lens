from types import SimpleNamespace

from src.services.model_observability import ModelActivityRegistry, extract_token_usage


def test_extracts_openai_responses_usage() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            input_tokens_details=SimpleNamespace(cached_tokens=20),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        )
    )

    usage = extract_token_usage(response)

    assert usage is not None
    assert usage.model_dump() == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cached_tokens": 20,
        "reasoning_tokens": 10,
    }


def test_extracts_provider_usage_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=200,
            candidates_token_count=40,
            total_token_count=240,
            cached_content_token_count=25,
            thoughts_token_count=15,
        )
    )

    usage = extract_token_usage(response)

    assert usage is not None
    assert usage.total_tokens == 240
    assert usage.cached_tokens == 25
    assert usage.reasoning_tokens == 15


def test_registry_tracks_activity_per_incident() -> None:
    registry = ModelActivityRegistry()
    activity_id = registry.start(
        incident_id="INC-OBS",
        step="vlm",
        operation="video_analysis",
        description="Phân tích video.",
        provider="openai",
        model="gpt-test",
        metadata={"image_count": 2},
    )

    assert registry.list("INC-OBS")[0].status == "running"

    registry.complete(
        activity_id,
        SimpleNamespace(usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}),
    )

    activity = registry.list("INC-OBS")[0]
    assert activity.status == "completed"
    assert activity.usage is not None
    assert activity.usage.total_tokens == 12
    assert activity.duration_ms is not None
