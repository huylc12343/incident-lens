"""Deterministic CSV slicing and vehicle-signal analysis."""

from __future__ import annotations

import csv
import math
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from src.models.incidents import (
    Claim,
    ClaimDerivedDynamics,
    ClaimDerivedDynamicsMetric,
    ClaimDynamicHint,
    ClaimLogEvidence,
    ClaimLogSummary,
    ClaimRawTelemetry,
    ClaimTelemetryDerived,
    ClaimTelemetrySnapshot,
    ClaimVerificationContext,
    DynamicHintSignal,
    LogAnalysisResult,
    LogEvent,
    LogEvidenceSummary,
    TelemetrySignalName,
)

TIMESTAMP_ALIASES = ("timestamp_s", "timestamp", "time_s", "time_sec", "time")
SPEED_ALIASES = ("speed_kmh", "ego_speed_kmh", "vehicle_speed_kmh", "speed")
ACCELERATION_ALIASES = ("acceleration_mps2", "accel_mps2", "acceleration")
BRAKE_ALIASES = ("brake", "ego_brake", "brake_pedal", "brake_pressure")
THROTTLE_ALIASES = ("throttle", "ego_throttle", "throttle_pedal")
STEERING_ALIASES = ("steering_angle", "steer", "ego_steer", "steering")
STEER_STRAIGHT_ABS_THRESHOLD = 0.1
CAMERA_FRAME_ALIASES = ("camera_frame",)
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
LogEventType = Literal[
    "brake_rise",
    "steering_change",
    "strong_steering_change",
    "strong_deceleration",
    "strong_acceleration",
    "extreme_acceleration",
    "disengagement",
    "warning",
    "error",
]

NEAR_STOPPED_SPEED_KMH = 1.0
STRONG_SPEED_DROP_KMH = 10.0
CONTROL_ZERO_THRESHOLD = 0.01
CONTROL_CHANGE_THRESHOLD = 0.1
ADAPTIVE_ROLLING_WINDOW = 20
ADAPTIVE_MIN_BASELINE_SAMPLES = 5
ADAPTIVE_EMA_ALPHA = 0.2
ADAPTIVE_ENTER_Z_SCORE = 3.0
ADAPTIVE_EXIT_Z_SCORE = 1.5
ADAPTIVE_MERGE_GAP_SAMPLES = 1
ADAPTIVE_MIN_SCALE = 0.1
ADAPTIVE_ACCELERATION_MIN_SCALE = 1.0
ROBUST_SCALE_NORMALIZER = 1.4826
MAX_LOG_ATTENTION_TIMESTAMPS = 12
# Trần số interval cho mỗi tín hiệu, để một kênh nhiễu không chiếm hết chỗ của kênh khác.
MAX_INTERVALS_PER_SIGNAL = 4
# Hai đợt cùng tín hiệu và cùng hướng cách nhau dưới ngưỡng này được gộp thành một interval.
MERGE_GAP_S = 0.3
# Interval ngắn hơn ngưỡng này được coi là spike và mở rộng thành cửa sổ tối thiểu.
MIN_INTERVAL_S = 0.2
# Nửa bề rộng cửa sổ tối thiểu, mở đối xứng quanh điểm peak của spike.
MIN_INTERVAL_PAD_S = 0.15
# Biến thiên nhỏ hơn ngưỡng này coi như đứng yên khi gom pha chuyển tiếp.
TRANSITION_EPSILON = 1e-6
# Số mẫu đứng yên tối đa được phép nằm giữa một pha chuyển tiếp mà không cắt pha.
TRANSITION_MAX_GAP_SAMPLES = 2
# Số mẫu tối thiểu để một đoạn gia tốc vượt ngưỡng vật lý được coi là pha kéo dài.
SUSTAINED_MIN_SAMPLES = 2
# Phần interval phải nằm trong cửa sổ quanh claim thì hint mới được gắn vào claim đó.
MIN_CLAIM_HINT_OVERLAP_RATIO = 0.5
PHYSICAL_MIN_BRAKE_RISE = 0.3
PHYSICAL_MIN_THROTTLE_DELTA = 0.2
PHYSICAL_MIN_BRAKE_DELTA_FOR_HINT = 0.5
PHYSICAL_MIN_STEERING_DELTA = 0.3
PHYSICAL_STRONG_DECELERATION_MPS2 = -5.0
PHYSICAL_STRONG_ACCELERATION_MPS2 = 4.0
PHYSICAL_EXTREME_ACCELERATION_MPS2 = 8.0
MAX_VERIFICATION_EVIDENCE_ROWS = 5

VERIFICATION_SIGNAL_ALIASES: dict[TelemetrySignalName, tuple[str, ...]] = {
    "speed_kmh": SPEED_ALIASES,
    "throttle": THROTTLE_ALIASES,
    "brake": BRAKE_ALIASES,
    "steer": STEERING_ALIASES,
}
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


@dataclass(frozen=True)
class AdaptiveChange:
    start_index: int
    end_index: int
    peak_index: int
    direction: Literal[-1, 1]
    peak_z_score: float
    previous_value: float
    value: float


@dataclass(frozen=True)
class AdaptiveObservation:
    """One sample scored against its rolling baseline, before episodes are assembled."""

    index: int
    score: float
    direction: Literal[-1, 1]
    previous_value: float
    value: float
    baseline_ready: bool


@dataclass(frozen=True)
class SignalInterval:
    """An anomalous stretch of one signal, kept as a time window instead of a single instant."""

    signal: DynamicHintSignal
    start_s: float
    end_s: float
    peak_timestamp_s: float
    # Prominence used only for ranking: adaptive episodes contribute their peak z-score,
    # physical detectors contribute ENTER_Z_SCORE scaled by how far past their gate they went.
    score: float
    peak_value: float
    # Value the signal moved from and to across the detected stretch, before any widening.
    start_value: float
    end_value: float
    direction: Literal[-1, 1]
    description: str


