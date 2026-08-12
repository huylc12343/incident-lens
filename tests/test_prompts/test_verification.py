import pytest

from src.models.incidents import Claim, ClaimLogSummary
from src.prompts.verification import build_verification_prompt


def test_verification_prompt_requires_one_result_per_claim() -> None:
    prompt = build_verification_prompt(
        claims=[Claim(claim_id="claim-1", text="Hard braking", timestamp_s=12.5)],
        claim_log_summaries=[
            ClaimLogSummary(
                claim_id="claim-1",
                claim_timestamp_s=12.5,
                nearest_timestamp_s=12.5,
                timestamp_distance_s=0,
                within_tolerance=True,
                metrics={"brake": {"max": 0.82}},
                allowed_evidence_ids=["log-row:12.5"],
                summary="Brake tăng mạnh tại 12.5 giây.",
            )
        ],
        timestamp_tolerance_s=0.5,
    )

    assert "chính xác một kết quả cho mỗi claim_id" in prompt.text
    assert "supported" in prompt.text
    assert "supported, contradicted hoặc unverified" in prompt.text
    assert "Log chỉ đo lường trạng thái vận hành cơ khí" in prompt.text
    assert "Không suy ra va chạm" in prompt.text
    assert "reason phải ngắn gọn bằng tiếng Việt" in prompt.text
    item = prompt.context["verification_items"][0]
    assert item["allowed_evidence_ids"] == ["log-row:12.5"]
    assert item["within_tolerance"] is True
    assert item["claim"]["log_summary"] == "Brake tăng mạnh tại 12.5 giây."
    assert set(item) == {"claim", "within_tolerance", "allowed_evidence_ids"}
    assert "verification_items" not in prompt.text
    assert "Brake tăng mạnh tại 12.5 giây." not in prompt.text
    assert "claim_log_summary" not in prompt.text
    assert '"metrics"' not in prompt.text
    assert "log_evidence_summary" not in prompt.context
    assert "raw" not in prompt.context


def test_verification_prompt_is_deterministic() -> None:
    kwargs = {
        "claims": [Claim(claim_id="claim-1", text="Claim")],
        "claim_log_summaries": [ClaimLogSummary(claim_id="claim-1", summary="Không có timestamp.")],
        "timestamp_tolerance_s": 0.5,
    }

    assert build_verification_prompt(**kwargs) == build_verification_prompt(**kwargs)


def test_verification_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValueError, match="claim IDs must be unique"):
        build_verification_prompt(
            claims=[Claim(claim_id="claim-1", text="A"), Claim(claim_id="claim-1", text="B")],
            claim_log_summaries=[
                ClaimLogSummary(claim_id="claim-1", summary="A"),
                ClaimLogSummary(claim_id="claim-1", summary="B"),
            ],
            timestamp_tolerance_s=0.5,
        )
