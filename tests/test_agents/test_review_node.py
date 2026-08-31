from unittest.mock import Mock

import pytest

import src.agents.nodes.review as review_module
from src.agents.nodes.review import apply_report_edits, human_review_interrupt_node
from src.models.api import ReportEdits
from src.models.incidents import (
    AnalysisMode,
    Claim,
    ClaimVerification,
    DraftReport,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportTimelineSection,
    ReportVideoObservationsSection,
    TimelineEvent,
    VerificationResult,
    VerificationStatus,
    VideoMemory,
)


def _report() -> DraftReport:
    return DraftReport(
        general_information=ReportGeneralInformation(incident_id="INC-REVIEW", video_uri="video.mp4", has_log=False),
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        summary="Summary",
        timeline=ReportTimelineSection(narrative="Timeline"),
        video_observations=ReportVideoObservationsSection(narrative="Video"),
        log_findings=ReportLogSection(narrative="No log"),
        alignment=ReportAlignmentSection(narrative="Unverified"),
        hypothesized_causes="Unknown",
        evidence_and_warnings=ReportEvidenceAndWarnings(),
    )


@pytest.mark.asyncio
async def test_review_payload_uses_claims_from_video_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Mock()

    def resume_review(payload: dict[str, object]) -> dict[str, str]:
        captured(payload)
        return {"action": "approve", "reviewer": "reviewer"}

    monkeypatch.setattr(review_module, "interrupt", resume_review)
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        claims=[Claim(claim_id="canonical-claim", text="Canonical claim")],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )

    result = await human_review_interrupt_node(
        {
            "incident_id": "INC-REVIEW",
            "draft_report": _report(),
            "video_memory": memory,
            "claims": [Claim(claim_id="stale-claim", text="Stale claim")],
        }
    )

    assert result["status"] == "approved"
    assert [claim["claim_id"] for claim in captured.call_args.args[0]["claims"]] == ["canonical-claim"]


def test_report_edits_persist_timeline_and_claim_verification_status() -> None:
    report = _report().model_copy(update={
        "timeline": ReportTimelineSection(
            narrative="Original timeline",
            events=[TimelineEvent(timestamp_s=1, description="Original event", evidence_ids=["frame-1"])],
        ),
        "alignment": ReportAlignmentSection(
            narrative="Original verification",
            verification=VerificationResult(results=[
                ClaimVerification(claim_id="claim-1", status="unverified", reason="Needs review")
            ]),
        ),
    })
    memory = VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        timeline=[TimelineEvent(timestamp_s=1, description="Original event", evidence_ids=["frame-1"])],
        claims=[Claim(claim_id="claim-1", text="Original claim", timestamp_s=1)],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )

    edited_report, edited_memory = apply_report_edits(
        report,
        memory,
        ReportEdits(
            timeline="Reviewer timeline",
            timeline_events=[
                TimelineEvent(timestamp_s=1.5, description="Reviewer event", evidence_ids=["frame-1"])
            ],
            claims=[{
                "claim_id": "claim-1",
                "text": "Reviewer claim",
                "timestamp_s": 1.5,
                "verification_status": "supported",
            }],
        ),
    )

    assert edited_report.timeline.narrative == "Reviewer timeline"
    assert edited_report.timeline.events[0].description == "Reviewer event"
    assert edited_report.alignment.verification is not None
    assert edited_report.alignment.verification.results[0].status == VerificationStatus.SUPPORTED
    assert edited_memory is not None
    assert edited_memory.timeline[0].timestamp_s == 1.5
    assert edited_memory.claims[0].text == "Reviewer claim"
    assert edited_memory.claims[0].verification_status == VerificationStatus.SUPPORTED


def test_report_edits_reject_out_of_order_timeline() -> None:
    with pytest.raises(ValueError, match="ordered"):
        ReportEdits(timeline_events=[
            TimelineEvent(timestamp_s=2, description="Later"),
            TimelineEvent(timestamp_s=1, description="Earlier"),
        ])
