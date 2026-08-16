"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { artifactUrl, getIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS, secondsToTimestamp } from "../lib/incidentSession";
import type { Claim, IncidentSnapshot } from "../types/incident";
import { IncidentNavigationSidebar } from "./incident-review/IncidentNavigationSidebar";
import { classifyIncidentForDisplay } from "../lib/incidentClassification";

type Finding = { id: string; timestamp: number; description: string; source: string; status: string; evidenceIds: string[] };

export function ReportContent() {
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident. Open an incident from the review queue first."); return; }
    getIncident(id).then(setSnapshot).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load report."));
  }, []);

  const exportJson = () => {
    if (!snapshot) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${snapshot.incident_id}-agent-report.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="report-app-frame">
      <IncidentNavigationSidebar snapshot={snapshot} />
      <section className="report-view">
        {!snapshot ? (
          <section className={`report-load-state ${error ? "error-state" : ""}`} role={error ? "alert" : "status"}>
            {!error && <span className="state-spinner" aria-hidden="true" />}
            <div><strong>{error ? "Report unavailable" : "Loading forensic report"}</strong><p>{error || "Retrieving the reviewed incident artifact…"}</p></div>
          </section>
        ) : <ReportDocument snapshot={snapshot} onExportJson={exportJson} />}
      </section>
    </div>
  );
}

