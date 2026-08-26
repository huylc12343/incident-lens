"use client";

import type { ReactNode } from "react";
import { artifactUrl } from "../../lib/incidentApi";
import type { IncidentSnapshot } from "../../types/incident";

export function TechnicalDetails({ snapshot, comparison }: { snapshot: IncidentSnapshot; comparison?: ReactNode }) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const warnings = [...new Set([...snapshot.warnings, ...(report?.evidence_and_warnings?.warnings ?? [])])];
  return <details className="workspace-panel technical-details">
    <summary><span>Chi tiết kỹ thuật</span><small>Model activity, raw evidence, warnings và audit</small></summary>
    <div className="technical-details-body">
      {comparison}
      <section><h3>Workflow counters</h3><dl className="technical-facts"><div><dt>Auto re-analysis</dt><dd>{snapshot.auto_reanalysis_count}</dd></div><div><dt>Manual re-analysis</dt><dd>{snapshot.manual_reanalysis_count}</dd></div><div><dt>Conflict claims</dt><dd>{snapshot.conflict_claim_ids.join(", ") || "None"}</dd></div></dl></section>
      <section><h3>Model activities</h3><div className="model-activity-list">{snapshot.model_activities.map((activity) => <div key={activity.activity_id}><span className={`activity-dot ${activity.status}`} /><strong>{activity.step}</strong><p>{activity.description}</p><small>{activity.provider} / {activity.model} · {activity.status} · {activity.duration_ms ?? 0} ms · input {activity.usage?.input_tokens ?? 0} · output {activity.usage?.output_tokens ?? 0} · cached {activity.usage?.cached_tokens ?? 0} · reasoning {activity.usage?.reasoning_tokens ?? 0}</small></div>)}{!snapshot.model_activities.length && <p>Không có model activity.</p>}</div></section>
      <section><h3>Warnings</h3>{warnings.length ? <ul className="technical-warning-list">{warnings.map((warning) => <li key={warning}><code>{warning}</code></li>)}</ul> : <p>Không có warning.</p>}</section>
      <section><h3>Raw evidence references</h3><ul className="technical-evidence-list">{snapshot.claims.map((claim) => <li key={claim.claim_id}><strong>{claim.claim_id}</strong><span>{claim.evidence.map((item) => item.evidence_id).join(", ") || "No frame IDs"}</span></li>)}</ul></section>
      <section><h3>Artifacts</h3><ul className="technical-evidence-list">{Object.entries(snapshot.artifact_uris).map(([name, uri]) => <li key={name}><strong>{name}</strong><a href={artifactUrl(uri)} target="_blank" rel="noreferrer">Open artifact</a></li>)}</ul></section>
      <section><h3>Review audit</h3>{snapshot.review_audit.length ? <ul className="technical-evidence-list">{snapshot.review_audit.map((entry, index) => <li key={`${entry.action}-${entry.reviewer}-${index}`}><strong>{entry.action}</strong><span>{entry.reviewer}{entry.feedback ? ` · ${entry.feedback}` : ""}{entry.reason ? ` · ${entry.reason}` : ""}</span></li>)}</ul> : <p>Chưa có review audit.</p>}</section>
    </div>
  </details>;
}
