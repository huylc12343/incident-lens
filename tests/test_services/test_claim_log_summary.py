import pytest

from src.models.incidents import Claim
from src.services.log_analysis import (
    build_claim_log_summaries,
    build_claim_verification_inputs,
    build_verification_log_artifact,
)


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
        timestamp_tolerance_s=0.16,
    )[0]

    assert summary.sample_count == 7
    assert summary.sample_start_s == 0.05
    assert summary.sample_end_s == 0.35
    assert summary.nearest_timestamp_s == 0.2
    assert summary.timestamp_distance_s == pytest.approx(0.01)
    assert summary.within_tolerance is True
    assert summary.allowed_evidence_ids == [item.evidence_id for item in summary.evidence]
    assert summary.metrics["speed_kmh"]["start"] == 58
    assert summary.metrics["speed_kmh"]["end"] == 25
    assert "acceleration_outlier_count" not in summary.metrics["speed_kmh"]
    assert summary.metrics["speed_kmh"]["max_deceleration"] == pytest.approx(-55.555556)
    assert summary.metrics["brake"]["strongest_increase"] == pytest.approx(0.4)
    assert summary.metrics["brake"]["strongest_increase_timestamp_s"] == 0.25
    assert summary.metrics["steer"]["max_change"] == pytest.approx(0.4)
    assert summary.metrics["acceleration_magnitude"]["peak"] == 5
    assert summary.metrics["yaw"]["delta_wrapped"] == 20
    assert summary.metrics["pitch"]["range"] == 4
    assert summary.metrics["roll"]["range"] == 4
    assert summary.metrics["z"]["min"] == 0.1
    assert "Đối chiếu thời gian" in summary.summary
    assert "Chuyển động" in summary.summary
    assert "Trạng thái cuối cửa sổ: xe vẫn đang di chuyển." in summary.summary
    assert "Xe đã **giảm tốc mạnh** trong cửa sổ." in summary.summary
    assert "Điều khiển" in summary.summary
    assert "Hướng xe" in summary.summary


def test_claim_log_summary_uses_configured_sample_radius(tmp_path) -> None:
    log = tmp_path / "vehicle.csv"
    _write_log(log)

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-1", text="Xe phanh", timestamp_s=0.21)],
        timestamp_tolerance_s=0.16,
        sample_radius=1,
    )[0]

    assert summary.sample_count == 3
    assert summary.sample_start_s == 0.15
    assert summary.sample_end_s == 0.25
    assert "Log window: 0.15s → 0.25s" in summary.summary
    assert "Số mẫu log trong cửa sổ: 3" in summary.summary


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
    assert "Trong tolerance: **Không**" in summary.summary
    assert "Mẫu gần nhất nằm ngoài tolerance" in summary.summary


def test_claim_log_summary_reuses_global_steering_aliases_and_ignores_unknown_columns(tmp_path) -> None:
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

    assert summary.available_signals == ["timestamp", "steer"]
    assert summary.metrics["steer"]["start"] == 30
    assert summary.metrics["steer"]["end"] == 60


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
        timestamp_tolerance_s=0.2,
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
    assert "Đã loại" not in summary.summary
    assert "Giảm tốc cực đại trong cửa sổ" in summary.summary
    assert "Trạng thái cuối cửa sổ: gần như đứng yên." in summary.summary
    assert "Xe đã **giảm tốc mạnh** trong cửa sổ." in summary.summary
    assert "Throttle: 1 → 0 => có sự nhả ga." in summary.summary


def test_claim_log_summary_formats_rule_derived_states_for_verification(tmp_path) -> None:
    log = tmp_path / "claim-window.csv"
    log.write_text(
        "timestamp,speed_kmh,throttle,brake,steer,yaw\n"
        "16.7,29.7,0.6,0.0,0.01,5.00\n"
        "17.0,0.65,0.0,1.0,0.02,5.03\n"
        "17.3,0.01,0.0,1.0,0.03,5.05\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-2", text="Xe ego dừng lại", timestamp_s=17.0)],
        timestamp_tolerance_s=0.31,
        sample_radius=1,
    )[0]

    assert "Claim timestamp: 17.0s" in summary.summary
    assert "Log window: 16.7s → 17.3s" in summary.summary
    assert "Số mẫu log trong cửa sổ: 3" in summary.summary
    assert "Sai lệch timestamp: 0.0s" in summary.summary
    assert "Trong tolerance: **Có**" in summary.summary
    assert "Tốc độ tại giây thứ 16.7: 29.7 km/h" in summary.summary
    assert "Tốc độ tại giây thứ 17.3: 0.01 km/h" in summary.summary
    assert "Trạng thái cuối cửa sổ: gần như đứng yên." in summary.summary
    assert "Xe đã **giảm tốc mạnh** trong cửa sổ." in summary.summary
    assert "Brake: 0 → 1 => có sự ấn phanh trong cửa sổ." in summary.summary
    assert "Throttle: 0.6 → 0 => có sự nhả ga." in summary.summary
    assert "Gia tốc tại 17.0s: -26.8981 m/s²" in summary.summary
    assert "Đã loại" not in summary.summary
    assert "Yaw thay đổi: 0.05°" in summary.summary
    # 0.02 sits inside the ±0.1 straight-ahead deadband.
    assert "Steering tại 17.0s: 0.02 => steering gần trung tâm." in summary.summary
    assert "| 17.0s | 0.65 |" in summary.summary


