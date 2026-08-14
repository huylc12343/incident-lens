"use client";

import { useEffect, useState } from "react";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";

export function ReviewSidebar({ snapshot, selectedClaim, busy, error, onSelectClaim, onReview }: { snapshot: IncidentSnapshot; selectedClaim?: Claim; busy: boolean; error: string; onSelectClaim: (claim: Claim) => void; onReview: (payload: ReviewPayload) => Promise<void> }) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const window = report?.incident_window;
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [reason, setReason] = useState("Insufficient evidence");
  const [summary, setSummary] = useState(report?.summary ?? snapshot.video_summary);
  const [editingSummary, setEditingSummary] = useState(false);
  const [feedback, setFeedback] = useState("");
  useEffect(() => setSummary(report?.summary ?? snapshot.video_summary), [report?.summary, snapshot.video_summary]);
  const counts = snapshot.claims.reduce<Record<string, number>>((result, claim) => { result[claim.verification_status] = (result[claim.verification_status] ?? 0) + 1; return result; }, {});
  const canReview = snapshot.status === "awaiting_review" && !busy;
  const warnings = [...new Set([...snapshot.warnings, ...(report?.evidence_and_warnings?.warnings ?? [])])];

  return (
    <aside className="incident-review-sidebar expanded-ai-review">
      <div className="forensic-panel-title"><div><span>Forensic report</span><strong>AI-assisted evidence review</strong></div><span className="forensic-live-dot">FULL REPORT</span></div>
      <section className="sidebar-section incident-information incident-info-card">
        <div className="incident-info-heading"><div><p className="eyebrow">Incident information</p><strong>{snapshot.incident_id}</strong></div><span className={`status ${snapshot.status}`}><i />{snapshot.status.replace("_", " ")}</span></div>
        <div className="incident-window-visual"><div><span>Analysis window</span><strong>{secondsToTimestamp(window?.t_start ?? 0)} <i>→</i> {secondsToTimestamp(window?.t_end ?? 0)}</strong></div><span className="incident-focus-time"><small>Detected event</small><b>{secondsToTimestamp(window?.t0 ?? 0)}</b></span></div>
        <div className="incident-info-grid">
          <article><span className="incident-info-icon" aria-hidden="true">D</span><div><small>Incident type</small><strong>Disengagement</strong></div></article>
          <article><span className="incident-info-icon severity" aria-hidden="true">!</span><div><small>Severity</small><strong>Not classified</strong></div></article>
          <article><span className="incident-info-icon sources" aria-hidden="true">S</span><div><small>Evidence sources</small><strong>{snapshot.has_log ? "Video + telemetry" : "Video only"}</strong></div></article>
          <article><span className="incident-info-icon claims" aria-hidden="true">#</span><div><small>AI observations</small><strong>{snapshot.claims.length} grounded claim(s)</strong></div></article>
        </div>
      </section>

      <section className="sidebar-section all-ai-observations"><div className="sidebar-section-title"><p className="eyebrow">All AI observations</p><strong>{snapshot.claims.length}</strong></div><p className="observation-help">Select an observation to seek the original video and highlight its evidence.</p><div className="ai-observation-list">{snapshot.claims.map((item, index) => <button type="button" className={item.claim_id === selectedClaim?.claim_id ? "selected" : ""} key={item.claim_id} onClick={() => onSelectClaim(item)} aria-pressed={item.claim_id === selectedClaim?.claim_id}><header><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.claim_id}</strong><time>{secondsToTimestamp(item.timestamp_s)}</time></header><p>{item.text}</p><footer><span className={`finding-status ${item.verification_status}`}>{item.verification_status.replace("_", " ")}</span><small>{item.evidence.map((evidence) => evidence.evidence_id).join(", ") || "No frame reference"}</small></footer></button>)}{!snapshot.claims.length && <p>No AI observations have been published yet.</p>}</div></section>

      <section className="sidebar-section verification-summary"><p className="eyebrow">Evidence verification</p><div className="verification-counts">{["supported", "contradicted", "unverified", "video_only"].map((status) => <div className={status} key={status}><span>{status.replace("_", " ")}</span><strong>{counts[status] ?? 0}</strong></div>)}</div></section>

      <section className="sidebar-section structured-summary"><div className="sidebar-section-title"><p className="eyebrow">Final structured summary</p><button type="button" className="text-button" disabled={!canReview || busy} onClick={() => setEditingSummary((current) => !current)}>{editingSummary ? "Cancel" : "Edit"}</button></div>{editingSummary ? <><textarea aria-label="Edit final structured summary" value={summary} onChange={(event) => setSummary(event.target.value)} /><button type="button" className="secondary-action summary-save-action" disabled={!summary.trim() || busy} onClick={() => void onReview({ action: "edit", reviewer, edits: { summary } }).then(() => setEditingSummary(false))}>Save correction</button></> : <p>{summary}</p>}</section>
      <section className="sidebar-section full-analysis-section"><p className="eyebrow">Timeline assessment</p><p>{report?.timeline?.narrative || "No additional timeline narrative."}</p></section>
      <section className="sidebar-section full-analysis-section"><p className="eyebrow">Video assessment</p><p>{report?.video_observations?.narrative || snapshot.video_summary}</p></section>
      <section className="sidebar-section full-analysis-section"><p className="eyebrow">Log assessment</p><p>{report?.log_findings?.narrative || (snapshot.has_log ? "Log findings are listed with each aligned event." : "No telemetry log was supplied.")}</p></section>
      <section className="sidebar-section full-analysis-section"><p className="eyebrow">Evidence alignment</p><p>{report?.alignment?.narrative || "No additional alignment narrative."}</p></section>
      <section className="sidebar-section full-analysis-section"><p className="eyebrow">Hypothesized causes</p><p>{report?.hypothesized_causes || "No cause hypothesis was recorded."}</p></section>
      {warnings.length > 0 && <section className="sidebar-section ai-warning-section"><p className="eyebrow">Evidence limitations</p><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}

      <section className="sidebar-section interactive-reanalysis"><div className="sidebar-section-title"><p className="eyebrow">Focused re-analysis</p><strong>{selectedClaim?.claim_id ?? "Select a claim"}</strong></div><textarea aria-label="Focused re-analysis feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Describe what the agent should verify again…" /><button type="button" className="secondary-action" disabled={!canReview || !selectedClaim || !feedback.trim() || busy} onClick={() => void onReview({ action: "reanalyze", reviewer, feedback, target_claim_ids: selectedClaim ? [selectedClaim.claim_id] : [] }).then(() => setFeedback(""))}>Re-analyze selected observation</button></section>

      <section className="sidebar-section review-action-dock"><label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>Reject reason<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>{error && <p className="form-error" role="alert">{error}</p>}<div><button type="button" className="reject-action" disabled={!canReview || !reason.trim()} onClick={() => void onReview({ action: "not_incident", reviewer, reason })}>Reject</button><button type="button" className="approve-action" disabled={!canReview} onClick={() => void onReview({ action: "approve", reviewer })}>Approve</button></div></section>
    </aside>
  );
}
