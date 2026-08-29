"use client";

import Image from "next/image";
import { useState } from "react";
import { artifactUrl } from "../../lib/incidentApi";
import { orderClaimsByTimeline } from "../../lib/claimOrdering";
import { secondsToTimestamp } from "../../lib/incidentSession";
import { normalizeReviewText } from "../../lib/reviewText";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";
import { StructuredReportEditor } from "./StructuredReportEditor";

function EvidenceImage({ src, fallback, alt }: { src: string; fallback: string; alt: string }) {
  const [fallbackActive, setFallbackActive] = useState(false);
  const activeSrc = fallbackActive ? fallback : src;
  if (!activeSrc) return null;
  return <Image
    unoptimized
    width={640}
    height={360}
    src={activeSrc}
    alt={alt}
    onError={() => { if (!fallbackActive && fallback) setFallbackActive(true); }}
  />;
}

function ClaimEvidenceGallery({ snapshot, claim }: { snapshot: IncidentSnapshot; claim: Claim }) {
  const directory = snapshot.artifact_uris.incident_frames?.replace(/[\\/]+$/, "") ?? "";
  const representative = artifactUrl(snapshot.artifact_uris.representative_frame);
  const evidence = [...claim.evidence].sort((left, right) => left.timestamp_s - right.timestamp_s || left.evidence_id.localeCompare(right.evidence_id)).map((item) => {
    const filename = /\.[a-z0-9]+$/i.test(item.evidence_id) ? item.evidence_id : `${item.evidence_id}.jpg`;
    return { ...item, imageUrl: directory ? artifactUrl(`${directory}/${filename}`) : representative };
  });

  if (!evidence.length && !representative) return <div className="focused-evidence-empty"><strong>Không có ảnh bằng chứng</strong><p>Backend chưa trả frame liên kết hoặc ảnh đại diện cho claim này.</p></div>;
  return <div className="focused-evidence-gallery" aria-label={`Ảnh bằng chứng của ${claim.claim_id}`}>
    {evidence.map((item, index) => <figure key={item.evidence_id}>
      <div><EvidenceImage src={item.imageUrl} fallback={representative} alt={`Bằng chứng ${index + 1} của ${claim.claim_id}`} /><time>{secondsToTimestamp(item.timestamp_s)}</time></div>
      <figcaption>Bằng chứng {index + 1}</figcaption>
    </figure>)}
    {!evidence.length && representative && <figure>
      <div><EvidenceImage src={representative} fallback="" alt={`Ảnh đại diện của sự cố ${snapshot.incident_id}`} /></div>
      <figcaption>Ảnh đại diện <small>Claim chưa có frame liên kết</small></figcaption>
    </figure>}
  </div>;
}

