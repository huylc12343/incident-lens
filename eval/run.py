"""Run the production incident graph against the local golden set.

The evaluator never starts FastAPI and never reimplements workflow behavior.  It
creates the existing runtime from ``src`` with evaluator-only temporary storage,
runs ``WorkflowService.create()``, and reads the graph checkpoint history.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from eval.metrics import (
    aggregate_resource_usage,
    aggregate_temporal_errors,
    binary_incident_metrics,
    evidence_id_validity,
    multiclass_metrics,
    paired_temporal_comparison,
    report_decision_consistency,
    sample_resource_usage,
    status_distribution,
    temporal_iou,
)
from src.config import get_settings
from src.models.api import IncidentCreateRequest
from src.models.incidents import ReportModelOutput, VerificationResult, VideoMemory
from src.services.incident_runtime import ProviderClients, incident_workflow_service


@dataclass(frozen=True)
class GoldenSample:
    sample_id: str
    video_uri: Path
    log_uri: Path | None
    label: dict[str, Any]


class CaptureResponses:
    """Delegate the existing OpenAI client while retaining raw parsed output locally."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client
        self.parsed_outputs: list[dict[str, Any] | None] = []
        self.responses = SimpleNamespace(parse=self._parse)

    async def _parse(self, *args: Any, **kwargs: Any) -> Any:
        response = await self._client.responses.parse(*args, **kwargs)
        parsed = getattr(response, "output_parsed", None)
        self.parsed_outputs.append(_json_value(parsed) if parsed is not None else None)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def discover_samples(golden_root: Path) -> list[GoldenSample]:
    """Load only the directory layout fixed by the evaluation plan."""
    if not golden_root.is_dir():
        raise ValueError(f"golden set directory does not exist: {golden_root}")

    samples: list[GoldenSample] = []
    for label_path in sorted(golden_root.glob("*/labels/*.json")):
        sample_root = label_path.parents[1]
        label = _read_json(label_path)
        # A reviewer marks a sample unusable (bad annotation, unresolved
        # inconsistency) with "eval_exclude": true; skip it before any validation.
        if label.get("eval_exclude") is True:
            continue
        sample_id = label.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError(f"{label_path} must contain a non-empty sample_id")
        videos = sorted((sample_root / "input").glob("*.mp4"))
        if len(videos) != 1:
            raise ValueError(f"{sample_root} must contain exactly one input/*.mp4")
        logs = sorted((sample_root / "input").glob("*.csv"))
        if len(logs) > 1:
            raise ValueError(f"{sample_root} must contain at most one input/*.csv")
        samples.append(GoldenSample(sample_id, videos[0], logs[0] if logs else None, label))
    if not samples:
        raise ValueError(f"no labels found below {golden_root}")
    return samples


