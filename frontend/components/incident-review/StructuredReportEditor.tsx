"use client";

import { useMemo, useState } from "react";
import { normalizeReviewText } from "../../lib/reviewText";
import type { Claim, DraftReport, ReviewPayload, TimelineEvent, VerificationStatus } from "../../types/incident";

const verificationStatuses: Array<{ value: VerificationStatus; label: string }> = [
  { value: "supported", label: "Được hỗ trợ" },
  { value: "contradicted", label: "Mâu thuẫn" },
  { value: "unverified", label: "Chưa xác minh" },
];

type EditableClaim = Pick<Claim, "claim_id" | "text" | "timestamp_s" | "verification_status">;

export function StructuredReportEditor({ report, claims, reviewer, busy, onCancel, onReview }: {
  report: DraftReport;
  claims: Claim[];
  reviewer: string;
  busy: boolean;
  onCancel: () => void;
  onReview: (payload: ReviewPayload) => Promise<boolean>;
}) {
  const [timeline, setTimeline] = useState(normalizeReviewText(report.timeline?.narrative));
  const [videoObservations, setVideoObservations] = useState(normalizeReviewText(report.video_observations?.narrative));
  const [causes, setCauses] = useState(normalizeReviewText(report.hypothesized_causes));
  const [events, setEvents] = useState<TimelineEvent[]>(() => (report.timeline?.events ?? []).map((event) => ({ ...event })));
  const [editableClaims, setEditableClaims] = useState<EditableClaim[]>(() => claims.map((claim) => ({
    claim_id: claim.claim_id,
    text: normalizeReviewText(claim.text),
    timestamp_s: claim.timestamp_s,
    verification_status: claim.verification_status,
  })));

  const initial = useMemo(() => JSON.stringify({
    timeline: normalizeReviewText(report.timeline?.narrative),
    videoObservations: normalizeReviewText(report.video_observations?.narrative),
    causes: normalizeReviewText(report.hypothesized_causes),
    events: report.timeline?.events ?? [],
    claims: claims.map(({ claim_id, text, timestamp_s, verification_status }) => ({ claim_id, text: normalizeReviewText(text), timestamp_s, verification_status })),
  }), [claims, report]);
  const current = JSON.stringify({ timeline, videoObservations, causes, events, claims: editableClaims });
  const dirty = current !== initial;
  const ordered = events.every((event, index) => index === 0 || event.timestamp_s >= events[index - 1].timestamp_s);
  const invalidEvent = events.some((event) => !Number.isFinite(event.timestamp_s) || event.timestamp_s < 0 || !event.description.trim());
  const invalidClaim = editableClaims.some((claim) => !claim.text.trim() || claim.timestamp_s === null || !Number.isFinite(claim.timestamp_s) || claim.timestamp_s < 0);
  const validation = !reviewer.trim()
    ? "Người rà soát không được để trống."
    : !videoObservations.trim() || !causes.trim() || !timeline.trim()
      ? "Các nội dung đang hiển thị trong Review không được để trống."
      : invalidEvent || invalidClaim
        ? "Timestamp phải là số không âm và nội dung không được để trống."
        : !ordered ? "Các mốc timeline phải theo thứ tự tăng dần." : "";

  const updateEvent = (index: number, update: Partial<TimelineEvent>) => setEvents((currentEvents) => currentEvents.map((event, eventIndex) => eventIndex === index ? { ...event, ...update } : event));
  const updateClaim = (claimId: string, update: Partial<EditableClaim>) => setEditableClaims((currentClaims) => currentClaims.map((claim) => claim.claim_id === claimId ? { ...claim, ...update } : claim));
  const save = async () => {
    if (validation || busy || !dirty) return;
    const saved = await onReview({
      action: "edit",
      reviewer: reviewer.trim(),
      edits: {
        timeline: timeline.trim(),
        timeline_events: events.map((event) => ({ ...event, description: event.description.trim() })),
        video_observations: videoObservations.trim(),
        hypothesized_causes: causes.trim(),
        claims: editableClaims.map((claim) => ({ ...claim, text: claim.text.trim(), timestamp_s: claim.timestamp_s ?? undefined })),
      },
    });
    if (saved) onCancel();
  };

  return <div className="structured-report-editor report-editor-vertical">
    <section className="review-editor-section"><h3>Nội dung báo cáo</h3>
      <label>Nhận định tổng quát<textarea rows={6} value={videoObservations} onChange={(event) => setVideoObservations(event.target.value)} /></label>
      <label>Nguyên nhân giả thuyết<textarea rows={6} value={causes} onChange={(event) => setCauses(event.target.value)} /></label>
    </section>
    <section className="review-editor-section"><h3>Diễn biến theo thời gian</h3>
      <label>Mô tả timeline<textarea rows={5} value={timeline} onChange={(event) => setTimeline(event.target.value)} /></label>
      <div className="timeline-editor-list">{events.map((event, index) => <fieldset key={`${index}-${event.evidence_ids.join("-")}`}><legend>Mốc {index + 1}</legend><div className="timeline-event-editor"><label>Thời gian (giây)<input type="number" min="0" step="0.01" value={event.timestamp_s} onChange={(change) => updateEvent(index, { timestamp_s: Number(change.target.value) })} /></label><label>Sự kiện<textarea rows={3} value={normalizeReviewText(event.description)} onChange={(change) => updateEvent(index, { description: change.target.value })} /></label></div></fieldset>)}</div>
    </section>
    <section className="review-editor-section"><h3>Claims và trạng thái xác minh</h3>
      <div className="claim-editor-list">{editableClaims.map((claim) => <fieldset className="claim-editor-row" key={claim.claim_id}><legend>{claim.claim_id}</legend><div className="claim-editor-meta"><label>Timestamp (giây)<input type="number" min="0" step="0.01" value={claim.timestamp_s ?? ""} onChange={(event) => updateClaim(claim.claim_id, { timestamp_s: Number(event.target.value) })} /></label><label>Trạng thái xác minh<select value={claim.verification_status} onChange={(event) => updateClaim(claim.claim_id, { verification_status: event.target.value as VerificationStatus })}>{verificationStatuses.map((status) => <option value={status.value} key={status.value}>{status.label}</option>)}</select></label></div><label>Nhận định<textarea rows={4} value={claim.text} onChange={(event) => updateClaim(claim.claim_id, { text: event.target.value })} /></label></fieldset>)}</div>
    </section>
    {validation && <p className="form-error" role="alert">{validation}</p>}
    <div className="structured-editor-actions"><button type="button" className="report-text-action" onClick={onCancel} disabled={busy}>Hủy</button><button type="button" className="report-secondary-action" onClick={() => void save()} disabled={Boolean(validation) || busy || !dirty}>{busy ? "Đang lưu…" : "Lưu thay đổi"}</button></div>
  </div>;
}
