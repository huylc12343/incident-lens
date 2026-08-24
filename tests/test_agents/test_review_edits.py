import pytest
from pydantic import ValidationError

from src.agents.nodes.review import apply_report_edits
from src.models.api import ReportEdits, ReviewDecision
from src.models.incidents import (
    AccidentType,
    AnalysisMode,
    Claim,
    DraftReport,
    EvidenceReference,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportTimelineSection,
    ReportVideoObservationsSection,
    VerificationStatus,
    VideoMemory,
)


def _report() -> DraftReport:
    return DraftReport(
        general_information=ReportGeneralInformation(
            incident_id="INC-EDIT", video_uri="video.mp4", has_log=True, log_uri="vehicle.csv"
        ),
        type_of_accident=AccidentType.OTHER_UNKNOWN,
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        summary="Original summary",
        timeline=ReportTimelineSection(narrative="Original timeline"),
        video_observations=ReportVideoObservationsSection(narrative="Original video assessment"),
        log_findings=ReportLogSection(narrative="Original log assessment"),
        alignment=ReportAlignmentSection(narrative="Original alignment"),
        hypothesized_causes="Original cause",
        evidence_and_warnings=ReportEvidenceAndWarnings(warnings=["Original warning"]),
    )


def _memory() -> VideoMemory:
    return VideoMemory(
        global_scene="Road scene",
        video_summary="Original summary",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        claims=[
            Claim(
                claim_id="claim-1",
                text="Original claim",
                timestamp_s=2,
                evidence=[EvidenceReference(evidence_id="frame-old", timestamp_s=2)],
            )
        ],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )


def test_structured_report_edit_updates_report_window_and_claims_without_reanalysis() -> None:
    edits = ReportEdits(
        type_of_accident=AccidentType.SIDE_COLLISION,
        t_start=1.5,
        t0=2.5,
        t_end=4,
        claims=[
            {
                "claim_id": "claim-1",
                "text": "Engineer corrected claim",
                "timestamp_s": 2.6,
                "verification_status": "supported",
                "evidence_ids": ["frame-new"],
            }
        ],
        summary="Engineer summary",
        timeline="Engineer timeline assessment",
        video_observations="Engineer video assessment",
        log_findings="Engineer log assessment",
        alignment="Engineer alignment",
        hypothesized_causes="Engineer cause assessment",
        warnings=["Engineer warning"],
    )

    report, memory = apply_report_edits(_report(), _memory(), edits)

    assert report.type_of_accident == AccidentType.SIDE_COLLISION
    assert report.incident_window == IncidentWindow(t_start=1.5, t0=2.5, t_end=4)
    assert report.summary == "Engineer summary"
    assert report.timeline.narrative == "Engineer timeline assessment"
    assert report.video_observations.narrative == "Engineer video assessment"
    assert report.log_findings.narrative == "Engineer log assessment"
    assert report.alignment.narrative == "Engineer alignment"
    assert report.hypothesized_causes == "Engineer cause assessment"
    assert report.review_status == "edited"
    assert report.evidence_and_warnings.warnings == ["Engineer warning"]
    assert memory is not None
    assert memory.video_summary == "Engineer summary"
    assert memory.incident_window == report.incident_window
    assert memory.claims[0].text == "Engineer corrected claim"
    assert memory.claims[0].timestamp_s == 2.6
    assert memory.claims[0].verification_status == VerificationStatus.SUPPORTED
    assert [item.evidence_id for item in memory.claims[0].evidence] == ["frame-new"]
    assert memory.claims[0].evidence[0].timestamp_s == 2.6


def test_structured_report_edit_rejects_invalid_timestamp_order() -> None:
    with pytest.raises(ValueError, match="incident timestamps"):
        apply_report_edits(_report(), _memory(), ReportEdits(t_start=3, t0=2, t_end=4))


def test_review_decision_rejects_unknown_edit_fields() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate(
            {"action": "edit", "reviewer": "engineer", "edits": {"incident_window": "tampered"}}
        )
