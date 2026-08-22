"""Human-review interrupt and allowlisted report editing."""

from __future__ import annotations

from langgraph.types import interrupt

from src.agents.incident_state import IncidentState
from src.models.api import ReviewAuditEntry, ReviewDecision
from src.models.incidents import DraftReport


async def human_review_interrupt_node(state: IncidentState) -> dict[str, object]:
    report = state.get("draft_report")
    memory = state.get("video_memory")
    if report is None:
        return {
            "status": "failed",
            "error_code": "REVIEW_REPORT_MISSING",
            "error_message": "draft report is required before human review",
        }

    payload = {
        "incident_id": state.get("incident_id"),
        "report": report.model_dump(mode="json"),
        "artifacts": state.get("artifact_uris", {}),
        "claims": [claim.model_dump(mode="json") for claim in (memory.claims if memory else [])],
        "warnings": state.get("warnings", []),
        "actions": ["approve", "edit", "reanalyze", "not_incident"],
    }
    decision = ReviewDecision.model_validate(interrupt(payload))
    audit = [
        *state.get("review_audit", []),
        ReviewAuditEntry(
            action=decision.action,
            reviewer=decision.reviewer,
            reason=decision.reason,
            feedback=decision.feedback,
            target_claim_ids=decision.target_claim_ids,
        ),
    ]

    if decision.action == "approve":
        return {
            "status": "approved",
            "draft_report": report.model_copy(update={"review_status": "approved"}),
            "last_review_action": decision.action,
            "review_audit": audit,
        }
    if decision.action == "not_incident":
        return {
            "status": "not_incident",
            "draft_report": report.model_copy(update={"review_status": "not_incident"}),
            "last_review_action": decision.action,
            "review_audit": audit,
        }
    if decision.action == "edit":
        return {
            "status": "awaiting_review",
            "draft_report": apply_report_edits(report, decision.edits),
            "last_review_action": decision.action,
            "review_audit": audit,
        }
    return {
        "status": "running",
        "review_target_claim_ids": decision.target_claim_ids,
        "review_feedback": decision.feedback or "",
        "last_review_action": decision.action,
        "review_audit": audit,
    }


def apply_report_edits(report: DraftReport, edits: dict[str, str]) -> DraftReport:
    updates: dict[str, object] = {"review_status": "edited"}
    for field, value in edits.items():
        if field in {"summary", "hypothesized_causes"}:
            updates[field] = value
        elif field == "timeline":
            updates[field] = report.timeline.model_copy(update={"narrative": value})
        elif field == "video_observations":
            updates[field] = report.video_observations.model_copy(update={"narrative": value})
        elif field == "log_findings":
            updates[field] = report.log_findings.model_copy(update={"narrative": value})
        elif field == "alignment":
            updates[field] = report.alignment.model_copy(update={"narrative": value})
        else:  # ReviewDecision normally rejects this before the graph is resumed.
            raise ValueError(f"report field is not editable: {field}")
    return report.model_copy(update=updates)