def test_claim_log_summary_formats_per_second_series_and_claim_acceleration(tmp_path) -> None:
    log = tmp_path / "seven-second-window.csv"
    rows = [
        (7.0, 28, 0.03, 0.90, 0.10),
        (7.5, 27, 0.03, 0.82, 0.10),
        (8.0, 26, 0.03, 0.74, 0.05),
        (8.5, 25, 0.03, 0.66, 0.00),
        (9.0, 24, 0.02, 0.58, -0.05),
        (9.5, 22, 0.02, 0.50, -0.10),
        (10.0, 15.5, 0.02, 0.42, -0.34),
        (10.5, 12.5, 0.02, 0.36, -0.30),
        (11.0, 10, 0.02, 0.31, -0.25),
        (11.5, 7, 0.02, 0.27, -0.20),
        (12.0, 4, 0.01, 0.23, -0.15),
        (12.5, 2, 0.01, 0.20, -0.10),
        (13.0, 1.2, 0.01, 0.17, -0.05),
    ]
    log.write_text(
        "timestamp,speed_kmh,throttle,brake,steer\n"
        + "\n".join(",".join(str(value) for value in row) for row in rows)
        + "\n",
        encoding="utf-8",
    )

    summaries = build_claim_log_summaries(
        str(log),
        [
            Claim(claim_id="claim-10", text="Xe giảm tốc", timestamp_s=10.0),
            Claim(claim_id="claim-10-5", text="Xe tiếp tục giảm tốc", timestamp_s=10.5),
        ],
        timestamp_tolerance_s=3.0,
        sample_radius=6,
    )
    summary = summaries[0]

    assert summary.sample_count == 13
    assert "Log window: 7.0s → 13.0s" in summary.summary
    assert "Số mẫu log trong cửa sổ: 13" in summary.summary
    assert "Số dòng log model được phép dùng: 13" in summary.summary
    assert "brake [0, 1]: 0 là không phanh, 1 là đạp phanh hết cỡ;" in summary.summary
    assert "steering <= -0.1 rẽ trái" in summary.summary
    assert "| Timestamp | Speed (km/h) |" in summary.summary
    for timestamp_s, speed, _, brake, _ in rows:
        assert f"| {timestamp_s:.1f}s | {speed:g} |" in summary.summary
        assert f"| {timestamp_s:.1f}s | {brake:g} |" in summary.summary
    assert "| Timestamp | Brake |" in summary.summary
    assert "| Timestamp | Throttle |" in summary.summary
    assert "| Timestamp | Steering |" in summary.summary
    assert "Gia tốc tại 10.0s: -3.61111 m/s²" in summary.summary
    assert "Giảm tốc cực đại trong cửa sổ: -3.61111 m/s² tại 10.0s" in summary.summary
    assert "Steering tại 10.0s: -0.34 => xe có xu hướng rẽ trái." in summary.summary
    assert summaries[0].metrics["speed_kmh"]["acceleration_at_claim"] == pytest.approx(-3.611111)
    assert summaries[1].metrics["speed_kmh"]["acceleration_at_claim"] == pytest.approx(-1.666667)


@pytest.mark.parametrize(
    ("steer", "expected_direction"),
    [
        (-0.1, "left"),
        (-0.099, "straight"),
        (0.0, "straight"),
        (0.099, "straight"),
        (0.1, "right"),
    ],
)
def test_claim_verification_uses_steering_deadband(tmp_path, steer: float, expected_direction: str) -> None:
    log = tmp_path / "steering.csv"
    log.write_text(
        f"timestamp_s,speed_kmh,steer\n10.0,20,{steer}\n",
        encoding="utf-8",
    )

    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="turn", text="Hướng lái", timestamp_s=10.0)],
        timestamp_tolerance_s=0.5,
    )

    assert contexts[0].derived.steer_direction_at_claim == expected_direction


