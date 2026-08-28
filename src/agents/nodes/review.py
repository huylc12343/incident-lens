"""Human-review interrupt and allowlisted report editing."""

from __future__ import annotations

from langgraph.types import interrupt

from src.agents.incident_state import IncidentState
from src.models.api import ReportEdits, ReviewAuditEntry, ReviewDecision
from src.models.incidents import DraftReport, EvidenceReference, IncidentWindow, VideoMemory


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
        edited_report, edited_memory = apply_report_edits(report, memory, decision.edits)
        return {
            "status": "awaiting_review",
            "draft_report": edited_report,
            "video_memory": edited_memory,
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


def apply_report_edits(
    report: DraftReport,
    memory_or_edits: VideoMemory | ReportEdits | None,
    edits: ReportEdits | None = None,
) -> DraftReport | tuple[DraftReport, VideoMemory | None]:
    """Apply allowlisted reviewer corrections without invoking a model.

    The two-argument form remains compatible with older callers and returns
    only the report. The structured three-argument form also synchronizes the
    canonical VideoMemory used by subsequent review/re-analysis steps.
    """
    legacy_call = edits is None
    if legacy_call:
        memory = None
        edits = ReportEdits.model_validate(memory_or_edits)
    else:
        memory = memory_or_edits if isinstance(memory_or_edits, VideoMemory) else None
    if edits is None:
        raise ValueError("report edits are required")

    updates: dict[str, object] = {"review_status": "edited"}
    if edits.type_of_accident is not None:
        updates["type_of_accident"] = edits.type_of_accident

    if any(value is not None for value in (edits.t_start, edits.t0, edits.t_end)):
        updates["incident_window"] = IncidentWindow(
            t_start=report.incident_window.t_start if edits.t_start is None else edits.t_start,
            t0=report.incident_window.t0 if edits.t0 is None else edits.t0,
            t_end=report.incident_window.t_end if edits.t_end is None else edits.t_end,
        )
    if edits.summary is not None:
        updates["summary"] = edits.summary
    if edits.hypothesized_causes is not None:
        updates["hypothesized_causes"] = edits.hypothesized_causes
    if edits.timeline is not None:
        updates["timeline"] = report.timeline.model_copy(update={"narrative": edits.timeline})
    if edits.timeline_events is not None:
        timeline = updates.get("timeline", report.timeline)
        updates["timeline"] = timeline.model_copy(update={"events": edits.timeline_events})
    if edits.video_observations is not None:
        updates["video_observations"] = report.video_observations.model_copy(
            update={"narrative": edits.video_observations}
        )
    if edits.log_findings is not None:
        updates["log_findings"] = report.log_findings.model_copy(
            update={"narrative": edits.log_findings}
        )
    if edits.alignment is not None:
        updates["alignment"] = report.alignment.model_copy(update={"narrative": edits.alignment})
    if edits.claims is not None and report.alignment.verification is not None:
        alignment = updates.get("alignment", report.alignment)
        status_by_claim_id = {
            edit.claim_id: edit.verification_status
            for edit in edits.claims
            if edit.verification_status is not None
        }
        verification = report.alignment.verification.model_copy(update={
            "results": [
                result.model_copy(update={"status": status_by_claim_id[result.claim_id]})
                if result.claim_id in status_by_claim_id else result
                for result in report.alignment.verification.results
            ]
        })
        updates["alignment"] = alignment.model_copy(update={"verification": verification})
    if edits.warnings is not None:
        updates["evidence_and_warnings"] = report.evidence_and_warnings.model_copy(
            update={"warnings": edits.warnings}
        )

    edited_report = report.model_copy(update=updates)
    edited_memory = _apply_memory_edits(memory, edited_report, edits)
    if legacy_call:
        return edited_report
    return edited_report, edited_memory


def _apply_memory_edits(
    memory: VideoMemory | None,
    report: DraftReport,
    edits: ReportEdits,
) -> VideoMemory | None:
    if memory is None:
        return None
    memory_updates: dict[str, object] = {"incident_window": report.incident_window}
    if edits.timeline_events is not None:
        memory_updates["timeline"] = edits.timeline_events
    if edits.summary is not None:
        memory_updates["video_summary"] = edits.summary
    if edits.claims is not None:
        claims_by_id = {claim.claim_id: claim for claim in memory.claims}
        for edit in edits.claims:
            claim = claims_by_id.get(edit.claim_id)
            if claim is None:
                raise ValueError(f"claim does not exist: {edit.claim_id}")
            claim_updates = edit.model_dump(exclude={"claim_id", "evidence_ids"}, exclude_none=True)
            timestamp_s = claim_updates.get("timestamp_s", claim.timestamp_s)
            if edit.evidence_ids is not None:
                if timestamp_s is None:
                    raise ValueError("claim evidence requires a timestamp")
                claim_updates["evidence"] = [
                    EvidenceReference(evidence_id=evidence_id, timestamp_s=timestamp_s)
                    for evidence_id in edit.evidence_ids
                ]
            claims_by_id[edit.claim_id] = claim.model_copy(update=claim_updates)
        memory_updates["claims"] = [claims_by_id[claim.claim_id] for claim in memory.claims]
    return memory.model_copy(update=memory_updates)
