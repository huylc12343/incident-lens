from pathlib import Path

from src.models.incidents import Claim, IncidentWindow
from src.services.charts import ChartService
from src.services.log_analysis import LogAnalysisService


def test_creates_full_log_charts_with_all_window_markers(tmp_path: Path, monkeypatch) -> None:
    window = IncidentWindow(t_start=6, t0=7.5, t_end=14.5)
    analysis = LogAnalysisService().analyze(
        "data_mock/INC_LOSS_CONTROL_001/vehicle_state.csv",
        str(tmp_path / "log_slice.csv"),
        window=window,
    )
    service = ChartService()
    marker_calls: list[tuple[float, float, float]] = []
    claim_marker_calls: list[list[tuple[str, float | None]]] = []
    claims = [Claim(claim_id="claim-1", text="Xe ego giảm tốc.", timestamp_s=7.2)]
    original = service._mark_window
    original_claims = service._mark_claims
    original_speed_chart = service._speed_acceleration_chart
    chart_timestamps: list[list[float]] = []

    def record_markers(axis, marked_window: IncidentWindow) -> None:
        marker_calls.append((marked_window.t_start, marked_window.t0, marked_window.t_end))
        original(axis, marked_window)

    monkeypatch.setattr(service, "_mark_window", record_markers)

    def record_claim_markers(axis, marked_claims: list[Claim]) -> None:
        claim_marker_calls.append([(claim.claim_id, claim.timestamp_s) for claim in marked_claims])
        original_claims(axis, marked_claims)

    monkeypatch.setattr(service, "_mark_claims", record_claim_markers)

    def record_speed_chart(destination, timestamps, speed, acceleration, marked_window, marked_claims):
        chart_timestamps.append(timestamps)
        return original_speed_chart(destination, timestamps, speed, acceleration, marked_window, marked_claims)

    monkeypatch.setattr(service, "_speed_acceleration_chart", record_speed_chart)
    chart_uris = service.create_charts(
        "data_mock/INC_LOSS_CONTROL_001/vehicle_state.csv",
        str(tmp_path / "charts"),
        window=window,
        events=analysis.events,
        claims=claims,
    )

    assert [Path(uri).name for uri in chart_uris] == [
        "01_speed_acceleration.png",
        "02_brake_throttle.png",
        "03_steering.png",
        "04_autonomy_events.png",
    ]
    assert marker_calls == [(6, 7.5, 14.5)] * 4
    assert claim_marker_calls == [[("claim-1", 7.2)]] * 4
    assert len(chart_timestamps[0]) > analysis.row_count
    assert chart_timestamps[0][0] < window.t_start
    assert chart_timestamps[0][-1] > window.t_end
    assert all(Path(uri).read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for uri in chart_uris)


def test_charts_accept_deterministic_telemetry_anomaly_events(tmp_path: Path) -> None:
    source = tmp_path / "anomalies.csv"
    source.write_text(
        "timestamp_s,speed_kmh,steer,acceleration_mps2\n"
        "0,30,0,0\n"
        "1,30,0.4,-5.5\n"
        "2,30,0,4.5\n"
        "3,30,0.5,-8\n",
        encoding="utf-8",
    )
    window = IncidentWindow(t_start=0, t0=1, t_end=3)
    analysis = LogAnalysisService().analyze(str(source), str(tmp_path / "log_slice.csv"), window=window)

    chart_uris = ChartService().create_charts(
        str(source),
        str(tmp_path / "charts"),
        window=window,
        events=analysis.events,
        claims=[],
    )

    assert {event.event_type for event in analysis.events} >= {
        "strong_deceleration",
        "strong_acceleration",
        "extreme_acceleration",
        "strong_steering_change",
    }
    assert all(Path(uri).is_file() for uri in chart_uris)
