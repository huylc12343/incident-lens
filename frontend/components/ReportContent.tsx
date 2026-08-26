"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS } from "../lib/incidentSession";
import { classifyIncidentForDisplay } from "../lib/incidentClassification";
import { incidentStatusLabel } from "../lib/incidentStatus";
import type { IncidentSnapshot } from "../types/incident";
import { ClaimReviewList } from "./incident-review/ClaimReviewList";
import { IncidentEvidenceGallery } from "./incident-review/IncidentEvidenceGallery";
import { IncidentNavigationSidebar } from "./incident-review/IncidentNavigationSidebar";
import { IncidentTimeline } from "./incident-review/IncidentTimeline";
import { TechnicalDetails } from "./incident-review/TechnicalDetails";
import { TelemetryPanel, telemetryChartArtifacts } from "./incident-review/TelemetryPanel";

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

  return <div className="report-app-frame">
    <IncidentNavigationSidebar snapshot={snapshot} />
    <section className="report-view">{!snapshot ? <section className={`report-load-state ${error ? "error-state" : ""}`} role={error ? "alert" : "status"}>{!error && <span className="state-spinner" aria-hidden="true" />}<div><strong>{error ? "Report unavailable" : "Loading forensic report"}</strong><p>{error || "Retrieving the reviewed incident artifact…"}</p></div></section> : <ReportDocument snapshot={snapshot} onExportJson={exportJson} />}</section>
  </div>;
}

function ReportDocument({ snapshot, onExportJson }: { snapshot: IncidentSnapshot; onExportJson: () => void }) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const classification = classifyIncidentForDisplay(snapshot);
  const audit = snapshot.review_audit.at(-1);
  if (!report) return <section className="report-load-state error-state"><div><strong>Report not produced yet</strong><p>The workflow must reach report generation before this page is available.</p><Link href="/processing">Return to workspace</Link></div></section>;
  const charts = telemetryChartArtifacts(snapshot.artifact_uris);
  const verificationResults = report.alignment?.verification?.results ?? [];
  const storedDate = snapshot.stored_at ? new Date(snapshot.stored_at).toLocaleString() : "Active incident";

  return <>
    <div className="report-toolbar"><div><Link href="/processing#engineer-review"><span aria-hidden="true">←</span> Back</Link><p>Incidents <span>›</span> <b>{snapshot.incident_id}</b> <span>›</span> <strong>Report</strong></p></div><div><button type="button" className="report-download" onClick={() => window.print()}>Download PDF</button><button type="button" className="report-export" onClick={onExportJson}>Export JSON</button></div></div>
    <article className="forensic-report-document report-flow-vertical">
      <header className="report-document-header"><div className="report-title-row"><div><p className="eyebrow">Forensic incident report</p><h1>{classification.type}</h1></div><span className={`status ${snapshot.status}`}>{incidentStatusLabel(snapshot.status)}</span></div><div className="report-document-meta"><span>Incident ID: <b>{snapshot.incident_id}</b></span><i /><span>Date: <b>{storedDate}</b></span><i /><span>Reviewed by: <b>{audit?.reviewer ?? "Pending engineer review"}</b></span></div></header>

      <section className="report-primary-narrative"><p className="eyebrow">Nhận định từ video</p><h2>Nhận định tổng quát</h2><p>{report.video_observations?.narrative || "Backend chưa cung cấp nhận định từ video."}</p></section>
      <IncidentEvidenceGallery snapshot={snapshot} />
      <IncidentTimeline report={report} claims={snapshot.claims} />
      <TelemetryPanel hasLog={snapshot.has_log} charts={charts} />
      <ClaimReviewList claims={snapshot.claims} summaries={snapshot.claim_log_summaries} verificationResults={verificationResults} hasLog={snapshot.has_log} />

      <section className="workspace-panel vertical-report-sections final-report-sections"><div className="workspace-panel-heading"><div><p className="eyebrow">Report</p><h2>Nội dung báo cáo</h2></div></div><section><h3>Kết luận báo cáo</h3><p>{report.summary}</p></section><section><h3>Nguyên nhân giả thuyết</h3><p>{report.hypothesized_causes}</p></section></section>
      <TechnicalDetails snapshot={snapshot} />
      <section className="engineer-signature"><div><strong>Engineer review record</strong><p>{audit?.reason || audit?.feedback || (audit ? `Decision recorded: ${audit.action}.` : "This report is awaiting an engineer decision.")}</p>{audit && <small>Reviewed by {audit.reviewer} · Action: {audit.action}</small>}</div><span className={audit ? "signed" : ""}>{audit ? "✓ Reviewed" : "Pending"}</span></section>
      <footer className="report-document-actions"><Link href="/processing#engineer-review">← Back to workspace</Link><div><button type="button" onClick={onExportJson}>Export JSON</button><button type="button" onClick={() => window.print()}>Download PDF</button></div></footer>
    </article>
  </>;
}
