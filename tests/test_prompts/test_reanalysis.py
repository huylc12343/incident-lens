import pytest

from src.models.incidents import (
    Claim,
    IncidentWindow,
    LogEvidenceSummary,
    PromptSource,
)
from src.prompts.reanalysis import build_auto_reanalysis_prompt, build_human_reanalysis_prompt


def test_auto_reanalysis_contains_only_automatic_context() -> None:
    prompt = build_auto_reanalysis_prompt(
        conflict_claim=Claim(claim_id="claim-1", text="The vehicle braked hard", timestamp_s=12.5),
        verification_reason="Brake signal did not rise near the claimed timestamp.",
        log_evidence_summary=LogEvidenceSummary(
            metrics={"max_brake": 0.12},
            events=[{"timestamp_s": 12.5, "type": "speed_drop"}],
            evidence_ids=["log-1"],
        ),
        timestamp_window=IncidentWindow(t_start=11.2, t0=12.5, t_end=15.1),
        version="auto-v2",
    )

    assert prompt.source == PromptSource.AGENT_GENERATED
    assert prompt.version == "auto-v2"
    assert set(prompt.context) == {
        "conflict_claim",
        "verification_reason",
        "log_evidence_summary",
        "timestamp_window",
    }
    assert "feedback" not in prompt.context
    assert "claim-1" not in prompt.text
    assert prompt.context["conflict_claim"]["claim_id"] == "claim-1"


def test_human_reanalysis_contains_only_reviewer_context() -> None:
    claim = Claim(claim_id="claim-1", text="The vehicle braked hard", timestamp_s=12.5)
    prompt = build_human_reanalysis_prompt(
        target_claim_ids=["claim-1"],
        feedback="Check whether the brake lights illuminate.",
        current_claims=[claim],
        version="human-v3",
    )

    assert prompt.source == PromptSource.HUMAN_PROVIDED
    assert prompt.version == "human-v3"
    assert set(prompt.context) == {"target_claim_ids", "feedback", "current_claims"}
    assert "verification_reason" not in prompt.context
    assert "Check whether" not in prompt.text
    assert prompt.context["feedback"] == "Check whether the brake lights illuminate."
    assert "nội dung giải thích mới phải bằng tiếng Việt" in prompt.text


def test_auto_and_human_prompts_are_deterministic_and_distinct() -> None:
    claim = Claim(claim_id="claim-1", text="Claim")
    auto_kwargs = {
        "conflict_claim": claim,
        "verification_reason": "Conflict",
        "log_evidence_summary": LogEvidenceSummary(),
        "timestamp_window": IncidentWindow(t_start=1, t0=2, t_end=3),
    }
    human_kwargs = {
        "target_claim_ids": ["claim-1"],
        "feedback": "Review this claim",
        "current_claims": [claim],
    }

    assert build_auto_reanalysis_prompt(**auto_kwargs) == build_auto_reanalysis_prompt(**auto_kwargs)
    assert build_human_reanalysis_prompt(**human_kwargs) == build_human_reanalysis_prompt(**human_kwargs)
    assert build_auto_reanalysis_prompt(**auto_kwargs).text == build_human_reanalysis_prompt(**human_kwargs).text
    assert build_auto_reanalysis_prompt(**auto_kwargs).context != build_human_reanalysis_prompt(**human_kwargs).context


@pytest.mark.parametrize("feedback", ["", "   "])
def test_human_reanalysis_rejects_blank_feedback(feedback: str) -> None:
    with pytest.raises(ValueError, match="feedback must not be blank"):
        build_human_reanalysis_prompt(
            target_claim_ids=["claim-1"],
            feedback=feedback,
            current_claims=[Claim(claim_id="claim-1", text="Claim")],
        )


def test_human_reanalysis_rejects_unknown_target_claim() -> None:
    with pytest.raises(ValueError, match="target claims do not exist"):
        build_human_reanalysis_prompt(
            target_claim_ids=["missing"],
            feedback="Review",
            current_claims=[Claim(claim_id="claim-1", text="Claim")],
        )