class LogAnalysisService:
    def analyze(
        self,
        log_uri: str,
        output_uri: str,
        *,
        video_duration_s: float | None = None,
    ) -> LogAnalysisResult:
        fieldnames, records = load_log_records(log_uri)
        sliced = _select_records(records, video_duration_s=video_duration_s)
        if not sliced:
            raise LogAnalysisError("LOG_WINDOW_EMPTY", "log contains no rows within the video duration")
        output = Path(output_uri).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_log_slice(output, fieldnames, sliced)

        speed = [record.number(SPEED_ALIASES) for record in sliced]
        brake = [record.number(BRAKE_ALIASES) for record in sliced]
        steering = [record.number(STEERING_ALIASES) for record in sliced]
        acceleration = _acceleration_series(sliced, speed)
        events = self._detect_events(sliced, brake, steering, acceleration)
        warnings = [
            *_unique_text_values(sliced, WARNING_ALIASES),
            *_anomaly_warnings(events),
        ]
        errors = _unique_text_values(sliced, ERROR_ALIASES)

        speed_values = [value for value in speed if value is not None]
        brake_values = [value for value in brake if value is not None]
        acceleration_values = [value for value in acceleration if value is not None]
        steering_changes = _changes(steering)
        min_acceleration_index = _series_extreme_index(acceleration, smallest=True)
        max_acceleration_index = _series_extreme_index(acceleration, smallest=False)
        extreme_acceleration_index = _series_extreme_abs_index(acceleration)
        max_deceleration = acceleration[min_acceleration_index] if min_acceleration_index is not None else None
        if max_deceleration is not None and max_deceleration > 0:
            max_deceleration = 0.0
        metrics: dict[str, float | int | str | bool | None] = {
            "speed_start": speed_values[0] if speed_values else None,
            "speed_end": speed_values[-1] if speed_values else None,
            "speed_min": min(speed_values) if speed_values else None,
            "speed_max": max(speed_values) if speed_values else None,
            "acceleration_min": min(acceleration_values) if acceleration_values else None,
            "acceleration_max": max(acceleration_values) if acceleration_values else None,
            "max_deceleration": max_deceleration,
            "max_brake": max(brake_values) if brake_values else None,
            "brake_rise_time": _first_event_time(events, "brake_rise"),
            "max_steering_change": max(steering_changes, default=None),
            "steering_change_time": _first_event_time(events, "steering_change"),
            "strong_steering_change_time": _first_event_time(events, "strong_steering_change"),
            "max_deceleration_time": _acceleration_time_if(
                sliced,
                acceleration,
                min_acceleration_index,
                lambda value: value <= PHYSICAL_STRONG_DECELERATION_MPS2,
            ),
            "max_acceleration_time": _acceleration_time_if(
                sliced,
                acceleration,
                max_acceleration_index,
                lambda value: value >= PHYSICAL_STRONG_ACCELERATION_MPS2,
            ),
            "max_absolute_acceleration_time": _acceleration_time_if(
                sliced,
                acceleration,
                extreme_acceleration_index,
                lambda value: abs(value) >= PHYSICAL_EXTREME_ACCELERATION_MPS2,
            ),
            "disengagement_time": _first_event_time(events, "disengagement"),
        }
        metric_evidence_ids = [
            _metric_evidence_id(name) for name, value in metrics.items() if value is not None
        ]
        available_metrics = {name: value for name, value in metrics.items() if value is not None}
        summary = LogEvidenceSummary(
            summary=_build_summary(
                start_s=sliced[0].timestamp_s,
                end_s=sliced[-1].timestamp_s,
                metrics=metrics,
                warnings=warnings,
                errors=errors,
            ),
            metrics=available_metrics,
            events=[event.model_dump(mode="json") for event in events],
            evidence_ids=[*metric_evidence_ids, *(event.evidence_id for event in events)],
            warnings=warnings,
            errors=errors,
        )
        return LogAnalysisResult(
            log_artifact_uri=str(output),
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
        acceleration: list[float | None],
    ) -> list[LogEvent]:
        events: list[LogEvent] = []
        for change in _adaptive_changes(brake, detect_delta=True):
            change = _representative_control_change(change, brake)
            if change.direction > 0 and _change_magnitude(change) >= PHYSICAL_MIN_BRAKE_RISE:
                events.append(_adaptive_event("brake_rise", records, "brake", change))
        for change in _adaptive_changes(steering, detect_delta=True):
            change = _representative_control_change(change, steering)
            if _change_magnitude(change) >= PHYSICAL_MIN_STEERING_DELTA:
                events.append(_adaptive_event("steering_change", records, "steering", change))
        for change in _adaptive_changes(
            acceleration,
            detect_delta=False,
            minimum_scale=ADAPTIVE_ACCELERATION_MIN_SCALE,
        ):
            change = _representative_acceleration_change(change, acceleration)
            event_type = _acceleration_event_type(change.value)
            if event_type is not None:
                events.append(_adaptive_event(event_type, records, "acceleration_mps2", change))

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


def _select_records(
    records: list[LogRecord],
    *,
    video_duration_s: float | None,
) -> list[LogRecord]:
    if video_duration_s is not None and video_duration_s <= 0:
        raise ValueError("video_duration_s must be positive")
    return [
        record
        for record in records
        if video_duration_s is None or record.timestamp_s <= video_duration_s
    ]


def build_verification_log_artifact(
    log_uri: str,
    output_uri: str,
    *,
    video_duration_s: float | None = None,
) -> str:
    """Persist all telemetry verification can sample within the video bounds."""
    fieldnames, records = load_log_records(log_uri)
    selected = _select_records(records, video_duration_s=video_duration_s)
    if not selected:
        raise LogAnalysisError(
            "LOG_VERIFICATION_WINDOW_EMPTY",
            "log contains no rows within the video duration",
        )

    output = Path(output_uri).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_log_slice(output, fieldnames, selected)
    return str(output)


def acceleration_series(records: list[LogRecord]) -> list[float | None]:
    speed = [record.number(SPEED_ALIASES) for record in records]
    return _acceleration_series(records, speed)


def build_log_attention_hint(log_uri: str, *, video_duration_s: float | None = None) -> str:
    """Return qualitative time windows that guide video attention without exposing telemetry values."""
    _, records = load_log_records(log_uri)
    if video_duration_s is not None:
        if video_duration_s <= 0:
            raise ValueError("video_duration_s must be positive")
        records = [record for record in records if record.timestamp_s <= video_duration_s]
    if not records:
        raise LogAnalysisError("LOG_WINDOW_EMPTY", "log contains no rows within the video duration")
    intervals = detect_signal_intervals(records, video_duration_s=video_duration_s)
    if not intervals:
        return ""
    lines = [
        f"- {_capitalize(interval_text(interval))}."
        for interval in _select_hint_intervals(intervals)
    ]
    return "\n".join(
        [
            "Attention hint từ telemetry — chỉ gợi ý khoảng thời gian cần xem kỹ, không phải bằng chứng:",
            *lines,
        ]
    )


