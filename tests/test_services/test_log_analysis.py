import csv
import re
from pathlib import Path

import pytest

from src.models.incidents import IncidentWindow
from src.services.log_analysis import (
    MAX_INTERVALS_PER_SIGNAL,
    MIN_INTERVAL_PAD_S,
    MIN_INTERVAL_S,
    LogAnalysisError,
    LogAnalysisService,
    SignalInterval,
    _finalize_intervals,
    build_log_attention_hint,
    build_verification_log_artifact,
)

REAL_LOG = Path("data_mock/vehicle_state.csv")
CONFLICT_LOG = Path("data_mock/vehicle_state_fake.csv")
WINDOW = IncidentWindow(t_start=6, t0=7.5, t_end=14.5)


def test_analyze_real_log_slices_window_and_derives_metrics(tmp_path: Path) -> None:
    result = LogAnalysisService().analyze(
        str(REAL_LOG),
        str(tmp_path / "log_full_video.csv"),
        video_duration_s=WINDOW.t_end,
    )

    assert result.row_count == 18
    assert result.summary.metrics["speed_start"] == 40
    assert result.summary.metrics["speed_end"] == 0
    assert result.summary.metrics["max_brake"] == 1
    assert result.summary.metrics["max_deceleration"] == pytest.approx(-3.611111, rel=1e-5)
    assert result.summary.metrics["brake_rise_time"] == 6.5
    assert "Tốc độ đầu 40 km/h" in result.summary.summary
    assert "Brake tăng mạnh lần đầu tại 6.5 giây" in result.summary.summary
    assert "log-metric:speed_start" in result.summary.evidence_ids
    assert "log-metric:max_deceleration" in result.summary.evidence_ids
    assert any(event.event_type == "brake_rise" for event in result.events)

    with Path(result.log_artifact_uri).open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert float(rows[0]["timestamp_s"]) == WINDOW.t_start
    assert float(rows[-1]["timestamp_s"]) == WINDOW.t_end


def test_conflict_log_has_no_strong_brake_rise_near_incident(tmp_path: Path) -> None:
    service = LogAnalysisService()
    real = service.analyze(str(REAL_LOG), str(tmp_path / "real.csv"), video_duration_s=WINDOW.t_end)
    conflict = service.analyze(str(CONFLICT_LOG), str(tmp_path / "conflict.csv"), video_duration_s=WINDOW.t_end)

    assert real.summary.metrics["brake_rise_time"] == 6.5
    assert "brake_rise_time" not in conflict.summary.metrics
    assert conflict.summary.metrics["speed_end"] == 2.5
    assert not any(event.event_type == "brake_rise" for event in conflict.events)
    assert "Không phát hiện brake tăng mạnh" in conflict.summary.summary


def test_detects_disengagement_warning_and_error(tmp_path: Path) -> None:
    source = tmp_path / "events.csv"
    source.write_text(
        "timestamp_s,speed_kmh,autonomy_state,warning_code,error_code\n"
        "6.0,30,engaged,,\n"
        "7.0,25,off,TAKEOVER,\n"
        "8.0,20,off,,SENSOR_FAILURE\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=8,
    )

    assert {event.event_type for event in result.events} == {"disengagement", "warning", "error"}
    assert result.summary.metrics["disengagement_time"] == 7
    assert result.summary.warnings == ["TAKEOVER"]
    assert result.summary.errors == ["SENSOR_FAILURE"]


