import json

import pytest

from eval.metrics import (
    aggregate_event_mae,
    binary_incident_metrics,
    evidence_id_validity,
    multiclass_metrics,
    report_decision_consistency,
    temporal_iou,
)
from eval.run import (
    _node_was_scheduled,
    _read_completed_sample,
    _sample_failure,
    _sample_result_path,
    _workflow_error,
    _write_json,
    discover_samples,
)


def test_temporal_iou_matches_plan_formula() -> None:
    assert temporal_iou(pred_start=10, pred_end=12, gold_start=11, gold_end=13) == 1 / 3


def test_binary_incident_metrics_include_confusion_matrix() -> None:
    result = binary_incident_metrics([True, True, False, False], [True, False, True, False], prefix="vlm_incident")
    assert result == {
        "vlm_incident_precision": 0.5,
        "vlm_incident_recall": 0.5,
        "vlm_incident_f1": 0.5,
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "tn": 1,
    }


def test_multiclass_metrics_scores_exact_type_match() -> None:
    assert multiclass_metrics(
        ["crossing_collision"], ["crossing_collision"], prefix="type_of_accident"
    ) == {
        "type_of_accident_precision": 1.0,
        "type_of_accident_recall": 1.0,
        "type_of_accident_f1": 1.0,
        "num_samples_used": 1,
    }


def test_evidence_validity_excludes_empty_lists_from_id_denominator() -> None:
    result = evidence_id_validity(
        [
            {"claim_id": "one", "evidence_ids": ["allowed", "invented"]},
            {"claim_id": "two", "evidence_ids": []},
        ],
        {"one": ["allowed"], "two": []},
    )
    assert result == {
        "evidence_id_precision": 0.5,
        "claim_evidence_validity_rate": 0.5,
        "invalid_evidence_ids": ["invented"],
    }


def test_event_mae_is_null_without_semantic_matches() -> None:
    assert aggregate_event_mae([{"event_matches": []}]) == {
        "event_timestamp_mae_s": None,
        "num_matched_events": 0,
    }


def test_event_mae_uses_per_sample_event_matches() -> None:
    result = aggregate_event_mae(
        [{"event_matches": [{"gold_timestamp": 10.0, "pred_timestamp": 10.2}]}]
    )
    assert result["event_timestamp_mae_s"] == pytest.approx(0.2)
    assert result["num_matched_events"] == 1


def test_report_consistency_skips_missing_verification() -> None:
    result = report_decision_consistency(
        [
            {"has_accident": False, "type_of_accident": "no_incident"},
            {"has_accident": True, "type_of_accident": "no_incident"},
            {"has_accident": None, "type_of_accident": "other_unknown"},
        ]
    )
    assert result == {"report_decision_consistency": 0.5, "passed": 1, "eligible": 2}


def test_discover_samples_uses_fixed_golden_layout(tmp_path) -> None:
    sample_root = tmp_path / "Data_001"
    (sample_root / "input").mkdir(parents=True)
    (sample_root / "labels").mkdir()
    (sample_root / "input" / "video.mp4").touch()
    (sample_root / "input" / "telemetry.csv").touch()
    (sample_root / "labels" / "ground_truth.json").write_text(
        '{"sample_id":"sample-1","is_incident":true,"timeline":{"t_start":0,"t0":1,"t_end":2}}',
        encoding="utf-8",
    )

    samples = discover_samples(tmp_path)

    assert [(sample.sample_id, sample.video_uri.name, sample.log_uri.name) for sample in samples] == [
        ("sample-1", "video.mp4", "telemetry.csv")
    ]


def test_completed_sample_is_reused_only_for_the_same_prompt(tmp_path) -> None:
    path = _sample_result_path(tmp_path, "sample-1")
    _write_json(path, {"sample_id": "sample-1", "analysis_prompt": "fixed prompt"})

    assert _read_completed_sample(path, "sample-1", "fixed prompt") is not None
    assert _read_completed_sample(path, "sample-1", "another prompt") is None


def test_failed_workflow_is_not_reused_and_is_reported_as_failed(tmp_path) -> None:
    path = _sample_result_path(tmp_path, "sample-1")
    _write_json(
        path,
        {
            "sample_id": "sample-1",
            "analysis_prompt": "fixed prompt",
            "workflow_status": "failed",
        },
    )

    assert _read_completed_sample(path, "sample-1", "fixed prompt") is None
    assert _sample_failure(json.loads(path.read_text(encoding="utf-8"))) == (
        "WORKFLOW_FAILED: graph ended with status=failed without an error detail"
    )


def test_reanalysis_attempt_and_workflow_error_are_preserved() -> None:
    states = [{"next": ("verify",)}, {"next": ("auto_reanalyze",)}, {"next": ()}]

    assert _node_was_scheduled(states, "auto_reanalyze") is True
    assert _node_was_scheduled(states, "manual_reanalyze") is False
    assert _workflow_error("failed", {"error_code": "AUTO_REANALYSIS_FAILED", "error_message": "provider error"}) == (
        "AUTO_REANALYSIS_FAILED: provider error"
    )
