import type { IncidentSnapshot } from "../../types/incident";

export function IncidentHeader({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const ready = snapshot?.status === "awaiting_review";
  return (
    <section className="incident-workspace-header">
      <div>
        <p className="eyebrow">Incident Review</p>
        <h1>Disengagement</h1>
        <span>Incident #{snapshot?.incident_id ?? "Starting…"}</span>
      </div>
      <div className={`workspace-status ${ready ? "ready" : ""}`}>
        <strong>{ready ? "Processing complete · Ready for review" : snapshot?.status ?? "Initializing"}</strong>
        <small>{snapshot?.claims.length ?? 0} grounded observation(s)</small>
      </div>
    </section>
  );
}
