"""Deterministic chart artifacts for the full telemetry log."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from src.models.incidents import Claim, IncidentWindow, LogEvent
from src.services.log_analysis import (  # noqa: E402
    AUTONOMY_ALIASES,
    BRAKE_ALIASES,
    SPEED_ALIASES,
    STEERING_ALIASES,
    THROTTLE_ALIASES,
    acceleration_series,
    load_log_records,
    numeric_series,
)


class ChartService:
    def create_charts(
        self,
        log_uri: str,
        output_dir: str,
        *,
        window: IncidentWindow,
        events: list[LogEvent],
        claims: list[Claim],
    ) -> list[str]:
        _, records = load_log_records(log_uri)
        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        timestamps = [record.timestamp_s for record in records]
        speed = numeric_series(records, SPEED_ALIASES)
        acceleration = acceleration_series(records)
        brake = numeric_series(records, BRAKE_ALIASES)
        throttle = numeric_series(records, THROTTLE_ALIASES)
        steering = numeric_series(records, STEERING_ALIASES)
        autonomy = [_autonomy_value(record.text(AUTONOMY_ALIASES)) for record in records]

        chart_uris = [
            self._speed_acceleration_chart(destination, timestamps, speed, acceleration, window, claims),
            self._brake_throttle_chart(destination, timestamps, brake, throttle, window, claims),
            self._steering_chart(destination, timestamps, steering, window, claims),
            self._autonomy_event_chart(destination, timestamps, autonomy, events, window, claims),
        ]
        return [str(path) for path in chart_uris]

    def _speed_acceleration_chart(
        self,
        destination: Path,
        timestamps: list[float],
        speed: list[float | None],
        acceleration: list[float | None],
        window: IncidentWindow,
        claims: list[Claim],
    ) -> Path:
        figure, axis = plt.subplots(figsize=(10, 4.5))
        axis.plot(timestamps, speed, color="#1565c0", label="Speed (km/h)")
        axis.set_ylabel("Speed (km/h)")
        second_axis = axis.twinx()
        second_axis.plot(timestamps, acceleration, color="#d32f2f", label="Acceleration (m/s²)")
        second_axis.set_ylabel("Acceleration (m/s²)")
        self._mark_window(axis, window)
        self._mark_claims(axis, claims)
        axis.set_title("Speed and acceleration")
        axis.set_xlabel("Time (s)")
        _combined_legend(axis, second_axis)
        return _save_figure(figure, destination / "01_speed_acceleration.png")

    def _brake_throttle_chart(
        self,
        destination: Path,
        timestamps: list[float],
        brake: list[float | None],
        throttle: list[float | None],
        window: IncidentWindow,
        claims: list[Claim],
    ) -> Path:
        figure, axis = plt.subplots(figsize=(10, 4.5))
        axis.plot(timestamps, brake, color="#c62828", label="Brake")
        axis.plot(timestamps, throttle, color="#2e7d32", label="Throttle")
        self._mark_window(axis, window)
        self._mark_claims(axis, claims)
        axis.set(title="Brake and throttle", xlabel="Time (s)", ylabel="Normalized input")
        axis.legend(loc="best")
        return _save_figure(figure, destination / "02_brake_throttle.png")

    def _steering_chart(
        self,
        destination: Path,
        timestamps: list[float],
        steering: list[float | None],
        window: IncidentWindow,
        claims: list[Claim],
    ) -> Path:
        figure, axis = plt.subplots(figsize=(10, 4.5))
        axis.plot(timestamps, steering, color="#6a1b9a", label="Steering")
        self._mark_window(axis, window)
        self._mark_claims(axis, claims)
        axis.set(title="Steering angle/input", xlabel="Time (s)", ylabel="Steering")
        axis.legend(loc="best")
        return _save_figure(figure, destination / "03_steering.png")

    def _autonomy_event_chart(
        self,
        destination: Path,
        timestamps: list[float],
        autonomy: list[float],
        events: list[LogEvent],
        window: IncidentWindow,
        claims: list[Claim],
    ) -> Path:
        figure, axis = plt.subplots(figsize=(10, 4.5))
        axis.step(timestamps, autonomy, where="post", color="#00695c", label="Autonomy state")
        event_colors = {
            "disengagement": "#ef6c00",
            "warning": "#f9a825",
            "error": "#b71c1c",
            "brake_rise": "#c62828",
            "steering_change": "#6a1b9a",
            "strong_steering_change": "#4a148c",
            "strong_deceleration": "#d84315",
            "strong_acceleration": "#1565c0",
            "extreme_acceleration": "#b71c1c",
        }
        for event in events:
            axis.scatter(
                [event.timestamp_s],
                [1.1],
                color=event_colors[event.event_type],
                marker="x",
                label=event.event_type,
            )
        self._mark_window(axis, window)
        self._mark_claims(axis, claims)
        axis.set(title="Autonomy, disengagement, warnings and errors", xlabel="Time (s)", ylabel="State/event")
        axis.set_ylim(-0.1, 1.25)
        _deduplicated_legend(axis)
        return _save_figure(figure, destination / "04_autonomy_events.png")

    def _mark_window(self, axis: Axes, window: IncidentWindow) -> None:
        axis.axvline(window.t_start, color="#455a64", linestyle="--", label="t_start")
        axis.axvline(window.t0, color="#e65100", linestyle="-", label="t0")
        axis.axvline(window.t_end, color="#455a64", linestyle=":", label="t_end")
        axis.grid(alpha=0.25)

    def _mark_claims(self, axis: Axes, claims: list[Claim]) -> None:
        marked_count = 0
        for claim in claims:
            if claim.timestamp_s is None:
                continue
            axis.axvline(
                claim.timestamp_s,
                color="#00838f",
                linestyle="-.",
                alpha=0.8,
                label="Claim" if marked_count == 0 else "_nolegend_",
            )
            axis.text(
                claim.timestamp_s,
                0.98,
                claim.claim_id,
                transform=axis.get_xaxis_transform(),
                rotation=90,
                va="top",
                ha="right",
                fontsize=8,
                color="#006064",
            )
            marked_count += 1


def _autonomy_value(value: str | None) -> float:
    if value is None:
        return 0.0
    return 1.0 if value.strip().lower() in {"1", "true", "on", "active", "engaged", "autonomous"} else 0.0


def _save_figure(figure: Figure, path: Path) -> Path:
    figure.tight_layout()
    figure.savefig(path, dpi=120, metadata={"Software": "Incident Analysis Backend"})
    plt.close(figure)
    return path


def _combined_legend(first: Axes, second: Axes) -> None:
    lines = [
        line
        for line in [*first.get_lines(), *second.get_lines()]
        if not line.get_label().startswith("_")
    ]
    first.legend(lines, [line.get_label() for line in lines], loc="best")


def _deduplicated_legend(axis: Axes) -> None:
    handles, labels = axis.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=False))
    axis.legend(unique.values(), unique.keys(), loc="best")