def test_claim_sample_radius_uses_full_verification_artifact(tmp_path) -> None:
    source = tmp_path / "vehicle.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steer\n"
        + "".join(f"{timestamp}.0,20,0\n" for timestamp in range(21)),
        encoding="utf-8",
    )
    artifact = build_verification_log_artifact(
        str(source),
        str(tmp_path / "verification_log.csv"),
        video_duration_s=20,
    )

    summaries, _ = build_claim_verification_inputs(
        artifact,
        [Claim(claim_id="claim-3", text="Xe tiếp tục chạy", timestamp_s=11.0)],
        timestamp_tolerance_s=0.5,
        sample_radius=128,
        video_duration_s=20,
    )

    assert summaries[0].sample_start_s == 0
    assert summaries[0].sample_end_s == 20


def test_claim_log_summary_includes_all_allowed_subsecond_rows(tmp_path) -> None:
    log = tmp_path / "subsecond-window.csv"
    rows = [
        (3.7 + index * 0.05, 20 + index, index / 20, index / 12, -0.3 + index * 0.05)
        for index in range(13)
    ]
    log.write_text(
        "timestamp,speed_kmh,throttle,brake,steer\n"
        + "\n".join(",".join(str(value) for value in row) for row in rows)
        + "\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-3", text="Xe thay đổi chuyển động", timestamp_s=4.0)],
        timestamp_tolerance_s=0.31,
        sample_radius=6,
    )[0]

    assert summary.sample_count == 13
    assert "Số mẫu log trong cửa sổ: 13" in summary.summary
    assert "Số dòng log model được phép dùng: 13" in summary.summary
    for value_label in ("Speed (km/h)", "Brake", "Throttle", "Steering"):
        table = summary.summary.split(f"| Timestamp | {value_label} |", 1)[1].split("\n\n", 1)[0]
        for timestamp_s, *_ in rows:
            formatted = f"{timestamp_s:.6f}".rstrip("0").rstrip(".")
            if "." not in formatted:
                formatted = f"{formatted}.0"
            assert f"| {formatted}s |" in table


def test_model_visible_rows_exactly_match_allowed_evidence(tmp_path) -> None:
    log = tmp_path / "claim-window.csv"
    log.write_text(
        "timestamp,speed_kmh,brake,steer\n"
        "7.6,22,0,-0.2\n"
        "9.2,22,0,-0.2\n"
        "9.6,22,0,-0.2\n"
        "10.0,22,0,-0.2\n"
        "10.4,22,0,-0.2\n"
        "10.8,22,0,-0.2\n"
        "12.4,22,0,-0.2\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-10", text="Xe đang rẽ", timestamp_s=10.0)],
        timestamp_tolerance_s=0.5,
        sample_radius=10,
    )[0]

    visible_ids = [item.evidence_id for item in summary.evidence]
    assert visible_ids == ["log-row:9.6", "log-row:10", "log-row:10.4"]
    assert summary.allowed_evidence_ids == visible_ids
    assert summary.sample_start_s == 9.6
    assert summary.sample_end_s == 10.4
    for timestamp_s in (9.6, 10.0, 10.4):
        assert f"| {timestamp_s:.1f}s |" in summary.summary
    assert "7.6s" not in summary.summary
    assert "12.4s" not in summary.summary


def test_claim_evidence_uses_full_telemetry(tmp_path) -> None:
    log = tmp_path / "video-end.csv"
    log.write_text(
        "timestamp,speed_kmh,brake\n"
        "44.70,10,0\n"
        "44.75,10,0\n"
        "44.80,10,0\n"
        "44.85,10,0\n"
        "44.90,10,0\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-end", text="Video kết thúc", timestamp_s=44.72)],
        timestamp_tolerance_s=0.3,
        sample_radius=10,
    )[0]

    assert [item.timestamp_s for item in summary.evidence] == [44.7, 44.75, 44.8, 44.85, 44.9]
    assert summary.allowed_evidence_ids == [
        "log-row:44.7",
        "log-row:44.75",
        "log-row:44.8",
        "log-row:44.85",
        "log-row:44.9",
    ]
    assert summary.sample_end_s == 44.9
    assert "44.75" in summary.summary


