"""Deterministic metrics defined by ``eval/plan_eval.md``."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from eval.pricing import model_cost_usd


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


def multiclass_metrics(predictions: Sequence[str], labels: Sequence[str], *, prefix: str) -> dict[str, Any]:
    """Score class labels: plain accuracy, macro precision/recall/F1, confusion.

    Comparison is case-insensitive (``Crossing_collision`` == ``crossing_collision``)
    because the golden set is not consistent about capitalisation and the label is
    an identifier, not prose. Macro P/R/F1 average over every class that appears in
    either predictions or labels, so a class the model can never emit still counts
    as a zero row; read ``{prefix}_accuracy`` and ``{prefix}_confusion`` alongside
    the macro numbers rather than in isolation.
    """
    if len(predictions) != len(labels):
        raise ValueError("predictions and labels must have the same length")
    if not labels:
        return {
            f"{prefix}_accuracy": None,
            f"{prefix}_precision": None,
            f"{prefix}_recall": None,
            f"{prefix}_f1": None,
            f"{prefix}_confusion": {},
            f"{prefix}_num_samples_used": 0,
        }

    predictions = [value.lower() for value in predictions]
    labels = [value.lower() for value in labels]
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

    confusion: dict[str, dict[str, int]] = {}
    for prediction, label in zip(predictions, labels, strict=True):
        confusion.setdefault(label, {})
        confusion[label][prediction] = confusion[label].get(prediction, 0) + 1

    return {
        f"{prefix}_accuracy": sum(
            prediction == label for prediction, label in zip(predictions, labels, strict=True)
        ) / len(labels),
        f"{prefix}_precision": statistics.fmean(precision_values),
        f"{prefix}_recall": statistics.fmean(recall_values),
        f"{prefix}_f1": statistics.fmean(f1_values),
        f"{prefix}_confusion": {gold: dict(sorted(preds.items())) for gold, preds in sorted(confusion.items())},
        f"{prefix}_num_samples_used": len(labels),
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
    """Aggregate valid per-sample t0 errors and temporal IoUs.

    Every stage gates its own rows (VLM on ``vlm_has_accident``, the report on the
    verifier decision), so these means describe absolute per-stage quality on
    different sample sets. Use ``paired_temporal_comparison`` for a fair
    VLM-vs-report side-by-side.
    """
    values = list(rows)
    errors = [row["t0_error_s"] for row in values if row.get("t0_error_s") is not None]
    ious = [row["temporal_iou"] for row in values if row.get("temporal_iou") is not None]
    return {
        f"{prefix}_median_t0_error_s": statistics.median(errors) if errors else None,
        f"{prefix}_temporal_iou_mean": statistics.fmean(ious) if ious else None,
        f"{prefix}_temporal_iou_median": statistics.median(ious) if ious else None,
        f"{prefix}_num_samples_used": len(errors),
    }


def paired_temporal_comparison(
    vlm_rows: Sequence[Mapping[str, Any]],
    report_rows: Sequence[Mapping[str, Any]],
    *,
    num_gold_incidents: int,
) -> dict[str, float | int | None]:
    """Compare VLM and report incident-window IoU fairly.

    ``*_temporal_iou_mean`` is scored on each stage's own sample set, so it cannot
    say whether the report improved localisation. This reports two things instead:

    * coverage: how many gold incidents each stage actually localised
      (``t0 != 0`` and predicted has_accident), and
    * a paired IoU mean over only the samples both stages localised, plus the
      report-minus-VLM delta on that shared set.
    """
    if len(vlm_rows) != len(report_rows):
        raise ValueError("vlm_rows and report_rows must be aligned per sample")
    vlm_localised = sum(1 for row in vlm_rows if row.get("temporal_iou") is not None)
    report_localised = sum(1 for row in report_rows if row.get("temporal_iou") is not None)
    pairs = [
        (vlm["temporal_iou"], report["temporal_iou"])
        for vlm, report in zip(vlm_rows, report_rows, strict=True)
        if vlm.get("temporal_iou") is not None and report.get("temporal_iou") is not None
    ]
    vlm_mean = statistics.fmean(value for value, _ in pairs) if pairs else None
    report_mean = statistics.fmean(value for _, value in pairs) if pairs else None
    return {
        "num_gold_incidents": num_gold_incidents,
        "vlm_localised_count": vlm_localised,
        "report_localised_count": report_localised,
        "paired_num_samples": len(pairs),
        "vlm_temporal_iou_mean_paired": vlm_mean,
        "report_temporal_iou_mean_paired": report_mean,
        "report_minus_vlm_temporal_iou_delta": (
            report_mean - vlm_mean if vlm_mean is not None and report_mean is not None else None
        ),
    }


def _member(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _usage_int(usage: Any, key: str) -> int:
    raw = _member(usage, key)
    return int(raw) if isinstance(raw, (int, float)) and raw >= 0 else 0


def sample_resource_usage(model_activities: Iterable[Any], *, wall_time_s: float | None) -> dict[str, Any]:
    """Roll up tokens, provider time and USD cost for one evaluated sample.

    ``model_activities`` is ``IncidentSnapshot.model_activities`` (``ModelActivity``
    objects or their dict form); only ``completed`` calls count. ``cost_usd`` is
    ``None`` when any billed model is missing from ``eval.pricing`` (that model is
    then named in ``unpriced_models``). ``wall_time_s`` is the evaluator's measured
    ``WorkflowService.create`` wall clock; ``model_time_s`` is the summed provider
    call duration and is always ``<= wall_time_s`` for a serial run.
    """
    input_tokens = output_tokens = total_tokens = cached_tokens = 0
    model_time_s = 0.0
    num_requests = 0
    by_model: dict[str, dict[str, Any]] = {}
    unpriced: set[str] = set()
    cost_usd: float | None = 0.0

    for activity in model_activities:
        if _member(activity, "status") != "completed":
            continue
        num_requests += 1
        duration_ms = _member(activity, "duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
            model_time_s += duration_ms / 1000
        model = _member(activity, "model") or "unknown"
        usage = _member(activity, "usage")
        call_input = _usage_int(usage, "input_tokens")
        call_output = _usage_int(usage, "output_tokens")
        call_total = _usage_int(usage, "total_tokens") or (call_input + call_output)
        call_cached = _usage_int(usage, "cached_tokens")
        input_tokens += call_input
        output_tokens += call_output
        total_tokens += call_total
        cached_tokens += call_cached

        entry = by_model.setdefault(
            model,
            {
                "num_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        entry["num_requests"] += 1
        entry["input_tokens"] += call_input
        entry["output_tokens"] += call_output
        entry["total_tokens"] += call_total
        entry["cached_tokens"] += call_cached

        call_cost = model_cost_usd(
            model, input_tokens=call_input, output_tokens=call_output, cached_tokens=call_cached
        )
        if call_cost is None:
            unpriced.add(model)
            entry["cost_usd"] = None
            cost_usd = None
        else:
            if entry["cost_usd"] is not None:
                entry["cost_usd"] += call_cost
            if cost_usd is not None:
                cost_usd += call_cost

    return {
        "wall_time_s": wall_time_s,
        "model_time_s": model_time_s,
        "num_model_requests": num_requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost_usd,
        "unpriced_models": sorted(unpriced),
        "by_model": by_model,
    }


def aggregate_resource_usage(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Average tokens, completion time and USD cost across evaluated samples.

    A sample feeds the token/time means once it recorded at least one completed
    model call, and the cost mean only when every billed model was priced. Each
    ``mean_*`` is ``None`` when no sample qualifies.
    """
    values = [row for row in rows if isinstance(row, Mapping)]
    with_calls = [row for row in values if int(row.get("num_model_requests") or 0) > 0]
    costed = [row for row in with_calls if isinstance(row.get("cost_usd"), (int, float))]
    wall_times = [row["wall_time_s"] for row in with_calls if isinstance(row.get("wall_time_s"), (int, float))]
    unpriced = sorted({model for row in with_calls for model in row.get("unpriced_models", [])})
    costs = [row["cost_usd"] for row in costed]

    def _mean(key: str) -> float | None:
        numbers = [row[key] for row in with_calls if isinstance(row.get(key), (int, float))]
        return statistics.fmean(numbers) if numbers else None

    return {
        "mean_total_tokens": _mean("total_tokens"),
        "mean_input_tokens": _mean("input_tokens"),
        "mean_output_tokens": _mean("output_tokens"),
        "mean_num_model_requests": _mean("num_model_requests"),
        "mean_wall_time_s": statistics.fmean(wall_times) if wall_times else None,
        "mean_model_time_s": _mean("model_time_s"),
        "mean_cost_usd": statistics.fmean(costs) if costs else None,
        "total_cost_usd": sum(costs) if costs else None,
        "num_samples_used": len(with_calls),
        "num_samples_costed": len(costed),
        "unpriced_models": unpriced,
    }
