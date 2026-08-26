"use client";

import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim, ClaimLogSummary, ClaimVerification } from "../../types/incident";

function number(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : String(value ?? "—");
}

function signalLabel(value: string) {
  const labels: Record<string, string> = {
    speed_kmh: "Speed",
    acceleration: "Acceleration",
    max_deceleration: "Max deceleration",
    brake: "Brake",
    throttle: "Throttle",
    steer: "Steering",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function LogReference({ summary, hasLog }: { summary?: ClaimLogSummary; hasLog: boolean }) {
  if (!hasLog) return <p className="claim-log-empty">Không có dữ liệu telemetry</p>;
  if (!summary) return <p className="claim-log-empty">Backend chưa cung cấp log tham chiếu cho nhận định này.</p>;
  const hasWindow = typeof summary.sample_start_s === "number" && typeof summary.sample_end_s === "number";
  return <div className="claim-log-reference">
    <strong>{hasWindow ? `${summary.sample_start_s?.toFixed(2)}s → ${summary.sample_end_s?.toFixed(2)}s` : "Không có log window"}</strong>
    {typeof summary.nearest_timestamp_s === "number" && <span>Nearest sample: {summary.nearest_timestamp_s.toFixed(2)}s</span>}
  </div>;
}

function ClaimDetails({ claim, summary }: { claim: Claim; summary?: ClaimLogSummary }) {
  return <details className="claim-technical-details">
    <summary>Mở chi tiết</summary>
    <div className="claim-detail-grid">
      <div><span>Claim timestamp</span><strong>{typeof claim.timestamp_s === "number" ? secondsToTimestamp(claim.timestamp_s) : "—"}</strong></div>
      <div><span>Nearest log timestamp</span><strong>{typeof summary?.nearest_timestamp_s === "number" ? `${summary.nearest_timestamp_s.toFixed(2)}s` : "—"}</strong></div>
      <div><span>Log window</span><strong>{typeof summary?.sample_start_s === "number" && typeof summary.sample_end_s === "number" ? `${summary.sample_start_s.toFixed(2)}s → ${summary.sample_end_s.toFixed(2)}s` : "—"}</strong></div>
      <div><span>Sample count</span><strong>{summary?.sample_count ?? 0}</strong></div>
      <div className="claim-detail-wide"><span>Signals</span><strong>{summary?.available_signals.join(", ") || "Không có signal"}</strong></div>
    </div>
    {summary && Object.keys(summary.metrics).length > 0 && <div className="claim-metric-groups">
      {Object.entries(summary.metrics).map(([signal, metrics]) => <section key={signal}>
        <h4>{signalLabel(signal)}</h4>
        <dl>{Object.entries(metrics).map(([metric, value]) => <div key={metric}><dt>{signalLabel(metric)}</dt><dd>{number(value)}</dd></div>)}</dl>
      </section>)}
    </div>}
  </details>;
}

export function ClaimReviewList({
  claims,
  summaries,
  verificationResults,
  hasLog,
  selectedClaimId,
  onSelect,
}: {
  claims: Claim[];
  summaries: ClaimLogSummary[];
  verificationResults: ClaimVerification[];
  hasLog: boolean;
  selectedClaimId?: string;
  onSelect?: (claim: Claim) => void;
}) {
  const summaryByClaim = new Map(summaries.map((item) => [item.claim_id, item]));
  const verificationByClaim = new Map(verificationResults.map((item) => [item.claim_id, item]));
  return <section className="workspace-panel claim-review-section" id="claims" aria-labelledby="claims-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">Nhận định AI</p><h2 id="claims-title">Claims và đối chiếu bằng chứng</h2></div><span>{claims.length} claim</span></div>
    <div className="claim-review-list">
      {claims.map((claim, index) => {
        const summary = summaryByClaim.get(claim.claim_id);
        const verification = verificationByClaim.get(claim.claim_id);
        return <article className={`claim-review-card ${selectedClaimId === claim.claim_id ? "selected" : ""}`} key={claim.claim_id}>
          <header>
            <button type="button" onClick={() => onSelect?.(claim)} disabled={!onSelect}>
              <span>Claim {index + 1}</span><small>{claim.claim_id}</small>
            </button>
            <div><time>{typeof claim.timestamp_s === "number" ? secondsToTimestamp(claim.timestamp_s) : "Không có timestamp"}</time><span className={`finding-status ${claim.verification_status}`}>{claim.verification_status.replaceAll("_", " ")}</span></div>
          </header>
          <div className="claim-primary-fields">
            <section><h3>Nhận định</h3><p>{claim.text}</p></section>
            <section><h3>Lý do xác thực</h3><p>{verification?.reason || "Backend chưa cung cấp lý do xác thực cho claim này."}</p></section>
            <section><h3>Tham chiếu log</h3><LogReference summary={summary} hasLog={hasLog} /></section>
          </div>
          <ClaimDetails claim={claim} summary={summary} />
        </article>;
      })}
      {!claims.length && <p className="report-empty-copy">Chưa có nhận định AI để hiển thị.</p>}
    </div>
  </section>;
}