export function ReviewSidebar({ snapshot, selectedClaim, busy, error, onSelectClaim, onReview }: {
  snapshot: IncidentSnapshot;
  selectedClaim?: Claim;
  busy: boolean;
  error: string;
  onSelectClaim: (claim: Claim) => void;
  onReview: (payload: ReviewPayload) => Promise<boolean>;
}) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [reason, setReason] = useState("Insufficient evidence");
  const [feedback, setFeedback] = useState("");
  const [editingReport, setEditingReport] = useState(false);
  const canReview = snapshot.status === "awaiting_review" && !busy;
  const orderedClaims = orderClaimsByTimeline(snapshot.claims);

  return <section className="workspace-panel review-report-panel" id="report" aria-labelledby="report-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">Report</p><h2 id="report-title">Báo cáo rà soát</h2></div>{report && <button type="button" className="report-text-action" disabled={!canReview} onClick={() => setEditingReport((current) => !current)}>{editingReport ? "Cancel" : "Edit report"}</button>}</div>
    {editingReport && report ? <StructuredReportEditor report={report} claims={snapshot.claims} reviewer={reviewer} busy={busy} onCancel={() => setEditingReport(false)} onReview={onReview} /> : <div className="vertical-report-sections">
      <section><h3>Nhận định tổng quát</h3><p className="review-multiline">{normalizeReviewText(report?.video_observations?.narrative) || "Backend chưa cung cấp nhận định từ video."}</p></section>
      <section><h3>Nguyên nhân giả thuyết</h3><p className="review-multiline">{normalizeReviewText(report?.hypothesized_causes) || "Chưa ghi nhận nguyên nhân giả thuyết."}</p></section>
    </div>}

    <section className="review-action-section focused-reanalysis-card" aria-labelledby="focused-reanalysis-title">
      <header className="focused-reanalysis-heading"><div><span className="focused-reanalysis-icon" aria-hidden="true">↻</span><div><p className="eyebrow">Agent verification</p><h3 id="focused-reanalysis-title">Phân tích lại có trọng tâm</h3></div></div><small>Chỉ claim được chọn sẽ được gửi lại cho agent</small></header>

      <div className="focused-claim-picker" role="radiogroup" aria-label="Chọn claim cần phân tích lại">
        {orderedClaims.map((claim, index) => <button type="button" role="radio" aria-checked={selectedClaim?.claim_id === claim.claim_id} className={selectedClaim?.claim_id === claim.claim_id ? "selected" : ""} key={claim.claim_id} onClick={() => onSelectClaim(claim)}>
          <span>{index + 1}</span><div><strong>{claim.claim_id}</strong><small>{typeof claim.timestamp_s === "number" ? secondsToTimestamp(claim.timestamp_s) : "Không có timestamp"}</small></div><p className="review-multiline">{normalizeReviewText(claim.text)}</p>
        </button>)}
      </div>

      {selectedClaim ? <div className="focused-selected-claim">
        <header><div><span>Claim đang chọn</span><strong>{selectedClaim.claim_id}</strong></div>{typeof selectedClaim.timestamp_s === "number" && <time>{secondsToTimestamp(selectedClaim.timestamp_s)}</time>}</header>
        <p className="review-multiline">{normalizeReviewText(selectedClaim.text)}</p>
        <ClaimEvidenceGallery snapshot={snapshot} claim={selectedClaim} />
      </div> : <p className="focused-claim-required">Chọn một claim để xem bằng chứng và yêu cầu agent xác minh lại.</p>}

      <label className="focused-feedback-field"><span>Nội dung cần xác minh lại</span><textarea aria-label="Phản hồi để phân tích lại" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Ví dụ: Kiểm tra lại thời điểm bắt đầu phanh và đối chiếu với tốc độ trong telemetry…" /></label>
      <button type="button" className="report-secondary-action focused-reanalysis-submit" disabled={!canReview || !selectedClaim || !feedback.trim() || !reviewer.trim()} onClick={() => void onReview({ action: "reanalyze", reviewer: reviewer.trim(), feedback: feedback.trim(), target_claim_ids: selectedClaim ? [selectedClaim.claim_id] : [] }).then((saved) => { if (saved) setFeedback(""); })}>{busy ? "Đang gửi yêu cầu…" : `Phân tích lại ${selectedClaim?.claim_id ?? "claim đã chọn"}`}</button>
    </section>

    <section className="review-action-section">
      <h3>Review actions</h3>
      <div className="engineer-review-fields"><label>Người rà soát<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>Lý do Not incident<input value={reason} onChange={(event) => setReason(event.target.value)} /></label></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="engineer-review-actions"><button type="button" className="reject-action" disabled={!canReview || !reason.trim() || !reviewer.trim()} onClick={() => void onReview({ action: "not_incident", reviewer, reason })}>{busy ? "Đang gửi…" : "Not incident"}</button><button type="button" className="approve-action" disabled={!canReview || !reviewer.trim()} onClick={() => void onReview({ action: "approve", reviewer })}>{busy ? "Đang gửi…" : "Approve"}</button></div>
    </section>
  </section>;
}