def detect_signal_intervals(
    records: list[LogRecord],
    *,
    video_duration_s: float | None = None,
) -> list[SignalInterval]:
    """Detect anomalous stretches per signal and return them as merged, clamped time windows.

    Three complementary detectors feed the same interval list. The adaptive one catches sharp
    single-sample jumps; it cannot see a manoeuvre spread over many samples (each step stays far
    below the z-score gate) nor a long phase right after a spike (the spike inflates the rolling
    scale). The two physical detectors cover exactly those blind spots.
    """
    upper_bound_s = (
        video_duration_s if video_duration_s is not None else max(record.timestamp_s for record in records)
    )
    intervals: list[SignalInterval] = []
    for signal, aliases, physical_gate in (
        ("throttle", THROTTLE_ALIASES, PHYSICAL_MIN_THROTTLE_DELTA),
        ("brake", BRAKE_ALIASES, PHYSICAL_MIN_BRAKE_DELTA_FOR_HINT),
        ("steer", STEERING_ALIASES, PHYSICAL_MIN_STEERING_DELTA),
    ):
        values = numeric_series(records, aliases)
        observations = _adaptive_observations(
            values,
            detect_delta=True,
            minimum_scale=ADAPTIVE_MIN_SCALE,
        )
        for episode in _adaptive_episodes(observations):
            change = _representative_control_change(episode, values)
            if _change_magnitude(change) < physical_gate:
                continue
            intervals.append(_signal_interval(records, observations, episode, change, signal=signal))
        intervals.extend(
            _transition_intervals(records, values, signal=signal, physical_gate=physical_gate)
        )

    acceleration = acceleration_series(records)
    observations = _adaptive_observations(
        acceleration,
        detect_delta=False,
        minimum_scale=ADAPTIVE_ACCELERATION_MIN_SCALE,
    )
    for episode in _adaptive_episodes(observations):
        change = _representative_acceleration_change(episode, acceleration)
        if _acceleration_event_type(change.value) is None:
            continue
        intervals.append(
            _signal_interval(records, observations, episode, change, signal="acceleration")
        )
    intervals.extend(_sustained_acceleration_intervals(records, acceleration))
    return _finalize_intervals(intervals, upper_bound_s=upper_bound_s)


def _select_hint_intervals(intervals: list[SignalInterval]) -> list[SignalInterval]:
    """Rank by prominence, but cap each signal so one noisy channel cannot fill the whole hint."""
    selected: list[SignalInterval] = []
    used: dict[DynamicHintSignal, int] = {}
    for interval in sorted(intervals, key=lambda item: (-item.score, item.start_s)):
        if used.get(interval.signal, 0) >= MAX_INTERVALS_PER_SIGNAL:
            continue
        used[interval.signal] = used.get(interval.signal, 0) + 1
        selected.append(interval)
        if len(selected) >= MAX_LOG_ATTENTION_TIMESTAMPS:
            break
    return sorted(selected, key=lambda item: (item.start_s, item.signal))


def _prominence(magnitude: float, gate: float) -> float:
    """Score a physical detection on the same scale as an adaptive z-score."""
    return ADAPTIVE_ENTER_Z_SCORE * magnitude / gate


def _transition_runs(values: list[float | None]) -> list[tuple[int, int, Literal[-1, 1]]]:
    """Split a control signal into direction-consistent moves, tolerating brief plateaus."""
    runs: list[tuple[int, int, Literal[-1, 1]]] = []
    start: int | None = None
    direction: Literal[-1, 1] = 1
    last_move = 0
    for index in range(1, len(values)):
        current, previous = values[index], values[index - 1]
        if current is None or previous is None:
            step: int | None = None
        else:
            delta = current - previous
            step = 0 if abs(delta) < TRANSITION_EPSILON else (1 if delta > 0 else -1)
        if start is None:
            if step:
                start, direction, last_move = index - 1, step, index
            continue
        if step == direction:
            last_move = index
            continue
        if step == 0 and index - last_move <= TRANSITION_MAX_GAP_SAMPLES:
            continue
        runs.append((start, last_move, direction))
        if step:
            start, direction, last_move = index - 1, step, index
        else:
            start = None
    if start is not None:
        runs.append((start, last_move, direction))
    return runs


def _transition_intervals(
    records: list[LogRecord],
    values: list[float | None],
    *,
    signal: DynamicHintSignal,
    physical_gate: float,
) -> list[SignalInterval]:
    """Flag a control move whose TOTAL swing clears the gate, however many samples it took."""
    intervals: list[SignalInterval] = []
    for start, end, direction in _transition_runs(values):
        first, last = values[start], values[end]
        if first is None or last is None:
            continue
        swing = abs(last - first)
        if swing < physical_gate:
            continue
        peak_index = end if abs(last) >= abs(first) else start
        intervals.append(
            SignalInterval(
                signal=signal,
                start_s=records[start].timestamp_s,
                end_s=records[end].timestamp_s,
                peak_timestamp_s=records[peak_index].timestamp_s,
                score=_prominence(swing, physical_gate),
                peak_value=values[peak_index],
                start_value=first,
                end_value=last,
                direction=direction,
                description=_interval_description(signal, direction),
            )
        )
    return intervals


def _sustained_acceleration_intervals(
    records: list[LogRecord],
    values: list[float | None],
) -> list[SignalInterval]:
    """Flag every stretch that stays past a physical acceleration gate for several samples."""
    intervals: list[SignalInterval] = []
    start: int | None = None
    run_sign = 0
    for index in range(len(values) + 1):
        value = values[index] if index < len(values) else None
        active = value is not None and _acceleration_event_type(value) is not None
        sign = 0 if value is None else (1 if value >= 0 else -1)
        if active and (start is None or sign == run_sign):
            # A braking phase and an acceleration spike are separate events even when adjacent,
            # so a sign flip always closes the current run.
            if start is None:
                start, run_sign = index, sign
            continue
        if start is None:
            continue
        end = index - 1
        samples = [(position, values[position]) for position in range(start, end + 1)]
        if end - start + 1 >= SUSTAINED_MIN_SAMPLES and samples:
            peak_index, peak_value = max(samples, key=lambda item: abs(item[1]))
            direction: Literal[-1, 1] = 1 if peak_value >= 0 else -1
            gate = (
                PHYSICAL_STRONG_ACCELERATION_MPS2
                if direction > 0
                else abs(PHYSICAL_STRONG_DECELERATION_MPS2)
            )
            intervals.append(
                SignalInterval(
                    signal="acceleration",
                    start_s=records[start].timestamp_s,
                    end_s=records[end].timestamp_s,
                    peak_timestamp_s=records[peak_index].timestamp_s,
                    score=_prominence(abs(peak_value), gate),
                    peak_value=peak_value,
                    # Start from the last sample before the phase began, so the text shows what
                    # the signal moved away from rather than repeating the phase's own first value.
                    start_value=_value_before(values, start, samples[0][1]),
                    # End on the extreme reached, so the text agrees with the reported value.
                    end_value=peak_value,
                    direction=direction,
                    description=_interval_description("acceleration", direction),
                )
            )
        # A sign flip closes one run and opens the next on the very same sample.
        start, run_sign = (index, sign) if active else (None, 0)
    return intervals


def interval_text(interval: SignalInterval) -> str:
    """Render one interval as a qualitative Vietnamese sentence with no raw telemetry values."""
    return (
        f"trong khoảng {_format_interval_bound_s(interval.start_s)}s"
        f"–{_format_interval_bound_s(interval.end_s)}s, {interval.description}"
    )


def interval_text_with_values(interval: SignalInterval) -> str:
    """Same sentence plus the values moved through, for the verifier which may see telemetry."""
    start = _format_signal_value(interval.signal, interval.start_value)
    end = _format_signal_value(interval.signal, interval.end_value)
    if start == end:
        return interval_text(interval)
    return f"{interval_text(interval)} từ {start} -> {end}"


