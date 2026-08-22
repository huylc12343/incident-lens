"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS } from "../lib/incidentSession";
import type { IncidentSnapshot } from "../types/incident";

type Metrics = { reviewDurationMs: number; engineerEditCount: number; aiRevisionCycles: number };

export function EvaluationContent() {
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [metrics, setMetrics] = useState<Metrics>({ reviewDurationMs: 0, engineerEditCount: 0, aiRevisionCycles: 0 });
  const [error, setError] = useState("");
  useEffect(() => {
    const stored = sessionStorage.getItem(INCIDENT_KEYS.reviewMetrics);
    if (stored) try { setMetrics(JSON.parse(stored) as Metrics); } catch { /* ignore invalid browser state */ }
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (id) getIncident(id).then(setSnapshot).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load evaluation."));
  }, []);
  if (!snapshot) return <section className="evaluation-hero"><p>{error || "Loading evaluation…"}</p></section>;
  const linked = snapshot.claims.filter((claim) => claim.evidence.length).length;
  const traceability = snapshot.claims.length ? Math.round(linked / snapshot.claims.length * 100) : 0;
  const duration = `${Math.floor(metrics.reviewDurationMs / 60000)}m ${Math.floor(metrics.reviewDurationMs % 60000 / 1000)}s`;
  const totalTokens = snapshot.model_activities.reduce((sum, activity) => sum + Number((activity as unknown as { usage?: { total_tokens?: number } }).usage?.total_tokens ?? 0), 0);
  return <>
    <section className="evaluation-hero"><div><p className="eyebrow">Incident {snapshot.incident_id}</p><h2>Review outcome: {snapshot.status}</h2><p>Metrics below come from the completed workflow and engineer audit.</p></div><span className={`status ${snapshot.status}`}>{snapshot.status}</span></section>
    <section className="evaluation-grid" aria-label="Evaluation metrics">
      <article><span>Evidence traceability</span><strong>{traceability}%</strong><small>{linked}/{snapshot.claims.length} claims linked</small></article>
      <article><span>Review duration</span><strong>{duration}</strong><small>Engineer active review time</small></article>
      <article><span>Engineer decisions</span><strong>{snapshot.review_audit.length}</strong><small>{metrics.engineerEditCount} direct edits</small></article>
      <article><span>AI revision cycles</span><strong>{snapshot.manual_reanalysis_count}</strong><small>{totalTokens.toLocaleString()} model tokens</small></article>
    </section>
    <section className="evaluation-details"><div><h3>Workflow evidence</h3><p>{snapshot.final_report?.summary ?? snapshot.draft_report?.summary ?? snapshot.video_summary}</p></div><div className="evaluation-actions"><Link className="secondary-action" href="/processing#engineer-review">← Return to review</Link><Link className="approve-action" href="/report">Open reviewed report →</Link></div></section>
  </>;
}
