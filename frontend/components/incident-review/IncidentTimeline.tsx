import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim } from "../../types/incident";

export function IncidentTimeline({ claims, selectedId, onSelect }: { claims: Claim[]; selectedId: string; onSelect: (claim: Claim) => void }) {
  if (!claims.length) return <section className="workspace-strip"><p>Event markers will appear when the agent publishes observations.</p></section>;
  const ordered = [...claims].sort((a, b) => a.timestamp_s - b.timestamp_s);
  const start = ordered[0].timestamp_s;
  const end = Math.max(ordered.at(-1)?.timestamp_s ?? start, start + 0.001);
  const selected = ordered.find((claim) => claim.claim_id === selectedId) ?? ordered[0];
  return (
    <section className="workspace-strip incident-timeline" aria-label="Incident timeline">
      <div className="timeline-axis">
        {ordered.map((claim) => <button key={claim.claim_id} type="button" className={selectedId === claim.claim_id ? "selected" : ""} style={{ left: `${Math.max(2, Math.min(98, ((claim.timestamp_s - start) / (end - start)) * 100))}%` }} onClick={() => onSelect(claim)} title={claim.text}><span>●</span><small>{secondsToTimestamp(claim.timestamp_s)}</small></button>)}
      </div>
      <div className="timeline-caption"><span>{secondsToTimestamp(start)}</span><strong>{ordered.length} event marker(s)</strong><span>{secondsToTimestamp(end)}</span></div>
      <div className="selected-event-row"><span className="selected-event-dot" /><strong>{selected.claim_id}</strong><time>{secondsToTimestamp(selected.timestamp_s)}</time><p>{selected.text}</p></div>
    </section>
  );
}
