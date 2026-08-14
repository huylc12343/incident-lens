"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { saveUploadedVideo } from "../lib/uploadStorage";
import { INCIDENT_KEYS } from "../lib/incidentSession";
import { createIncident, uploadIncident } from "../lib/incidentApi";
import { uiText as text } from "../lib/ui-copy";

export function AnalysisForm() {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null);
  const [telemetry, setTelemetry] = useState<File[]>([]);
  const [toast, setToast] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitProgress, setSubmitProgress] = useState(0);
  const [error, setError] = useState("");
  const ready = Boolean(video && telemetry.length);

  useEffect(() => {
    if (!submitting) return;
    setSubmitProgress(12);
    const timer = window.setInterval(() => {
      setSubmitProgress((current) => Math.min(90, current + Math.max(1, Math.round((90 - current) / 8))));
    }, 450);
    return () => window.clearInterval(timer);
  }, [submitting]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !video || !telemetry.length || submitting) return;
    setSubmitting(true);
    setError("");
    const previousUrl = sessionStorage.getItem("vlens:video-url");
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    sessionStorage.setItem("vlens:video-url", URL.createObjectURL(video));
    try {
      await saveUploadedVideo(video);
    } catch {
      // The session object URL above remains available as the playback fallback.
    }
    sessionStorage.setItem("vlens:video-name", video.name);
    const incidentId = `INC-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
    try {
      const uploaded = await uploadIncident(video, telemetry[0]);
      const snapshot = await createIncident({
        incident_id: incidentId,
        video_uri: uploaded.video_uri,
        log_uri: uploaded.log_uri,
        analysis_prompt: "Analyze the full recording, automatically identify the disengagement event timestamp, and use only observable video and telemetry evidence.",
        metadata: { timestamp_detection: "automatic", telemetry_files: telemetry.map((file) => file.name) },
      });
      setSubmitProgress(100);
      sessionStorage.removeItem(INCIDENT_KEYS.timestamp);
      sessionStorage.setItem(INCIDENT_KEYS.incidentId, snapshot.incident_id);
      sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(snapshot));
      setToast(true);
      router.push("/processing");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : text("Could not start incident analysis.", "Không thể bắt đầu phân tích sự cố."));
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <section className="workspace-card" aria-labelledby="analysis-title">
      <div className="section-title analysis-section-title">
        <div>
          <p className="eyebrow">{text("New analysis", "Phân tích mới")}</p>
          <h2 id="analysis-title">{text("Upload incident evidence", "Tải lên bằng chứng sự cố")}</h2>
          <p className="section-description">{text("Add the original recording and matching vehicle telemetry to begin a grounded review.", "Thêm video gốc và telemetry tương ứng để bắt đầu rà soát dựa trên bằng chứng.")}</p>
        </div>
        <div className="automatic-timestamp" role="note">
          <strong>{text("Automatic event detection", "Tự động phát hiện sự kiện")}</strong>
          <span>{text("The event timestamp will be detected from the uploaded recording.", "Mốc thời gian sự kiện sẽ được phát hiện từ video đã tải lên.")}</span>
        </div>
      </div>
      <form onSubmit={submit}>
        <div className="upload-grid">
          <FileUploadCard
            kind="video"
            files={video ? [video] : []}
            onChange={(files) => setVideo(files[0] ?? null)}
          />
          <FileUploadCard
            kind="telemetry"
            files={telemetry}
            onChange={setTelemetry}
          />
        </div>
        {submitting && (
          <div className="submission-progress" role="status" aria-live="polite">
            <div><strong>{text("Starting analysis…", "Đang bắt đầu phân tích…")}</strong><span>{submitProgress}%</span></div>
            <div className="progress-track"><span style={{ width: `${submitProgress}%` }} /></div>
            <p>{text("Please keep this page open while the files are uploaded.", "Vui lòng giữ trang này mở trong khi tải tệp lên.")}</p>
          </div>
        )}
        <div className="form-footer">
          <p>{text("Files are used to review this recorded disengagement only.", "Các tệp chỉ được dùng để rà soát sự kiện disengagement này.")}</p>
          <button className="primary-button" type="submit" disabled={!ready || submitting}>
            {submitting ? text("Uploading…", "Đang tải lên…") : text("Analyze Disengagement", "Phân tích Disengagement")} <span>→</span>
          </button>
        </div>
      </form>
      {toast && (
        <div className="toast" role="status">
          <span>✓</span> {text("Analysis request ready.", "Yêu cầu phân tích đã sẵn sàng.")}
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
