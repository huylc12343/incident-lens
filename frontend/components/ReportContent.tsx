"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS, secondsToTimestamp } from "../lib/incidentSession";
import type { IncidentSnapshot } from "../types/incident";

export function ReportContent() {
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident. Open an incident from the review queue first."); return; }
    getIncident(id).then(setSnapshot).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load report."));
  }, []);

  if (!snapshot) return <section className="report-card"><p>{error || "Loading report…"}</p></section>;
  const report = snapshot.final_report ?? snapshot.draft_report;
  if (!report) return <section className="report-card"><p>The agent has not produced a report yet.</p><Link href="/processing">Return to processing</Link></section>;
  const window = report.incident_window;
  const audit = snapshot.review_audit.at(-1);
  const exportJson = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `${snapshot.incident_id}-agent-report.json`; link.click(); URL.revokeObjectURL(url);
  };

  return <>
    <section className="report-meta">
      <div><p>Incident ID</p><strong>{snapshot.incident_id}</strong></div>
      <div><p>Detected Event</p><strong>{secondsToTimestamp(window?.t0 ?? snapshot.claims[0]?.timestamp_s ?? 0)}</strong></div>
      <div><p>Workflow Status</p><span className={`status ${snapshot.status}`}>{snapshot.status}</span></div>
      <div><p>Reviewed by</p><strong>{audit?.reviewer ?? "Pending engineer review"}</strong></div>
      <div><p>Evidence</p><strong>{snapshot.claims.length} claims · {snapshot.has_log ? "Video + telemetry" : "Video only"}</strong></div>
    </section>
    <div className="report-layout">
      <div className="report-main">
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">1. Video analysis</p><h2>Agent summary</h2></div><p>{snapshot.video_summary || report.summary}</p></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">2. Structured report</p><h2>Incident summary</h2></div><p>{report.summary}</p></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">3. Timeline</p><h2>Evidence-grounded sequence</h2></div><p>{report.timeline?.narrative || "No timeline narrative."}</p><div className="review-observations">{report.timeline?.events?.map((event, index) => <article key={`${event.timestamp_s}-${index}`}><div><strong>Event {index + 1}</strong><span>{secondsToTimestamp(event.timestamp_s)}</span></div><p>{event.description}</p><small>Evidence: {event.evidence_ids?.join(", ") || "None"}</small></article>)}</div></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">4. Visual observations</p><h2>Claims and frame evidence</h2></div><p>{report.video_observations?.narrative}</p><div className="report-table-wrap"><table className="report-table"><thead><tr><th>Timestamp</th><th>Claim</th><th>Evidence</th><th>Verification</th></tr></thead><tbody>{snapshot.claims.map((claim) => <tr key={claim.claim_id}><td className="mono">{secondsToTimestamp(claim.timestamp_s)}</td><td><strong>{claim.text}</strong><small>{claim.claim_id}</small></td><td>{claim.evidence.map((item) => item.evidence_id).join(", ") || "None"}</td><td>{claim.verification_status}</td></tr>)}</tbody></table></div></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">5. Telemetry log</p><h2>Timestamped log findings</h2></div><p>{report.log_findings?.narrative || (snapshot.has_log ? "Log analysis is pending." : "No telemetry log was supplied.")}</p><div className="signal-list">{snapshot.claim_log_summaries.map((item) => <div className={item.within_tolerance ? "event-signal" : ""} key={item.claim_id}><strong>{secondsToTimestamp(item.nearest_timestamp_s ?? item.claim_timestamp_s ?? 0)}</strong><span>{item.summary}</span><small>{item.sample_count} samples · {item.available_signals.join(", ") || "No signals"}</small></div>)}</div></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">6. Alignment</p><h2>Video and telemetry verification</h2></div><p>{report.alignment?.narrative || "No alignment narrative."}</p></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">7. Hypotheses</p><h2>Potential causes</h2></div><p>{report.hypothesized_causes}</p></section>
        <section className="report-card"><div className="panel-heading"><p className="eyebrow">8. Model activity</p><h2>Agent execution log</h2></div><div className="signal-list">{snapshot.model_activities.map((activity) => <div className={activity.status === "failed" ? "event-signal" : ""} key={activity.activity_id}><strong>{activity.step}</strong><span>{activity.description}</span><small>{activity.provider} / {activity.model} · {activity.status} · {activity.duration_ms ?? 0} ms · {activity.usage?.total_tokens ?? 0} tokens{activity.error_code ? ` · ${activity.error_code}` : ""}</small></div>)}</div></section>
      </div>
      <aside className="report-sidebar">
        <section className="report-card limitations"><p className="eyebrow">9. Evidence limitations</p><ul>{[...snapshot.warnings, ...(report.evidence_and_warnings?.warnings ?? [])].length ? [...new Set([...snapshot.warnings, ...(report.evidence_and_warnings?.warnings ?? [])])].map((warning) => <li key={warning}>{warning}</li>) : <li>No additional warnings were reported.</li>}</ul></section>
        <section className="report-card audit-card"><p className="eyebrow">10. Review audit</p><dl>{snapshot.review_audit.length ? snapshot.review_audit.map((entry, index) => <div key={`${entry.action}-${index}`}><dt>{entry.action}</dt><dd>{entry.reviewer}{entry.reason ? ` · ${entry.reason}` : ""}</dd></div>) : <div><dt>Status</dt><dd>Awaiting engineer review</dd></div>}</dl></section>
        <section className="report-card export-card"><p className="eyebrow">Export</p><h2>Complete agent response</h2><p>Download the same structured data returned by FastAPI.</p><button type="button" className="approve-action" onClick={exportJson}>Export JSON</button></section>
        <Link className="return-review" href="/review">← Return to Review</Link>
      </aside>
    </div>
  </>;
}
