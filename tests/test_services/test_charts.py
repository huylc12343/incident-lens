from pathlib import Path

from src.models.incidents import IncidentWindow
from src.services.charts import ChartService
from src.services.log_analysis import LogAnalysisService


def test_creates_four_png_charts_with_all_window_markers(tmp_path: Path, monkeypatch) -> None:
    window = IncidentWindow(t_start=6, t0=7.5, t_end=14.5)
    analysis = LogAnalysisService().analyze(
        "data_mock/vehicle_state.csv",
        str(tmp_path / "log_slice.csv"),
        window=window,
    )
    service = ChartService()
    marker_calls: list[tuple[float, float, float]] = []
    original = service._mark_window

    def record_markers(axis, marked_window: IncidentWindow) -> None:
        marker_calls.append((marked_window.t_start, marked_window.t0, marked_window.t_end))
        original(axis, marked_window)

    monkeypatch.setattr(service, "_mark_window", record_markers)
    chart_uris = service.create_charts(
        analysis.log_slice_uri,
        str(tmp_path / "charts"),
        window=window,
        events=analysis.events,
    )

    assert [Path(uri).name for uri in chart_uris] == [
        "01_speed_acceleration.png",
        "02_brake_throttle.png",
        "03_steering.png",
        "04_autonomy_events.png",
    ]
    assert marker_calls == [(6, 7.5, 14.5)] * 4
    assert all(Path(uri).read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for uri in chart_uris)