def test_verification_claim_outside_incident_window_uses_full_video_telemetry(tmp_path) -> None:
    log = tmp_path / "full-video.csv"
    log.write_text(
        "timestamp,speed_kmh,brake\n"
        "9.5,20,0\n"
        "10.0,18,0\n"
        "10.5,16,0\n"
        "27.0,5,1\n"
        "45.1,0,1\n",
        encoding="utf-8",
    )

    summaries, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="claim-early", text="Xe giảm tốc ở đầu video", timestamp_s=10)],
        timestamp_tolerance_s=0.5,
        sample_radius=10,
        video_duration_s=45,
    )

    assert summaries[0].within_tolerance is True
    assert [item.timestamp_s for item in summaries[0].evidence] == [9.5, 10, 10.5, 27]
    assert contexts[0].raw_telemetry.at_claim.timestamp_s == 10
    assert contexts[0].allowed_evidence_ids == [
        "log-row:9.5",
        "log-row:10",
        "log-row:27",
    ]


def test_claim_verification_derives_dynamics_without_change_points(tmp_path) -> None:
    log = tmp_path / "derived-dynamics.csv"
    log.write_text(
        "timestamp,speed_kmh,brake,steer\n"
        "26.0,25,0,0.3\n"
        "26.5,23,,-0.3\n"
        "27.0,20.902,0,-0.3\n"
        "27.5,0.699,1,-0.3\n",
        encoding="utf-8",
    )

    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="claim-1", text="Xe giảm tốc", timestamp_s=26.5)],
        timestamp_tolerance_s=0.5,
        sample_radius=48,
    )

    dynamics = contexts[0].derived_dynamics
    assert dynamics.max_deceleration_mps2.model_dump() == {
        "value": pytest.approx(11.223889),
        "level": "strong_abnormal",
        "text": "Xe có giảm tốc rất mạnh trong khoảng claim.",
    }
    assert dynamics.steering_activity.model_dump() == {
        "value": pytest.approx(0.2),
        "level": "strong_abnormal",
        "text": "Steering biến động rất mạnh trong khoảng claim.",
    }
    assert dynamics.decel_brake_mismatch.model_dump() == {
        "value": 0,
        "level": "normal",
        "text": "Giảm tốc và tín hiệu brake không có mismatch đáng kể.",
    }


def test_extreme_acceleration_is_preserved_in_claim_summary(tmp_path) -> None:
    log = tmp_path / "acceleration-outlier.csv"
    log.write_text(
        "timestamp,speed_kmh,brake\n"
        "0.0,20,0\n"
        "0.1,10,0\n"
        "0.2,10,0\n",
        encoding="utf-8",
    )

    summary = build_claim_log_summaries(
        str(log),
        [Claim(claim_id="claim-no-crash", text="Xe chạy bình thường", timestamp_s=0.1)],
        timestamp_tolerance_s=0.11,
        sample_radius=3,
    )[0]

    speed = summary.metrics["speed_kmh"]
    assert "acceleration_outlier_count" not in speed
    assert speed["acceleration_at_claim"] == pytest.approx(-27.777778)
    assert speed["max_deceleration"] == pytest.approx(-27.777778)
    assert "-27.777" in summary.summary
    assert "Đã loại" not in summary.summary


def _write_dynamic_log(path) -> None:
    """A calm run, then a hard right steering jump held from 2.0s to 2.4s."""
    rows = ["timestamp_s,speed_kmh,throttle,brake,steer"]
    rows.extend(f"{index / 10:.1f},40,0.5,0.0,0.0" for index in range(20))
    rows.extend(f"{(20 + index) / 10:.1f},40,0.5,0.0,0.38" for index in range(5))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_claim_dynamic_hints_carry_numeric_values_for_the_covering_claim(tmp_path) -> None:
    log = tmp_path / "dynamic.csv"
    _write_dynamic_log(log)

    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="turn", text="Xe đánh lái sang phải", timestamp_s=2.0)],
        timestamp_tolerance_s=0.2,
    )

    hints = contexts[0].dynamic_hints
    assert [hint.signal for hint in hints] == ["steer"]
    hint = hints[0]
    assert hint.start_s <= 2.0 <= hint.end_s
    # Unlike the VLM hint, the verification hint exposes the peak telemetry value.
    assert hint.value == pytest.approx(0.38)
    assert "trong khoảng " in hint.text
    assert "góc đánh lái thay đổi bất thường sang phải" in hint.text


def test_claim_dynamic_hints_skip_claims_outside_the_interval(tmp_path) -> None:
    log = tmp_path / "dynamic.csv"
    _write_dynamic_log(log)

    _, contexts = build_claim_verification_inputs(
        str(log),
        [
            Claim(claim_id="early", text="Xe đi thẳng", timestamp_s=0.5),
            Claim(claim_id="turn", text="Xe đánh lái sang phải", timestamp_s=2.0),
        ],
        timestamp_tolerance_s=0.2,
    )

    # Only the claim whose timestamp the interval covers receives the hint.
    assert contexts[0].dynamic_hints == []
    assert [hint.signal for hint in contexts[1].dynamic_hints] == ["steer"]


