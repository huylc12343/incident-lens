from hashlib import sha256

import pytest

from src.models.incidents import (
    Claim,
    ClaimLogSummary,
    ClaimRawTelemetry,
    ClaimTelemetryDerived,
    ClaimTelemetrySnapshot,
    ClaimVerificationContext,
)
from src.prompts.verification import build_reverification_prompt, build_verification_prompt
from src.services.log_analysis import build_claim_verification_inputs


def _compact_context(claim_id: str, *, brake: float | None = None) -> ClaimVerificationContext:
    snapshot = ClaimTelemetrySnapshot(
        timestamp_s=12.5 if brake is not None else None,
        evidence_id="log-row:12.5" if brake is not None else None,
        brake=brake,
    )
    return ClaimVerificationContext(
        claim_id=claim_id,
        available_signals=["brake"] if brake is not None else [],
        raw_telemetry=ClaimRawTelemetry(
            window_start=snapshot,
            at_claim=snapshot,
            window_end=snapshot,
        ),
        derived=ClaimTelemetryDerived(),
        allowed_evidence_ids=["log-row:12.5"] if brake is not None else [],
    )


def test_verification_system_prompt_matches_approved_text_exactly() -> None:
    prompt = build_verification_prompt(
        claims=[],
        claim_log_summaries=[],
        timestamp_tolerance_s=0.5,
    )

    assert sha256(prompt.text.encode("utf-8")).hexdigest() == (
        "dddc7af3e3f3f4a6f384b3150a55e5880b5b59af2c09d5f68e0c305eb1dca4bd"
    )


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
                available_signals=["timestamp", "brake"],
                summary=(
                    "Đối chiếu thời gian\n"
                    "Claim timestamp: 12.5s\n"
                    "Số mẫu đại diện tối đa trong mỗi bảng: 4\n"
                    "Trong tolerance: **Có**\n\n"
                    "Log có thể kiểm tra\n"
                    "timestamp: mốc ghép claim;\n"
                    "brake [0, 1]: 0 không phanh, 1 phanh hết cỡ;\n\n"
                    "Điều khiển\nBrake tăng mạnh tại 12.5 giây."
                ),
            )
        ],
        claim_verification_contexts=[_compact_context("claim-1", brake=0.82)],
        timestamp_tolerance_s=0.5,
    )

    assert "Trả chính xác một result cho mỗi claim_id" in prompt.text
    assert "supported" in prompt.text
    assert "supported, contradicted, unverified" in prompt.text
    assert "Log chỉ có thẩm quyền với chuyển động của xe ego" in prompt.text
    assert "Không dùng telemetry gián tiếp để phủ định hiện tượng hình ảnh" in prompt.text
    assert "has_accident" in prompt.text
    assert "reason phải ngắn, rõ" in prompt.text
    item = prompt.context["verification_items"][0]
    assert item["allowed_evidence_ids"] == ["log-row:12.5"]
    assert item["within_tolerance"] is True
    assert item["claim"] == {
        "claim_id": "claim-1",
        "text": "Hard braking",
        "timestamp_s": 12.5,
    }
    assert item["available_signals"] == ["brake"]
    assert item["log_facts"]["raw_telemetry"]["at_claim"]["brake"] == 0.82
    assert set(item) == {
        "claim",
        "within_tolerance",
        "available_signals",
        "log_facts",
        "allowed_evidence_ids",
    }
    assert "verification_items" not in prompt.text
    assert "Brake tăng mạnh tại 12.5 giây." not in prompt.text
    assert "brake, throttle thuộc [0,1]" in prompt.text
    assert "Trong tolerance:" not in str(item)
    assert "Log có thể kiểm tra" not in str(item)
    assert "claim_log_summary" not in prompt.text
    assert '"metrics"' not in prompt.text
    assert "log_evidence_summary" not in prompt.context
    assert "raw_telemetry" in item["log_facts"]
    assert item["log_facts"]["derived_dynamics"] == {
        "max_deceleration_mps2": {
            "value": None,
            "text": "",
        },
        "steering_activity": {
            "value": None,
            "text": "",
        },
        "decel_brake_mismatch": {
            "value": None,
            "text": "",
        },
    }
    assert "change_points" not in item["log_facts"]
    assert "level" not in str(item["log_facts"]["derived_dynamics"])


def test_reverification_prompt_is_claim_only_and_excludes_accident_decision() -> None:
    prompt = build_reverification_prompt(
        claims=[Claim(claim_id="claim-1", text="Hard braking", timestamp_s=12.5)],
        claim_log_summaries=[ClaimLogSummary(claim_id="claim-1", summary="Log available.")],
        claim_verification_contexts=[_compact_context("claim-1", brake=0.82)],
        timestamp_tolerance_s=0.5,
    )

    assert "XÁC THỰC LẠI sau automatic reanalysis" in prompt.text
    assert "không đánh giá có/không có tai nạn" in prompt.text
    assert "has_accident" not in prompt.text
    assert list(prompt.context) == ["verification_items"]
    assert prompt.context["verification_items"][0]["claim"]["claim_id"] == "claim-1"


