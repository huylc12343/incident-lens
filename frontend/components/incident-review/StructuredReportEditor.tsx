"use client";

import { useMemo, useState } from "react";
import type { DraftReport, ReviewPayload } from "../../types/incident";

export function StructuredReportEditor({ report, reviewer, busy, onCancel, onReview }: {
  report: DraftReport;
  reviewer: string;
  busy: boolean;
  onCancel: () => void;
  onReview: (payload: ReviewPayload) => Promise<void>;
}) {
  const [summary, setSummary] = useState(report.summary ?? "");
  const [timeline, setTimeline] = useState(report.timeline?.narrative ?? "");
  const [videoObservations, setVideoObservations] = useState(report.video_observations?.narrative ?? "");
  const [logFindings, setLogFindings] = useState(report.log_findings?.narrative ?? "");
  const [alignment, setAlignment] = useState(report.alignment?.narrative ?? "");
  const [causes, setCauses] = useState(report.hypothesized_causes ?? "");

  const fields = useMemo(() => [summary, timeline, videoObservations, logFindings, alignment, causes], [alignment, causes, logFindings, summary, timeline, videoObservations]);
  const validation = !reviewer.trim() ? "Người rà soát không được để trống." : fields.some((value) => !value.trim()) ? "Sáu nội dung báo cáo hợp lệ không được để trống." : "";

  const save = async () => {
    if (validation || busy) return;
    await onReview({
      action: "edit",
      reviewer: reviewer.trim(),
      edits: {
        summary: summary.trim(),
        timeline: timeline.trim(),
        video_observations: videoObservations.trim(),
        log_findings: logFindings.trim(),
        alignment: alignment.trim(),
        hypothesized_causes: causes.trim(),
      },
    });
    onCancel();
  };

  return <div className="structured-report-editor report-editor-vertical">
    <label>Tóm tắt báo cáo<textarea rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} /></label>
    <label>Diễn biến theo thời gian<textarea rows={5} value={timeline} onChange={(event) => setTimeline(event.target.value)} /></label>
    <label>Nhận định từ video<textarea rows={5} value={videoObservations} onChange={(event) => setVideoObservations(event.target.value)} /></label>
    <label>Phân tích telemetry phục vụ báo cáo<textarea rows={5} value={logFindings} onChange={(event) => setLogFindings(event.target.value)} /></label>
    <label>Lý do đối chiếu bằng chứng<textarea rows={5} value={alignment} onChange={(event) => setAlignment(event.target.value)} /></label>
    <label>Nguyên nhân giả thuyết<textarea rows={5} value={causes} onChange={(event) => setCauses(event.target.value)} /></label>
    {validation && <p className="form-error" role="alert">{validation}</p>}
    <div className="structured-editor-actions"><button type="button" className="report-text-action" onClick={onCancel} disabled={busy}>Hủy</button><button type="button" className="report-secondary-action" onClick={() => void save()} disabled={Boolean(validation) || busy}>{busy ? "Đang lưu…" : "Save changes"}</button></div>
  </div>;
}
