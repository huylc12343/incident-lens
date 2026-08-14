"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { artifactUrl, getIncident, reviewIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS, secondsToTimestamp } from "../lib/incidentSession";
import type { IncidentSnapshot, ReviewPayload } from "../types/incident";

export function ReviewContent({ embedded = false }: { embedded?: boolean }) {
  const router = useRouter();
  const startedAt = useRef(Date.now());
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [summary, setSummary] = useState("");
  const [feedback, setFeedback] = useState("");
  const [reason, setReason] = useState("Insufficient evidence");
  const [targets, setTargets] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null);

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident."); return; }
    getIncident(id).then((next) => {
      setSnapshot(next);
      setSummary(next.draft_report?.summary ?? next.video_summary);
      setDraft(next.draft_report?.summary ?? next.video_summary);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load incident."));
  }, []);

  const submit = async (payload: ReviewPayload) => {
    if (!snapshot || !reviewer.trim()) return;
    setBusy(true); setError("");
    try {
      const next = await reviewIncident(snapshot.incident_id, payload);
      setSnapshot(next);
      sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
      if (["approved", "not_incident"].includes(next.status)) {
        const duration = Date.now() - startedAt.current;
        sessionStorage.setItem(INCIDENT_KEYS.reviewMetrics, JSON.stringify({
          incidentId: next.incident_id, decision: next.status, reviewDurationMs: duration,
          engineerEditCount: payload.action === "edit" ? 1 : 0,
          aiRevisionCycles: next.manual_reanalysis_count,
          observationCount: next.claims.length,
          evidenceLinkedCount: next.claims.filter((claim) => claim.evidence.length).length,
        }));
        router.push("/evaluation");
      } else if (payload.action === "reanalyze") {
        router.push("/processing");
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Review failed."); }
    finally { setBusy(false); }
  };

  if (!snapshot) return <section className="review-card"><p>{error || "Loading incident…"}</p></section>;
  const report = snapshot.draft_report;
  const incidentWindow = (report?.incident_window ?? {}) as { t_start?: number; t0?: number; t_end?: number };
  const start = secondsToTimestamp(incidentWindow.t_start ?? Math.max(0, snapshot.claims[0]?.timestamp_s ?? 0));
  const event = secondsToTimestamp(incidentWindow.t0 ?? snapshot.claims[0]?.timestamp_s ?? 0);
  const end = secondsToTimestamp(incidentWindow.t_end ?? snapshot.claims.at(-1)?.timestamp_s ?? 0);
  return (
    <>
      <section className="review-context">
        <div><p>Recorded Disengagement</p><strong>{event}</strong><small>{snapshot.incident_id}</small></div>
        <div><p>Review Status</p><span className="status pending-review">{snapshot.status}</span></div>
        <div><p>Analysis window</p><strong>{start} <i>→</i> {end}</strong></div>
        {!embedded && <Link href="/processing">← Back to Processing</Link>}
      </section>
      <div className="review-layout">
        <div className="review-main">
          <section className="review-card evidence-video"><div className="panel-heading inline-heading"><div><p className="eyebrow">Video evidence</p><h2>Incident window playback</h2></div><span className="video-source">{start} – {end}</span></div>{artifactUrl(snapshot.artifact_uris.incident_clip) ? <div className="review-video"><video controls src={artifactUrl(snapshot.artifact_uris.incident_clip)} style={{ width: "100%", height: "100%", objectFit: "contain" }} /></div> : <div className="review-video"><div className="video-overlay"><span>FRONT CAMERA</span><span>{event}</span></div><div className="lane-boundary" /></div>}<div className="review-timeline"><div className="review-line">{snapshot.claims.slice(0, 6).map((claim, index) => <span className={`review-marker ${Math.abs(claim.timestamp_s - (incidentWindow.t0 ?? 0)) < 0.5 ? "event" : ""}`} style={{ left: `${10 + index * (80 / Math.max(1, Math.min(snapshot.claims.length - 1, 5)))}%` }} key={claim.claim_id}><b>●</b><small>{claim.claim_id}</small><em>{secondsToTimestamp(claim.timestamp_s)}</em></span>)}</div><div className="review-range"><span>{start}</span><strong>Recorded event · {event}</strong><span>{end}</span></div></div></section>
          <section className="review-card"><div className="panel-heading"><p className="eyebrow">Visual observations</p><h2>Grounded observations</h2></div><div className="review-observations">{snapshot.claims.map((claim) => <article key={claim.claim_id}><div><strong><input type="checkbox" checked={targets.includes(claim.claim_id)} onChange={(change) => setTargets((current) => change.target.checked ? [...current, claim.claim_id] : current.filter((id) => id !== claim.claim_id))} /> {claim.claim_id}</strong><span>{secondsToTimestamp(claim.timestamp_s)}</span></div><p>{claim.text}</p><small>Evidence: <b>{claim.evidence.map((item) => item.evidence_id).join(", ") || "None"}</b> · {claim.verification_status}</small></article>)}</div></section>
          <section className="review-card"><div className="panel-heading"><p className="eyebrow">Telemetry evidence</p><h2>Timestamped vehicle signals</h2></div><div className="signal-list">{snapshot.has_log && snapshot.claim_log_summaries.length ? snapshot.claim_log_summaries.map((item) => <div className={item.within_tolerance ? "event-signal" : ""} key={item.claim_id}><strong>{secondsToTimestamp(item.nearest_timestamp_s ?? item.claim_timestamp_s ?? 0)}</strong><span>{item.summary}</span><small>{item.sample_count} samples · {item.available_signals.join(", ") || "No signal names"}</small></div>) : <div><strong>NO LOG</strong><span>No telemetry evidence is available for this incident.</span></div>}</div></section>
          {report?.timeline?.narrative && <section className="review-card"><h2>Timeline</h2><p>{report.timeline.narrative}</p></section>}
        </div>
        <aside className="review-sidebar">
          <section className="review-card summary-card"><div className="panel-heading inline-heading"><div><p className="eyebrow">Structured summary</p><h2>Evidence summary</h2></div>{editing && <span className="editing-label">Editing</span>}</div>{editing ? <textarea value={draft} onChange={(change) => setDraft(change.target.value)} aria-label="Editable structured summary" /> : <div className="summary-text">{summary.split("\n").map((line, index) => line ? <p className={index === 0 || /event|response|reference|established/i.test(line) ? "summary-subtitle" : ""} key={`${line}-${index}`}>{line}</p> : <br key={index} />)}</div>}<div className="reference-chips">{snapshot.claims.slice(0, 3).map((claim) => <button type="button" key={claim.claim_id} onClick={() => setTargets((current) => current.includes(claim.claim_id) ? current : [...current, claim.claim_id])}>{claim.claim_id}</button>)}</div>{editing ? <div className="edit-actions"><button type="button" className="secondary-action" onClick={() => { setDraft(summary); setEditing(false); }}>Cancel</button><button type="button" className="approve-action" disabled={busy || !draft.trim()} onClick={() => { setSummary(draft); void submit({ action: "edit", reviewer, edits: { summary: draft } }); setEditing(false); }}>Save Changes</button></div> : <div className="review-actions"><button type="button" className="secondary-action" onClick={() => { setDraft(summary); setEditing(true); }}>Edit</button><button type="button" className="reject-action" disabled={busy} onClick={() => setDialog("reject")}>Reject</button><button type="button" className="approve-action" disabled={busy} onClick={() => setDialog("approve")}>Approve</button></div>}</section>
          <section className="review-card ai-rereview-card"><p className="eyebrow">Engineer-guided AI review</p><h2>Review again with AI</h2><p>Select one or more observations, then provide a concrete correction request.</p><label>Engineer request</label><textarea value={feedback} onChange={(change) => setFeedback(change.target.value)} placeholder="Re-check braking evidence and remove unsupported claims." /><button className="approve-action" disabled={busy || !feedback.trim() || !targets.length} onClick={() => void submit({ action: "reanalyze", reviewer, feedback, target_claim_ids: targets })}>Send request to AI</button><small>{snapshot.manual_reanalysis_count} AI revision cycle(s)</small></section>
          <section className="review-card limitations"><p className="eyebrow">Evidence limitations</p><ul>{snapshot.warnings.length ? snapshot.warnings.map((warning) => <li key={warning}>{warning}</li>) : <><li>Root cause is outside the scope of automated evidence review.</li><li>Engineer review is required before approval.</li></>}</ul>{error && <p role="alert" className="form-error">{error}</p>}</section>
        </aside>
      </div>
      {dialog && <div className="dialog-backdrop" role="presentation"><section className="review-dialog" role="dialog" aria-modal="true"><p className="eyebrow">Engineer review</p><h2>{dialog === "approve" ? "Approve this structured summary?" : "Mark this as not an incident?"}</h2><label>Reviewer</label><input value={reviewer} onChange={(change) => setReviewer(change.target.value)} />{dialog === "reject" && <><label>Reason</label><textarea value={reason} onChange={(change) => setReason(change.target.value)} /></>}<div className="dialog-actions"><button className="secondary-action" onClick={() => setDialog(null)}>Cancel</button><button className={dialog === "approve" ? "approve-action" : "reject-action"} disabled={busy || (dialog === "reject" && !reason.trim())} onClick={() => void submit(dialog === "approve" ? { action: "approve", reviewer } : { action: "not_incident", reviewer, reason })}>{dialog === "approve" ? "Approve Summary" : "Confirm Reject"}</button></div></section></div>}
    </>
  );
}
