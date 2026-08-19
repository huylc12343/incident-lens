import csv
from pathlib import Path

import pytest

from src.models.incidents import IncidentWindow
from src.services.log_analysis import (
    LogAnalysisError,
    LogAnalysisService,
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
    assert result.summary.metrics["extreme_acceleration_time"] == 6
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
    assert "Tại giây thứ 8.0" in hint
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
    assert result.summary.metrics["strong_deceleration_time"] == 10.9
    assert result.summary.metrics["extreme_acceleration_time"] == 10.9
    assert "Phát hiện gia tốc cực đoan tại 10.9 giây." in result.summary.summary


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


def test_build_log_attention_hint_contains_only_qualitative_changes(tmp_path: Path) -> None:
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

    assert "Tại giây thứ 6.0" in hint
    assert "ga tăng bất thường so với diễn biến gần đó" in hint
    assert "phanh tăng bất thường so với diễn biến gần đó" in hint
    assert "góc đánh lái thay đổi bất thường sang trái" in hint
    assert "gia tốc giảm bất thường so với diễn biến gần đó" in hint
    for raw_value in ("0.1", "0.5", "0.6", "-0.5", "-6.0"):
        assert raw_value not in hint
    assert "evidence_id" not in hint


def test_build_log_attention_hint_uses_acceleration_without_raw_values(tmp_path: Path) -> None:
    source = tmp_path / "stable.csv"
    source.write_text(
        "timestamp_s,throttle,brake,steering_angle,acceleration_mps2\n"
        "0.0,0.1,0.0,0.0,0.0\n"
        "1.0,0.1,0.0,0.0,0.0\n"
        "2.0,0.1,0.0,0.0,0.0\n"
        "3.0,0.1,0.0,0.0,0.0\n"
        "4.0,0.1,0.0,0.0,0.0\n"
        "5.0,0.1,0.0,0.0,0.0\n"
        "6.0,0.1,0.0,0.0,-4.0\n"
        "7.0,0.1,0.0,0.0,-25.87\n",
        encoding="utf-8",
    )

    hint = build_log_attention_hint(str(source))

    assert "Tại giây thứ 7.0" in hint
    assert "gia tốc giảm bất thường so với diễn biến gần đó" in hint
    assert "-4.0" not in hint
    assert "-25.87" not in hint


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

    assert "Tại giây thứ 0.6" in hint
    assert "gia tốc giảm bất thường so với diễn biến gần đó" in hint
    assert "27.777" not in hint
