import pytest

from src.models.incidents import Claim
from src.services.log_analysis import build_claim_log_summaries


def _write_log(path) -> None:
    rows = [
        "timestamp,camera_frame,speed_kmh,throttle,brake,steer,acceleration_x,acceleration_y,acceleration_z,yaw,pitch,roll,z",
        "0.00,100,60,0.8,0.0,-0.1,0,0,1,160,0,0,1.0",
        "0.05,101,58,0.8,0.0,0.0,0,0,1,170,1,-1,0.9",
        "0.10,102,55,0.7,0.1,0.1,1,0,1,175,2,-2,0.8",
        "0.15,103,50,0.6,0.3,0.2,2,0,1,179,3,-3,0.7",
        "0.20,104,45,0.4,0.6,0.5,3,4,0,-179,4,-4,0.5",
        "0.25,105,35,0.2,1.0,0.8,1,2,2,-175,5,-5,0.3",
        "0.30,106,30,0.1,1.0,0.4,0,1,1,-172,4,-4,0.2",
        "0.35,107,25,0.1,0.8,0.2,0,0,1,-170,3,-3,0.1",
        "0.40,108,20,0.0,0.5,0.0,0,0,1,-168,2,-2,0.0",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_claim_log_summary_uses_three_samples_each_side_and_precomputes_metrics(tmp_path) -> None:
    log = tmp_path / "vehicle.csv"
    _write_log(log)

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-1", text="Xe phanh", timestamp_s=0.21)],
        timestamp_tolerance_s=0.011,
    )[0]

    assert summary.sample_count == 7
    assert summary.sample_start_s == 0.05
    assert summary.sample_end_s == 0.35
    assert summary.nearest_timestamp_s == 0.2
    assert summary.timestamp_distance_s == pytest.approx(0.01)
    assert summary.within_tolerance is True
    assert summary.allowed_evidence_ids == ["log-row:0.2"]
    assert summary.metrics["speed_kmh"]["start"] == 58
    assert summary.metrics["speed_kmh"]["end"] == 25
    assert summary.metrics["speed_kmh"]["max_deceleration"] == pytest.approx(-55.555555, rel=1e-5)
    assert summary.metrics["speed_kmh"]["max_deceleration_timestamp_s"] == 0.25
    assert summary.metrics["brake"]["strongest_increase"] == pytest.approx(0.4)
    assert summary.metrics["brake"]["strongest_increase_timestamp_s"] == 0.25
    assert summary.metrics["steer"]["max_change"] == pytest.approx(0.4)
    assert summary.metrics["acceleration_magnitude"]["peak"] == 5
    assert summary.metrics["yaw"]["delta_wrapped"] == 20
    assert summary.metrics["pitch"]["range"] == 4
    assert summary.metrics["roll"]["range"] == 4
    assert summary.metrics["z"]["min"] == 0.1
    assert "Steer chuẩn hóa" in summary.summary


def test_claim_log_summary_withholds_evidence_outside_timestamp_tolerance(tmp_path) -> None:
    log = tmp_path / "vehicle.csv"
    _write_log(log)

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-1", text="Xe phanh", timestamp_s=1.0)],
        timestamp_tolerance_s=0.1,
    )[0]

    assert summary.nearest_timestamp_s == 0.4
    assert summary.timestamp_distance_s == pytest.approx(0.6)
    assert summary.within_tolerance is False
    assert summary.allowed_evidence_ids == []
    assert "ngoài timestamp_tolerance_s" in summary.summary


def test_claim_log_summary_ignores_non_allowlisted_raw_columns(tmp_path) -> None:
    log = tmp_path / "extra-columns.csv"
    log.write_text(
        "timestamp,frame,x,velocity_x,hand_brake,steering_angle\n"
        "0.0,10,100,20,false,30\n"
        "0.1,11,200,30,true,60\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-1", text="Ngoại cảnh", timestamp_s=0.05)],
        timestamp_tolerance_s=0.1,
    )[0]

    assert summary.available_signals == ["timestamp"]
    assert summary.metrics == {}


def test_claim_log_summary_supports_ego_signal_column_names(tmp_path) -> None:
    log = tmp_path / "ego-vehicle.csv"
    log.write_text(
        "time_sec,ego_speed_kmh,ego_throttle,ego_brake,ego_steer\n"
        "0.00,30,1.0,0.0,-0.3\n"
        "0.05,25,0.8,0.0,-0.2\n"
        "0.10,20,0.5,0.2,-0.1\n"
        "0.15,10,0.1,0.7,0.2\n"
        "0.20,0,0.0,1.0,0.5\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-impact", text="Xe ego va chạm vật cản", timestamp_s=0.15)],
        timestamp_tolerance_s=0.01,
    )[0]

    assert summary.available_signals == ["timestamp", "speed_kmh", "throttle", "brake", "steer"]
    assert summary.metrics["speed_kmh"]["start"] == 30
    assert summary.metrics["speed_kmh"]["end"] == 0
    assert summary.metrics["throttle"]["start"] == 1
    assert summary.metrics["brake"]["max"] == 1
    assert summary.metrics["steer"]["max"] == 0.5
    assert all(
        value is not None
        for signal_metrics in summary.metrics.values()
        for value in signal_metrics.values()
    )
    assert "Giảm tốc cực đại" in summary.summary
