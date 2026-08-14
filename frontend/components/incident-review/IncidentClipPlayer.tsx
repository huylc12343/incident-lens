import { secondsToTimestamp } from "../../lib/incidentSession";

export function IncidentClipPlayer({ clipUrl, start, focus, end }: { clipUrl: string; start?: number; focus?: number; end?: number }) {
  const duration = start !== undefined && end !== undefined ? Math.max(0, end - start) : undefined;
  const focusPosition = start !== undefined && focus !== undefined && end !== undefined && end > start ? Math.max(0, Math.min(100, ((focus - start) / (end - start)) * 100)) : 50;
  return (
    <section className="incident-clip-card refined-clip-card" aria-labelledby="incident-clip-title">
      <header className="refined-clip-header"><div><span className="clip-record-dot" /><div><p className="eyebrow">Extracted evidence</p><h2 id="incident-clip-title">Incident evidence clip</h2></div></div><div className="clip-header-meta"><span>FORENSIC CUT</span><strong>{duration !== undefined ? `${duration.toFixed(1)} sec` : "Pending"}</strong></div></header>
      <div className="refined-clip-stage">{clipUrl ? <video controls playsInline preload="metadata" src={clipUrl} aria-label="Extracted incident evidence clip" /> : <div className="clip-empty-state"><span className="state-spinner" /><p>Generating evidence clip…</p></div>}<div className="clip-stage-topline"><span>EVIDENCE · INCIDENT WINDOW</span><small>{secondsToTimestamp(start ?? 0)} — {secondsToTimestamp(end ?? 0)}</small></div><div className="clip-event-pin" style={{ left: `${focusPosition}%` }}><span>EVENT</span><i /></div></div>
      <div className="refined-clip-controls"><div className="clip-progress-track"><span style={{ width: `${focusPosition}%` }} /><i style={{ left: `${focusPosition}%` }} /></div><div className="clip-time-scale"><span>{secondsToTimestamp(start ?? 0)}</span><strong>Detected at {secondsToTimestamp(focus ?? 0)}</strong><span>{secondsToTimestamp(end ?? 0)}</span></div></div>
      <footer className="refined-clip-footer"><div><span>Pre-event context</span><strong>{start !== undefined && focus !== undefined ? `${Math.max(0, focus - start).toFixed(1)}s` : "—"}</strong></div><div className="event-meta"><span>Detected event</span><strong>{secondsToTimestamp(focus ?? 0)}</strong></div><div><span>Post-event context</span><strong>{focus !== undefined && end !== undefined ? `${Math.max(0, end - focus).toFixed(1)}s` : "—"}</strong></div></footer>
    </section>
  );
}