async def evaluate_sample(
    sample: GoldenSample,
    *,
    analysis_prompt: str,
    golden_root: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    """Run one golden sample through the existing production workflow."""
    base_settings = get_settings()
    settings = base_settings.model_copy(
        update={
            "incident_input_roots": ",".join(
                item for item in (base_settings.incident_input_roots, str(golden_root.resolve())) if item
            ),
            "artifact_dir": str(runtime_root / "artifacts"),
            "incident_database_path": str(runtime_root / "reports.sqlite3"),
            "incident_checkpoint_path": str(runtime_root / "checkpoints.sqlite3"),
            # Raw evaluator captures stay local and are not sent to a trace.
            "langsmith_tracing": False,
        }
    )
    verification_client = CaptureResponses(AsyncOpenAI(api_key=settings.openai_api_key))
    report_client = CaptureResponses(AsyncOpenAI(api_key=settings.openai_api_key))
    clients = ProviderClients(
        openai_verification=verification_client,
        openai_report=report_client,
    )
    request = IncidentCreateRequest(
        incident_id=sample.sample_id,
        video_uri=str(sample.video_uri),
        log_uri=str(sample.log_uri) if sample.log_uri is not None else None,
        analysis_prompt=analysis_prompt,
        metadata={"evaluation_sample_id": sample.sample_id},
    )
    async with incident_workflow_service(settings, clients=clients) as service:
        started_at = time.perf_counter()
        snapshot = await service.create(request)
        wall_time_s = time.perf_counter() - started_at
        states = await _state_history(service, sample.sample_id)

    resource = sample_resource_usage(snapshot.model_activities, wall_time_s=wall_time_s)
    stage_states = _select_stage_states(states)
    final_state = stage_states["final"]
    auto_reanalysis_attempted = _node_was_scheduled(states, "auto_reanalyze")
    manual_reanalysis_attempted = _node_was_scheduled(states, "manual_reanalyze")
    workflow_error = _workflow_error(snapshot.status, final_state)
    initial_memory = _optional_model(stage_states["vlm_initial"].get("video_memory"), VideoMemory)
    if initial_memory is None:
        return _failed_sample(
            sample,
            snapshot.status,
            final_state,
            analysis_prompt,
            auto_reanalysis_attempted=auto_reanalysis_attempted,
            manual_reanalysis_attempted=manual_reanalysis_attempted,
            workflow_error=workflow_error,
            resource=resource,
        )
    final_verification = _optional_model(final_state.get("verification"), VerificationResult)
    raw_verification = _last_raw_output(verification_client.parsed_outputs)
    raw_report = _last_model_output(report_client.parsed_outputs)
    return _evaluate_snapshot(
        sample=sample,
        public_status=snapshot.status,
        initial_memory=initial_memory,
        final_verification=final_verification,
        raw_verification=raw_verification,
        raw_report=raw_report,
        resource=resource,
        allowed_ids_by_claim=_allowed_evidence_ids(final_state),
        auto_reanalysis_count=final_state.get("auto_reanalysis_count", 0),
        manual_reanalysis_count=final_state.get("manual_reanalysis_count", 0),
        auto_reanalysis_attempted=auto_reanalysis_attempted,
        manual_reanalysis_attempted=manual_reanalysis_attempted,
        workflow_error=workflow_error,
        warnings=final_state.get("warnings", []),
        analysis_prompt=analysis_prompt,
    )


async def evaluate_dataset(
    golden_root: Path,
    *,
    analysis_prompt: str,
    results_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    samples = discover_samples(golden_root)
    results_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="incident-eval-") as temp_dir:
        runtime_root = Path(temp_dir)
        rows: list[dict[str, Any]] = []
        for sample in samples:
            result_path = _sample_result_path(results_dir, sample.sample_id)
            previous = _read_completed_sample(result_path, sample.sample_id, analysis_prompt)
            if previous is not None and not force:
                print(f"Skipping completed sample: {sample.sample_id}")
                rows.append(previous)
                continue
            try:
                row = await evaluate_sample(
                    sample,
                    analysis_prompt=analysis_prompt,
                    golden_root=golden_root,
                    runtime_root=runtime_root / sample.sample_id,
                )
            except Exception as exc:
                row = _evaluation_exception_sample(sample, analysis_prompt, exc)
            _write_json(result_path, row)
            rows.append(row)
            print(f"Saved sample result: {result_path}")

    failed_rows = [row for row in rows if _sample_failure(row) is not None]
    metric = {
        "generated_at": datetime.now(UTC).isoformat(),
        "golden_set": str(golden_root),
        "num_samples_total": len(rows),
        "num_samples_completed": len(rows) - len(failed_rows),
        "failed_samples": [
            {
                "sample_id": row["sample_id"],
                "workflow_status": row.get("workflow_status"),
                "error": _sample_failure(row),
            }
            for row in failed_rows
        ],
        "aggregate": _aggregate(
            rows,
            [_required_bool(sample.label, "is_incident") for sample in samples],
            [_required_incident_type(sample.label) for sample in samples],
        ),
    }
    _write_json(results_dir / "metric.json", metric)
    return metric


def _evaluate_snapshot(
    *,
    sample: GoldenSample,
    public_status: str,
    initial_memory: VideoMemory,
    final_verification: VerificationResult | None,
    raw_verification: dict[str, Any] | None,
    raw_report: ReportModelOutput | None,
    resource: dict[str, Any],
    allowed_ids_by_claim: dict[str, list[str]],
    auto_reanalysis_count: Any,
    manual_reanalysis_count: Any,
    auto_reanalysis_attempted: bool,
    manual_reanalysis_attempted: bool,
    workflow_error: str | None,
    warnings: Any,
    analysis_prompt: str,
) -> dict[str, Any]:
    gold_incident = _required_bool(sample.label, "is_incident")
    gold_window = _gold_window(sample.label, gold_incident)
    vlm_pred = initial_memory.vlm_has_accident
    vlm_timing = _timing_row(initial_memory.incident_window.model_dump(), gold_window, gold_incident, vlm_pred)
    report_payload = raw_report.model_dump(mode="json") if raw_report is not None else None
    report_timing = (
        _timing_row(report_payload["incident_window"], gold_window, gold_incident, final_verification.has_accident)
        if report_payload is not None and final_verification is not None
        else {"t0_error_s": None, "temporal_iou": None}
    )
    raw_results = raw_verification.get("results", []) if raw_verification is not None else []
    return {
        "sample_id": sample.sample_id,
        "analysis_prompt": analysis_prompt,
        "workflow_status": public_status,
        "auto_reanalysis_count": auto_reanalysis_count if isinstance(auto_reanalysis_count, int) else 0,
        "manual_reanalysis_count": manual_reanalysis_count if isinstance(manual_reanalysis_count, int) else 0,
        "auto_reanalysis_attempted": auto_reanalysis_attempted,
        "manual_reanalysis_attempted": manual_reanalysis_attempted,
        "has_reanalyze": auto_reanalysis_attempted or manual_reanalysis_attempted,
        "workflow_error": workflow_error,
        "warnings": warnings if isinstance(warnings, list) else [],
        "model_outputs": {
            "vlm_initial": initial_memory.model_dump(mode="json"),
            "verification_final": final_verification.model_dump(mode="json") if final_verification else None,
            "verification_raw_final": raw_verification,
            "verification_allowed_evidence_ids": allowed_ids_by_claim,
            "report_final": report_payload,
        },
        "metrics": {
            "vlm": {"has_accident": vlm_pred, **vlm_timing},
            "verifier": {
                "has_accident": final_verification.has_accident if final_verification else None,
                "evidence_id_validity": evidence_id_validity(raw_results, allowed_ids_by_claim),
                "status_distribution": status_distribution(raw_results),
            },
            "report": {
                "type_of_accident": report_payload["type_of_accident"] if report_payload else None,
                "has_accident": final_verification.has_accident if final_verification else None,
                **report_timing,
            },
            "resource": resource,
        },
    }


def _failed_sample(
    sample: GoldenSample,
    public_status: str,
    state: dict[str, Any],
    analysis_prompt: str,
    *,
    auto_reanalysis_attempted: bool,
    manual_reanalysis_attempted: bool,
    workflow_error: str | None,
    resource: dict[str, Any],
) -> dict[str, Any]:
    """Preserve a production workflow failure without inventing a score."""
    error_code = state.get("error_code")
    error_message = state.get("error_message")
    detail = ": ".join(
        item for item in (error_code, error_message) if isinstance(item, str) and item
    ) or "workflow ended before VideoMemory was available"
    return {
        "sample_id": sample.sample_id,
        "analysis_prompt": analysis_prompt,
        "workflow_status": public_status,
        "auto_reanalysis_count": 0,
        "manual_reanalysis_count": 0,
        "auto_reanalysis_attempted": auto_reanalysis_attempted,
        "manual_reanalysis_attempted": manual_reanalysis_attempted,
        "has_reanalyze": auto_reanalysis_attempted or manual_reanalysis_attempted,
        "workflow_error": workflow_error,
        "warnings": state.get("warnings", []) if isinstance(state.get("warnings"), list) else [],
        "evaluation_error": detail,
        "model_outputs": {
            "vlm_initial": None,
            "verification_final": None,
            "verification_raw_final": None,
            "verification_allowed_evidence_ids": {},
            "report_final": None,
        },
        "metrics": {
            "vlm": {"has_accident": None, "t0_error_s": None, "temporal_iou": None},
            "verifier": {
                "has_accident": None,
                "evidence_id_validity": evidence_id_validity([], {}),
                "status_distribution": status_distribution([]),
            },
            "report": {
                "type_of_accident": None,
                "has_accident": None,
                "t0_error_s": None,
                "temporal_iou": None,
            },
            "resource": resource,
        },
    }


def _evaluation_exception_sample(sample: GoldenSample, analysis_prompt: str, exc: Exception) -> dict[str, Any]:
    """Persist evaluator failures, such as a network error from the event judge."""
    return {
        "sample_id": sample.sample_id,
        "analysis_prompt": analysis_prompt,
        "workflow_status": "failed",
        "auto_reanalysis_count": 0,
        "manual_reanalysis_count": 0,
        "auto_reanalysis_attempted": False,
        "manual_reanalysis_attempted": False,
        "has_reanalyze": False,
        "workflow_error": None,
        "warnings": [],
        "evaluation_error": f"EVALUATION_FAILED: {exc}",
        "model_outputs": {
            "vlm_initial": None,
            "verification_final": None,
            "verification_raw_final": None,
            "verification_allowed_evidence_ids": {},
            "report_final": None,
        },
        "metrics": {
            "vlm": {"has_accident": None, "t0_error_s": None, "temporal_iou": None},
            "verifier": {
                "has_accident": None,
                "evidence_id_validity": evidence_id_validity([], {}),
                "status_distribution": status_distribution([]),
            },
            "report": {
                "type_of_accident": None,
                "has_accident": None,
                "t0_error_s": None,
                "temporal_iou": None,
            },
            "resource": sample_resource_usage([], wall_time_s=None),
        },
    }


def _aggregate(rows: list[dict[str, Any]], labels: list[bool], incident_types: list[str]) -> dict[str, Any]:
    vlm_predictions = [row["metrics"]["vlm"]["has_accident"] for row in rows]
    verifier_predictions = [row["metrics"]["verifier"]["has_accident"] for row in rows]
    report_predictions = [row["metrics"]["report"]["type_of_accident"] for row in rows]
    return _aggregate_without_labels(rows, labels, incident_types, vlm_predictions, verifier_predictions, report_predictions)


def _aggregate_without_labels(
    rows: list[dict[str, Any]],
    labels: list[bool],
    incident_types: list[str],
    vlm_predictions: list[Any],
    verifier_predictions: list[Any],
    report_predictions: list[Any],
) -> dict[str, Any]:
    # Kept separate only to make every metric input explicit and testable.
    valid_vlm = [(prediction, label) for prediction, label in zip(vlm_predictions, labels, strict=True) if isinstance(prediction, bool)]
    valid_verifier = [
        (prediction, label)
        for prediction, label in zip(verifier_predictions, labels, strict=True)
        if isinstance(prediction, bool)
    ]
    valid_report_types = [
        (prediction, label)
        for prediction, label in zip(report_predictions, incident_types, strict=True)
        if isinstance(prediction, str)
    ]
    vlm_rows = [row["metrics"]["vlm"] for row in rows]
    report_rows = [row["metrics"]["report"] for row in rows]
    resource_rows = [row["metrics"].get("resource", {}) for row in rows]
    raw_verifier_rows = [row["model_outputs"]["verification_raw_final"] for row in rows]
    all_raw_results = [
        result
        for raw in raw_verifier_rows
        if isinstance(raw, dict)
        for result in raw.get("results", [])
        if isinstance(result, dict)
    ]
    evidence_metrics = [row["metrics"]["verifier"]["evidence_id_validity"] for row in rows]
    invalid_ids = [item for metric in evidence_metrics for item in metric["invalid_evidence_ids"]]
    aggregate_evidence = _aggregate_evidence(rows)
    return {
        "vlm": {
            **binary_incident_metrics(
                [prediction for prediction, _ in valid_vlm],
                [label for _, label in valid_vlm],
                prefix="vlm_incident",
            ),
            **aggregate_temporal_errors(vlm_rows, prefix="vlm"),
            "num_incident_samples_used": len(valid_vlm),
        },
        "verifier": {
            **binary_incident_metrics(
                [prediction for prediction, _ in valid_verifier],
                [label for _, label in valid_verifier],
                prefix="verifier_incident",
            ),
            "evidence_id_precision": aggregate_evidence["evidence_id_precision"],
            "claim_evidence_validity_rate": aggregate_evidence["claim_evidence_validity_rate"],
            "invalid_evidence_ids": invalid_ids,
            "status_distribution": status_distribution(all_raw_results),
            "num_verifier_samples_used": len(valid_verifier),
            "num_verification_results": len(all_raw_results),
        },
        "report": {
            **report_decision_consistency(report_rows),
            **aggregate_temporal_errors(report_rows, prefix="report"),
            **multiclass_metrics(
                [prediction for prediction, _ in valid_report_types],
                [label for _, label in valid_report_types],
                prefix="type_of_accident",
            ),
        },
        "temporal_comparison": paired_temporal_comparison(
            vlm_rows, report_rows, num_gold_incidents=sum(labels)
        ),
        "resource": aggregate_resource_usage(resource_rows),
    }


def _aggregate_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    predicted_ids = 0
    valid_ids = 0
    valid_claims = 0
    claim_count = 0
    invalid_ids: list[str] = []
    for row in rows:
        raw = row["model_outputs"]["verification_raw_final"]
        if not isinstance(raw, dict):
            continue
        allowed = row["model_outputs"]["verification_allowed_evidence_ids"]
        for result in raw.get("results", []):
            if not isinstance(result, dict) or not isinstance(result.get("claim_id"), str):
                continue
            claim_count += 1
            evidence_ids = result.get("evidence_ids", [])
            if not isinstance(evidence_ids, list):
                evidence_ids = []
            allowed_ids = set(allowed.get(result["claim_id"], []))
            invalid = [item for item in evidence_ids if not isinstance(item, str) or item not in allowed_ids]
            if not invalid:
                valid_claims += 1
            for evidence_id in evidence_ids:
                if isinstance(evidence_id, str) and evidence_id in allowed_ids:
                    valid_ids += 1
                else:
                    invalid_ids.append(str(evidence_id))
                predicted_ids += 1
    return {
        "evidence_id_precision": valid_ids / predicted_ids if predicted_ids else None,
        "claim_evidence_validity_rate": valid_claims / claim_count if claim_count else None,
        "invalid_evidence_ids": invalid_ids,
    }


async def _state_history(service: Any, incident_id: str) -> list[dict[str, Any]]:
    runner = getattr(service, "_runner")
    graph = getattr(runner, "_graph")
    states: list[dict[str, Any]] = []
    async for snapshot in graph.aget_state_history(runner.thread_config(incident_id)):
        states.append({"next": tuple(snapshot.next), "values": dict(snapshot.values)})
    return list(reversed(states))


def _select_stage_states(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not states:
        raise RuntimeError("workflow did not write a checkpoint")
    initial_vlm = next(
        (state["values"] for state in states if state["next"] == ("map_canonical_evidence",)),
        {},
    )
    verification_states = [
        state["values"]
        for state in states
        if "verification" in state["values"]
        and state["next"] in {("auto_reanalyze",), ("draft_report",)}
    ]
    final = states[-1]["values"]
    return {
        "vlm_initial": initial_vlm,
        "verification_initial": verification_states[0] if verification_states else final,
        "verification_final": verification_states[-1] if verification_states else final,
        "final": final,
    }


def _node_was_scheduled(states: list[dict[str, Any]], node_name: str) -> bool:
    """Return whether a graph node was reached, including attempts that failed."""
    return any(node_name in state.get("next", ()) for state in states)


def _workflow_error(public_status: str, state: dict[str, Any]) -> str | None:
    """Preserve a graph failure even when earlier stages produced usable outputs."""
    if public_status != "failed":
        return None
    code = state.get("error_code")
    message = state.get("error_message")
    detail = ": ".join(item for item in (code, message) if isinstance(item, str) and item)
    return detail or "WORKFLOW_FAILED: graph ended with status=failed without an error detail"


def _timing_row(
    prediction: dict[str, Any], gold: dict[str, float], gold_incident: bool, prediction_incident: bool | None
) -> dict[str, float | None]:
    if not gold_incident or prediction_incident is not True or prediction["t0"] == 0:
        return {"t0_error_s": None, "temporal_iou": None}
    return {
        "t0_error_s": abs(float(prediction["t0"]) - gold["t0"]),
        "temporal_iou": temporal_iou(
            pred_start=float(prediction["t_start"]),
            pred_end=float(prediction["t_end"]),
            gold_start=gold["t_start"],
            gold_end=gold["t_end"],
        ),
    }


def _last_raw_output(values: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    for value in reversed(values):
        if isinstance(value, dict):
            return value
    return None


def _last_model_output(values: list[dict[str, Any] | None]) -> ReportModelOutput | None:
    for value in reversed(values):
        if isinstance(value, dict):
            try:
                return ReportModelOutput.model_validate(value)
            except ValidationError:
                continue
    return None


def _allowed_evidence_ids(state: dict[str, Any]) -> dict[str, list[str]]:
    summaries = state.get("claim_log_summaries", [])
    return {
        summary.claim_id: list(summary.allowed_evidence_ids)
        for summary in summaries
        if hasattr(summary, "claim_id") and hasattr(summary, "allowed_evidence_ids")
    }


_WINDOW_FIELDS = ("t_start", "t0", "t_end")


def _required_window(value: Any, name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return {field: float(value[field]) for field in _WINDOW_FIELDS}


def _gold_window(label: dict[str, Any], gold_incident: bool) -> dict[str, float]:
    """Numeric incident window for scoring.

    An incident sample must carry a numeric ``t_start/t0/t_end``. A non-incident
    sample may legitimately have a null (or absent) timeline; timing metrics gate
    on ``gold_incident`` and never read the window in that case, so return zeros.
    """
    timeline = label.get("timeline")
    if gold_incident:
        return _required_window(timeline, "label.timeline")
    if isinstance(timeline, dict) and all(
        isinstance(timeline.get(field), (int, float)) for field in _WINDOW_FIELDS
    ):
        return {field: float(timeline[field]) for field in _WINDOW_FIELDS}
    return dict.fromkeys(_WINDOW_FIELDS, 0.0)


def _required_bool(value: dict[str, Any], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise ValueError(f"{name} must be a boolean")
    return result


def _required_incident_type(label: dict[str, Any]) -> str:
    incident_type = label.get("incident_type")
    if not isinstance(incident_type, str) or not incident_type:
        raise ValueError("label.incident_type must be a non-empty string")
    return incident_type


def _sample_result_path(results_dir: Path, sample_id: str) -> Path:
    if Path(sample_id).name != sample_id or sample_id in {"", ".", ".."}:
        raise ValueError(f"sample_id is not a safe file name: {sample_id!r}")
    return results_dir / f"{sample_id}.json"


def _read_completed_sample(path: Path, sample_id: str, analysis_prompt: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        row = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if (
        row.get("sample_id") == sample_id
        and row.get("analysis_prompt") == analysis_prompt
        and _sample_failure(row) is None
    ):
        return row
    return None


def _sample_failure(row: dict[str, Any]) -> str | None:
    """Return an evaluator or production-workflow failure stored in one sample row."""
    for field in ("evaluation_error", "workflow_error"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value
    if row.get("workflow_status") == "failed":
        return "WORKFLOW_FAILED: graph ended with status=failed without an error detail"
    return None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def _optional_model(value: Any, model: type[BaseModel]) -> Any | None:
    return value if isinstance(value, model) else None


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _json_value(value: Any) -> dict[str, Any] | None:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the production incident graph against golden_set.")
    parser.add_argument("--golden-set", type=Path, default=Path("golden_set"))
    parser.add_argument("--analysis-prompt", required=True, help="The fixed user prompt to use for every sample.")
    parser.add_argument("--results-dir", type=Path, default=Path("eval/results"))
    parser.add_argument("--force", action="store_true", help="Run successful samples again instead of reusing their JSON.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    metric = asyncio.run(
        evaluate_dataset(
            args.golden_set,
            analysis_prompt=args.analysis_prompt,
            results_dir=args.results_dir,
            force=args.force,
        )
    )
    for sample in metric["failed_samples"]:
        print(f"Evaluation failed for {sample['sample_id']}: {sample['error']}")
    print(f"Evaluation complete: {args.results_dir / 'metric.json'}")


if __name__ == "__main__":
    main()
