import type { IncidentSnapshot } from "../../types/incident";

export function IncidentHeader({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const ready = snapshot?.status === "awaiting_review";
  return (
    <section className="incident-workspace-header">
      <div>
        <p className="incident-breadcrumb">Incidents <span>›</span> {snapshot?.incident_id ?? "New incident"}</p>
        <h1>Disengagement</h1>
        <div className="incident-header-chips"><span>Incident #{snapshot?.incident_id ?? "Starting…"}</span><span className="source-chip">Video evidence</span>{snapshot?.has_log && <span className="source-chip">Telemetry linked</span>}</div>
      </div>
      <div className={`workspace-status ${ready ? "ready" : ""}`}>
        <strong>{ready ? "Processing complete · Ready for review" : snapshot?.status ?? "Initializing"}</strong>
        <small>{snapshot?.claims.length ?? 0} grounded observation(s)</small>
      </div>
    </section>
  );
}