def test_rejects_non_increasing_timestamps(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("timestamp_s,speed_kmh\n1,10\n1,9\n", encoding="utf-8")

    with pytest.raises(LogAnalysisError) as exc_info:
        LogAnalysisService().analyze(
            str(source),
            str(tmp_path / "slice.csv"),
            video_duration_s=2,
        )

    assert exc_info.value.code == "LOG_TIMESTAMP_ORDER_INVALID"


def test_rejects_log_without_timestamp_column(tmp_path: Path) -> None:
    source = tmp_path / "missing_timestamp.csv"
    source.write_text("speed_kmh,brake\n10,0.5\n", encoding="utf-8")

    with pytest.raises(LogAnalysisError) as exc_info:
        LogAnalysisService().analyze(
            str(source),
            str(tmp_path / "slice.csv"),
            video_duration_s=2,
        )

    assert exc_info.value.code == "LOG_TIMESTAMP_MISSING"


def test_accepts_time_sec_timestamp_column(tmp_path: Path) -> None:
    source = tmp_path / "vehicle_state.csv"
    source.write_text(
        "time_sec,ego_speed_kmh,ego_brake\n"
        "0.0,3.528,0.0\n"
        "0.05,5.292,0.0\n"
        "0.1,7.056,0.0\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=0.1,
    )

    assert result.row_count == 3
    assert result.summary.metrics["speed_start"] == 3.528
    assert result.summary.metrics["speed_end"] == 7.056
    assert result.summary.metrics["max_brake"] == 0
    assert all(value is not None for value in result.summary.metrics.values())


def test_analysis_preserves_extreme_acceleration_for_model_context(tmp_path: Path) -> None:
    source = tmp_path / "outlier.csv"
    source.write_text(
        "timestamp_s,speed_kmh,brake\n"
        "0.0,20,0\n"
        "0.1,10,0\n"
        "0.2,10,0\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=0.2,
    )

    assert result.summary.metrics["max_deceleration"] == pytest.approx(-27.777778)
    assert result.summary.metrics["acceleration_min"] == pytest.approx(-27.777778)
    assert result.summary.metrics["acceleration_max"] == 0
    assert "acceleration_outlier_count" not in result.summary.metrics
    assert "LOG_ACCELERATION_OUTLIER_FILTERED" not in result.summary.warnings
    assert "27.778" in result.summary.summary
    assert "Dải gia tốc" in result.summary.summary


def test_analysis_adaptively_detects_and_merges_telemetry_changes(tmp_path: Path) -> None:
    source = tmp_path / "anomalies.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steer,acceleration_mps2\n"
        "0.0,30,0.0,0.0\n"
        "1.0,30,0.0,0.0\n"
        "2.0,30,0.0,0.0\n"
        "3.0,30,0.0,0.0\n"
        "4.0,30,0.0,0.0\n"
        "5.0,30,0.0,0.0\n"
        "6.0,30,0.5,-8.0\n"
        "7.0,30,0.5,-8.0\n"
        "8.0,30,0.0,0.0\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=8,
    )

    event_types = [event.event_type for event in result.events]
    assert "extreme_acceleration" in event_types
    assert "steering_change" in event_types
    assert "strong_acceleration" not in event_types
    assert "strong_deceleration" not in event_types
    assert "strong_steering_change" not in event_types
    assert "LOG_EXTREME_ACCELERATION" in "\n".join(result.summary.warnings)
    assert "LOG_ADAPTIVE_STEERING_CHANGE" in "\n".join(result.summary.warnings)
    assert result.summary.metrics["max_absolute_acceleration_time"] == 6
    assert result.summary.metrics["steering_change_time"] == 6
    assert len([event for event in result.events if event.signal == "steering"]) == 1
    assert len([event for event in result.events if event.signal == "acceleration_mps2"]) == 1
    assert "merged from 6.000s to 8.000s" in "\n".join(event.details for event in result.events)


def test_adaptive_candidates_require_physical_acceleration_and_steering_gates(tmp_path: Path) -> None:
    source = tmp_path / "physical-gates.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steer,acceleration_mps2\n"
        "0,30,0.0002,3.211\n"
        "1,30,0.0002,3.211\n"
        "2,30,0.0002,3.211\n"
        "3,30,0.0002,3.211\n"
        "4,30,0.0002,3.211\n"
        "5,30,0.0002,3.211\n"
        "6,30,0.0007,2.472\n"
        "7,30,0.0002,-0.105\n"
        "8,30,0.644,-65.789\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=8,
    )

    assert [(event.event_type, event.timestamp_s) for event in result.events] == [
        ("extreme_acceleration", 8.0),
        ("steering_change", 8.0),
    ]
    hint = build_log_attention_hint(str(source), video_duration_s=8)
    assert "8.0s" in hint
    assert "góc đánh lái thay đổi bất thường sang phải" in hint
    assert "3.211" not in hint
    assert "2.472" not in hint
    assert "-0.105" not in hint
    assert "0.0007" not in hint


