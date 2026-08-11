"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { INCIDENT_KEYS } from "../lib/incidentSession";

type Metrics = {
  incidentId: string;
  decision: string;
  reviewDurationMs: number;
  engineerEditCount: number;
  aiRevisionCycles: number;
  observationCount: number;
  evidenceLinkedCount: number;
};

const fallback: Metrics = {
  incidentId: "DG-MVP",
  decision: "Pending Review",
  reviewDurationMs: 0,
  engineerEditCount: 0,
  aiRevisionCycles: 0,
  observationCount: 3,
  evidenceLinkedCount: 3,
};

export function EvaluationContent() {
  const [metrics, setMetrics] = useState<Metrics>(fallback);
  useEffect(() => {
    const stored = sessionStorage.getItem(INCIDENT_KEYS.reviewMetrics);
    if (stored) {
      try {
        setMetrics(JSON.parse(stored) as Metrics);
      } catch {
        // Keep the fallback metrics when stored session data is invalid.
      }
    }
  }, []);
  const traceability = metrics.observationCount
    ? Math.round((metrics.evidenceLinkedCount / metrics.observationCount) * 100)
    : 0;
  const duration = `${Math.floor(metrics.reviewDurationMs / 60000)}m ${Math.floor((metrics.reviewDurationMs % 60000) / 1000)}s`;
  return (
    <>
      <section className="evaluation-hero">
        <div>
          <p className="eyebrow">Incident {metrics.incidentId}</p>
          <h2>Review outcome: {metrics.decision}</h2>
          <p>Metrics are computed from this engineer review session.</p>
        </div>
        <span className={`status ${metrics.decision.toLowerCase().replace(" ", "-")}`}>
          {metrics.decision}
        </span>
      </section>
      <section className="evaluation-grid" aria-label="Evaluation metrics">
        <article><span>Evidence traceability</span><strong>{traceability}%</strong><small>{metrics.evidenceLinkedCount}/{metrics.observationCount} observations linked</small></article>
        <article><span>Review duration</span><strong>{duration}</strong><small>Engineer active review time</small></article>
        <article><span>Engineer edits</span><strong>{metrics.engineerEditCount}</strong><small>Direct summary edits</small></article>
        <article><span>AI revision cycles</span><strong>{metrics.aiRevisionCycles}</strong><small>Engineer-guided re-reviews</small></article>
      </section>
      <section className="evaluation-details">
        <div><h3>MVP evaluation scope</h3><p>Measures workflow completion, evidence linkage, review effort, revision count, and final decision. Model-quality metrics require labeled benchmark incidents.</p></div>
        <div className="evaluation-actions"><Link className="secondary-action" href="/review">← Return to review</Link><Link className="approve-action" href="/report">Open reviewed report →</Link></div>
      </section>
    </>
  );
}
