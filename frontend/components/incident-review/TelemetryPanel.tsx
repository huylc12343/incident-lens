import { secondsToTimestamp } from "../../lib/incidentSession";
import type { ClaimLogSummary } from "../../types/incident";

function metricEntries(item: ClaimLogSummary) {
  return Object.entries(item.metrics).flatMap(([signal, values]) => Object.entries(values).slice(0, 3).map(([name, value]) => ({ signal, name, value })));
}

export function TelemetryPanel({ summaries, selectedClaimId, hasLog }: { summaries: ClaimLogSummary[]; selectedClaimId: string; hasLog: boolean }) {
  const selected = summaries.find((item) => item.claim_id === selectedClaimId) ?? summaries[0];
  return (
    <section className="workspace-panel telemetry-workspace-panel">
      <div className="workspace-panel-heading"><div><p className="eyebrow">Telemetry / log evidence</p><h2>Vehicle state at selected event</h2></div>{selected && <strong>{secondsToTimestamp(selected.nearest_timestamp_s ?? selected.claim_timestamp_s ?? 0)}</strong>}</div>
      {!hasLog && <p>No telemetry log was supplied. Verification uses video evidence only.</p>}
      {hasLog && !selected && <p>Telemetry is being aligned with agent observations.</p>}
      {selected && <><div className="telemetry-metrics">{metricEntries(selected).map((metric) => <article key={`${metric.signal}-${metric.name}`}><span>{metric.signal}</span><strong>{String(metric.value ?? "—")}</strong><small>{metric.name}</small></article>)}</div><p className="telemetry-summary">{selected.summary}</p><small>{selected.sample_count} samples · {selected.available_signals.join(", ") || "No named signals"}</small></>}
    </section>
  );
}
