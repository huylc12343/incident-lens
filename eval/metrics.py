"""Deterministic metrics defined by ``eval/plan_eval.md``."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def temporal_iou(*, pred_start: float, pred_end: float, gold_start: float, gold_end: float) -> float:
    """Calculate the incident-window temporal IoU from the evaluation plan."""
    intersection = max(0.0, min(pred_end, gold_end) - max(pred_start, gold_start))
    union = max(pred_end, gold_end) - min(pred_start, gold_start)
    return intersection / union if union > 0 else 0.0


def binary_incident_metrics(
    predictions: Sequence[bool],
    labels: Sequence[bool],
    *,
    prefix: str,
) -> dict[str, float | int]:
    """Return precision, recall, F1, and confusion counts for binary incidents."""
    if len(predictions) != len(labels):
        raise ValueError("predictions and labels must have the same length")

    tp = sum(prediction and label for prediction, label in zip(predictions, labels, strict=True))
    fp = sum(prediction and not label for prediction, label in zip(predictions, labels, strict=True))
    fn = sum(not prediction and label for prediction, label in zip(predictions, labels, strict=True))
    tn = sum(not prediction and not label for prediction, label in zip(predictions, labels, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        f"{prefix}_precision": precision,
        f"{prefix}_recall": recall,
        f"{prefix}_f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def multiclass_metrics(predictions: Sequence[str], labels: Sequence[str], *, prefix: str) -> dict[str, float | int | None]:
    """Calculate macro precision, recall, and F1 for exact class labels."""
    if len(predictions) != len(labels):
        raise ValueError("predictions and labels must have the same length")
    if not labels:
        return {
            f"{prefix}_precision": None,
            f"{prefix}_recall": None,
            f"{prefix}_f1": None,
            "num_samples_used": 0,
        }

    classes = sorted(set(predictions) | set(labels))
    precision_values: list[float] = []
    recall_values: list[float] = []
    f1_values: list[float] = []
    for item in classes:
        tp = sum(prediction == item and label == item for prediction, label in zip(predictions, labels, strict=True))
        fp = sum(prediction == item and label != item for prediction, label in zip(predictions, labels, strict=True))
        fn = sum(prediction != item and label == item for prediction, label in zip(predictions, labels, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        precision_values.append(precision)
        recall_values.append(recall)
        f1_values.append(f1)
    return {
        f"{prefix}_precision": statistics.fmean(precision_values),
        f"{prefix}_recall": statistics.fmean(recall_values),
        f"{prefix}_f1": statistics.fmean(f1_values),
        "num_samples_used": len(labels),
    }


def evidence_id_validity(
    results: Iterable[Mapping[str, Any]],
    allowed_ids_by_claim: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Measure validity against the backend-provided evidence allowlists."""
    predicted_ids = 0
    valid_ids = 0
    valid_claims = 0
    claim_count = 0
    invalid_ids: list[str] = []

    for result in results:
        claim_id = result.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        claim_count += 1
        allowed = set(allowed_ids_by_claim.get(claim_id, ()))
        evidence_ids = result.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        invalid = [item for item in evidence_ids if not isinstance(item, str) or item not in allowed]
        if not invalid:
            valid_claims += 1
        for evidence_id in evidence_ids:
            if not isinstance(evidence_id, str):
                invalid_ids.append(str(evidence_id))
                continue
            predicted_ids += 1
            if evidence_id in allowed:
                valid_ids += 1
            else:
                invalid_ids.append(evidence_id)

    return {
        "evidence_id_precision": valid_ids / predicted_ids if predicted_ids else None,
        "claim_evidence_validity_rate": valid_claims / claim_count if claim_count else None,
        "invalid_evidence_ids": invalid_ids,
    }


def status_distribution(results: Iterable[Mapping[str, Any]]) -> dict[str, float | None]:
    """Return the per-status proportions requested for verifier output."""
    values = [item.get("status") for item in results]
    count = len(values)
    return {
        status: values.count(status) / count if count else None
        for status in ("supported", "contradicted", "unverified")
    }


def report_decision_consistency(rows: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    """Apply the report decision rule without deriving a duplicate final F1."""
    eligible = 0
    passed = 0
    for row in rows:
        has_accident = row.get("has_accident")
        accident_type = row.get("type_of_accident")
        if not isinstance(has_accident, bool) or not isinstance(accident_type, str):
            continue
        eligible += 1
        if (not has_accident and accident_type == "no_incident") or (
            has_accident and accident_type != "no_incident"
        ):
            passed += 1
    return {
        "report_decision_consistency": passed / eligible if eligible else None,
        "passed": passed,
        "eligible": eligible,
    }


def aggregate_temporal_errors(rows: Iterable[Mapping[str, Any]], *, prefix: str) -> dict[str, float | int | None]:
    """Aggregate valid per-sample t0 errors and temporal IoUs."""
    values = list(rows)
    errors = [row["t0_error_s"] for row in values if row.get("t0_error_s") is not None]
    ious = [row["temporal_iou"] for row in values if row.get("temporal_iou") is not None]
    return {
        f"{prefix}_median_t0_error_s": statistics.median(errors) if errors else None,
        f"{prefix}_temporal_iou_mean": statistics.fmean(ious) if ious else None,
        f"{prefix}_temporal_iou_median": statistics.median(ious) if ious else None,
        "num_samples_used": len(errors),
    }


def aggregate_event_mae(rows: Iterable[Mapping[str, Any]]) -> dict[str, float | int | None]:
    """Aggregate only semantically matched events; no match is never scored as zero."""
    matches = [match for row in rows for match in row.get("event_matches", [])]
    errors = [abs(match["pred_timestamp"] - match["gold_timestamp"]) for match in matches]
    return {
        "event_timestamp_mae_s": statistics.fmean(errors) if errors else None,
        "num_matched_events": len(errors),
    }
