import { secondsToTimestamp } from "../../lib/incidentSession";
import { normalizeReviewText } from "../../lib/reviewText";
import type { Claim, DraftReport } from "../../types/incident";

export function IncidentTimeline({ report, claims, onSelect }: { report?: DraftReport | null; claims: Claim[]; onSelect?: (claim: Claim) => void }) {
  const reportEvents = report?.timeline?.events ?? [];
  const events: Array<{ timestamp_s: number; description: string; claim?: Claim }> = reportEvents.length > 0
    ? reportEvents.map((event) => ({ timestamp_s: event.timestamp_s, description: event.description }))
    : claims.filter((claim) => typeof claim.timestamp_s === "number").map((claim) => ({ timestamp_s: claim.timestamp_s ?? 0, description: claim.text, claim }));
  const ordered = [...events].sort((left, right) => left.timestamp_s - right.timestamp_s);
  return <section className="workspace-panel vertical-timeline-section" id="timeline" aria-labelledby="timeline-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">Timeline</p><h2 id="timeline-title">Diễn biến theo thời gian</h2></div><span>{ordered.length} event</span></div>
    {report?.timeline?.narrative && <p className="timeline-narrative review-multiline">{normalizeReviewText(report.timeline.narrative)}</p>}
    {ordered.length > 0 ? <ol className="vertical-timeline">{ordered.map((event, index) => {
      const linkedClaim = event.claim ?? claims.find((claim) => typeof claim.timestamp_s === "number" && Math.abs((claim.timestamp_s ?? 0) - event.timestamp_s) < 0.01);
      return <li key={`${event.timestamp_s}-${index}`}><span className="timeline-node" /><div><time>{secondsToTimestamp(event.timestamp_s)}</time><p className="review-multiline">{normalizeReviewText(event.description)}</p>{linkedClaim && onSelect && <button type="button" onClick={() => onSelect(linkedClaim)}>Xem claim liên quan</button>}</div></li>;
    })}</ol> : <div className="telemetry-empty"><strong>Timeline chưa sẵn sàng</strong><p>Backend chưa trả timeline event hoặc claim có timestamp.</p></div>}
  </section>;
}
