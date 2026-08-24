from pathlib import Path

import pytest

from src.models.api import GroundTruth
from src.models.incidents import (
    AccidentType,
    DraftReport,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportTimelineSection,
    ReportVideoObservationsSection,
)
from src.services.ground_truth import GroundTruthError, evaluate_ground_truth, load_ground_truth, parse_ground_truth


def _report(*, incident_type: AccidentType = AccidentType.SIDE_COLLISION) -> DraftReport:
    return DraftReport(
        general_information=ReportGeneralInformation(
            incident_id="INC-GT", video_uri="video.mp4", has_log=False
        ),
        type_of_accident=incident_type,
        incident_window=IncidentWindow(t_start=10, t0=10.5, t_end=12),
        summary="Summary",
        timeline=ReportTimelineSection(narrative="Timeline"),
        video_observations=ReportVideoObservationsSection(narrative="Observations"),
        log_findings=ReportLogSection(narrative="No log"),
        alignment=ReportAlignmentSection(narrative="Aligned"),
        hypothesized_causes="Unknown",
        evidence_and_warnings=ReportEvidenceAndWarnings(),
    )


def test_parse_ground_truth_normalizes_carla_and_legacy_cut_in_label() -> None:
    truth = parse_ground_truth(
        {
            "label_provenance": "carla_simulator",
            "is_incident": True,
            "incident_type": "cut_in_collision",
            "severity": "high",
            "timeline": {"t_start": 10, "t0": 10.7, "t_end": 11.65},
        }
    )

    assert truth.source == "CARLA Incident"
    assert truth.incident_type == AccidentType.SIDE_COLLISION
    assert truth.timeline is not None
    assert truth.timeline.t0 == 10.7


def test_evaluate_ground_truth_uses_only_comparable_fields() -> None:
    truth = GroundTruth.model_validate(
        {
            "source": "CARLA Incident",
            "incident_type": "side_collision",
            "severity": "high",
            "timeline": {"t_start": 10, "t0": 10.7, "t_end": 11.65},
        }
    )

    evaluation = evaluate_ground_truth(truth, _report())

    assert evaluation is not None
    assert evaluation.incident_type_match is True
    assert evaluation.severity_match is None
    assert evaluation.t0_delta_s == pytest.approx(0.2)
    assert evaluation.timeline_iou == pytest.approx(1.65 / 2)
    assert evaluation.overall_accuracy == pytest.approx((1 + 0.96 + (1.65 / 2)) / 3)


def test_evaluate_ground_truth_reports_type_mismatch() -> None:
    truth = GroundTruth.model_validate(
        {"source": "Human annotation", "incident_type": "rear_end_collision"}
    )

    evaluation = evaluate_ground_truth(truth, _report())

    assert evaluation is not None
    assert evaluation.incident_type_match is False
    assert evaluation.overall_accuracy == 0


def test_load_ground_truth_rejects_file_outside_upload_root(tmp_path: Path) -> None:
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    outside = tmp_path / "ground_truth.json"
    outside.write_text('{"source":"Human annotation"}', encoding="utf-8")

    with pytest.raises(GroundTruthError, match="outside the upload directory"):
        load_ground_truth(str(outside), upload_root=upload_root)
