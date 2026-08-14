"use client";

import { useEffect, useState } from "react";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";

export function ReviewSidebar({ snapshot, selectedClaim, busy, error, onReview }: { snapshot: IncidentSnapshot; selectedClaim?: Claim; busy: boolean; error: string; onReview: (payload: ReviewPayload) => Promise<void> }) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const window = report?.incident_window;
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [summary, setSummary] = useState(report?.summary ?? snapshot.video_summary);
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("Insufficient evidence");
  const [feedback, setFeedback] = useState("");
  useEffect(() => setSummary(report?.summary ?? snapshot.video_summary), [report?.summary, snapshot.video_summary]);
  const counts = snapshot.claims.reduce<Record<string, number>>((result, claim) => { result[claim.verification_status] = (result[claim.verification_status] ?? 0) + 1; return result; }, {});
  const canReview = snapshot.status === "awaiting_review" && !busy;

  return (
    <aside className="incident-review-sidebar">
      <div className="forensic-panel-title"><div><span>Forensic report</span><strong>AI-assisted evidence review</strong></div><span className="forensic-live-dot">LIVE</span></div>
      <section className="sidebar-section incident-information"><div className="sidebar-section-title"><p className="eyebrow">Incident information</p><span className={`status ${snapshot.status}`}>{snapshot.status}</span></div><dl><div><dt>Type</dt><dd>Disengagement</dd></div><div><dt>Severity</dt><dd>Not classified</dd></div><div><dt>Window</dt><dd>{secondsToTimestamp(window?.t_start ?? 0)} – {secondsToTimestamp(window?.t_end ?? 0)}</dd></div><div><dt>Sources</dt><dd>{snapshot.has_log ? "Video + telemetry" : "Video only"}</dd></div></dl></section>

      <section className="sidebar-section ai-observation"><div className="sidebar-section-title"><p className="eyebrow">AI observation</p><strong>{selectedClaim?.claim_id ?? "Select an event"}</strong></div><h3>{selectedClaim?.text ?? snapshot.video_summary}</h3><dl><div><dt>Timestamp</dt><dd>{secondsToTimestamp(selectedClaim?.timestamp_s ?? window?.t0 ?? 0)}</dd></div><div><dt>Evidence</dt><dd>{selectedClaim?.evidence.map((item) => item.evidence_id).join(", ") || "Pending"}</dd></div><div><dt>Confidence</dt><dd>Not numerically scored</dd></div></dl></section>

      <section className="sidebar-section verification-summary"><p className="eyebrow">Evidence verification</p><div className="verification-counts">{["supported", "contradicted", "unverified", "video_only"].map((status) => <div className={status} key={status}><span>{status.replace("_", " ")}</span><strong>{counts[status] ?? 0}</strong></div>)}</div></section>

      <section className="sidebar-section structured-summary"><div className="sidebar-section-title"><p className="eyebrow">Final structured summary</p><button type="button" className="text-button" disabled={!canReview} onClick={() => setEditing((value) => !value)}>{editing ? "Cancel" : "Edit"}</button></div>{editing ? <textarea value={summary} onChange={(event) => setSummary(event.target.value)} aria-label="Edit structured summary" /> : <p>{summary}</p>}{editing && <button type="button" className="secondary-action" disabled={!summary.trim() || busy} onClick={() => void onReview({ action: "edit", reviewer, edits: { summary } }).then(() => setEditing(false))}>Save summary</button>}</section>

      <section className="sidebar-section reanalysis-control"><p className="eyebrow">Engineer-guided AI review</p><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Explain what the AI should verify again…" /><button type="button" className="secondary-action" disabled={!canReview || !selectedClaim || !feedback.trim()} onClick={() => void onReview({ action: "reanalyze", reviewer, feedback, target_claim_ids: selectedClaim ? [selectedClaim.claim_id] : [] })}>Re-analyze selected observation</button></section>

      <section className="sidebar-section review-action-dock"><label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>Reject reason<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>{error && <p className="form-error" role="alert">{error}</p>}<div><button type="button" className="reject-action" disabled={!canReview || !reason.trim()} onClick={() => void onReview({ action: "not_incident", reviewer, reason })}>Reject</button><button type="button" className="approve-action" disabled={!canReview} onClick={() => void onReview({ action: "approve", reviewer })}>Approve</button></div></section>
    </aside>
  );
}
