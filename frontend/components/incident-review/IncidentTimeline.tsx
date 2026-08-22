import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim } from "../../types/incident";

export function IncidentTimeline({ claims, selectedId, windowStart, windowEnd, focusTime, onSelect }: { claims: Claim[]; selectedId: string; windowStart?: number; windowEnd?: number; focusTime?: number; onSelect: (claim: Claim) => void }) {
  if (!claims.length) return <section className="workspace-strip timeline-empty"><strong>Event timeline pending</strong><p>Markers will appear when the agent publishes observations.</p></section>;
  const ordered = [...claims].sort((a, b) => a.timestamp_s - b.timestamp_s);
  const start = Math.min(windowStart ?? ordered[0].timestamp_s, ordered[0].timestamp_s);
  const end = Math.max(windowEnd ?? ordered.at(-1)?.timestamp_s ?? start, ordered.at(-1)?.timestamp_s ?? start, start + 0.001);
  const selected = ordered.find((claim) => claim.claim_id === selectedId) ?? ordered[0];
  const position = (value: number) => Math.max(1.5, Math.min(98.5, ((value - start) / (end - start)) * 100));
  return (
    <section className="workspace-strip incident-timeline redesigned-timeline" aria-labelledby="timeline-title">
      <header><div><p className="eyebrow">Synchronized evidence</p><h2 id="timeline-title">Incident event markers</h2></div><span>{ordered.length} detected event(s)</span></header>
      <div className="event-track-wrap">
        <div className="event-track"><span className="event-track-active" />{focusTime !== undefined && <i className="detected-focus-line" style={{ left: `${position(focusTime)}%` }} title={`Detected event ${secondsToTimestamp(focusTime)}`} />}{ordered.map((claim, index) => <button key={claim.claim_id} type="button" className={selected.claim_id === claim.claim_id ? "selected" : ""} style={{ left: `${position(claim.timestamp_s)}%` }} onClick={() => onSelect(claim)} aria-label={`Seek to ${secondsToTimestamp(claim.timestamp_s)}: ${claim.text}`} aria-pressed={selected.claim_id === claim.claim_id}><span>{index + 1}</span><small>{secondsToTimestamp(claim.timestamp_s)}</small></button>)}</div>
        <div className="event-track-scale"><span>{secondsToTimestamp(start)}</span><span>Incident window</span><span>{secondsToTimestamp(end)}</span></div>
      </div>
      <div className="selected-event-card"><span className="selected-event-number">{ordered.findIndex((claim) => claim.claim_id === selected.claim_id) + 1}</span><div><header><strong>{selected.claim_id}</strong><time>{secondsToTimestamp(selected.timestamp_s)}</time><span className={`finding-status ${selected.verification_status}`}>{selected.verification_status.replace("_", " ")}</span></header><p>{selected.text}</p><small>Evidence: {selected.evidence.map((item) => item.evidence_id).join(", ") || "No frame reference"}</small></div></div>
    </section>
  );
}
