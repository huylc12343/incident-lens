from unittest.mock import Mock

import pytest

import src.agents.nodes.review as review_module
from src.agents.nodes.review import human_review_interrupt_node
from src.models.incidents import (
    AnalysisMode,
    Claim,
    DraftReport,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportTimelineSection,
    ReportVideoObservationsSection,
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