def test_verification_prompt_is_deterministic() -> None:
    kwargs = {
        "claims": [Claim(claim_id="claim-1", text="Claim")],
        "claim_log_summaries": [ClaimLogSummary(claim_id="claim-1", summary="Không có timestamp.")],
        "claim_verification_contexts": [_compact_context("claim-1")],
        "timestamp_tolerance_s": 0.5,
    }

    assert build_verification_prompt(**kwargs) == build_verification_prompt(**kwargs)


def test_verification_prompt_uses_compact_timestamp_semantics(tmp_path) -> None:
    log = tmp_path / "claim-semantics.csv"
    log.write_text(
        "timestamp,vehicle_speed_kmh,throttle_pedal,brake_pressure,steering_angle\n"
        "26.0,25,0.2,0,0.3\n"
        "26.5,23,0.1,,-0.3\n"
        "27.0,20.902,0,0,-0.3\n"
        "27.5,0.699,0,1,-0.3\n",
        encoding="utf-8",
    )
    claims = [
        Claim(claim_id="turn", text="Xe rẽ phải", timestamp_s=26.5),
        Claim(claim_id="stop", text="Xe dừng", timestamp_s=27.0),
    ]
    summaries, compact_contexts = build_claim_verification_inputs(
        str(log),
        claims,
        timestamp_tolerance_s=0.5,
        sample_radius=48,
    )

    prompt = build_verification_prompt(
        claims=claims,
        claim_log_summaries=summaries,
        claim_verification_contexts=compact_contexts,
        timestamp_tolerance_s=0.5,
    )
    turn, stop = prompt.context["verification_items"]

    turn_raw = turn["log_facts"]["raw_telemetry"]
    assert turn_raw["window_start"]["steer"] == 0.3
    assert turn_raw["at_claim"]["steer"] == -0.3
    assert turn_raw["at_claim"]["brake"] is None
    assert turn["log_facts"]["derived"]["steer_direction_at_claim"] == "left"
    turn_dynamics = turn["log_facts"]["derived_dynamics"]
    assert turn_dynamics["max_deceleration_mps2"]["value"] == pytest.approx(11.223889)
    assert turn_dynamics["max_deceleration_mps2"]["text"] == "Xe có giảm tốc rất mạnh trong khoảng claim."
    assert turn_dynamics["steering_activity"]["value"] == pytest.approx(0.2)
    assert turn_dynamics["decel_brake_mismatch"]["value"] == 0

    stop_raw = stop["log_facts"]["raw_telemetry"]
    assert stop_raw["at_claim"]["speed_kmh"] == 20.902
    assert stop_raw["window_end"]["speed_kmh"] == 0.699
    assert stop["log_facts"]["derived"]["movement_state_at_claim"] == "moving"
    assert stop["log_facts"]["derived"]["speed_trend"] == "strong_decrease"

    expected_signal_keys = {"speed_kmh", "throttle", "brake", "steer"}
    for item in (turn, stop):
        snapshots = item["log_facts"]["raw_telemetry"]
        assert {key for key in snapshots["window_start"] if key in expected_signal_keys} == expected_signal_keys
        assert snapshots["window_start"].keys() == snapshots["at_claim"].keys()
        assert snapshots["at_claim"].keys() == snapshots["window_end"].keys()
        assert 1 <= len(item["allowed_evidence_ids"]) <= 5


def test_verification_prompt_does_not_send_all_21_raw_samples(tmp_path) -> None:
    log = tmp_path / "twenty-one.csv"
    rows = [f"{10 + index * 0.05:.2f},20,0.2,0,-0.1" for index in range(21)]
    log.write_text(
        "timestamp,speed_kmh,throttle,brake,steer\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    claims = [Claim(claim_id="claim-1", text="Xe đang chạy", timestamp_s=10.5)]
    summaries, compact_contexts = build_claim_verification_inputs(
        str(log),
        claims,
        timestamp_tolerance_s=0.5,
        sample_radius=48,
    )

    prompt = build_verification_prompt(
        claims=claims,
        claim_log_summaries=summaries,
        claim_verification_contexts=compact_contexts,
        timestamp_tolerance_s=0.5,
    )
    item = prompt.context["verification_items"][0]

    assert summaries[0].sample_count == 21
    assert len(summaries[0].evidence) == 21
    assert "log_summary" not in item["claim"]
    assert set(item["log_facts"]["raw_telemetry"]) == {"window_start", "at_claim", "window_end"}
    assert item["allowed_evidence_ids"] == ["log-row:10", "log-row:10.5", "log-row:11"]
    assert "10.05" not in str(prompt.context)


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
