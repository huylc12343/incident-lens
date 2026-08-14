"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getIncident, listIncidents } from "../lib/incidentApi";
import { INCIDENT_KEYS, secondsToTimestamp } from "../lib/incidentSession";
import type { IncidentSnapshot } from "../types/incident";

export function RecentReviewsTable() {
  const router = useRouter();
  const [reviews, setReviews] = useState<IncidentSnapshot[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    listIncidents()
      .then(({ incident_ids }) => Promise.all(incident_ids.slice(0, 10).map((id) => getIncident(id))))
      .then(setReviews)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load incident history."));
  }, []);

  const openIncident = (snapshot: IncidentSnapshot) => {
    sessionStorage.setItem(INCIDENT_KEYS.incidentId, snapshot.incident_id);
    sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(snapshot));
    const report = snapshot.final_report ?? snapshot.draft_report;
    const timestamp = report?.incident_window?.t0 ?? snapshot.claims[0]?.timestamp_s;
    if (timestamp !== undefined) sessionStorage.setItem(INCIDENT_KEYS.timestamp, secondsToTimestamp(timestamp));
    router.push(snapshot.status === "running" || snapshot.status === "queued" ? "/processing" : snapshot.status === "awaiting_review" ? "/review" : "/report");
  };

  return (
    <section id="recent-reviews" className="recent-section" aria-labelledby="recent-title">
      <div className="recent-heading"><div><p className="eyebrow">Review queue</p><h2 id="recent-title">Recent Disengagement Reviews</h2></div><span>{reviews.length} incident(s)</span></div>
      <div className="table-wrap"><table><thead><tr><th>Incident ID</th><th>Event Timestamp</th><th>Stored At</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
        <tbody>
          {reviews.map((review) => {
            const report = review.final_report ?? review.draft_report;
            const timestamp = report?.incident_window?.t0 ?? review.claims[0]?.timestamp_s ?? 0;
            return <tr key={review.incident_id}><td><strong>{review.incident_id}</strong></td><td className="mono">{secondsToTimestamp(timestamp)}</td><td>{review.stored_at ? new Date(review.stored_at).toLocaleString() : "Active"}</td><td><span className={`status ${review.status}`}>{review.status}</span></td><td><button type="button" className="row-action" onClick={() => openIncident(review)}>Open <span>→</span></button></td></tr>;
          })}
          {!reviews.length && <tr><td colSpan={5}>{error || "No incidents stored yet."}</td></tr>}
        </tbody>
      </table></div>
    </section>
  );
}
