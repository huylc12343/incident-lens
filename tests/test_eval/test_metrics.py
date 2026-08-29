import json

import pytest

from eval.metrics import (
    aggregate_resource_usage,
    binary_incident_metrics,
    evidence_id_validity,
    multiclass_metrics,
    paired_temporal_comparison,
    report_decision_consistency,
    sample_resource_usage,
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
        "type_of_accident_accuracy": 1.0,
        "type_of_accident_precision": 1.0,
        "type_of_accident_recall": 1.0,
        "type_of_accident_f1": 1.0,
        "type_of_accident_confusion": {"crossing_collision": {"crossing_collision": 1}},
        "type_of_accident_num_samples_used": 1,
    }


def test_multiclass_metrics_is_case_insensitive_and_reports_confusion() -> None:
    result = multiclass_metrics(
        ["crossing_collision", "vehicle_collision", "no_incident"],
        ["Crossing_collision", "crossing_collision", "no_incident"],
        prefix="t",
    )
    assert result["t_accuracy"] == pytest.approx(2 / 3)
    assert result["t_confusion"] == {
        "crossing_collision": {"crossing_collision": 1, "vehicle_collision": 1},
        "no_incident": {"no_incident": 1},
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


def test_paired_temporal_comparison_scores_only_shared_localised_samples() -> None:
    # sample 0: both localised; sample 1: only report; sample 2: neither.
    vlm_rows = [
        {"temporal_iou": 0.4, "t0_error_s": 0.1},
        {"temporal_iou": None, "t0_error_s": None},
        {"temporal_iou": None, "t0_error_s": None},
    ]
    report_rows = [
        {"temporal_iou": 0.6, "t0_error_s": 0.1},
        {"temporal_iou": 0.2, "t0_error_s": 5.0},
        {"temporal_iou": None, "t0_error_s": None},
    ]

    assert paired_temporal_comparison(vlm_rows, report_rows, num_gold_incidents=2) == {
        "num_gold_incidents": 2,
        "vlm_localised_count": 1,
        "report_localised_count": 2,
        "paired_num_samples": 1,
        "vlm_temporal_iou_mean_paired": 0.4,
        "report_temporal_iou_mean_paired": 0.6,
        "report_minus_vlm_temporal_iou_delta": pytest.approx(0.2),
    }


def test_paired_temporal_comparison_handles_no_shared_samples() -> None:
    result = paired_temporal_comparison(
        [{"temporal_iou": None}], [{"temporal_iou": 0.5}], num_gold_incidents=1
    )
    assert result["paired_num_samples"] == 0
    assert result["vlm_temporal_iou_mean_paired"] is None
    assert result["report_minus_vlm_temporal_iou_delta"] is None


def test_sample_resource_usage_sums_priced_and_flags_unpriced_models() -> None:
    activities = [
        {  # priced: gpt-4o-mini
            "status": "completed",
            "model": "gpt-4o-mini",
            "duration_ms": 1500,
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
        },
        {  # unpriced model -> cost_usd becomes None but tokens still count
            "status": "completed",
            "model": "mystery-model",
            "duration_ms": 500,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        },
        {"status": "failed", "model": "gpt-4o-mini", "usage": {"input_tokens": 999, "output_tokens": 0}},
    ]

    result = sample_resource_usage(activities, wall_time_s=4.0)

    assert result["num_model_requests"] == 2
    assert result["input_tokens"] == 1_000_010
    assert result["output_tokens"] == 1_000_005
    assert result["total_tokens"] == 2_000_015
    assert result["model_time_s"] == pytest.approx(2.0)
    assert result["wall_time_s"] == 4.0
    assert result["cost_usd"] is None
    assert result["unpriced_models"] == ["mystery-model"]
    assert result["by_model"]["gpt-4o-mini"]["cost_usd"] == pytest.approx(0.75)


def test_sample_resource_usage_costs_when_every_model_is_priced() -> None:
    result = sample_resource_usage(
        [
            {
                "status": "completed",
                "model": "gpt-4o-mini",
                "duration_ms": 200,
                "usage": {"input_tokens": 2_000_000, "output_tokens": 0, "total_tokens": 2_000_000},
            }
        ],
        wall_time_s=1.0,
    )
    assert result["cost_usd"] == pytest.approx(0.30)
    assert result["unpriced_models"] == []


def test_aggregate_resource_usage_means_only_over_samples_with_calls() -> None:
    rows = [
        {
            "num_model_requests": 3,
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "model_time_s": 2.0,
            "wall_time_s": 5.0,
            "cost_usd": 0.02,
            "unpriced_models": [],
        },
        {
            "num_model_requests": 1,
            "input_tokens": 300,
            "output_tokens": 150,
            "total_tokens": 450,
            "model_time_s": 4.0,
            "wall_time_s": 7.0,
            "cost_usd": None,
            "unpriced_models": ["qwen3-vl-flash"],
        },
        {"num_model_requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    ]

    result = aggregate_resource_usage(rows)

    assert result["num_samples_used"] == 2
    assert result["num_samples_costed"] == 1
    assert result["mean_total_tokens"] == pytest.approx(300.0)
    assert result["mean_wall_time_s"] == pytest.approx(6.0)
    assert result["mean_cost_usd"] == pytest.approx(0.02)
    assert result["total_cost_usd"] == pytest.approx(0.02)
    assert result["unpriced_models"] == ["qwen3-vl-flash"]


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


def test_discover_samples_skips_eval_exclude(tmp_path) -> None:
    for name, extra in (("keep", ""), ("drop", '"eval_exclude":true,')):
        root = tmp_path / name
        (root / "input").mkdir(parents=True)
        (root / "labels").mkdir()
        (root / "input" / "video.mp4").touch()
        (root / "labels" / "ground_truth.json").write_text(
            f'{{{extra}"sample_id":"{name}","is_incident":false,"incident_type":"no_incident",'
            '"timeline":{"t_start":0,"t0":0,"t_end":0}}',
            encoding="utf-8",
        )

    assert [sample.sample_id for sample in discover_samples(tmp_path)] == ["keep"]


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
