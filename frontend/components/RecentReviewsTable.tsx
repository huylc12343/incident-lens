"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getIncident, listIncidents } from "../lib/incidentApi";
import { INCIDENT_KEYS, processingPath, secondsToTimestamp } from "../lib/incidentSession";
import type { IncidentSnapshot } from "../types/incident";

export function RecentReviewsTable() {
  const router = useRouter();
  const [reviews, setReviews] = useState<IncidentSnapshot[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listIncidents()
      .then(({ incident_ids }) => Promise.all(incident_ids.slice(0, 10).map((id) => getIncident(id))))
      .then(setReviews)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load incident history."))
      .finally(() => setLoading(false));
  }, []);

  const openIncident = (snapshot: IncidentSnapshot) => {
    sessionStorage.setItem(INCIDENT_KEYS.incidentId, snapshot.incident_id);
    sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(snapshot));
    const report = snapshot.final_report ?? snapshot.draft_report;
    const timestamp = report?.incident_window?.t0 ?? snapshot.claims[0]?.timestamp_s;
    if (typeof timestamp === "number") sessionStorage.setItem(INCIDENT_KEYS.timestamp, secondsToTimestamp(timestamp));
    const processing = processingPath(snapshot.incident_id);
    router.push(snapshot.status === "awaiting_review" ? `${processing}#engineer-review` : snapshot.status === "running" || snapshot.status === "queued" ? processing : "/report");
  };

  return (
    <section id="recent-reviews" className="recent-section" aria-labelledby="recent-title">
      <div className="recent-heading"><div><p className="eyebrow">Incident history</p><h2 id="recent-title">Recent reviews</h2><p>Open an active investigation or inspect a completed decision.</p></div><span>{loading ? "Syncing…" : `${reviews.length} incident(s)`}</span></div>
      <div className="table-wrap"><table><thead><tr><th>Incident ID</th><th>Event Timestamp</th><th>Stored At</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
        <tbody>
          {reviews.map((review) => {
            const report = review.final_report ?? review.draft_report;
            const timestamp = report?.incident_window?.t0 ?? review.claims[0]?.timestamp_s ?? 0;
            return <tr key={review.incident_id}><td><strong>{review.incident_id}</strong></td><td className="mono">{secondsToTimestamp(timestamp)}</td><td>{review.stored_at ? new Date(review.stored_at).toLocaleString() : "Active"}</td><td><span className={`status ${review.status}`}>{review.status}</span></td><td><button type="button" className="row-action" onClick={() => openIncident(review)}>Open <span>→</span></button></td></tr>;
          })}
          {loading && <tr className="table-state-row"><td colSpan={5}><span className="state-spinner" aria-hidden="true" /> Loading incident history…</td></tr>}
          {!loading && !reviews.length && <tr className="table-state-row"><td colSpan={5}><strong>{error ? "History unavailable" : "No incidents yet"}</strong><small>{error || "Upload evidence above to create the first analysis."}</small></td></tr>}
        </tbody>
      </table></div>
    </section>
  );
}
