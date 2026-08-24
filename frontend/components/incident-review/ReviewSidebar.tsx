"use client";

import { useState } from "react";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";
import { uiText as text } from "../../lib/ui-copy";
import { classifyIncidentForDisplay } from "../../lib/incidentClassification";
import { formatEvidenceWarning } from "../../lib/evidenceWarnings";
import { StructuredReportEditor } from "./StructuredReportEditor";
import { incidentStatusLabel } from "../../lib/incidentStatus";

type Props = {
  snapshot: IncidentSnapshot;
  selectedClaim?: Claim;
  busy: boolean;
  error: string;
  onSelectClaim: (claim: Claim) => void;
  onReview: (payload: ReviewPayload) => Promise<void>;
};

export function ReviewSidebar({ snapshot, selectedClaim, busy, error, onSelectClaim, onReview }: Props) {
  const report = snapshot.final_report ?? snapshot.draft_report;
  const window = report?.incident_window;
  const [reviewer, setReviewer] = useState("engineer@example.com");
  const [reason, setReason] = useState("Insufficient evidence");
  const [editingReport, setEditingReport] = useState(false);
  const [feedback, setFeedback] = useState("");

  const counts = snapshot.claims.reduce<Record<string, number>>((result, claim) => {
    result[claim.verification_status] = (result[claim.verification_status] ?? 0) + 1;
    return result;
  }, {});
  const canReview = snapshot.status === "awaiting_review" && !busy;
  const warnings = [...new Set([...snapshot.warnings, ...(report?.evidence_and_warnings?.warnings ?? [])])];
  const classification = classifyIncidentForDisplay(snapshot);

  return (
    <aside className="incident-review-sidebar expanded-ai-review report-style-review">
      <header className="ai-review-report-header">
        <h2>{text("AI-assisted evidence review", "Rà soát bằng chứng với AI")}</h2>
        <span className={`status ${snapshot.status}`}>{incidentStatusLabel(snapshot.status)}</span>
      </header>

      <section className="ai-report-section incident-report-information">
        <h3>{text("Incident information", "Thông tin sự cố")}</h3>
        <dl className="incident-report-details">
          <div><dt>{text("Incident ID", "Mã sự cố")}</dt><dd className="mono-value">{snapshot.incident_id}</dd></div>
          <div><dt>{text("Analysis window", "Khoảng phân tích")}</dt><dd className="mono-value">{secondsToTimestamp(window?.t_start ?? 0)} → {secondsToTimestamp(window?.t_end ?? 0)}</dd></div>
          <div><dt>{text("Detected event", "Sự kiện phát hiện")}</dt><dd className="mono-value">{secondsToTimestamp(window?.t0 ?? 0)}</dd></div>
          <div><dt>{text("Incident type", "Loại sự cố")}</dt><dd>{classification.type}</dd></div>
          <div><dt>{text("Evidence sources", "Nguồn bằng chứng")}</dt><dd>{snapshot.has_log ? "Video + telemetry" : text("Video only", "Chỉ video")}</dd></div>
          <div><dt>{text("AI observations", "Quan sát AI")}</dt><dd>{snapshot.claims.length} {text("grounded claim(s)", "nhận định có bằng chứng")}</dd></div>
          <div><dt>{text("Review status", "Trạng thái rà soát")}</dt><dd>{incidentStatusLabel(snapshot.status)}</dd></div>
        </dl>
      </section>

      <section className="ai-report-section all-ai-observations">
        <div className="ai-report-section-heading"><h3>{text("AI observations", "Quan sát AI")}</h3><span>{snapshot.claims.length}</span></div>
        <p className="section-help">{text("Select an observation to seek the incident clip and highlight synchronized evidence.", "Chọn một quan sát để tua video sự cố và làm nổi bật bằng chứng đồng bộ.")}</p>
        <div className="ai-observation-list">
          {snapshot.claims.map((item, index) => (
            <button type="button" className={item.claim_id === selectedClaim?.claim_id ? "selected" : ""} key={item.claim_id} onClick={() => onSelectClaim(item)} aria-pressed={item.claim_id === selectedClaim?.claim_id}>
              <header><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.claim_id}</strong><time>{secondsToTimestamp(item.timestamp_s)}</time></header>
              <p>{item.text}</p>
              <footer><span className={`finding-status ${item.verification_status}`}>{item.verification_status.replaceAll("_", " ")}</span><small>{item.evidence.map((evidence) => evidence.evidence_id).join(", ") || "Không có frame tham chiếu"}</small></footer>
            </button>
          ))}
          {!snapshot.claims.length && <p className="report-empty-copy">{text("No AI observations have been published yet.", "Chưa có quan sát AI nào được công bố.")}</p>}
        </div>
      </section>

      <section className="ai-report-section verification-summary">
        <h3>{text("Evidence verification", "Xác minh bằng chứng")}</h3>
        <div className="verification-counts">
          {["supported", "contradicted", "unverified", "video_only"].map((status) => <div className={status} key={status}><span>{status.replaceAll("_", " ")}</span><strong>{counts[status] ?? 0}</strong></div>)}
        </div>
      </section>

      <section className="ai-report-section structured-summary">
        <div className="ai-report-section-heading"><h3>{text("Structured report", "Báo cáo có cấu trúc")}</h3><button type="button" className="report-text-action" disabled={!canReview || busy || !report} onClick={() => setEditingReport((current) => !current)}>{editingReport ? text("Cancel", "Hủy") : text("Edit report", "Chỉnh sửa báo cáo")}</button></div>
        {editingReport && report ? <StructuredReportEditor snapshot={snapshot} report={report} reviewer={reviewer} busy={busy} onCancel={() => setEditingReport(false)} onReview={onReview} /> : <p>{report?.summary ?? snapshot.video_summary}</p>}
      </section>

      <ReportNarrative title={text("Timeline assessment", "Đánh giá dòng thời gian")} content={report?.timeline?.narrative || text("No additional timeline narrative.", "Không có mô tả dòng thời gian bổ sung.")} />
      <ReportNarrative title={text("Video assessment", "Đánh giá video")} content={report?.video_observations?.narrative || snapshot.video_summary} />
      <ReportNarrative title={text("Log assessment", "Đánh giá log")} content={report?.log_findings?.narrative || (snapshot.has_log ? text("Log findings are listed with each aligned event.", "Kết quả log được liệt kê theo từng sự kiện đã căn chỉnh.") : text("No telemetry log was supplied.", "Không có log telemetry."))} />
      <ReportNarrative title={text("Evidence alignment", "Đối chiếu bằng chứng")} content={report?.alignment?.narrative || text("No additional alignment narrative.", "Không có mô tả đối chiếu bổ sung.")} />
      <ReportNarrative title={text("Hypothesized causes", "Nguyên nhân giả định")} content={report?.hypothesized_causes || text("No cause hypothesis was recorded.", "Chưa ghi nhận giả thuyết nguyên nhân.")} />

      {warnings.length > 0 && <section className="ai-report-section evidence-limitations" role="note"><h3><span aria-hidden="true">!</span> {text("Evidence warnings", "Cảnh báo bằng chứng")}</h3><ul>{warnings.map((warning) => <li key={warning}>{formatEvidenceWarning(warning)}</li>)}</ul></section>}

      <section className="ai-report-section interactive-reanalysis">
        <div className="ai-report-section-heading"><h3>{text("Focused re-analysis", "Phân tích lại có trọng tâm")}</h3><span>{selectedClaim?.claim_id ?? text("Select a claim", "Chọn một nhận định")}</span></div>
        <textarea aria-label="Phản hồi để phân tích lại" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Mô tả nội dung agent cần xác minh lại..." />
        <button type="button" className="report-secondary-action" disabled={!canReview || !selectedClaim || !feedback.trim() || busy} onClick={() => void onReview({ action: "reanalyze", reviewer, feedback, target_claim_ids: selectedClaim ? [selectedClaim.claim_id] : [] }).then(() => setFeedback(""))}>{busy ? "Đang phân tích lại..." : "Phân tích lại quan sát đã chọn"}</button>
      </section>

      <section className="ai-report-section engineer-review-section">
        <h3>{text("Engineer review", "Rà soát của kỹ sư")}</h3>
        <div className="engineer-review-fields">
          <label>{text("Reviewer", "Người rà soát")}<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
          <label>{text("Reject reason", "Lý do từ chối")}<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="engineer-review-actions"><button type="button" className="reject-action" disabled={!canReview || !reason.trim()} onClick={() => void onReview({ action: "not_incident", reviewer, reason })}>{busy ? text("Submitting...", "Đang gửi...") : text("Reject", "Từ chối")}</button><button type="button" className="approve-action" disabled={!canReview} onClick={() => void onReview({ action: "approve", reviewer })}>{busy ? text("Submitting...", "Đang gửi...") : text("Approve", "Phê duyệt")}</button></div>
      </section>
    </aside>
  );
}

function ReportNarrative({ title, content }: { title: string; content: string }) {
  return <section className="ai-report-section report-narrative-section"><h3>{title}</h3><p>{content}</p></section>;
}
