"use client";

import { useEffect, useState } from "react";
import { secondsToTimestamp } from "../../lib/incidentSession";
import { normalizeReviewText } from "../../lib/reviewText";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";
import { StructuredReportEditor } from "./StructuredReportEditor";

type Decision = "approve" | "edit" | "not_incident" | "reanalyze";

const decisions: Array<{ id: Decision; title: string; description: string; symbol: string }> = [
  { id: "approve", title: "Accept & approve", description: "Finalize the reviewed report and close the incident.", symbol: "✓" },
  { id: "edit", title: "Edit report", description: "Correct all content shown in the AI-assisted evidence review.", symbol: "✎" },
  { id: "not_incident", title: "Not an incident", description: "Close the case because the evidence does not support an incident.", symbol: "×" },
  { id: "reanalyze", title: "Request re-analysis", description: "Send focused feedback to the agent for the selected claim.", symbol: "↻" },
];

export function DecisionModal({ open, snapshot, selectedClaim, busy, onClose, onReview }: {
  open: boolean;
  snapshot: IncidentSnapshot;
  selectedClaim?: Claim;
  busy: boolean;
  onClose: () => void;
  onReview: (payload: ReviewPayload) => Promise<boolean>;
}) {
  const [decision, setDecision] = useState<Decision>("approve");
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState("");
  const [targetClaimIds, setTargetClaimIds] = useState<string[]>(() => selectedClaim ? [selectedClaim.claim_id] : []);
  const defaultTargetClaimId = selectedClaim?.claim_id ?? snapshot.claims[0]?.claim_id ?? "";
  useEffect(() => {
    if (open) setTargetClaimIds(defaultTargetClaimId ? [defaultTargetClaimId] : []);
  }, [defaultTargetClaimId, open]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, busy, onClose]);
  if (!open) return null;

  const report = snapshot.final_report ?? snapshot.draft_report;
  const valid = reviewer.trim() && (decision === "approve" || (decision === "edit" && report) || (decision === "not_incident" && reason.trim()) || (decision === "reanalyze" && feedback.trim() && targetClaimIds.length > 0));
  const confirm = async () => {
    if (!valid || busy) return;
    let saved = false;
    if (decision === "approve") saved = await onReview({ action: "approve", reviewer });
    if (decision === "not_incident") saved = await onReview({ action: "not_incident", reviewer, reason });
    if (decision === "reanalyze" && targetClaimIds.length) saved = await onReview({ action: "reanalyze", reviewer: reviewer.trim(), feedback: feedback.trim(), target_claim_ids: targetClaimIds });
    if (saved) onClose();
  };

  return (
    <div className="decision-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <section className={`decision-modal ${decision === "edit" ? "wide-edit-modal" : decision === "reanalyze" ? "wide-reanalysis-modal" : ""}`} role="dialog" aria-modal="true" aria-labelledby="decision-title">
        <header><div><span>Human-in-the-loop</span><h2 id="decision-title">Make review decision</h2></div><button type="button" onClick={onClose} disabled={busy} aria-label="Close decision dialog">×</button></header>
        <div className="decision-modal-body">
          <p className="decision-incident-line">Incident <strong>{snapshot.incident_id}</strong> · Select the outcome supported by the evidence.</p>
          <div className="decision-option-grid" role="radiogroup" aria-label="Decision options">
            {decisions.map((item) => <button key={item.id} type="button" role="radio" aria-checked={decision === item.id} className={`${item.id} ${decision === item.id ? "selected" : ""}`} onClick={() => setDecision(item.id)}><span>{item.symbol}</span><div><strong>{item.title}</strong><small>{item.description}</small></div></button>)}
          </div>
          <div className="decision-inputs">
            <label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
            {decision === "not_incident" && <label>Reason for closing<textarea autoFocus rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain why this is not an incident…" /></label>}
            {decision === "reanalyze" && <div className="decision-claim-targets"><div className="decision-target-heading"><div><strong>Chọn claim cần phân tích lại</strong><small>Có thể chọn một hoặc nhiều claim</small></div><span>{targetClaimIds.length} đã chọn</span></div><div className="decision-claim-grid" role="group" aria-label="Claims cần phân tích lại">{snapshot.claims.map((claim, index) => {
              const selected = targetClaimIds.includes(claim.claim_id);
              return <button type="button" role="checkbox" aria-checked={selected} className={selected ? "selected" : ""} key={claim.claim_id} onClick={() => setTargetClaimIds((current) => selected ? current.filter((claimId) => claimId !== claim.claim_id) : [...current, claim.claim_id])}><span className="decision-claim-check" aria-hidden="true">{selected ? "✓" : index + 1}</span><div><header><strong>{claim.claim_id}</strong><time>{typeof claim.timestamp_s === "number" ? secondsToTimestamp(claim.timestamp_s) : "Không có timestamp"}</time></header><p className="review-multiline">{normalizeReviewText(claim.text)}</p></div></button>;
            })}</div>{!snapshot.claims.length && <p className="form-error">Incident chưa có claim để phân tích lại.</p>}</div>}
            {decision === "reanalyze" && <label>Yêu cầu agent xác minh lại<textarea autoFocus rows={4} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Mô tả rõ nội dung cần kiểm tra lại cho các claim đã chọn…" /></label>}
          </div>
          {decision === "edit" && report && <StructuredReportEditor report={report} claims={snapshot.claims} reviewer={reviewer} busy={busy} onCancel={() => setDecision("approve")} onReview={onReview} />}
          {decision === "edit" && !report && <p className="form-error" role="alert">This incident does not have a report to edit yet.</p>}
          {decision !== "edit" && <footer><button type="button" className="decision-cancel" onClick={onClose} disabled={busy}>Cancel</button><button type="button" className={`decision-confirm ${decision}`} disabled={!valid || busy} onClick={() => void confirm()}>{busy ? "Submitting…" : "Confirm decision"}</button></footer>}
        </div>
      </section>
    </div>
  );
}
