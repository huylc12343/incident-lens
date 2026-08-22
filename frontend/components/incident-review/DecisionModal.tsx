"use client";

import { useEffect, useState } from "react";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";

type Decision = "approve" | "edit" | "not_incident" | "reanalyze";

const decisions: Array<{ id: Decision; title: string; description: string; symbol: string }> = [
  { id: "approve", title: "Accept & approve", description: "Finalize the reviewed report and close the incident.", symbol: "✓" },
  { id: "edit", title: "Edit summary", description: "Save an engineer correction before making a final decision.", symbol: "✎" },
  { id: "not_incident", title: "Not an incident", description: "Close the case because the evidence does not support an incident.", symbol: "×" },
  { id: "reanalyze", title: "Request re-analysis", description: "Send focused feedback to the agent for the selected observation.", symbol: "↻" },
];

export function DecisionModal({ open, snapshot, selectedClaim, busy, onClose, onReview }: {
  open: boolean;
  snapshot: IncidentSnapshot;
  selectedClaim?: Claim;
  busy: boolean;
  onClose: () => void;
  onReview: (payload: ReviewPayload) => Promise<void>;
}) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const [decision, setDecision] = useState<Decision>("approve");
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [summary, setSummary] = useState(report?.summary ?? snapshot.video_summary);
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState("");
  useEffect(() => setSummary(report?.summary ?? snapshot.video_summary), [report?.summary, snapshot.video_summary]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, busy, onClose]);
  if (!open) return null;

  const valid = reviewer.trim() && (decision === "approve" || (decision === "edit" && summary.trim()) || (decision === "not_incident" && reason.trim()) || (decision === "reanalyze" && feedback.trim() && selectedClaim));
  const confirm = async () => {
    if (!valid || busy) return;
    if (decision === "approve") await onReview({ action: "approve", reviewer });
    if (decision === "edit") await onReview({ action: "edit", reviewer, edits: { summary } });
    if (decision === "not_incident") await onReview({ action: "not_incident", reviewer, reason });
    if (decision === "reanalyze" && selectedClaim) await onReview({ action: "reanalyze", reviewer, feedback, target_claim_ids: [selectedClaim.claim_id] });
    onClose();
  };

  return (
    <div className="decision-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <section className="decision-modal" role="dialog" aria-modal="true" aria-labelledby="decision-title">
        <header><div><span>Human-in-the-loop</span><h2 id="decision-title">Make review decision</h2></div><button type="button" onClick={onClose} disabled={busy} aria-label="Close decision dialog">×</button></header>
        <div className="decision-modal-body">
          <p className="decision-incident-line">Incident <strong>{snapshot.incident_id}</strong> · Select the outcome supported by the evidence.</p>
          <div className="decision-option-grid" role="radiogroup" aria-label="Decision options">
            {decisions.map((item) => <button key={item.id} type="button" role="radio" aria-checked={decision === item.id} className={`${item.id} ${decision === item.id ? "selected" : ""}`} onClick={() => setDecision(item.id)}><span>{item.symbol}</span><div><strong>{item.title}</strong><small>{item.description}</small></div></button>)}
          </div>
          <div className="decision-inputs">
            <label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
            {decision === "edit" && <label>Corrected structured summary<textarea rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} /></label>}
            {decision === "not_incident" && <label>Reason for closing<textarea autoFocus rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain why this is not an incident…" /></label>}
            {decision === "reanalyze" && <label>Focused feedback for {selectedClaim?.claim_id ?? "selected observation"}<textarea autoFocus rows={3} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Describe exactly what the agent should verify again…" /></label>}
          </div>
          <footer><button type="button" className="decision-cancel" onClick={onClose} disabled={busy}>Cancel</button><button type="button" className={`decision-confirm ${decision}`} disabled={!valid || busy} onClick={() => void confirm()}>{busy ? "Submitting…" : "Confirm decision"}</button></footer>
        </div>
      </section>
    </div>
  );
}
