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
            "warnings": decision.edits.warnings
            if decision.edits and decision.edits.warnings is not None
            else state.get("warnings", []),
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
    memory: VideoMemory | None,
    edits: ReportEdits | None,
) -> tuple[DraftReport, VideoMemory | None]:
    if edits is None:
        raise ValueError("report edits are required")
    updates: dict[str, object] = {"review_status": "edited"}
    if edits.type_of_accident is not None:
        updates["type_of_accident"] = edits.type_of_accident
    if edits.summary is not None:
        updates["summary"] = edits.summary
    if edits.hypothesized_causes is not None:
        updates["hypothesized_causes"] = edits.hypothesized_causes
    if edits.timeline is not None:
        updates["timeline"] = report.timeline.model_copy(update={"narrative": edits.timeline})
    if edits.video_observations is not None:
        updates["video_observations"] = report.video_observations.model_copy(
            update={"narrative": edits.video_observations}
        )
    if edits.log_findings is not None:
        updates["log_findings"] = report.log_findings.model_copy(update={"narrative": edits.log_findings})
    if edits.alignment is not None:
        updates["alignment"] = report.alignment.model_copy(update={"narrative": edits.alignment})
    if edits.warnings is not None:
        updates["evidence_and_warnings"] = report.evidence_and_warnings.model_copy(update={"warnings": edits.warnings})

    current_window = report.incident_window
    incident_window = IncidentWindow(
        t_start=edits.t_start if edits.t_start is not None else current_window.t_start,
        t0=edits.t0 if edits.t0 is not None else current_window.t0,
        t_end=edits.t_end if edits.t_end is not None else current_window.t_end,
    )
    if {"t_start", "t0", "t_end"} & edits.model_fields_set:
        updates["incident_window"] = incident_window

    edited_memory = memory
    if memory is not None:
        memory_updates: dict[str, object] = {}
        if edits.summary is not None:
            memory_updates["video_summary"] = edits.summary
        if {"t_start", "t0", "t_end"} & edits.model_fields_set:
            memory_updates["incident_window"] = incident_window
        if edits.claims is not None:
            claim_edits = {claim.claim_id: claim for claim in edits.claims}
            edited_claims = []
            for claim in memory.claims:
                claim_edit = claim_edits.get(claim.claim_id)
                if claim_edit is None:
                    edited_claims.append(claim)
                    continue
                claim_timestamp = claim_edit.timestamp_s
                existing_evidence = {item.evidence_id: item for item in claim.evidence}
                evidence = claim.evidence
                if claim_edit.evidence_ids is not None:
                    evidence = [
                        existing_evidence.get(evidence_id)
                        or EvidenceReference(
                            evidence_id=evidence_id,
                            timestamp_s=claim_timestamp if claim_timestamp is not None else claim.timestamp_s or 0,
                        )
                        for evidence_id in claim_edit.evidence_ids
                    ]
                edited_claims.append(
                    claim.model_copy(
                        update={
                            "text": claim_edit.text,
                            "timestamp_s": claim_timestamp,
                            "verification_status": claim_edit.verification_status or claim.verification_status,
                            "evidence": evidence,
                        }
                    )
                )
            memory_updates["claims"] = edited_claims
        if memory_updates:
            edited_memory = memory.model_copy(update=memory_updates)

    return report.model_copy(update=updates), edited_memory