def _value_before(values: list[float | None], index: int, fallback: float) -> float:
    previous = values[index - 1] if index > 0 else None
    return fallback if previous is None else previous


def _format_signal_value(signal: DynamicHintSignal, value: float) -> str:
    # Controls are normalised to [0,1] or [-1,1]; acceleration is m/s2 and needs less precision.
    return f"{value:.1f}" if signal == "acceleration" else f"{value:.2f}"


def _signal_interval(
    records: list[LogRecord],
    observations: list[AdaptiveObservation],
    episode: AdaptiveChange,
    change: AdaptiveChange,
    *,
    signal: DynamicHintSignal,
) -> SignalInterval:
    start_index = _extended_start_index(observations, episode)
    return SignalInterval(
        signal=signal,
        start_s=records[start_index].timestamp_s,
        end_s=records[episode.end_index].timestamp_s,
        peak_timestamp_s=records[change.peak_index].timestamp_s,
        score=change.peak_z_score,
        peak_value=change.value,
        start_value=change.previous_value,
        end_value=change.value,
        direction=change.direction,
        description=_interval_description(signal, change.direction),
    )


def _interval_description(signal: DynamicHintSignal, direction: Literal[-1, 1]) -> str:
    if signal == "steer":
        return f"góc đánh lái thay đổi bất thường sang {'phải' if direction > 0 else 'trái'}"
    label = {"throttle": "ga", "brake": "phanh", "acceleration": "gia tốc"}[signal]
    return f"{label} {'tăng' if direction > 0 else 'giảm'} bất thường"


def _extended_start_index(observations: list[AdaptiveObservation], episode: AdaptiveChange) -> int:
    """Walk back over the ramp-up shoulder that still holds the exit z-score in the same direction."""
    positions = {observation.index: position for position, observation in enumerate(observations)}
    position = positions.get(episode.start_index)
    if position is None:
        return episode.start_index
    start_index = episode.start_index
    for candidate in range(position - 1, -1, -1):
        observation = observations[candidate]
        if (
            not observation.baseline_ready
            or observation.direction != episode.direction
            or observation.score < ADAPTIVE_EXIT_Z_SCORE
        ):
            break
        start_index = observation.index
    return start_index


def _finalize_intervals(
    intervals: list[SignalInterval],
    *,
    upper_bound_s: float,
) -> list[SignalInterval]:
    merged: list[SignalInterval] = []
    for interval in sorted(intervals, key=lambda item: (item.signal, item.direction, item.start_s)):
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.signal == interval.signal
            and previous.direction == interval.direction
            and interval.start_s - previous.end_s < MERGE_GAP_S
        ):
            merged[-1] = _merge_intervals(previous, interval)
            continue
        merged.append(interval)
    return sorted(
        (_with_minimum_width(interval, upper_bound_s=upper_bound_s) for interval in merged),
        key=lambda item: (item.start_s, item.signal),
    )


def _merge_intervals(previous: SignalInterval, interval: SignalInterval) -> SignalInterval:
    strongest = interval if interval.score > previous.score else previous
    earliest = previous if previous.start_s <= interval.start_s else interval
    latest = interval if interval.end_s >= previous.end_s else previous
    return replace(
        strongest,
        start_s=earliest.start_s,
        end_s=latest.end_s,
        start_value=earliest.start_value,
        end_value=latest.end_value,
    )


def _with_minimum_width(interval: SignalInterval, *, upper_bound_s: float) -> SignalInterval:
    """Widen a spike into a viewable window so the VLM never gets a single-frame hint."""
    if interval.end_s - interval.start_s >= MIN_INTERVAL_S:
        return interval
    return replace(
        interval,
        start_s=max(0.0, interval.peak_timestamp_s - MIN_INTERVAL_PAD_S),
        end_s=min(upper_bound_s, interval.peak_timestamp_s + MIN_INTERVAL_PAD_S),
    )


def _format_interval_bound_s(value: float) -> str:
    return f"{value:.1f}"


def _capitalize(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}"


def _adaptive_changes(
    values: list[float | None],
    *,
    detect_delta: bool,
    minimum_scale: float = ADAPTIVE_MIN_SCALE,
) -> list[AdaptiveChange]:
    """Detect sustained changes relative to each signal's rolling EMA baseline."""
    return _adaptive_episodes(
        _adaptive_observations(values, detect_delta=detect_delta, minimum_scale=minimum_scale)
    )


def _adaptive_observations(
    values: list[float | None],
    *,
    detect_delta: bool,
    minimum_scale: float = ADAPTIVE_MIN_SCALE,
) -> list[AdaptiveObservation]:
    """Score every usable sample against its rolling EMA baseline."""
    if minimum_scale <= 0:
        raise ValueError("minimum_scale must be positive")
    observations: list[tuple[int, float, float, float]] = []
    for index, value in enumerate(values):
        if value is None:
            continue
        if detect_delta:
            if index == 0 or values[index - 1] is None:
                continue
            previous_value = values[index - 1]
            observations.append((index, value - previous_value, previous_value, value))
        else:
            previous_value = values[index - 1] if index > 0 and values[index - 1] is not None else value
            observations.append((index, value, previous_value, value))
    if len(observations) <= ADAPTIVE_MIN_BASELINE_SAMPLES:
        return []

    history: deque[float] = deque(maxlen=ADAPTIVE_ROLLING_WINDOW)
    ema_mean = 0.0
    ema_variance = 0.0
    scored: list[AdaptiveObservation] = []
    for position, (index, observation, previous_value, value) in enumerate(observations):
        if history:
            rolling_mean = sum(history) / len(history)
            baseline = (ema_mean + rolling_mean) / 2
            robust_scale = max(math.sqrt(ema_variance), _mad_scale(history))
            scale = max(robust_scale, minimum_scale)
            signed_z_score = (observation - baseline) / scale
        else:
            signed_z_score = 0.0
        direction: Literal[-1, 1] = 1 if signed_z_score >= 0 else -1
        scored.append(
            AdaptiveObservation(
                index=index,
                score=abs(signed_z_score),
                direction=direction,
                previous_value=previous_value,
                value=value,
                baseline_ready=position >= ADAPTIVE_MIN_BASELINE_SAMPLES,
            )
        )

        previous_ema_mean = ema_mean
        if history:
            ema_mean = (1 - ADAPTIVE_EMA_ALPHA) * ema_mean + ADAPTIVE_EMA_ALPHA * observation
            ema_variance = (1 - ADAPTIVE_EMA_ALPHA) * (
                ema_variance + ADAPTIVE_EMA_ALPHA * (observation - previous_ema_mean) ** 2
            )
        else:
            ema_mean = observation
            ema_variance = 0.0
        history.append(observation)
    return scored


