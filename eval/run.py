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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.metrics import (
    aggregate_event_mae,
    aggregate_temporal_errors,
    binary_incident_metrics,
    evidence_id_validity,
    report_decision_consistency,
    status_distribution,
    temporal_iou,
)
from src.config import get_settings
from src.models.api import IncidentCreateRequest
from src.models.incidents import ReportModelOutput, VerificationResult, VideoMemory
from src.services.incident_runtime import ProviderClients, incident_workflow_service
from src.services.llm import get_llm


@dataclass(frozen=True)
class GoldenSample:
    sample_id: str
    video_uri: Path
    log_uri: Path | None
    label: dict[str, Any]


class EventMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gold_event_index: int = Field(ge=0)
    pred_event_index: int = Field(ge=0)
    gold_event_type: str = Field(min_length=1)
    gold_timestamp: float = Field(ge=0)
    pred_timestamp: float = Field(ge=0)


class EventMatches(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[EventMatch] = Field(default_factory=list)


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


async def semantic_event_matches(label: dict[str, Any], memory: VideoMemory) -> list[dict[str, Any]]:
    """Use the configured ``src.services.llm.get_llm`` semantic judge for event matching."""
    candidates = [
        {"pred_event_index": index, "timestamp": event.timestamp_s, "text": event.description}
        for index, event in enumerate(memory.timeline)
    ] + [
        {
            "pred_event_index": len(memory.timeline) + index,
            "timestamp": claim.timestamp_s,
            "text": claim.text,
        }
        for index, claim in enumerate(memory.claims)
        if claim.timestamp_s is not None
    ]
    events = label.get("evaluation_events", [])
    if not candidates or not isinstance(events, list):
        return []
    prompt = (
        "Đối chiếu semantic các gold event với event dự đoán. Chỉ match khi cùng sự kiện/diễn biến; "
        "mỗi gold_event_index và pred_event_index được dùng tối đa một lần. Không match chỉ vì timestamp gần nhau. "
        "Trả matches với nguyên event type và timestamp đã cho, không tạo event mới."
    )
    judge = get_llm().with_structured_output(EventMatches)
    result = await judge.ainvoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(
                content=json.dumps(
                    {"gold_events": events, "predicted_events": candidates},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        ]
    )
    if not isinstance(result, EventMatches):
        result = EventMatches.model_validate(result)
    _validate_event_matches(result.matches, events, candidates)
    return [item.model_dump(mode="json") for item in result.matches]


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
        snapshot = await service.create(request)
        states = await _state_history(service, sample.sample_id)

    stage_states = _select_stage_states(states)
    final_state = stage_states["final"]
    initial_memory = _optional_model(stage_states["vlm_initial"].get("video_memory"), VideoMemory)
    if initial_memory is None:
        return _failed_sample(sample, snapshot.status, final_state)
    final_verification = _optional_model(final_state.get("verification"), VerificationResult)
    raw_verification = _last_raw_output(verification_client.parsed_outputs)
    raw_report = _last_model_output(report_client.parsed_outputs)
    matches = await semantic_event_matches(sample.label, initial_memory)
    return _evaluate_snapshot(
        sample=sample,
        public_status=snapshot.status,
        initial_memory=initial_memory,
        final_verification=final_verification,
        raw_verification=raw_verification,
        raw_report=raw_report,
        matches=matches,
        allowed_ids_by_claim=_allowed_evidence_ids(final_state),
        auto_reanalysis_count=final_state.get("auto_reanalysis_count", 0),
        warnings=final_state.get("warnings", []),
    )


async def evaluate_dataset(golden_root: Path, *, analysis_prompt: str) -> dict[str, Any]:
    samples = discover_samples(golden_root)
    with tempfile.TemporaryDirectory(prefix="incident-eval-") as temp_dir:
        runtime_root = Path(temp_dir)
        rows = [
            await evaluate_sample(
                sample,
                analysis_prompt=analysis_prompt,
                golden_root=golden_root,
                runtime_root=runtime_root / sample.sample_id,
            )
            for sample in samples
        ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "golden_set": str(golden_root),
        "samples": rows,
        "aggregate": _aggregate(rows, [_required_bool(sample.label, "is_incident") for sample in samples]),
    }


def _evaluate_snapshot(
    *,
    sample: GoldenSample,
    public_status: str,
    initial_memory: VideoMemory,
    final_verification: VerificationResult | None,
    raw_verification: dict[str, Any] | None,
    raw_report: ReportModelOutput | None,
    matches: list[dict[str, Any]],
    allowed_ids_by_claim: dict[str, list[str]],
    auto_reanalysis_count: Any,
    warnings: Any,
) -> dict[str, Any]:
    gold_incident = _required_bool(sample.label, "is_incident")
    gold_window = _required_window(sample.label["timeline"], "label.timeline")
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
        "workflow_status": public_status,
        "auto_reanalysis_count": auto_reanalysis_count if isinstance(auto_reanalysis_count, int) else 0,
        "warnings": warnings if isinstance(warnings, list) else [],
        "model_outputs": {
            "vlm_initial": initial_memory.model_dump(mode="json"),
            "verification_final": final_verification.model_dump(mode="json") if final_verification else None,
            "verification_raw_final": raw_verification,
            "verification_allowed_evidence_ids": allowed_ids_by_claim,
            "report_final": report_payload,
        },
        "metrics": {
            "vlm": {"has_accident": vlm_pred, **vlm_timing, "event_matches": matches},
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
        },
    }