def test_deceleration_metrics_use_the_peak_timestamp_not_the_first_event(tmp_path: Path) -> None:
    source = tmp_path / "deceleration-peak.csv"
    source.write_text(
        "timestamp_s,speed_kmh,acceleration_mps2\n"
        "0,30,0\n"
        "1,30,0\n"
        "2,30,0\n"
        "3,30,-6\n"
        "4,30,0\n"
        "5,30,0\n"
        "6,30,0\n"
        "7,30,0\n"
        "8,30,0\n"
        "9,30,0\n"
        "10.9,30,-65.789\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=10.9,
    )

    assert result.summary.metrics["max_deceleration"] == pytest.approx(-65.789)
    assert result.summary.metrics["max_deceleration_time"] == 10.9
    assert result.summary.metrics["max_absolute_acceleration_time"] == 10.9
    assert "Đỉnh trị tuyệt đối gia tốc tại 10.9 giây." in result.summary.summary


def test_adaptive_detector_uses_a_minimum_scale_for_flat_baselines(tmp_path: Path) -> None:
    source = tmp_path / "flat-baseline.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steer,acceleration_mps2\n"
        "0,30,0,0\n"
        "1,30,0,0\n"
        "2,30,0,0\n"
        "3,30,0,0\n"
        "4,30,0,0\n"
        "5,30,0,0\n"
        "6,30,-0.36,-20\n"
        "7,30,-0.36,-20\n"
        "8,30,0,0\n",
        encoding="utf-8",
    )

    result = LogAnalysisService().analyze(
        str(source),
        str(tmp_path / "slice.csv"),
        video_duration_s=8,
    )

    details = "\n".join(event.details for event in result.events)
    assert "peak z-score 3.60" in details
    assert "peak z-score 20.00" in details
    assert "000000" not in details


def test_verification_log_artifact_keeps_full_video_log_for_claim_sampling(tmp_path: Path) -> None:
    source = tmp_path / "vehicle.csv"
    source.write_text(
        "timestamp_s,speed_kmh\n"
        "2.5,20\n"
        "3.0,20\n"
        "3.5,20\n"
        "4.5,20\n"
        "5.0,20\n"
        "6.0,20\n"
        "12.0,20\n"
        "12.5,20\n"
        "13.0,20\n"
        "13.5,20\n",
        encoding="utf-8",
    )

    artifact_uri = build_verification_log_artifact(
        str(source),
        str(tmp_path / "verification_log.csv"),
    )

    with Path(artifact_uri).open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [float(row["timestamp_s"]) for row in rows] == [2.5, 3.0, 3.5, 4.5, 5.0, 6.0, 12.0, 12.5, 13.0, 13.5]


def test_verification_log_artifact_excludes_rows_after_video_end(tmp_path: Path) -> None:
    source = tmp_path / "vehicle.csv"
    source.write_text(
        "timestamp_s,speed_kmh\n"
        "44.70,10\n"
        "44.75,10\n"
        "44.80,10\n",
        encoding="utf-8",
    )

    artifact_uri = build_verification_log_artifact(
        str(source),
        str(tmp_path / "verification_log.csv"),
        video_duration_s=44.73,
    )

    with Path(artifact_uri).open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [float(row["timestamp_s"]) for row in rows] == [44.7]


def _hint_intervals(hint: str, needle: str) -> list[tuple[float, float]]:
    """Return the (start, end) bounds of every hint line describing `needle`."""
    bounds = []
    for line in hint.splitlines():
        if needle not in line:
            continue
        window = line.split("rong khoảng ", 1)[1].split(",", 1)[0]
        start, end = window.split("–")
        bounds.append((float(start.rstrip("s")), float(end.rstrip("s"))))
    return bounds


def test_build_log_attention_hint_contains_only_qualitative_intervals(tmp_path: Path) -> None:
    source = tmp_path / "attention.csv"
    source.write_text(
        "timestamp_s,throttle,brake,steering_angle,acceleration_mps2\n"
        "0.0,0.1,0.0,0.0,0.0\n"
        "1.0,0.1,0.0,0.0,0.0\n"
        "2.0,0.1,0.0,0.0,0.0\n"
        "3.0,0.1,0.0,0.0,0.0\n"
        "4.0,0.1,0.0,0.0,0.0\n"
        "5.0,0.1,0.0,0.0,0.0\n"
        "6.0,0.5,0.6,-0.5,-6.0\n"
        "7.0,0.5,0.6,-0.5,-6.0\n"
        "8.0,0.1,0.0,0.0,0.0\n",
        encoding="utf-8",
    )

    hint = build_log_attention_hint(str(source))

    assert "khoảng thời gian cần xem kỹ" in hint
    assert "ga tăng bất thường" in hint
    assert "phanh tăng bất thường" in hint
    assert "góc đánh lái thay đổi bất thường sang trái" in hint
    assert "gia tốc giảm bất thường" in hint
    assert "Tại giây thứ" not in hint
    for raw_value in ("0.1", "0.5", "0.6", "-0.5", "-6.0"):
        assert raw_value not in hint
    assert "evidence_id" not in hint