def _adaptive_episodes(observations: list[AdaptiveObservation]) -> list[AdaptiveChange]:
    """Assemble scored samples into sustained, merged change episodes."""
    active: AdaptiveChange | None = None
    completed: list[AdaptiveChange] = []
    for observation in observations:
        index = observation.index
        score = observation.score
        direction = observation.direction
        previous_value = observation.previous_value
        value = observation.value
        baseline_ready = observation.baseline_ready

        if active is None:
            if baseline_ready and score >= ADAPTIVE_ENTER_Z_SCORE:
                active = AdaptiveChange(
                    start_index=index,
                    end_index=index,
                    peak_index=index,
                    direction=direction,
                    peak_z_score=score,
                    previous_value=previous_value,
                    value=value,
                )
        elif direction == active.direction and score >= ADAPTIVE_EXIT_Z_SCORE:
            peak_index = active.peak_index
            peak_score = active.peak_z_score
            peak_previous = active.previous_value
            peak_value = active.value
            if score > peak_score:
                peak_index = index
                peak_score = score
                peak_previous = previous_value
                peak_value = value
            active = AdaptiveChange(
                start_index=active.start_index,
                end_index=index,
                peak_index=peak_index,
                direction=active.direction,
                peak_z_score=peak_score,
                previous_value=peak_previous,
                value=peak_value,
            )
        else:
            completed.append(active)
            active = None
            if baseline_ready and score >= ADAPTIVE_ENTER_Z_SCORE:
                active = AdaptiveChange(
                    start_index=index,
                    end_index=index,
                    peak_index=index,
                    direction=direction,
                    peak_z_score=score,
                    previous_value=previous_value,
                    value=value,
                )
    if active is not None:
        completed.append(active)
    return _merge_adaptive_changes(completed)


def _mad_scale(values: deque[float]) -> float:
    """Return a MAD-based scale so flat baselines cannot collapse the denominator."""
    median = _median(values)
    return ROBUST_SCALE_NORMALIZER * _median(abs(value - median) for value in values)


def _median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return (float(ordered[midpoint - 1]) + float(ordered[midpoint])) / 2


def _merge_adaptive_changes(changes: list[AdaptiveChange]) -> list[AdaptiveChange]:
    if not changes:
        return []
    merged = [changes[0]]
    for change in changes[1:]:
        previous = merged[-1]
        if change.start_index - previous.end_index <= ADAPTIVE_MERGE_GAP_SAMPLES + 1:
            if change.peak_z_score > previous.peak_z_score:
                merged[-1] = AdaptiveChange(
                    start_index=previous.start_index,
                    end_index=change.end_index,
                    peak_index=change.peak_index,
                    direction=previous.direction,
                    peak_z_score=change.peak_z_score,
                    previous_value=change.previous_value,
                    value=change.value,
                )
            else:
                merged[-1] = AdaptiveChange(
                    start_index=previous.start_index,
                    end_index=change.end_index,
                    peak_index=previous.peak_index,
                    direction=previous.direction,
                    peak_z_score=previous.peak_z_score,
                    previous_value=previous.previous_value,
                    value=previous.value,
                )
        else:
            merged.append(change)
    return merged


def _representative_control_change(
    change: AdaptiveChange,
    values: list[float | None],
) -> AdaptiveChange:
    candidates = [
        (index, values[index - 1], values[index])
        for index in range(max(change.start_index, 1), change.end_index + 1)
        if values[index - 1] is not None and values[index] is not None
    ]
    if not candidates:
        return change
    index, previous_value, value = max(candidates, key=lambda item: abs(item[2] - item[1]))
    direction: Literal[-1, 1] = 1 if value - previous_value >= 0 else -1
    return AdaptiveChange(
        start_index=change.start_index,
        end_index=change.end_index,
        peak_index=index,
        direction=direction,
        peak_z_score=change.peak_z_score,
        previous_value=previous_value,
        value=value,
    )


def _representative_acceleration_change(
    change: AdaptiveChange,
    values: list[float | None],
) -> AdaptiveChange:
    candidates = [
        (index, value)
        for index in range(change.start_index, change.end_index + 1)
        if (value := values[index]) is not None
    ]
    if not candidates:
        return change
    index, value = max(candidates, key=lambda item: abs(item[1]))
    previous_value = values[index - 1] if index > 0 and values[index - 1] is not None else value
    direction: Literal[-1, 1] = 1 if value >= 0 else -1
    return AdaptiveChange(
        start_index=change.start_index,
        end_index=change.end_index,
        peak_index=index,
        direction=direction,
        peak_z_score=change.peak_z_score,
        previous_value=previous_value,
        value=value,
    )


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
    records = _claim_records(
        log_uri,
        timestamp_tolerance_s=timestamp_tolerance_s,
        sample_radius=sample_radius,
    )
    return _build_claim_log_summaries_from_records(
        records,
        claims,
        timestamp_tolerance_s=timestamp_tolerance_s,
        sample_radius=sample_radius,
    )


def build_claim_verification_inputs(
    log_uri: str,
    claims: list[Claim],
    *,
    timestamp_tolerance_s: float,
    sample_radius: int = 3,
    video_duration_s: float | None = None,
) -> tuple[list[ClaimLogSummary], list[ClaimVerificationContext]]:
    """Build rich summaries plus compact, deterministic telemetry for the verification LLM."""
    records = _claim_records(
        log_uri,
        timestamp_tolerance_s=timestamp_tolerance_s,
        sample_radius=sample_radius,
        video_duration_s=video_duration_s,
    )
    summaries = _build_claim_log_summaries_from_records(
        records,
        claims,
        timestamp_tolerance_s=timestamp_tolerance_s,
        sample_radius=sample_radius,
        sample_from_full_records=True,
    )
    intervals = detect_signal_intervals(records, video_duration_s=video_duration_s) if records else []
    # sample_radius is a row count; the hint window needs it in seconds.
    claim_radius_s = sample_radius * _sample_period_s(records)
    contexts = [
        _claim_verification_context(records, claim, summary, intervals, claim_radius_s)
        for claim, summary in zip(claims, summaries, strict=True)
    ]
    return summaries, contexts


def _sample_period_s(records: list[LogRecord]) -> float:
    """Median gap between rows, so a few missing samples cannot distort the window."""
    if len(records) < 2:
        return 0.0
    return _median(
        records[index].timestamp_s - records[index - 1].timestamp_s
        for index in range(1, len(records))
    )


def _claim_records(
    log_uri: str,
    *,
    timestamp_tolerance_s: float,
    sample_radius: int,
    video_duration_s: float | None = None,
) -> list[LogRecord]:
    if timestamp_tolerance_s < 0 or sample_radius < 0:
        raise ValueError("timestamp_tolerance_s and sample_radius must be non-negative")
    _, records = load_log_records(log_uri)
    return _select_records(
        records,
        video_duration_s=video_duration_s,
    )


def _build_claim_log_summaries_from_records(
    records: list[LogRecord],
    claims: list[Claim],
    *,
    timestamp_tolerance_s: float,
    sample_radius: int,
    sample_from_full_records: bool = False,
) -> list[ClaimLogSummary]:
    return [
        _claim_log_summary(
            records,
            claim,
            timestamp_tolerance_s=timestamp_tolerance_s,
            sample_radius=sample_radius,
            sample_from_full_records=sample_from_full_records,
        )
        for claim in claims
    ]


