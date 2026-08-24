"use client";

import { useMemo, useState } from "react";
import type { DraftReport, IncidentSnapshot, ReviewPayload } from "../../types/incident";

const incidentTypes = [
  { value: "rear_end_collision", label: "Va chạm phía sau — Rear-end collision" },
  { value: "crossing_collision", label: "Va chạm cắt ngang — Crossing collision" },
  { value: "side_collision", label: "Va chạm bên hông — Side collision" },
  { value: "head_on_collision", label: "Va chạm đối đầu — Head-on collision" },
  { value: "pedestrian_collision", label: "Va chạm với người đi bộ — Pedestrian collision" },
  { value: "static_object_collision", label: "Va chạm vật thể tĩnh — Static-object collision" },
  { value: "roadside_collision", label: "Sự cố ven đường — Roadside collision" },
  { value: "no_incident", label: "Không có sự cố — No incident" },
  { value: "other_unknown", label: "Khác/chưa xác định — Other/unknown" },
];

const verificationStatuses = ["supported", "contradicted", "unverified"];

type EditableClaim = { claim_id: string; text: string; timestamp: string; verificationStatus: string; evidenceIds: string };

export function StructuredReportEditor({
  snapshot,
  report,
  reviewer,
  busy,
  onCancel,
  onReview,
}: {
  snapshot: IncidentSnapshot;
  report: DraftReport;
  reviewer: string;
  busy: boolean;
  onCancel: () => void;
  onReview: (payload: ReviewPayload) => Promise<void>;
}) {
  const window = report.incident_window;
  const [incidentType, setIncidentType] = useState(report.type_of_accident ?? "other_unknown");
  const [tStart, setTStart] = useState(String(window?.t_start ?? 0));
  const [t0, setT0] = useState(String(window?.t0 ?? 0));
  const [tEnd, setTEnd] = useState(String(window?.t_end ?? 0));
  const [summary, setSummary] = useState(report.summary ?? snapshot.video_summary);
  const [timeline, setTimeline] = useState(report.timeline?.narrative ?? "");
  const [videoAssessment, setVideoAssessment] = useState(report.video_observations?.narrative ?? "");
  const [logAssessment, setLogAssessment] = useState(report.log_findings?.narrative ?? "");
  const [alignment, setAlignment] = useState(report.alignment?.narrative ?? "");
  const [causes, setCauses] = useState(report.hypothesized_causes ?? "");
  const [warnings, setWarnings] = useState([...new Set([
    ...snapshot.warnings,
    ...(report.evidence_and_warnings?.warnings ?? []),
  ])].join("\n"));
  const [claims, setClaims] = useState<EditableClaim[]>(() => snapshot.claims.map((claim) => ({
    claim_id: claim.claim_id,
    text: claim.text,
    timestamp: String(claim.timestamp_s ?? 0),
    verificationStatus: claim.verification_status,
    evidenceIds: claim.evidence.map((item) => item.evidence_id).join(", "),
  })));

  const validation = useMemo(() => {
    if (!reviewer.trim()) return "Người rà soát / Reviewer không được để trống.";
    const timestamps = [tStart, t0, tEnd].map(Number);
    if (timestamps.some((value) => !Number.isFinite(value) || value < 0)) return "Timestamp phải là số không âm.";
    if (!(timestamps[0] <= timestamps[1] && timestamps[1] <= timestamps[2])) return "Timestamp phải thỏa t_start ≤ t0 ≤ t_end.";
    if (![summary, timeline, videoAssessment, logAssessment, alignment, causes].every((value) => value.trim())) return "Các phần tóm tắt và đánh giá không được để trống.";
    if (claims.some((claim) => !claim.text.trim() || !Number.isFinite(Number(claim.timestamp)) || Number(claim.timestamp) < 0)) return "Mỗi nhận định cần nội dung và timestamp hợp lệ.";
    if (claims.some((claim) => {
      const evidenceIds = claim.evidenceIds.split(",").map((item) => item.trim()).filter(Boolean);
      return evidenceIds.length !== new Set(evidenceIds).size;
    })) return "Evidence IDs trong mỗi nhận định không được trùng nhau.";
    return "";
  }, [alignment, causes, claims, logAssessment, reviewer, summary, t0, tEnd, timeline, tStart, videoAssessment]);

  const save = async () => {
    if (validation || busy) return;
    await onReview({
      action: "edit",
      reviewer,
      edits: {
        type_of_accident: incidentType,
        t_start: Number(tStart),
        t0: Number(t0),
        t_end: Number(tEnd),
        claims: claims.map((claim) => ({
          claim_id: claim.claim_id,
          text: claim.text.trim(),
          timestamp_s: Number(claim.timestamp),
          verification_status: claim.verificationStatus,
          evidence_ids: claim.evidenceIds.split(",").map((item) => item.trim()).filter(Boolean),
        })),
        summary: summary.trim(),
        timeline: timeline.trim(),
        video_observations: videoAssessment.trim(),
        log_findings: logAssessment.trim(),
        alignment: alignment.trim(),
        hypothesized_causes: causes.trim(),
        warnings: warnings.split("\n").map((item) => item.trim()).filter(Boolean),
      },
    });
    onCancel();
  };

  const updateClaim = (claimId: string, field: "text" | "timestamp" | "verificationStatus" | "evidenceIds", value: string) => {
    setClaims((current) => current.map((claim) => claim.claim_id === claimId ? { ...claim, [field]: value } : claim));
  };

  return <div className="structured-report-editor">
    <div className="structured-editor-grid">
      <label>Loại sự cố / Incident type<select value={incidentType} onChange={(event) => setIncidentType(event.target.value)}>{incidentTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
      <fieldset><legend>Timestamp sự cố (giây)</legend><div className="timestamp-edit-grid"><label>t_start<input type="number" min="0" step="0.01" value={tStart} onChange={(event) => setTStart(event.target.value)} /></label><label>t0<input type="number" min="0" step="0.01" value={t0} onChange={(event) => setT0(event.target.value)} /></label><label>t_end<input type="number" min="0" step="0.01" value={tEnd} onChange={(event) => setTEnd(event.target.value)} /></label></div></fieldset>
    </div>

    <label>Tóm tắt có cấu trúc<textarea rows={5} value={summary} onChange={(event) => setSummary(event.target.value)} /></label>

    <fieldset className="claim-editor-list"><legend>Nhận định AI / AI observations</legend>{claims.length ? claims.map((claim, index) => <div className="claim-editor-row" key={claim.claim_id}><header><strong>{String(index + 1).padStart(2, "0")} · {claim.claim_id}</strong><label>Giây<input type="number" min="0" step="0.01" value={claim.timestamp} onChange={(event) => updateClaim(claim.claim_id, "timestamp", event.target.value)} /></label></header><textarea rows={3} value={claim.text} onChange={(event) => updateClaim(claim.claim_id, "text", event.target.value)} /><div className="claim-metadata-editor"><label>Xác minh / Verification<select value={claim.verificationStatus} onChange={(event) => updateClaim(claim.claim_id, "verificationStatus", event.target.value)}>{verificationStatuses.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></label><label>Evidence IDs<input value={claim.evidenceIds} onChange={(event) => updateClaim(claim.claim_id, "evidenceIds", event.target.value)} placeholder="frame-000044, frame-000045" /></label></div></div>) : <p>Không có nhận định để chỉnh sửa.</p>}</fieldset>

    <div className="narrative-editor-grid">
      <label>Đánh giá dòng thời gian<textarea rows={4} value={timeline} onChange={(event) => setTimeline(event.target.value)} /></label>
      <label>Đánh giá video<textarea rows={4} value={videoAssessment} onChange={(event) => setVideoAssessment(event.target.value)} /></label>
      <label>Đánh giá log<textarea rows={4} value={logAssessment} onChange={(event) => setLogAssessment(event.target.value)} /></label>
      <label>Đối chiếu bằng chứng<textarea rows={4} value={alignment} onChange={(event) => setAlignment(event.target.value)} /></label>
      <label className="full-width-field">Nguyên nhân giả định<textarea rows={4} value={causes} onChange={(event) => setCauses(event.target.value)} /></label>
      <label className="full-width-field">Cảnh báo bằng chứng / Evidence warnings<textarea rows={4} value={warnings} onChange={(event) => setWarnings(event.target.value)} placeholder="Mỗi cảnh báo một dòng" /></label>
    </div>

    {validation && <p className="form-error" role="alert">{validation}</p>}
    <div className="structured-editor-actions"><button type="button" className="report-text-action" onClick={onCancel} disabled={busy}>Hủy</button><button type="button" className="report-secondary-action" onClick={() => void save()} disabled={Boolean(validation) || busy}>{busy ? "Đang lưu…" : "Lưu toàn bộ chỉnh sửa"}</button></div>
  </div>;
}
