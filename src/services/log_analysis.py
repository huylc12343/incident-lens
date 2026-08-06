"""Deterministic CSV slicing and vehicle-signal analysis."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.models.incidents import IncidentWindow, LogAnalysisResult, LogEvent, LogEvidenceSummary

TIMESTAMP_ALIASES = ("timestamp_s", "timestamp", "time_s", "time")
SPEED_ALIASES = ("speed_kmh", "vehicle_speed_kmh", "speed")
ACCELERATION_ALIASES = ("acceleration_mps2", "accel_mps2", "acceleration")
BRAKE_ALIASES = ("brake", "brake_pedal", "brake_pressure")
THROTTLE_ALIASES = ("throttle", "throttle_pedal")
STEERING_ALIASES = ("steering_angle", "steer", "steering")
AUTONOMY_ALIASES = ("autonomous_state", "autonomy_state", "autopilot", "automated_driving")
DISENGAGEMENT_ALIASES = ("disengagement", "driver_takeover", "manual_takeover")
WARNING_ALIASES = ("warning_code", "warning", "warnings")
ERROR_ALIASES = ("error_code", "error", "errors")
LogEventType = Literal["brake_rise", "steering_change", "disengagement", "warning", "error"]


class LogAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LogRecord:
    timestamp_s: float
    values: dict[str, str]

    def number(self, aliases: tuple[str, ...]) -> float | None:
        key = _first_present(self.values, aliases)
        if key is None or not self.values[key].strip():
            return None
        try:
            return float(self.values[key])
        except ValueError as exc:
            raise LogAnalysisError(
                "LOG_VALUE_INVALID",
                f"signal {key} is not numeric at {self.timestamp_s}s",
            ) from exc

    def text(self, aliases: tuple[str, ...]) -> str | None:
        key = _first_present(self.values, aliases)
        if key is None:
            return None
        value = self.values[key].strip()
        return value or None


class LogAnalysisService:
    def __init__(
        self,
        *,
        brake_rise_threshold: float = 0.3,
        steering_change_threshold: float = 10.0,
    ) -> None:
        if brake_rise_threshold < 0 or steering_change_threshold < 0:
            raise ValueError("log thresholds must be non-negative")
        self._brake_rise_threshold = brake_rise_threshold
        self._steering_change_threshold = steering_change_threshold

    def analyze(
        self,
        log_uri: str,
        output_uri: str,
        *,
        window: IncidentWindow,
    ) -> LogAnalysisResult:
        fieldnames, records = load_log_records(log_uri)
        sliced = [record for record in records if window.t_start <= record.timestamp_s <= window.t_end]
        if not sliced:
            raise LogAnalysisError("LOG_WINDOW_EMPTY", "log contains no rows in the incident window")
        output = Path(output_uri).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_log_slice(output, fieldnames, sliced)

        speed = [record.number(SPEED_ALIASES) for record in sliced]
        brake = [record.number(BRAKE_ALIASES) for record in sliced]
        steering = [record.number(STEERING_ALIASES) for record in sliced]
        acceleration = _acceleration_series(sliced, speed)
        events = self._detect_events(sliced, brake, steering)
        warnings = _unique_text_values(sliced, WARNING_ALIASES)
        errors = _unique_text_values(sliced, ERROR_ALIASES)

        speed_values = [value for value in speed if value is not None]
        brake_values = [value for value in brake if value is not None]
        acceleration_values = [value for value in acceleration if value is not None]
        steering_changes = _changes(steering)
        max_deceleration = min(acceleration_values) if acceleration_values else None
        if max_deceleration is not None and max_deceleration > 0:
            max_deceleration = 0.0
        metrics: dict[str, float | int | str | bool | None] = {
            "speed_start": speed_values[0] if speed_values else None,
            "speed_end": speed_values[-1] if speed_values else None,
            "speed_min": min(speed_values) if speed_values else None,
            "speed_max": max(speed_values) if speed_values else None,
            "max_deceleration": max_deceleration,
            "max_brake": max(brake_values) if brake_values else None,
            "brake_rise_time": _first_event_time(events, "brake_rise"),
            "max_steering_change": max(steering_changes, default=None),
            "steering_change_time": _first_event_time(events, "steering_change"),
            "disengagement_time": _first_event_time(events, "disengagement"),
        }
        metric_evidence_ids = [
            _metric_evidence_id(name) for name, value in metrics.items() if value is not None
        ]
        summary = LogEvidenceSummary(
            summary=_build_summary(window, metrics, warnings, errors),
            metrics=metrics,
            events=[event.model_dump(mode="json") for event in events],
            evidence_ids=[*metric_evidence_ids, *(event.evidence_id for event in events)],
            warnings=warnings,
            errors=errors,
        )
        return LogAnalysisResult(
            log_slice_uri=str(output),
            summary=summary,
            events=events,
            row_count=len(sliced),
            signal_names=fieldnames,
        )

    def _detect_events(
        self,
        records: list[LogRecord],
        brake: list[float | None],
        steering: list[float | None],
    ) -> list[LogEvent]:
        events: list[LogEvent] = []
        for index in range(1, len(records)):
            current = records[index]
            if brake[index] is not None and brake[index - 1] is not None:
                brake_delta = brake[index] - brake[index - 1]
                if brake_delta >= self._brake_rise_threshold:
                    events.append(
                        _event(
                            "brake_rise",
                            current.timestamp_s,
                            "brake",
                            brake[index],
                            brake[index - 1],
                            f"brake increased by {brake_delta:.3f}",
                        )
                    )
            if steering[index] is not None and steering[index - 1] is not None:
                steering_delta = abs(steering[index] - steering[index - 1])
                if steering_delta >= self._steering_change_threshold:
                    events.append(
                        _event(
                            "steering_change",
                            current.timestamp_s,
                            "steering",
                            steering[index],
                            steering[index - 1],
                            f"absolute steering change {steering_delta:.3f}",
                        )
                    )

        disengagement_time = _find_disengagement(records)
        if disengagement_time is not None:
            events.append(
                _event(
                    "disengagement",
                    disengagement_time,
                    "autonomy_state",
                    False,
                    True,
                    "autonomous driving disengaged or driver takeover detected",
                )
            )
        for record in records:
            warning = record.text(WARNING_ALIASES)
            if warning and _is_active_text(warning):
                events.append(_event("warning", record.timestamp_s, "warning", warning, None, warning))
            error = record.text(ERROR_ALIASES)
            if error and _is_active_text(error):
                events.append(_event("error", record.timestamp_s, "error", error, None, error))
        return sorted(events, key=lambda event: (event.timestamp_s, event.event_type, event.event_id))


def load_log_records(log_uri: str) -> tuple[list[str], list[LogRecord]]:
    source = Path(log_uri).resolve()
    if not source.is_file():
        raise LogAnalysisError("LOG_NOT_FOUND", f"log file does not exist: {log_uri}")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                raise LogAnalysisError("LOG_SCHEMA_INVALID", "log CSV has no header")
            fieldnames = [_normalize_field(name) for name in reader.fieldnames]
            if len(fieldnames) != len(set(fieldnames)):
                raise LogAnalysisError("LOG_SCHEMA_INVALID", "log CSV contains duplicate columns")
            timestamp_key = next((name for name in TIMESTAMP_ALIASES if name in fieldnames), None)
            if timestamp_key is None:
                raise LogAnalysisError("LOG_TIMESTAMP_MISSING", "log CSV has no supported timestamp column")
            records = []
            for row_number, raw_row in enumerate(reader, start=2):
                values = {
                    _normalize_field(key): (value or "").strip() for key, value in raw_row.items() if key is not None
                }
                try:
                    timestamp_s = float(values[timestamp_key])
                except (KeyError, ValueError) as exc:
                    raise LogAnalysisError(
                        "LOG_TIMESTAMP_INVALID",
                        f"invalid timestamp at CSV row {row_number}",
                    ) from exc
                if timestamp_s < 0:
                    raise LogAnalysisError("LOG_TIMESTAMP_INVALID", "log timestamps must be non-negative")
                records.append(LogRecord(timestamp_s=timestamp_s, values=values))
    except UnicodeError as exc:
        raise LogAnalysisError("LOG_ENCODING_INVALID", "log CSV must be UTF-8") from exc
    if not records:
        raise LogAnalysisError("LOG_EMPTY", "log CSV contains no data rows")
    timestamps = [record.timestamp_s for record in records]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise LogAnalysisError("LOG_TIMESTAMP_ORDER_INVALID", "log timestamps must be unique and increasing")
    return fieldnames, records


def acceleration_series(records: list[LogRecord]) -> list[float | None]:
    speed = [record.number(SPEED_ALIASES) for record in records]
    return _acceleration_series(records, speed)


def numeric_series(records: list[LogRecord], aliases: tuple[str, ...]) -> list[float | None]:
    return [record.number(aliases) for record in records]


def _acceleration_series(
    records: list[LogRecord],
    speed: list[float | None],
) -> list[float | None]:
    explicit = [record.number(ACCELERATION_ALIASES) for record in records]
    if any(value is not None for value in explicit):
        return explicit
    acceleration: list[float | None] = [None]
    for index in range(1, len(records)):
        previous_speed = speed[index - 1]
        current_speed = speed[index]
        delta_t = records[index].timestamp_s - records[index - 1].timestamp_s
        if previous_speed is None or current_speed is None or delta_t <= 0:
            acceleration.append(None)
        else:
            acceleration.append(((current_speed - previous_speed) / 3.6) / delta_t)
    return acceleration


def _write_log_slice(output: Path, fieldnames: list[str], records: list[LogRecord]) -> None:
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.values.get(field, "") for field in fieldnames})


def _event(
    event_type: LogEventType,
    timestamp_s: float,
    signal: str,
    value: float | int | str | bool | None,
    previous_value: float | int | str | bool | None,
    details: str,
) -> LogEvent:
    timestamp_key = f"{timestamp_s:.3f}".rstrip("0").rstrip(".")
    event_id = f"log-event:{timestamp_key}:{event_type}"
    return LogEvent(
        event_id=event_id,
        event_type=event_type,
        timestamp_s=timestamp_s,
        signal=signal,
        value=value,
        previous_value=previous_value,
        details=details,
        evidence_id=f"log-evidence:{timestamp_key}:{event_type}",
    )


def _metric_evidence_id(name: str) -> str:
    return f"log-metric:{name}"


def _build_summary(
    window: IncidentWindow,
    metrics: dict[str, float | int | str | bool | None],
    warnings: list[str],
    errors: list[str],
) -> str:
    statements = [f"Log được cắt trong khoảng [{window.t_start:g}, {window.t_end:g}] giây."]
    speed_names = (
        ("speed_start", "Tốc độ đầu"),
        ("speed_end", "tốc độ cuối"),
        ("speed_min", "nhỏ nhất"),
        ("speed_max", "lớn nhất"),
    )
    speeds = [f"{label} {metrics[name]:g} km/h" for name, label in speed_names if metrics[name] is not None]
    if speeds:
        statements.append(", ".join(speeds) + ".")
    if metrics["max_deceleration"] is not None:
        statements.append(f"Mức giảm tốc lớn nhất là {abs(float(metrics['max_deceleration'])):.3f} m/s².")
    if metrics["max_brake"] is not None:
        statements.append(f"Giá trị brake lớn nhất là {metrics['max_brake']:g}.")
    if metrics["brake_rise_time"] is not None:
        statements.append(f"Brake tăng mạnh lần đầu tại {metrics['brake_rise_time']:g} giây.")
    else:
        statements.append("Không phát hiện brake tăng mạnh trong cửa sổ sự cố.")
    if metrics["max_steering_change"] is not None:
        steering = f"Thay đổi steering angle lớn nhất là {metrics['max_steering_change']:g}"
        if metrics["steering_change_time"] is not None:
            steering += f" tại {metrics['steering_change_time']:g} giây"
        statements.append(steering + ".")
    if metrics["disengagement_time"] is not None:
        statements.append(f"Disengagement hoặc tài xế tiếp quản tại {metrics['disengagement_time']:g} giây.")
    statements.append(f"Warning: {', '.join(warnings)}." if warnings else "Không có warning trong đoạn log.")
    statements.append(f"Error: {', '.join(errors)}." if errors else "Không có error trong đoạn log.")
    return " ".join(statements)


def _changes(values: list[float | None]) -> list[float]:
    return [
        abs(current - previous)
        for previous, current in zip(values, values[1:], strict=False)
        if previous is not None and current is not None
    ]


def _find_disengagement(records: list[LogRecord]) -> float | None:
    for record in records:
        direct = record.text(DISENGAGEMENT_ALIASES)
        if direct is not None and _as_bool(direct):
            return record.timestamp_s
    autonomy = [record.text(AUTONOMY_ALIASES) for record in records]
    for index in range(1, len(records)):
        if autonomy[index - 1] is not None and autonomy[index] is not None:
            if _as_bool(autonomy[index - 1]) and not _as_bool(autonomy[index]):
                return records[index].timestamp_s
    return None


def _unique_text_values(records: list[LogRecord], aliases: tuple[str, ...]) -> list[str]:
    values = [record.text(aliases) for record in records]
    return list(dict.fromkeys(value for value in values if value and _is_active_text(value)))


def _first_event_time(events: list[LogEvent], event_type: str) -> float | None:
    return next((event.timestamp_s for event in events if event.event_type == event_type), None)


def _first_present(values: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    return next((alias for alias in aliases if alias in values), None)


def _normalize_field(value: str) -> str:
    return value.lstrip("\ufeff").strip().lower()


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "active", "engaged", "autonomous"}


def _is_active_text(value: str) -> bool:
    return value.strip().lower() not in {"", "0", "false", "none", "null", "ok", "normal"}