def _claim_log_summary(
    records: list[LogRecord],
    claim: Claim,
    *,
    timestamp_tolerance_s: float,
    sample_radius: int,
    sample_from_full_records: bool = False,
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
    if not records:
        return _claim_log_summary_without_samples(claim, "Không có dòng log nào trong telemetry của video.")
    nearest_index = min(range(len(records)), key=lambda index: abs(records[index].timestamp_s - claim.timestamp_s))
    nearest = records[nearest_index]
    distance = abs(nearest.timestamp_s - claim.timestamp_s)
    within_tolerance = distance <= timestamp_tolerance_s
    if within_tolerance:
        if sample_from_full_records:
            start = max(0, nearest_index - sample_radius)
            end = min(len(records), nearest_index + sample_radius + 1)
            samples = records[start:end]
        else:
            eligible = [
                record
                for record in records
                if abs(record.timestamp_s - claim.timestamp_s) <= timestamp_tolerance_s
            ]
            eligible_nearest_index = min(
                range(len(eligible)),
                key=lambda index: abs(eligible[index].timestamp_s - claim.timestamp_s),
            )
            start = max(0, eligible_nearest_index - sample_radius)
            end = min(len(eligible), eligible_nearest_index + sample_radius + 1)
            samples = eligible[start:end]
    else:
        samples = []
    if not samples:
        return _claim_log_summary_without_samples(
            claim,
            "Mẫu gần nhất nằm ngoài tolerance; không dùng log để xác nhận hoặc bác bỏ claim.",
            nearest_timestamp_s=nearest.timestamp_s,
            timestamp_distance_s=distance,
        )
    metrics, available_signals = _claim_metrics(samples, claim.timestamp_s)
    evidence = [
        ClaimLogEvidence(
            evidence_id=_row_evidence_id(record.timestamp_s),
            timestamp_s=record.timestamp_s,
            camera_frame=record.text(CAMERA_FRAME_ALIASES),
        )
        for record in samples
    ]
    allowed_evidence_ids = [item.evidence_id for item in evidence]
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


def _claim_log_summary_without_samples(
    claim: Claim,
    message: str,
    *,
    nearest_timestamp_s: float | None = None,
    timestamp_distance_s: float | None = None,
) -> ClaimLogSummary:
    nearest = (
        f"{_format_timestamp_s(nearest_timestamp_s)}s"
        if nearest_timestamp_s is not None
        else "Không có"
    )
    distance = (
        f"{_format_timestamp_s(timestamp_distance_s)}s"
        if timestamp_distance_s is not None
        else "Không có"
    )
    return ClaimLogSummary(
        claim_id=claim.claim_id,
        claim_timestamp_s=claim.timestamp_s,
        nearest_timestamp_s=nearest_timestamp_s,
        timestamp_distance_s=timestamp_distance_s,
        summary=(
            "Đối chiếu thời gian\n"
            f"Claim timestamp: {_format_timestamp_s(claim.timestamp_s)}s\n"
            f"Mẫu log gần nhất: {nearest}\n"
            f"Sai lệch timestamp: {distance}\n"
            "Trong tolerance: **Không**\n\n"
            "Log có thể kiểm tra\n"
            f"{message}"
        ),
    )


def _claim_verification_context(
    records: list[LogRecord],
    claim: Claim,
    summary: ClaimLogSummary,
    intervals: list[SignalInterval],
    claim_radius_s: float,
) -> ClaimVerificationContext:
    allowed_timestamps = {item.timestamp_s for item in summary.evidence}
    samples = [record for record in records if record.timestamp_s in allowed_timestamps]
    if not samples or claim.timestamp_s is None:
        empty = ClaimTelemetrySnapshot()
        return ClaimVerificationContext(
            claim_id=claim.claim_id,
            raw_telemetry=ClaimRawTelemetry(
                window_start=empty,
                at_claim=empty,
                window_end=empty,
            ),
            derived=ClaimTelemetryDerived(),
        )

    at_claim = min(samples, key=lambda record: abs(record.timestamp_s - claim.timestamp_s))
    snapshot_records = (samples[0], at_claim, samples[-1])
    raw_telemetry = ClaimRawTelemetry(
        window_start=_telemetry_snapshot(snapshot_records[0]),
        at_claim=_telemetry_snapshot(snapshot_records[1]),
        window_end=_telemetry_snapshot(snapshot_records[2]),
    )
    available_signals = [
        signal
        for signal, aliases in VERIFICATION_SIGNAL_ALIASES.items()
        if any(record.number(aliases) is not None for record in samples)
    ]
    allowed_evidence_ids = list(
        dict.fromkeys(_row_evidence_id(record.timestamp_s) for record in snapshot_records)
    )
    return ClaimVerificationContext(
        claim_id=claim.claim_id,
        available_signals=available_signals,
        raw_telemetry=raw_telemetry,
        derived=_telemetry_derived(raw_telemetry),
        derived_dynamics=_derived_dynamics(samples),
        dynamic_hints=_claim_dynamic_hints(intervals, claim.timestamp_s, claim_radius_s),
        allowed_evidence_ids=allowed_evidence_ids,
    )


def _claim_dynamic_hints(
    intervals: list[SignalInterval],
    claim_timestamp_s: float | None,
    claim_radius_s: float,
) -> list[ClaimDynamicHint]:
    """Attach the intervals that fall inside this claim's sampling window.

    A claim timestamp is snapped to the nearest canonical frame, so requiring it to sit exactly
    inside an interval drops hints that are plainly about the same moment. The claim therefore
    carries the same window the verifier samples, and an interval joins it when most of the
    interval lies in that window.
    """
    if claim_timestamp_s is None:
        return []
    window_start = claim_timestamp_s - claim_radius_s
    window_end = claim_timestamp_s + claim_radius_s
    return [
        ClaimDynamicHint(
            signal=interval.signal,
            start_s=interval.start_s,
            end_s=interval.end_s,
            text=interval_text_with_values(interval),
            value=interval.peak_value,
        )
        for interval in intervals
        if _covers_claim(interval, claim_timestamp_s, window_start, window_end)
    ]


def _covers_claim(
    interval: SignalInterval,
    claim_timestamp_s: float,
    window_start: float,
    window_end: float,
) -> bool:
    if interval.start_s <= claim_timestamp_s <= interval.end_s:
        return True
    overlap = min(interval.end_s, window_end) - max(interval.start_s, window_start)
    if overlap <= 0:
        return False
    duration = interval.end_s - interval.start_s
    if duration <= 0:
        return True
    return overlap / duration > MIN_CLAIM_HINT_OVERLAP_RATIO


def _telemetry_snapshot(record: LogRecord) -> ClaimTelemetrySnapshot:
    return ClaimTelemetrySnapshot(
        timestamp_s=record.timestamp_s,
        evidence_id=_row_evidence_id(record.timestamp_s),
        speed_kmh=record.number(SPEED_ALIASES),
        throttle=record.number(THROTTLE_ALIASES),
        brake=record.number(BRAKE_ALIASES),
        steer=record.number(STEERING_ALIASES),
    )


def _telemetry_derived(raw: ClaimRawTelemetry) -> ClaimTelemetryDerived:
    speed_at_claim = raw.at_claim.speed_kmh
    if speed_at_claim is None:
        movement_state = None
    elif speed_at_claim == 0:
        movement_state = "stopped"
    elif speed_at_claim <= NEAR_STOPPED_SPEED_KMH:
        movement_state = "near_stopped"
    else:
        movement_state = "moving"

    steer_at_claim = raw.at_claim.steer
    if steer_at_claim is None:
        steer_direction = None
    else:
        steer_direction = _steer_direction(steer_at_claim)

    speed_start = raw.window_start.speed_kmh
    speed_end = raw.window_end.speed_kmh
    if speed_start is None or speed_end is None:
        speed_trend = None
    else:
        speed_delta = speed_end - speed_start
        if speed_delta <= -STRONG_SPEED_DROP_KMH:
            speed_trend = "strong_decrease"
        elif speed_delta < 0:
            speed_trend = "decrease"
        elif speed_delta > 0:
            speed_trend = "increase"
        else:
            speed_trend = "stable"
    return ClaimTelemetryDerived(
        movement_state_at_claim=movement_state,
        steer_direction_at_claim=steer_direction,
        speed_trend=speed_trend,
    )


def _derived_dynamics(records: list[LogRecord]) -> ClaimDerivedDynamics:
    # Pick the phase the same way speed_trend does, so the two never disagree: a window whose
    # speed ends higher than it started is an acceleration phase, and reporting its noise dips
    # as "giảm tốc" would contradict speed_trend.
    accelerating = _is_accelerating_window(records)
    magnitude = (
        _positive_max_acceleration(records) if accelerating else _positive_max_deceleration(records)
    )
    steering_activity = _steering_activity(records)
    max_brake = max(
        (value for value in numeric_series(records, BRAKE_ALIASES) if value is not None),
        default=None,
    )
    decel_brake_mismatch = (
        magnitude * (1 - max_brake) if magnitude is not None and max_brake is not None else None
    )
    return ClaimDerivedDynamics(
        max_deceleration_mps2=_dynamics_metric(
            magnitude,
            mild_threshold=3,
            strong_threshold=7,
            texts=(
                ("Không đủ dữ liệu tốc độ để tính tăng tốc.",
                 "Không ghi nhận tăng tốc đáng kể trong khoảng claim.",
                 "Xe có tăng tốc đáng chú ý trong khoảng claim.",
                 "Xe có tăng tốc rất mạnh trong khoảng claim.")
                if accelerating
                else
                ("Không đủ dữ liệu tốc độ để tính giảm tốc.",
                 "Không ghi nhận giảm tốc đáng kể trong khoảng claim.",
                 "Xe có giảm tốc đáng chú ý trong khoảng claim.",
                 "Xe có giảm tốc rất mạnh trong khoảng claim.")
            ),
        ),
        steering_activity=_dynamics_metric(
            steering_activity,
            mild_threshold=0.03,
            strong_threshold=0.10,
            texts=(
                "Không đủ dữ liệu steering để đánh giá biến động.",
                "Không ghi nhận biến động steering đáng kể.",
                "Steering có biến động đáng chú ý trong khoảng claim.",
                "Steering biến động rất mạnh trong khoảng claim.",
            ),
        ),
        decel_brake_mismatch=_dynamics_metric(
            decel_brake_mismatch,
            mild_threshold=3,
            strong_threshold=7,
            texts=(
                # Accelerating with little brake is simply normal driving, so that phase must not
                # carry the accident wording; only decelerating without brake is anomalous.
                ("Không đủ dữ liệu tốc độ hoặc brake để đánh giá mức không tương xứng.",
                 "Xe đang tăng tốc; mức brake thấp là bình thường.",
                 "Xe đang tăng tốc; mức brake thấp là bình thường.",
                 "Xe tăng tốc rất mạnh.")
                if accelerating
                else
                ("Không đủ dữ liệu tốc độ hoặc brake để đánh giá mức không tương xứng.",
                 "Giảm tốc và tín hiệu brake không có mismatch đáng kể.",
                 "Giảm tốc và tín hiệu brake có mismatch đáng chú ý.",
                 "Xe giảm tốc rất mạnh nhưng mức brake ghi nhận thấp; "
                 "diễn biến này có thể xảy ra tai nạn cần được chú ý.")
            ),
        ),
    )


def _is_accelerating_window(records: list[LogRecord]) -> bool:
    known = [value for value in numeric_series(records, SPEED_ALIASES) if value is not None]
    return len(known) >= 2 and known[-1] > known[0]


def _positive_max_acceleration(records: list[LogRecord]) -> float | None:
    return _max_signed_rate(records, sign=1)


def _positive_max_deceleration(records: list[LogRecord]) -> float | None:
    return _max_signed_rate(records, sign=-1)


def _max_signed_rate(records: list[LogRecord], *, sign: int) -> float | None:
    speed_values = numeric_series(records, SPEED_ALIASES)
    values = [
        max(
            0.0,
            sign * ((current - previous) / 3.6) / (records[index].timestamp_s - records[index - 1].timestamp_s),
        )
        for index, (previous, current) in enumerate(zip(speed_values, speed_values[1:]), start=1)
        if previous is not None
        and current is not None
        and records[index].timestamp_s > records[index - 1].timestamp_s
    ]
    return max(values, default=None)


def _steering_activity(records: list[LogRecord]) -> float | None:
    values = numeric_series(records, STEERING_ALIASES)
    changes = [
        abs(current - previous)
        for previous, current in zip(values, values[1:])
        if previous is not None and current is not None
    ]
    return sum(changes) / len(changes) if changes else None


def _dynamics_metric(
    value: float | None,
    *,
    mild_threshold: float,
    strong_threshold: float,
    texts: tuple[str, str, str, str],
) -> ClaimDerivedDynamicsMetric:
    if value is None:
        return ClaimDerivedDynamicsMetric(text=texts[0])
    if value < mild_threshold:
        return ClaimDerivedDynamicsMetric(value=value, level="normal", text=texts[1])
    if value < strong_threshold:
        return ClaimDerivedDynamicsMetric(value=value, level="mild_abnormal", text=texts[2])
    return ClaimDerivedDynamicsMetric(value=value, level="strong_abnormal", text=texts[3])


def _claim_metrics(
    records: list[LogRecord],
    claim_timestamp_s: float,
) -> tuple[dict[str, dict[str, float | int | str | bool | None]], list[str]]:
    signals = {
        "speed_kmh": numeric_series(records, SPEED_ALIASES),
        "throttle": numeric_series(records, THROTTLE_ALIASES),
        "brake": numeric_series(records, BRAKE_ALIASES),
        "steer": numeric_series(records, STEERING_ALIASES),
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
                f"Số dòng log model được phép dùng: {len(records)}",
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
            "Tốc độ — các dòng log được phép dùng:",
            *_allowed_signal_table(records, SPEED_ALIASES, "Speed (km/h)"),
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
                    "Brake — các dòng log được phép dùng:",
                    *_allowed_signal_table(records, BRAKE_ALIASES, "Brake"),
                ]
            )
        if throttle:
            control_lines.extend(
                [
                    _throttle_statement(throttle),
                    "Throttle — các dòng log được phép dùng:",
                    *_allowed_signal_table(records, THROTTLE_ALIASES, "Throttle"),
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
                    "Steering — các dòng log được phép dùng:",
                    *_allowed_signal_table(records, STEERING_ALIASES, "Steering"),
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


def _allowed_signal_table(
    records: list[LogRecord],
    aliases: tuple[str, ...],
    value_label: str,
) -> list[str]:
    rows = [
        (record.timestamp_s, value)
        for record in records
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
                "steering [-1, 1]: steering <= -0.1 rẽ trái, -0.1 < steering < 0.1 đi thẳng, "
                "steering >= 0.1 rẽ phải;",
                "hướng xe: được code suy ra từ steering tại timestamp claim.",
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
        (abs(record.timestamp_s - claim_timestamp_s), record.timestamp_s, record.number(STEERING_ALIASES))
        for record in records
    ]
    _, timestamp_s, value = min(
        (item for item in candidates if item[2] is not None),
        key=lambda item: item[0],
    )
    steering = float(value)
    direction = _steer_direction(steering)
    if direction == "right":
        state = "xe có xu hướng rẽ phải"
    elif direction == "left":
        state = "xe có xu hướng rẽ trái"
    else:
        state = "steering gần trung tâm"
    return f"Steering tại {_format_timestamp_s(timestamp_s)}s: {steering:g} => {state}."


def _steer_direction(steering: float) -> Literal["left", "straight", "right"]:
    if steering <= -STEER_STRAIGHT_ABS_THRESHOLD:
        return "left"
    if steering >= STEER_STRAIGHT_ABS_THRESHOLD:
        return "right"
    return "straight"


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


def _adaptive_event(
    event_type: LogEventType,
    records: list[LogRecord],
    signal: str,
    change: AdaptiveChange,
) -> LogEvent:
    start_s = records[change.start_index].timestamp_s
    end_s = records[change.end_index].timestamp_s
    details = (
        f"adaptive change (peak z-score {change.peak_z_score:.2f}) "
        f"merged from {start_s:.3f}s to {end_s:.3f}s"
    )
    return _event(
        event_type,
        records[change.peak_index].timestamp_s,
        signal,
        change.value,
        change.previous_value,
        details,
    )


def _change_magnitude(change: AdaptiveChange) -> float:
    return abs(change.value - change.previous_value)


def _acceleration_event_type(value: float) -> LogEventType | None:
    if abs(value) >= PHYSICAL_EXTREME_ACCELERATION_MPS2:
        return "extreme_acceleration"
    if value <= PHYSICAL_STRONG_DECELERATION_MPS2:
        return "strong_deceleration"
    if value >= PHYSICAL_STRONG_ACCELERATION_MPS2:
        return "strong_acceleration"
    return None


def _metric_evidence_id(name: str) -> str:
    return f"log-metric:{name}"


def _anomaly_warnings(events: list[LogEvent]) -> list[str]:
    codes = {
        "strong_deceleration": "LOG_ADAPTIVE_DECELERATION",
        "strong_acceleration": "LOG_ADAPTIVE_ACCELERATION",
        "extreme_acceleration": "LOG_EXTREME_ACCELERATION",
        "steering_change": "LOG_ADAPTIVE_STEERING_CHANGE",
    }
    return [
        f"{codes[event.event_type]} at {_format_timestamp_s(event.timestamp_s)}s: {event.details}"
        for event in events
        if event.event_type in codes
    ]


def _build_summary(
    *,
    start_s: float,
    end_s: float,
    metrics: dict[str, float | int | str | bool | None],
    warnings: list[str],
    errors: list[str],
) -> str:
    statements = [f"Log toàn video được phân tích trong khoảng [{start_s:g}, {end_s:g}] giây."]
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
    if metrics["acceleration_min"] is not None and metrics["acceleration_max"] is not None:
        statements.append(
            f"Dải gia tốc từ {float(metrics['acceleration_min']):.3f} đến "
            f"{float(metrics['acceleration_max']):.3f} m/s²."
        )
    if metrics["max_absolute_acceleration_time"] is not None:
        statements.append(
            "Đỉnh trị tuyệt đối gia tốc tại "
            f"{float(metrics['max_absolute_acceleration_time']):g} giây."
        )
    elif metrics["max_deceleration_time"] is not None:
        statements.append(
            f"Giảm tốc cực đại tại {float(metrics['max_deceleration_time']):g} giây."
        )
    elif metrics["max_acceleration_time"] is not None:
        statements.append(
            f"Tăng tốc cực đại tại {float(metrics['max_acceleration_time']):g} giây."
        )
    if metrics["max_brake"] is not None:
        statements.append(f"Giá trị brake lớn nhất là {metrics['max_brake']:g}.")
    if metrics["brake_rise_time"] is not None:
        statements.append(f"Brake tăng mạnh lần đầu tại {metrics['brake_rise_time']:g} giây.")
    else:
        statements.append("Không phát hiện brake tăng mạnh trong toàn bộ video.")
    if metrics["max_steering_change"] is not None:
        steering = f"Thay đổi steering angle lớn nhất là {metrics['max_steering_change']:g}"
        if metrics["steering_change_time"] is not None:
            steering += f" tại {metrics['steering_change_time']:g} giây"
        statements.append(steering + ".")
    if metrics["strong_steering_change_time"] is not None:
        statements.append(
            f"Phát hiện thay đổi lái mạnh tại {float(metrics['strong_steering_change_time']):g} giây."
        )
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


def _series_extreme_index(values: list[float | None], *, smallest: bool) -> int | None:
    indices = [index for index, value in enumerate(values) if value is not None]
    if not indices:
        return None
    return (min if smallest else max)(indices, key=lambda index: values[index])


def _series_extreme_abs_index(values: list[float | None]) -> int | None:
    indices = [index for index, value in enumerate(values) if value is not None]
    if not indices:
        return None
    return max(indices, key=lambda index: abs(values[index]))


def _acceleration_time_if(
    records: list[LogRecord],
    acceleration: list[float | None],
    index: int | None,
    predicate: Callable[[float], bool],
) -> float | None:
    if index is None:
        return None
    value = acceleration[index]
    return records[index].timestamp_s if value is not None and predicate(value) else None


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