def test_build_log_attention_hint_exposes_no_telemetry_units(tmp_path: Path) -> None:
    source = tmp_path / "units.csv"
    source.write_text(
        "timestamp_s,throttle,brake,steering_angle,acceleration_mps2\n"
        "0.0,0.1,0.0,0.0,0.0\n"
        "1.0,0.1,0.0,0.0,0.0\n"
        "2.0,0.1,0.0,0.0,0.0\n"
        "3.0,0.1,0.0,0.0,0.0\n"
        "4.0,0.1,0.0,0.0,0.0\n"
        "5.0,0.1,0.0,0.0,0.0\n"
        "6.0,0.5,0.6,-0.5,-6.0\n"
        "7.0,0.5,0.6,-0.5,-6.0\n",
        encoding="utf-8",
    )

    hint = build_log_attention_hint(str(source))

    assert hint
    for unit in ("m/s", "%", "°", "z-score", "km/h"):
        assert unit not in hint
    # Every number rendered in the hint is a second bound taken from an interval window.
    numbers = re.findall(r"\d+(?:\.\d+)?", hint)
    bounds = _hint_intervals(hint, "rong khoảng")
    assert bounds
    assert len(numbers) == 2 * len(bounds)


def test_build_log_attention_hint_keeps_a_sustained_phase_as_one_interval(tmp_path: Path) -> None:
    rows = ["timestamp_s,speed_kmh,acceleration_mps2"]
    rows.extend(f"{index / 10:.1f},30,0.0" for index in range(10))
    # A deceleration phase that deepens over several samples, not a one-frame spike.
    rows.extend(f"{(10 + index) / 10:.1f},30,{-6.0 - index * 0.5:.1f}" for index in range(10))
    source = tmp_path / "sustained.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hint = build_log_attention_hint(str(source))

    bounds = _hint_intervals(hint, "gia tốc giảm bất thường")
    assert len(bounds) == 1
    start_s, end_s = bounds[0]
    # The phase stays one interval and keeps its real width instead of collapsing to a point.
    assert end_s - start_s > MIN_INTERVAL_S
    assert start_s <= 1.0
    assert end_s >= 1.3


def test_finalize_intervals_merges_one_signal_but_keeps_overlapping_signals() -> None:
    def interval(signal: str, start_s: float, end_s: float, z_score: float) -> SignalInterval:
        return SignalInterval(
            signal=signal,
            start_s=start_s,
            end_s=end_s,
            peak_timestamp_s=start_s,
            score=z_score,
            peak_value=0.4,
            start_value=0.0,
            end_value=0.4,
            direction=1,
            description="mô tả",
        )

    # Same signal and direction, 0.2s apart -> one interval carrying the stronger peak.
    merged = _finalize_intervals(
        [interval("steer", 1.0, 1.4, 3.5), interval("steer", 1.6, 2.0, 5.0)],
        upper_bound_s=10.0,
    )
    assert [(item.start_s, item.end_s, item.score) for item in merged] == [(1.0, 2.0, 5.0)]

    # Two different signals overlapping in time are both useful and must both survive.
    kept = _finalize_intervals(
        [interval("steer", 1.0, 1.4, 3.5), interval("acceleration", 1.1, 1.5, 4.0)],
        upper_bound_s=10.0,
    )
    assert [item.signal for item in kept] == ["steer", "acceleration"]