function ReportDocument({ snapshot, onExportJson }: { snapshot: IncidentSnapshot; onExportJson: () => void }) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const classification = classifyIncidentForDisplay(snapshot);
  const audit = snapshot.review_audit.at(-1);
  const linkedClaims = snapshot.claims.filter((claim) => claim.evidence.length).length;
  const coverage = snapshot.claims.length ? Math.round(linkedClaims / snapshot.claims.length * 100) : 0;
  const warnings = [...new Set([...snapshot.warnings, ...(report?.evidence_and_warnings?.warnings ?? [])])];
  const findings = useMemo<Finding[]>(() => {
    if (snapshot.claims.length) return snapshot.claims.map((claim: Claim) => ({ id: claim.claim_id, timestamp: claim.timestamp_s, description: claim.text, source: snapshot.has_log ? "Video + telemetry" : "Video", status: claim.verification_status, evidenceIds: claim.evidence.map((item) => item.evidence_id) }));
    return (report?.timeline?.events ?? []).map((event, index) => ({ id: `event-${index + 1}`, timestamp: event.timestamp_s, description: event.description, source: "Agent timeline", status: "unverified", evidenceIds: event.evidence_ids ?? [] }));
  }, [report?.timeline?.events, snapshot.claims, snapshot.has_log]);
  const evidence = useMemo(() => {
    const seen = new Set<string>();
    return snapshot.claims.flatMap((claim) => claim.evidence.map((item) => ({ ...item, claimText: claim.text }))).filter((item) => !seen.has(item.evidence_id) && Boolean(seen.add(item.evidence_id)));
  }, [snapshot.claims]);
  const frameDirectory = snapshot.artifact_uris.incident_frames;
  const representative = artifactUrl(snapshot.artifact_uris.representative_frame);
  const storedDate = snapshot.stored_at ? new Date(snapshot.stored_at).toLocaleString() : "Active incident";

  if (!report) return <section className="report-load-state error-state"><div><strong>Report not produced yet</strong><p>The agent workflow must reach report generation before this page is available.</p><Link href="/processing">Return to workspace</Link></div></section>;

  return (
    <>
      <div className="report-toolbar">
        <div><Link href="/processing#engineer-review"><span aria-hidden="true">←</span> Back</Link><p>Incidents <span>›</span> <b>{snapshot.incident_id}</b> <span>›</span> <strong>Report</strong></p></div>
        <div><button type="button" className="report-download" onClick={() => window.print()}><span aria-hidden="true">⇩</span> Download PDF</button><button type="button" className="report-export" onClick={onExportJson}><span aria-hidden="true">{`{ }`}</span> Export JSON</button></div>
      </div>

      <article className="forensic-report-document">
        <header className="report-document-header">
          <div className="report-title-row"><div><p className="eyebrow">Forensic incident report</p><h1>{classification.type}</h1></div><span className={`status ${snapshot.status}`}>{snapshot.status}</span></div>
          <div className="report-document-meta"><span>Incident ID: <b>{snapshot.incident_id}</b></span><i /> <span>Date: <b>{storedDate}</b></span><i /> <span>Reviewed by: <b>{audit?.reviewer ?? "Pending engineer review"}</b></span></div>
          <div className="coverage-meter"><span>Evidence coverage</span><div><i style={{ width: `${coverage}%` }} /></div><strong>{coverage}%</strong><small>{linkedClaims}/{snapshot.claims.length} claims linked</small></div>
        </header>

        <section className="report-summary-block"><div><span /><strong>AI-generated summary</strong></div><p>{report.summary || snapshot.video_summary}</p><small>Engineer review remains authoritative. Summary is grounded in the evidence references below.</small></section>

        <section className="report-document-section"><div className="report-section-heading"><div><p className="eyebrow">Evidence timeline</p><h2>Detailed findings</h2></div><span>{findings.length} finding(s)</span></div><div className="document-table-wrap"><table><thead><tr><th>Timestamp</th><th>Event description</th><th>Source</th><th>Verification</th></tr></thead><tbody>{findings.map((finding) => <tr key={finding.id}><td className="mono">{secondsToTimestamp(finding.timestamp)}</td><td><strong>{finding.description}</strong><small>{finding.evidenceIds.join(", ") || finding.id}</small></td><td>{finding.source}</td><td><span className={`finding-status ${finding.status}`}>{finding.status.replace("_", " ")}</span></td></tr>)}</tbody></table></div></section>

        {warnings.length > 0 && <section className="report-warning" role="note"><span aria-hidden="true">!</span><div><strong>Evidence warning</strong><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></section>}

        <section className="report-document-section"><div className="report-section-heading"><div><p className="eyebrow">Visual evidence</p><h2>Evidence gallery</h2></div><span>{evidence.length || (representative ? 1 : 0)} artifact(s)</span></div><div className="document-evidence-gallery">{evidence.map((item) => <figure key={item.evidence_id}><div><Image unoptimized width={640} height={360} src={frameDirectory ? artifactUrl(`${frameDirectory}/${item.evidence_id}.jpg`) : representative} alt={`Evidence ${item.evidence_id} at ${secondsToTimestamp(item.timestamp_s)}`} /><span>{secondsToTimestamp(item.timestamp_s)}</span></div><figcaption><strong>{item.evidence_id}</strong><p>{item.claimText}</p></figcaption></figure>)}{!evidence.length && representative && <figure><div><Image unoptimized width={640} height={360} src={representative} alt="Representative incident frame" /><span>{secondsToTimestamp(report.incident_window?.t0 ?? 0)}</span></div><figcaption><strong>Representative frame</strong><p>{snapshot.video_summary}</p></figcaption></figure>}{!evidence.length && !representative && <div className="report-empty-gallery"><strong>No image artifacts available</strong><p>The report still retains timestamp and textual evidence references.</p></div>}</div></section>

        <section className="report-technical-appendix"><div className="report-section-heading"><div><p className="eyebrow">Full agent artifact</p><h2>Technical appendix</h2></div></div><div className="appendix-grid"><article><strong>Video observations</strong><p>{report.video_observations?.narrative || snapshot.video_summary}</p></article><article><strong>Telemetry findings</strong><p>{report.log_findings?.narrative || (snapshot.has_log ? "Telemetry findings are included in the claim verification records." : "No telemetry log was supplied.")}</p></article><article><strong>Evidence alignment</strong><p>{report.alignment?.narrative || "No additional alignment narrative."}</p></article><article><strong>Hypothesized causes</strong><p>{report.hypothesized_causes || "No cause hypothesis was recorded."}</p></article></div></section>

        <section className="report-document-section"><div className="report-section-heading"><div><p className="eyebrow">Execution trace</p><h2>Model activity</h2></div><span>{snapshot.model_activities.length} operation(s)</span></div><div className="model-activity-list">{snapshot.model_activities.map((activity) => <div key={activity.activity_id}><span className={`activity-dot ${activity.status}`} /><strong>{activity.step}</strong><p>{activity.description}</p><small>{activity.provider} / {activity.model} · {activity.status} · {activity.duration_ms ?? 0} ms · {activity.usage?.total_tokens ?? 0} tokens</small></div>)}{!snapshot.model_activities.length && <p>No model activity records were returned.</p>}</div></section>

        <section className="engineer-signature"><div><strong>Engineer review record</strong><p>{audit?.reason || audit?.feedback || (audit ? `Decision recorded: ${audit.action}.` : "This report is awaiting an engineer decision.")}</p>{audit && <small>Reviewed by {audit.reviewer} · Action: {audit.action}</small>}</div><span className={audit ? "signed" : ""}>{audit ? "✓ Reviewed" : "Pending"}</span></section>

        <footer className="report-document-actions"><Link href="/processing#engineer-review"><span aria-hidden="true">←</span> Back to workspace</Link><div><button type="button" onClick={onExportJson}>Export JSON</button><button type="button" onClick={() => window.print()}>Download PDF</button></div></footer>
      </article>
    </>
  );
}