def _failed_sample(sample: GoldenSample, public_status: str, state: dict[str, Any]) -> dict[str, Any]:
    """Preserve a production workflow failure without inventing a score."""
    error_code = state.get("error_code")
    error_message = state.get("error_message")
    detail = ": ".join(
        item for item in (error_code, error_message) if isinstance(item, str) and item
    ) or "workflow ended before VideoMemory was available"
    return {
        "sample_id": sample.sample_id,
        "workflow_status": public_status,
        "auto_reanalysis_count": 0,
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
            "vlm": {"has_accident": None, "t0_error_s": None, "temporal_iou": None, "event_matches": []},
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
        },
    }


def _aggregate(rows: list[dict[str, Any]], labels: list[bool]) -> dict[str, Any]:
    vlm_predictions = [row["metrics"]["vlm"]["has_accident"] for row in rows]
    verifier_predictions = [row["metrics"]["verifier"]["has_accident"] for row in rows]
    return _aggregate_without_labels(rows, labels, vlm_predictions, verifier_predictions)


def _aggregate_without_labels(
    rows: list[dict[str, Any]],
    labels: list[bool],
    vlm_predictions: list[Any],
    verifier_predictions: list[Any],
) -> dict[str, Any]:
    # Kept separate only to make every metric input explicit and testable.
    valid_vlm = [(prediction, label) for prediction, label in zip(vlm_predictions, labels, strict=True) if isinstance(prediction, bool)]
    valid_verifier = [
        (prediction, label)
        for prediction, label in zip(verifier_predictions, labels, strict=True)
        if isinstance(prediction, bool)
    ]
    vlm_rows = [row["metrics"]["vlm"] for row in rows]
    report_rows = [row["metrics"]["report"] for row in rows]
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
            **aggregate_event_mae(vlm_rows),
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
            "type_of_accident_f1": None,
            "type_of_accident_note": (
                "Not calculated: plan's golden incident_type taxonomy is not mapped to AccidentType."
            ),
        },
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


def _validate_event_matches(
    matches: list[EventMatch], gold_events: list[Any], candidates: list[dict[str, Any]]
) -> None:
    used_gold: set[int] = set()
    used_predictions: set[int] = set()
    for match in matches:
        if match.gold_event_index >= len(gold_events) or match.pred_event_index >= len(candidates):
            raise ValueError("semantic judge returned an event index outside the input")
        if match.gold_event_index in used_gold or match.pred_event_index in used_predictions:
            raise ValueError("semantic judge must return one-to-one event matches")
        gold = gold_events[match.gold_event_index]
        predicted = candidates[match.pred_event_index]
        if match.gold_event_type != gold.get("event_type") or match.gold_timestamp != gold.get("timestamp"):
            raise ValueError("semantic judge must copy the gold event type and timestamp")
        if match.pred_timestamp != predicted["timestamp"]:
            raise ValueError("semantic judge must copy the predicted timestamp")
        used_gold.add(match.gold_event_index)
        used_predictions.add(match.pred_event_index)


def _required_window(value: Any, name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return {field: float(value[field]) for field in ("t_start", "t0", "t_end")}


def _required_bool(value: dict[str, Any], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise ValueError(f"{name} must be a boolean")
    return result


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
    parser.add_argument("--output", type=Path, default=Path("eval/results/latest.json"))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = asyncio.run(evaluate_dataset(args.golden_set, analysis_prompt=args.analysis_prompt))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for sample in result["samples"]:
        if error := sample.get("evaluation_error"):
            print(f"Evaluation failed for {sample['sample_id']}: {error}")
    print(f"Evaluation complete: {args.output}")


if __name__ == "__main__":
    main()