def test_build_log_attention_hint_widens_a_single_sample_spike(tmp_path: Path) -> None:
    source = tmp_path / "spike.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steering_angle\n"
        "0.0,30,0.0\n"
        "0.1,30,0.0\n"
        "0.2,30,0.0\n"
        "0.3,30,0.0\n"
        "0.4,30,0.0\n"
        "0.5,30,0.0\n"
        "0.6,30,0.0\n"
        "0.7,30,0.45\n"
        "0.8,30,0.45\n"
        "0.9,30,0.45\n",
        encoding="utf-8",
    )

    hint = build_log_attention_hint(str(source))

    bounds = _hint_intervals(hint, "góc đánh lái")
    assert len(bounds) == 1
    start_s, end_s = bounds[0]
    # The one-sample jump at 0.7s becomes a viewable window instead of a single frame.
    assert start_s < 0.7 < end_s
    assert end_s - start_s == pytest.approx(2 * MIN_INTERVAL_PAD_S, abs=0.05)


def test_build_log_attention_hint_returns_empty_for_a_constant_log(tmp_path: Path) -> None:
    rows = ["timestamp_s,speed_kmh,throttle,brake,steering_angle,acceleration_mps2"]
    rows.extend(f"{index / 10:.1f},30,0.2,0.0,0.0,0.0" for index in range(40))
    source = tmp_path / "constant.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    assert build_log_attention_hint(str(source)) == ""


def test_build_log_attention_hint_derives_acceleration_from_speed(tmp_path: Path) -> None:
    source = tmp_path / "derived-acceleration.csv"
    source.write_text(
        "timestamp_s,speed_kmh\n"
        "0.0,20\n"
        "0.1,20\n"
        "0.2,20\n"
        "0.3,20\n"
        "0.4,20\n"
        "0.5,20\n"
        "0.6,10\n"
        "0.7,10\n",
        encoding="utf-8",
    )

    hint = build_log_attention_hint(str(source))

    assert "gia tốc giảm bất thường" in hint
    assert _hint_intervals(hint, "gia tốc")
    assert "27.777" not in hint


def test_build_log_attention_hint_catches_a_gradual_ramp(tmp_path: Path) -> None:
    rows = ["timestamp_s,speed_kmh,steering_angle"]
    rows.extend(f"{index / 10:.1f},30,0.0" for index in range(10))
    # Steering ramps 0 -> 0.38 over ~2s. No single step comes near the adaptive z-score gate,
    # so only the total-swing detector can see this manoeuvre.
    rows.extend(f"{(10 + index) / 10:.1f},30,{0.38 * (index + 1) / 20:.4f}" for index in range(20))
    source = tmp_path / "ramp.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hint = build_log_attention_hint(str(source))

    bounds = _hint_intervals(hint, "góc đánh lái thay đổi bất thường sang phải")
    assert len(bounds) == 1
    start_s, end_s = bounds[0]
    assert start_s <= 1.0
    assert end_s >= 2.8


def test_build_log_attention_hint_catches_a_phase_masked_by_a_preceding_spike(tmp_path: Path) -> None:
    rows = ["timestamp_s,speed_kmh,acceleration_mps2"]
    rows.extend(f"{index / 20:.2f},40,0.0" for index in range(20))
    # A one-sample +40 artefact inflates the rolling scale, then a real -12 phase follows.
    rows.append("1.00,40,40.0")
    rows.extend(f"{(21 + index) / 20:.2f},40,-12.0" for index in range(10))
    source = tmp_path / "masked.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hint = build_log_attention_hint(str(source))

    assert _hint_intervals(hint, "gia tốc tăng bất thường")
    decel = _hint_intervals(hint, "gia tốc giảm bất thường")
    assert len(decel) == 1
    start_s, end_s = decel[0]
    assert start_s <= 1.1
    assert end_s >= 1.5


def test_select_hint_intervals_caps_each_signal(tmp_path: Path) -> None:
    rows = ["timestamp_s,speed_kmh,throttle,steering_angle"]
    rows.extend(f"{index / 20:.2f},40,0.5,0.0" for index in range(20))
    # Throttle oscillates hard many times; steering makes one late manoeuvre.
    for index in range(12):
        level = 0.0 if index % 2 == 0 else 0.9
        rows.append(f"{(20 + index) / 20:.2f},40,{level},0.0")
    rows.extend(f"{(32 + index) / 20:.2f},40,0.5,{0.4 * (index + 1) / 8:.4f}" for index in range(8))
    source = tmp_path / "noisy.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hint = build_log_attention_hint(str(source))

    assert len(_hint_intervals(hint, "ga ")) <= MAX_INTERVALS_PER_SIGNAL
    # The capped noisy channel must not crowd the steering manoeuvre out of the hint.
    assert _hint_intervals(hint, "góc đánh lái")
