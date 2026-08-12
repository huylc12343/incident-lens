"""Deterministic CSV slicing and vehicle-signal analysis."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.models.incidents import (
    Claim,
    ClaimLogEvidence,
    ClaimLogSummary,
    IncidentWindow,
    LogAnalysisResult,
    LogEvent,
    LogEvidenceSummary,
)

TIMESTAMP_ALIASES = ("timestamp_s", "timestamp", "time_s", "time_sec", "time")
SPEED_ALIASES = ("speed_kmh", "ego_speed_kmh", "vehicle_speed_kmh", "speed")
ACCELERATION_ALIASES = ("acceleration_mps2", "accel_mps2", "acceleration")
BRAKE_ALIASES = ("brake", "ego_brake", "brake_pedal", "brake_pressure")
THROTTLE_ALIASES = ("throttle", "ego_throttle", "throttle_pedal")
STEERING_ALIASES = ("steering_angle", "steer", "ego_steer", "steering")
CAMERA_FRAME_ALIASES = ("camera_frame",)
CLAIM_SPEED_ALIASES = ("speed_kmh", "ego_speed_kmh")
CLAIM_THROTTLE_ALIASES = ("throttle", "ego_throttle")
CLAIM_BRAKE_ALIASES = ("brake", "ego_brake")
CLAIM_STEER_ALIASES = ("steer", "ego_steer")
ACCELERATION_X_ALIASES = ("acceleration_x",)
ACCELERATION_Y_ALIASES = ("acceleration_y",)
ACCELERATION_Z_ALIASES = ("acceleration_z",)
YAW_ALIASES = ("yaw",)
PITCH_ALIASES = ("pitch",)
ROLL_ALIASES = ("roll",)
Z_ALIASES = ("z",)
AUTONOMY_ALIASES = ("autonomous_state", "autonomy_state", "autopilot", "automated_driving")
DISENGAGEMENT_ALIASES = ("disengagement", "driver_takeover", "manual_takeover")
WARNING_ALIASES = ("warning_code", "warning", "warnings")
ERROR_ALIASES = ("error_code", "error", "errors")
LogEventType = Literal["brake_rise", "steering_change", "disengagement", "warning", "error"]

NEAR_STOPPED_SPEED_KMH = 1.0
STRONG_SPEED_DROP_KMH = 10.0
CONTROL_ZERO_THRESHOLD = 0.01
CONTROL_CHANGE_THRESHOLD = 0.1


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
        available_metrics = {name: value for name, value in metrics.items() if value is not None}
        summary = LogEvidenceSummary(
            summary=_build_summary(window, metrics, warnings, errors),
            metrics=available_metrics,
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


def build_claim_log_summaries(
    log_uri: str,
    claims: list[Claim],
    *,
    timestamp_tolerance_s: float,
    sample_radius: int = 3,
) -> list[ClaimLogSummary]:
    """Compute one deterministic, narrow log summary around each claim timestamp."""
    if timestamp_tolerance_s < 0 or sample_radius < 0:
        raise ValueError("timestamp_tolerance_s and sample_radius must be non-negative")
    _, records = load_log_records(log_uri)
    return [
        _claim_log_summary(
            records,
            claim,
            timestamp_tolerance_s=timestamp_tolerance_s,
            sample_radius=sample_radius,
        )
        for claim in claims
    ]


def _claim_log_summary(
    records: list[LogRecord],
    claim: Claim,
    *,
    timestamp_tolerance_s: float,
    sample_radius: int,
) -> ClaimLogSummary:
    if claim.timestamp_s is None:
        return ClaimLogSummary(
            claim_id=claim.claim_id,
            summary=(
                "Đối chiếu thời gian\n"
                "Claim timestamp: Không có\n"
                "Trong tolerance: **Không**\n\n"
                "Log có thể kiểm tra\n"
                "Không thể chọn cửa sổ log vì claim không có timestamp."
            ),
        )
    nearest_index = min(range(len(records)), key=lambda index: abs(records[index].timestamp_s - claim.timestamp_s))
    nearest = records[nearest_index]
    distance = abs(nearest.timestamp_s - claim.timestamp_s)
    start = max(0, nearest_index - sample_radius)
    end = min(len(records), nearest_index + sample_radius + 1)
    samples = records[start:end]
    within_tolerance = distance <= timestamp_tolerance_s
    metrics, available_signals = _claim_metrics(samples, claim.timestamp_s)
    evidence = [
        ClaimLogEvidence(
            evidence_id=_row_evidence_id(record.timestamp_s),
            timestamp_s=record.timestamp_s,
            camera_frame=record.text(CAMERA_FRAME_ALIASES),
        )
        for record in samples
    ]
    allowed_evidence_ids = [
        item.evidence_id
        for item in evidence
        if abs(item.timestamp_s - claim.timestamp_s) <= timestamp_tolerance_s
    ]
    return ClaimLogSummary(
        claim_id=claim.claim_id,
        claim_timestamp_s=claim.timestamp_s,
        nearest_timestamp_s=nearest.timestamp_s,
        timestamp_distance_s=distance,
        within_tolerance=within_tolerance,
        sample_start_s=samples[0].timestamp_s,
        sample_end_s=samples[-1].timestamp_s,
        sample_count=len(samples),
        available_signals=available_signals,
        metrics=metrics,
        evidence=evidence,
        allowed_evidence_ids=allowed_evidence_ids,
        summary=_build_claim_summary(
            claim.timestamp_s,
            nearest.timestamp_s,
            distance,
            within_tolerance,
            samples,
            metrics,
            available_signals,
        ),
    )


def _claim_metrics(
    records: list[LogRecord],
    claim_timestamp_s: float,
) -> tuple[dict[str, dict[str, float | int | str | bool | None]], list[str]]:
    signals = {
        "speed_kmh": numeric_series(records, CLAIM_SPEED_ALIASES),
        "throttle": numeric_series(records, CLAIM_THROTTLE_ALIASES),
        "brake": numeric_series(records, CLAIM_BRAKE_ALIASES),
        "steer": numeric_series(records, CLAIM_STEER_ALIASES),
        "acceleration_x": numeric_series(records, ACCELERATION_X_ALIASES),
        "acceleration_y": numeric_series(records, ACCELERATION_Y_ALIASES),
        "acceleration_z": numeric_series(records, ACCELERATION_Z_ALIASES),
        "yaw": numeric_series(records, YAW_ALIASES),
        "pitch": numeric_series(records, PITCH_ALIASES),
        "roll": numeric_series(records, ROLL_ALIASES),
        "z": numeric_series(records, Z_ALIASES),
    }
    metrics: dict[str, dict[str, float | int | str | bool | None]] = {}
    speed = _transition_metrics(records, signals["speed_kmh"], include_extrema=True)
    if speed:
        speed.update(_max_deceleration(records, signals["speed_kmh"]))
        speed.update(_acceleration_at_timestamp(records, signals["speed_kmh"], claim_timestamp_s))
        metrics["speed_kmh"] = speed
    brake = _transition_metrics(records, signals["brake"], include_extrema=True)
    if brake:
        brake.update(_largest_change(records, signals["brake"], positive_only=True, label="strongest_increase"))
        metrics["brake"] = brake
    throttle = _transition_metrics(records, signals["throttle"])
    if throttle:
        metrics["throttle"] = throttle
    steer = _transition_metrics(records, signals["steer"], include_extrema=True)
    if steer:
        steer.update(_largest_change(records, signals["steer"], label="max_change"))
        metrics["steer"] = steer
    acceleration = _acceleration_magnitude_metrics(records, signals)
    if acceleration:
        metrics["acceleration_magnitude"] = acceleration
    yaw = _angle_metrics(records, signals["yaw"])
    if yaw:
        metrics["yaw"] = yaw
    for name in ("pitch", "roll"):
        angle = _transition_metrics(records, signals[name], include_extrema=True)
        if angle:
            angle["range"] = float(angle["max"]) - float(angle["min"])
            angle.update(_largest_change(records, signals[name], label="max_change"))
            metrics[name] = angle
    z_metrics = _transition_metrics(records, signals["z"], include_extrema=True)
    if z_metrics:
        metrics["z"] = z_metrics
    metrics = {
        name: {metric_name: value for metric_name, value in values.items() if value is not None}
        for name, values in metrics.items()
    }
    available = ["timestamp"]
    if any(record.text(CAMERA_FRAME_ALIASES) is not None for record in records):
        available.append("camera_frame")
    available.extend(name for name, values in signals.items() if any(value is not None for value in values))
    return metrics, available


def _transition_metrics(
    records: list[LogRecord],
    values: list[float | None],
    *,
    include_extrema: bool = False,
) -> dict[str, float | int | str | bool | None]:
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if not present:
        return {}
    first_index, first = present[0]
    last_index, last = present[-1]
    output: dict[str, float | int | str | bool | None] = {
        "start": first,
        "start_timestamp_s": records[first_index].timestamp_s,
        "end": last,
        "end_timestamp_s": records[last_index].timestamp_s,
        "delta": last - first,
    }
    if include_extrema:
        min_index, minimum = min(present, key=lambda item: item[1])
        max_index, maximum = max(present, key=lambda item: item[1])
        output.update(
            {
                "min": minimum,
                "min_timestamp_s": records[min_index].timestamp_s,
                "max": maximum,
                "max_timestamp_s": records[max_index].timestamp_s,
            }
        )
    return output


def _max_deceleration(
    records: list[LogRecord],
    values: list[float | None],
) -> dict[str, float | int | str | bool | None]:
    candidates = []
    for index in range(1, len(records)):
        previous, current = values[index - 1], values[index]
        delta_t = records[index].timestamp_s - records[index - 1].timestamp_s
        if previous is not None and current is not None and delta_t > 0:
            candidates.append(( ((current - previous) / 3.6) / delta_t, records[index].timestamp_s))
    if not candidates:
        return {"max_deceleration": None, "max_deceleration_timestamp_s": None}
    value, timestamp_s = min(candidates)
    if value >= 0:
        return {"max_deceleration": 0.0, "max_deceleration_timestamp_s": None}
    return {"max_deceleration": value, "max_deceleration_timestamp_s": timestamp_s}


def _acceleration_at_timestamp(
    records: list[LogRecord],
    speed_values: list[float | None],
    claim_timestamp_s: float,
) -> dict[str, float | int | str | bool | None]:
    acceleration = _acceleration_series(records, speed_values)
    candidates = [
        (abs(record.timestamp_s - claim_timestamp_s), record.timestamp_s, value)
        for record, value in zip(records, acceleration, strict=True)
        if value is not None
    ]
    if not candidates:
        return {"acceleration_at_claim": None, "acceleration_timestamp_s": None}
    _, timestamp_s, value = min(candidates, key=lambda item: item[0])
    return {"acceleration_at_claim": value, "acceleration_timestamp_s": timestamp_s}


def _largest_change(
    records: list[LogRecord],
    values: list[float | None],
    *,
    label: str,
    positive_only: bool = False,
) -> dict[str, float | int | str | bool | None]:
    candidates = []
    for index in range(1, len(records)):
        previous, current = values[index - 1], values[index]
        if previous is None or current is None:
            continue
        change = current - previous
        score = change if positive_only else abs(change)
        candidates.append((score, change, records[index].timestamp_s))
    if not candidates:
        return {label: None, f"{label}_timestamp_s": None}
    score, change, timestamp_s = max(candidates, key=lambda item: item[0])
    if positive_only and score <= 0:
        return {label: 0.0, f"{label}_timestamp_s": None}
    return {label: change if positive_only else abs(change), f"{label}_timestamp_s": timestamp_s}


def _acceleration_magnitude_metrics(
    records: list[LogRecord],
    signals: dict[str, list[float | None]],
) -> dict[str, float | int | str | bool | None]:
    magnitudes = []
    for index, values in enumerate(
        zip(
            signals["acceleration_x"],
            signals["acceleration_y"],
            signals["acceleration_z"],
            strict=True,
        )
    ):
        if all(value is not None for value in values):
            magnitude = math.sqrt(sum(float(value) ** 2 for value in values))
            magnitudes.append((index, magnitude))
    if not magnitudes:
        return {}
    peak_index, peak = max(magnitudes, key=lambda item: item[1])
    return {"peak": peak, "peak_timestamp_s": records[peak_index].timestamp_s}


def _angle_metrics(
    records: list[LogRecord],
    values: list[float | None],
) -> dict[str, float | int | str | bool | None]:
    output = _transition_metrics(records, values)
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if not present:
        return {}
    output["delta_wrapped"] = _wrapped_angle_delta(present[-1][1] - present[0][1])
    changes = [
        (abs(_wrapped_angle_delta(current - previous)), records[index].timestamp_s)
        for index, (previous, current) in enumerate(zip(values, values[1:], strict=False), start=1)
        if previous is not None and current is not None
    ]
    if changes:
        output["max_change"] = max(changes, key=lambda item: item[0])[0]
        output["max_change_timestamp_s"] = max(changes, key=lambda item: item[0])[1]
    else:
        output.update({"max_change": None, "max_change_timestamp_s": None})
    return output


def _wrapped_angle_delta(delta: float) -> float:
    return (delta + 180.0) % 360.0 - 180.0


def _row_evidence_id(timestamp_s: float) -> str:
    timestamp_key = f"{timestamp_s:.6f}".rstrip("0").rstrip(".")
    return f"log-row:{timestamp_key}"


def _build_claim_summary(
    claim_timestamp_s: float,
    nearest_timestamp_s: float,
    distance_s: float,
    within_tolerance: bool,
    records: list[LogRecord],
    metrics: dict[str, dict[str, float | int | str | bool | None]],
    available_signals: list[str],
) -> str:
    sections = [
        "\n".join(
            [
                "Đối chiếu thời gian",
                f"Claim timestamp: {_format_timestamp_s(claim_timestamp_s)}s",
                f"Mẫu log gần nhất: {_format_timestamp_s(nearest_timestamp_s)}s",
                f"Log window: {_format_timestamp_s(records[0].timestamp_s)}s → "
                f"{_format_timestamp_s(records[-1].timestamp_s)}s",
                f"Số mẫu log trong cửa sổ: {len(records)}",
                f"Số mẫu đại diện tối đa trong mỗi bảng: {min(len(records), 4)}",
                f"Sai lệch timestamp: {_format_timestamp_s(distance_s)}s",
                f"Trong tolerance: **{'Có' if within_tolerance else 'Không'}**",
            ]
        ),
        "\n".join(
            [
                "Log có thể kiểm tra",
                *_available_signal_statements(available_signals, records),
            ]
        ),
    ]

    speed = metrics.get("speed_kmh")
    if speed:
        speed_lines = [
            "Chuyển động",
            f"Tốc độ tại giây thứ {_second_label(records[0].timestamp_s)}: {float(speed['start']):g} km/h",
            f"Tốc độ tại giây thứ {_second_label(records[-1].timestamp_s)}: {float(speed['end']):g} km/h",
            f"Tốc độ nhỏ nhất: {float(speed['min']):g} km/h",
            f"Tốc độ lớn nhất: {float(speed['max']):g} km/h",
            "Tốc độ — các mẫu đại diện phân bố đều:",
            *_representative_signal_table(records, CLAIM_SPEED_ALIASES, "Speed (km/h)"),
        ]
        speed_lines.extend(_derived_speed_states(speed))
        sections.append("\n".join(speed_lines))

    brake = metrics.get("brake")
    throttle = metrics.get("throttle")
    if brake or throttle or (speed and speed.get("max_deceleration") is not None):
        control_lines = ["Điều khiển"]
        if brake:
            control_lines.extend(
                [
                    _brake_statement(brake),
                    "Brake — các mẫu đại diện phân bố đều:",
                    *_representative_signal_table(records, CLAIM_BRAKE_ALIASES, "Brake"),
                ]
            )
        if throttle:
            control_lines.extend(
                [
                    _throttle_statement(throttle),
                    "Throttle — các mẫu đại diện phân bố đều:",
                    *_representative_signal_table(records, CLAIM_THROTTLE_ALIASES, "Throttle"),
                ]
            )
        if speed and speed.get("acceleration_at_claim") is not None:
            acceleration_timestamp = float(speed["acceleration_timestamp_s"])
            control_lines.append(
                f"Gia tốc tại {_format_timestamp_s(acceleration_timestamp)}s: "
                f"{float(speed['acceleration_at_claim']):g} m/s²"
            )
        if speed and speed.get("max_deceleration_timestamp_s") is not None:
            control_lines.append(
                f"Giảm tốc cực đại trong cửa sổ: {float(speed['max_deceleration']):g} m/s² "
                f"tại {_format_timestamp_s(float(speed['max_deceleration_timestamp_s']))}s"
            )
        sections.append("\n".join(control_lines))

    steer = metrics.get("steer")
    yaw = metrics.get("yaw")
    if steer or yaw:
        direction_lines = ["Hướng xe"]
        if yaw:
            yaw_change = abs(float(yaw["delta_wrapped"]))
            direction_lines.append(f"Yaw thay đổi: {yaw_change:g}°")
        if steer:
            steer_change = abs(float(steer.get("max_change", 0)))
            direction_lines.extend(
                [
                    f"Steering thay đổi lớn nhất: {steer_change:g}",
                    _steering_direction_statement(records, claim_timestamp_s),
                    "Steering — các mẫu đại diện phân bố đều:",
                    *_representative_signal_table(records, CLAIM_STEER_ALIASES, "Steering"),
                ]
            )
        sections.append("\n".join(direction_lines))

    if not within_tolerance:
        sections.append(
            "Kết luận ghép thời gian\n"
            "Mẫu gần nhất nằm ngoài tolerance; không dùng log để xác nhận hoặc bác bỏ claim."
        )
    return "\n\n".join(sections)


def _format_timestamp_s(value: float) -> str:
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted if "." in formatted else f"{formatted}.0"


def _second_label(value: float) -> str:
    return f"{value:g}"


def _representative_signal_table(
    records: list[LogRecord],
    aliases: tuple[str, ...],
    value_label: str,
    max_samples: int = 4,
) -> list[str]:
    if max_samples <= 0:
        raise ValueError("max_samples must be positive")
    sample_count = min(len(records), max_samples)
    if sample_count == 1:
        selected = records[:1]
    else:
        last_index = len(records) - 1
        indexes = [round(position * last_index / (sample_count - 1)) for position in range(sample_count)]
        selected = [records[index] for index in indexes]
    rows = [
        (record.timestamp_s, value)
        for record in selected
        if (value := record.number(aliases)) is not None
    ]
    return [
        f"| Timestamp | {value_label} |",
        "| --------: | -----------: |",
        *(f"| {_format_timestamp_s(timestamp_s)}s | {value:g} |" for timestamp_s, value in rows),
    ]


def _available_signal_statements(
    available_signals: list[str],
    records: list[LogRecord],
) -> list[str]:
    signal_set = set(available_signals)
    statements = [
        f"timestamp [{_format_timestamp_s(records[0].timestamp_s)}s, "
        f"{_format_timestamp_s(records[-1].timestamp_s)}s]: mốc thời gian dùng để ghép claim;"
    ]
    if "speed_kmh" in signal_set:
        statements.extend(
            [
                "trạng thái chuyển động: được code suy ra từ tốc độ;",
                "tốc độ [0, +∞) km/h: 0 là đứng yên, giá trị lớn hơn 0 là xe đang di chuyển;",
                "gia tốc (-∞, +∞) m/s²: âm là giảm tốc, dương là tăng tốc;",
            ]
        )
    if "brake" in signal_set:
        statements.append("brake [0, 1]: 0 là không phanh, 1 là đạp phanh hết cỡ;")
    if "throttle" in signal_set:
        statements.append("throttle [0, 1]: 0 là không ga, 1 là đạp ga hết cỡ;")
    if "steer" in signal_set:
        statements.extend(
            [
                "steering [-1, 1]: steering < 0 rẽ trái, steering = 0 đi thẳng, steering > 0 rẽ phải;",
                "hướng xe: được code suy ra từ dấu của steering tại timestamp claim.",
            ]
        )
    if "yaw" in signal_set:
        statements.append("hướng xe: yaw được đo bằng độ và so sánh theo góc có wrap.")
    if len(statements) == 1:
        statements.append("không có tín hiệu chuyển động hoặc điều khiển được hỗ trợ.")
    return statements


def _derived_speed_states(
    speed: dict[str, float | int | str | bool | None],
) -> list[str]:
    start = float(speed["start"])
    end = float(speed["end"])
    delta = float(speed["delta"])
    statements = []
    if end <= NEAR_STOPPED_SPEED_KMH:
        statements.append("Trạng thái cuối cửa sổ: gần như đứng yên.")
    else:
        statements.append("Trạng thái cuối cửa sổ: xe vẫn đang di chuyển.")
    if delta <= -STRONG_SPEED_DROP_KMH:
        statements.extend(
            [
                f"Xe giảm từ {start:g} km/h xuống {end:g} km/h.",
                "Xe đã **giảm tốc mạnh** trong cửa sổ.",
            ]
        )
    elif delta < 0:
        statements.append("Xe đã giảm tốc trong cửa sổ.")
    elif delta > 0:
        statements.append("Xe đã tăng tốc trong cửa sổ.")
    else:
        statements.append("Tốc độ không đổi trong cửa sổ.")
    return statements


def _brake_statement(
    metric: dict[str, float | int | str | bool | None],
) -> str:
    start = float(metric["start"])
    end = float(metric["end"])
    maximum = float(metric["max"])
    state = "có sự ấn phanh trong cửa sổ" if maximum > CONTROL_ZERO_THRESHOLD else "không ghi nhận ấn phanh"
    return f"Brake: {start:g} → {end:g} => {state}."


def _throttle_statement(metric: dict[str, float | int | str | bool | None]) -> str:
    start = float(metric["start"])
    end = float(metric["end"])
    delta = float(metric["delta"])
    if delta < 0:
        state = "có sự nhả ga"
    elif delta > 0:
        state = "có sự tăng ga"
    else:
        state = "ga không thay đổi"
    if abs(delta) < CONTROL_CHANGE_THRESHOLD and delta != 0:
        state += ", mức thay đổi nhỏ"
    return f"Throttle: {start:g} → {end:g} => {state}."


def _steering_direction_statement(records: list[LogRecord], claim_timestamp_s: float) -> str:
    candidates = [
        (abs(record.timestamp_s - claim_timestamp_s), record.timestamp_s, record.number(CLAIM_STEER_ALIASES))
        for record in records
    ]
    _, timestamp_s, value = min(
        (item for item in candidates if item[2] is not None),
        key=lambda item: item[0],
    )
    steering = float(value)
    if steering > 0:
        state = "xe có xu hướng rẽ phải"
    elif steering < 0:
        state = "xe có xu hướng rẽ trái"
    else:
        state = "steering gần trung tâm"
    return f"Steering tại {_format_timestamp_s(timestamp_s)}s: {steering:g} => {state}."


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