def test_claim_dynamic_hints_use_the_claim_sampling_window_not_strict_containment(tmp_path) -> None:
    log = tmp_path / "dynamic.csv"
    _write_dynamic_log(log)

    # sample_radius is a row count; at 0.1s per row a radius of 30 spans +/- 3.0s.
    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="turn", text="Xe đánh lái sang phải", timestamp_s=1.2)],
        timestamp_tolerance_s=0.2,
        sample_radius=30,
    )

    # The claim timestamp sits outside the steering interval, but the whole interval sits inside
    # the claim window, so the hint still belongs to this claim.
    hints = contexts[0].dynamic_hints
    assert [hint.signal for hint in hints] == ["steer"]
    assert not hints[0].start_s <= 1.2 <= hints[0].end_s


def test_claim_dynamic_hints_require_most_of_the_interval_inside_the_window(tmp_path) -> None:
    log = tmp_path / "dynamic.csv"
    _write_dynamic_log(log)

    def hints_for(sample_radius: int) -> list[str]:
        _, contexts = build_claim_verification_inputs(
            str(log),
            [Claim(claim_id="before", text="Xe đi thẳng", timestamp_s=1.7)],
            timestamp_tolerance_s=0.2,
            sample_radius=sample_radius,
        )
        return [hint.signal for hint in contexts[0].dynamic_hints]

    # The interval spans 1.85-2.15s. A +/-0.2s window overlaps a sixth of it and a +/-0.3s window
    # exactly half, neither of which clears the "more than half" rule; +/-0.4s overlaps five sixths.
    assert hints_for(2) == []
    assert hints_for(3) == []
    assert hints_for(4) == ["steer"]


def _dynamics_for(tmp_path, speeds: list[float]) -> dict[str, tuple[float | None, str]]:
    log = tmp_path / f"phase-{speeds[0]}-{speeds[-1]}.csv"
    rows = ["timestamp_s,speed_kmh,throttle,brake,steer"]
    rows.extend(
        f"{index / 10:.1f},{speed},0.5,0.0,0.0" for index, speed in enumerate(speeds)
    )
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="c", text="Chuyển động của ego", timestamp_s=0.5)],
        timestamp_tolerance_s=0.2,
        sample_radius=20,
    )
    return {name: (metric.value, metric.text) for name, metric in contexts[0].derived_dynamics}


def test_derived_dynamics_describe_acceleration_when_speed_rises(tmp_path) -> None:
    dynamics = _dynamics_for(tmp_path, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90])

    magnitude, text = dynamics["max_deceleration_mps2"]
    assert magnitude is not None
    # speed_trend is "increase" here, so the wording must not claim the car decelerated.
    assert "tăng tốc" in text
    assert "giảm tốc" not in text
    # Low brake while accelerating is normal driving and must not read as an accident signal.
    mismatch_text = dynamics["decel_brake_mismatch"][1]
    assert mismatch_text == "Xe tăng tốc rất mạnh."
    assert "tai nạn" not in mismatch_text


def test_derived_dynamics_keep_the_accident_wording_when_speed_drops(tmp_path) -> None:
    dynamics = _dynamics_for(tmp_path, [90, 80, 70, 60, 50, 40, 30, 20, 10, 0])

    assert "giảm tốc" in dynamics["max_deceleration_mps2"][1]
    assert "tai nạn" in dynamics["decel_brake_mismatch"][1]


def test_claim_dynamic_hint_text_carries_the_values_it_moved_through(tmp_path) -> None:
    log = tmp_path / "throttle-steps.csv"
    rows = ["timestamp_s,speed_kmh,throttle,brake,steer"]
    rows.extend(f"{index / 10:.1f},40,0.38,0.0,0.0" for index in range(20))
    rows.extend(f"{(20 + index) / 10:.1f},40,0.08,0.0,0.0" for index in range(5))
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")

    _, contexts = build_claim_verification_inputs(
        str(log),
        [Claim(claim_id="lift", text="Xe nhả ga", timestamp_s=2.0)],
        timestamp_tolerance_s=0.2,
        sample_radius=20,
    )

    texts = [hint.text for hint in contexts[0].dynamic_hints if hint.signal == "throttle"]
    assert texts
    assert "ga giảm bất thường từ 0.38 -> 0.08" in texts[0]
