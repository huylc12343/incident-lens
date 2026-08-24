"""Load optional incident labels and compare them with the workflow result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.models.api import (
    AiGroundTruthEvaluation,
    AiIncidentPrediction,
    GroundTruth,
    GroundTruthTimeline,
)
from src.models.incidents import AccidentType, DraftReport


class GroundTruthError(ValueError):
    """Raised when an uploaded Ground Truth artifact cannot be used safely."""


_SOURCE_NAMES = {
    "carla": "CARLA Incident",
    "carla_incident": "CARLA Incident",
    "carla_simulator": "CARLA Incident",
    "human": "Human annotation",
    "human_annotation": "Human annotation",
    "reviewer": "Reviewer verified",
    "reviewer_verified": "Reviewer verified",
}
_LEGACY_INCIDENT_TYPES = {
    "cut_in_collision": AccidentType.SIDE_COLLISION.value,
}


def load_ground_truth(uri: str, *, upload_root: Path | None = None) -> GroundTruth:
    """Read a JSON label artifact, constrained to the configured upload directory."""

    path = Path(uri).resolve()
    if upload_root is not None and not path.is_relative_to(upload_root.resolve()):
        raise GroundTruthError("ground-truth artifact is outside the upload directory")
    if not path.is_file():
        raise GroundTruthError("ground-truth artifact does not exist")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GroundTruthError("ground-truth artifact is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise GroundTruthError("ground-truth artifact must contain a JSON object")
    return parse_ground_truth(raw)


def parse_ground_truth(raw: dict[str, Any]) -> GroundTruth:
    """Normalize supported CARLA/human label shapes into the public API contract."""

    provenance = str(raw.get("label_provenance") or raw.get("source") or "").strip()
    source = _SOURCE_NAMES.get(provenance.casefold(), provenance)
    incident_type = raw.get("incident_type")
    if raw.get("is_incident") is False and not incident_type:
        incident_type = AccidentType.NO_INCIDENT.value
    if isinstance(incident_type, str):
        incident_type = _LEGACY_INCIDENT_TYPES.get(incident_type.strip().casefold(), incident_type.strip().casefold())
    timeline_raw = raw.get("timeline")
    timeline = _timeline(timeline_raw) if isinstance(timeline_raw, dict) else None
    try:
        return GroundTruth(
            source=source,
            incident_type=incident_type or None,
            severity=_optional_text(raw.get("severity")),
            timeline=timeline,
        )
    except ValidationError as exc:
        raise GroundTruthError("ground-truth artifact has unsupported label values") from exc


def evaluate_ground_truth(
    ground_truth: GroundTruth | None,
    report: DraftReport | None,
) -> AiGroundTruthEvaluation | None:
    """Build an evaluation only after the workflow has produced a structured prediction."""

    if ground_truth is None or report is None:
        return None
    prediction = AiIncidentPrediction(
        incident_type=report.type_of_accident,
        timeline=GroundTruthTimeline(
            t_start=report.incident_window.t_start,
            t0=report.incident_window.t0,
            t_end=report.incident_window.t_end,
        ),
    )
    type_match = _match(prediction.incident_type, ground_truth.incident_type)
    severity_match = _match(prediction.severity, ground_truth.severity)
    predicted_timeline = prediction.timeline
    truth_timeline = ground_truth.timeline
    t0_delta = (
        abs(predicted_timeline.t0 - truth_timeline.t0)
        if predicted_timeline is not None
        and truth_timeline is not None
        and predicted_timeline.t0 is not None
        and truth_timeline.t0 is not None
        else None
    )
    timeline_iou = _timeline_iou(predicted_timeline, truth_timeline)

    # Score only fields that both sides actually provide. A missing severity, for
    # example, must not silently count as an incorrect prediction.
    scores = [float(value) for value in (type_match, severity_match) if value is not None]
    if t0_delta is not None:
        scores.append(max(0.0, 1.0 - (t0_delta / 5.0)))
    if timeline_iou is not None:
        scores.append(timeline_iou)
    overall_accuracy = sum(scores) / len(scores) if scores else None
    return AiGroundTruthEvaluation(
        overall_accuracy=overall_accuracy,
        incident_type_match=type_match,
        severity_match=severity_match,
        t0_delta_s=t0_delta,
        timeline_iou=timeline_iou,
        prediction=prediction,
    )


def _timeline(raw: dict[str, Any]) -> GroundTruthTimeline | None:
    values = {key: raw.get(key) for key in ("t_start", "t0", "t_end")}
    if all(value is None for value in values.values()):
        return None
    try:
        return GroundTruthTimeline(**values)
    except ValidationError as exc:
        raise GroundTruthError("ground-truth timeline is invalid") from exc


def _timeline_iou(
    prediction: GroundTruthTimeline | None,
    truth: GroundTruthTimeline | None,
) -> float | None:
    if (
        prediction is None
        or truth is None
        or prediction.t_start is None
        or prediction.t_end is None
        or truth.t_start is None
        or truth.t_end is None
    ):
        return None
    intersection = max(0.0, min(prediction.t_end, truth.t_end) - max(prediction.t_start, truth.t_start))
    union = max(prediction.t_end, truth.t_end) - min(prediction.t_start, truth.t_start)
    return intersection / union if union > 0 else None


def _match(left: object | None, right: object | None) -> bool | None:
    if left is None or right is None:
        return None
    return str(left).strip().casefold() == str(right).strip().casefold()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
