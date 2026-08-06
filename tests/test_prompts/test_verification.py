import pytest

from src.models.incidents import Claim, LogEvidenceSummary
from src.prompts.verification import build_verification_prompt


def test_verification_prompt_requires_one_result_per_claim() -> None:
    prompt = build_verification_prompt(
        claims=[Claim(claim_id="claim-1", text="Hard braking")],
        log_evidence_summary=LogEvidenceSummary(
            metrics={"max_brake": 0.82},
            events=[{"timestamp_s": 12.5, "type": "brake_rise"}],
            evidence_ids=["log-1"],
        ),
        timestamp_tolerance_s=0.5,
    )

    assert "chính xác một kết quả cho mỗi claim_id" in prompt.text
    assert "supported" in prompt.text
    assert "reason phải ngắn gọn bằng tiếng Việt" in prompt.text
    assert prompt.context["timestamp_tolerance_s"] == 0.5
    assert prompt.context["log_evidence_summary"]["evidence_ids"] == ["log-1"]


def test_verification_prompt_is_deterministic() -> None:
    kwargs = {
        "claims": [Claim(claim_id="claim-1", text="Claim")],
        "log_evidence_summary": LogEvidenceSummary(),
        "timestamp_tolerance_s": 0.5,
    }

    assert build_verification_prompt(**kwargs) == build_verification_prompt(**kwargs)


def test_verification_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValueError, match="claim IDs must be unique"):
        build_verification_prompt(
            claims=[Claim(claim_id="claim-1", text="A"), Claim(claim_id="claim-1", text="B")],
            log_evidence_summary=LogEvidenceSummary(),
            timestamp_tolerance_s=0.5,
        )
