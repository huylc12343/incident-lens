from types import SimpleNamespace

import pytest

from src.services.model_observability import ModelActivityRegistry, ModelRequestBudgetError, extract_token_usage


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


def test_registry_enforces_hard_provider_request_budget() -> None:
    registry = ModelActivityRegistry(max_provider_requests_per_incident=2)
    kwargs = {
        "incident_id": "INC-BUDGET",
        "step": "vlm",
        "operation": "video_analysis",
        "description": "Provider attempt.",
        "provider": "qwen",
        "model": "qwen-test",
    }
    registry.start(**kwargs, metadata={"attempt": 1})
    registry.start(**kwargs, metadata={"attempt": 2})

    with pytest.raises(ModelRequestBudgetError) as exc_info:
        registry.start(**kwargs, metadata={"attempt": 3})

    assert exc_info.value.code == "PROVIDER_REQUEST_BUDGET_EXCEEDED"


def test_registry_grants_budget_for_one_manual_reanalysis_cycle() -> None:
    registry = ModelActivityRegistry(max_provider_requests_per_incident=1)
    kwargs = {
        "incident_id": "INC-REANALYZE",
        "step": "vlm",
        "operation": "claim_reanalysis",
        "description": "Manual re-analysis.",
        "provider": "qwen",
        "model": "qwen-test",
    }
    registry.start(**kwargs)
    registry.grant_additional_requests("INC-REANALYZE", 3)

    for _ in range(3):
        registry.start(**kwargs)

    with pytest.raises(ModelRequestBudgetError):
        registry.start(**kwargs)
