"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { saveUploadedVideo } from "../lib/uploadStorage";
import { INCIDENT_KEYS } from "../lib/incidentSession";
import { createIncident, uploadIncident } from "../lib/incidentApi";
import { uiText as text } from "../lib/ui-copy";

type DemoSample = {
  id: "with-ground-truth" | "with-log-no-ground-truth" | "video-only";
  title: string;
  description: string;
  detail: string;
  videoPath: string;
  videoName: string;
  telemetryPath?: string;
  telemetryName?: string;
  groundTruthPath?: string;
  groundTruthName?: string;
};

const demoSamples: DemoSample[] = [
  {
    id: "with-ground-truth",
    title: "Video + log + ground truth đầy đủ",
    description: "Va chạm cắt ngang, có dữ liệu xe và nhãn mô phỏng đã xác nhận.",
    detail: "Gửi inference_vehicle_state.csv + ground_truth.json",
    videoPath: "/demo-samples/with-ground-truth/cut-in-ground-truth.mp4",
    videoName: "cut-in-ground-truth.mp4",
    telemetryPath: "/demo-samples/with-ground-truth/telemetry.csv",
    telemetryName: "inference_vehicle_state.csv",
    groundTruthPath: "/demo-samples/with-ground-truth/ground_truth.json",
    groundTruthName: "ground_truth.json",
  },
  {
    id: "with-log-no-ground-truth",
    title: "Video + log, không có ground truth",
    description: "Tình huống người đi bộ, có các thông số như ga, phanh và lái.",
    detail: "Chỉ gửi inference_vehicle_state.csv",
    videoPath: "/demo-samples/with-log-no-ground-truth/pedestrian-no-ground-truth.mp4",
    videoName: "pedestrian-no-ground-truth.mp4",
    telemetryPath: "/demo-samples/with-log-no-ground-truth/telemetry.csv",
    telemetryName: "inference_vehicle_state.csv",
  },
  {
    id: "video-only",
    title: "Chỉ có video",
    description: "Video lái xe thực tế, không có dữ liệu xe hoặc ground truth.",
    detail: "Chỉ gửi video hành trình",
    videoPath: "/demo-samples/video-only/normal-driving-video-only.mp4",
    videoName: "normal-driving-video-only.mp4",
  },
];

async function loadDemoFile(path: string, name: string, type: string) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${name}.`);
  return new File([await response.blob()], name, { type });
}

function createIncidentId() {
  const bytes = new Uint8Array(6);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
    return `INC-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
  }
  const fallback = `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  return `INC-${fallback.slice(0, 12).toUpperCase()}`;
}

export function AnalysisForm({ highlighted = false }: { highlighted?: boolean }) {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null);
  const [telemetry, setTelemetry] = useState<File[]>([]);
  const [groundTruth, setGroundTruth] = useState<File | null>(null);
  const [toast, setToast] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitProgress, setSubmitProgress] = useState(0);
  const [error, setError] = useState("");
  const [selectedDemo, setSelectedDemo] = useState<DemoSample["id"] | null>(null);
  const [loadingDemo, setLoadingDemo] = useState<DemoSample["id"] | null>(null);
  const ready = Boolean(video);

  useEffect(() => {
    if (!submitting) return;
    setSubmitProgress(12);
    const timer = window.setInterval(() => {
      setSubmitProgress((current) => Math.min(90, current + Math.max(1, Math.round((90 - current) / 8))));
    }, 450);
    return () => window.clearInterval(timer);
  }, [submitting]);

  async function selectDemo(sample: DemoSample) {
    if (submitting || loadingDemo) return;
    setLoadingDemo(sample.id);
    setError("");
    try {
      const [demoVideo, demoTelemetry, demoGroundTruth] = await Promise.all([
        loadDemoFile(sample.videoPath, sample.videoName, "video/mp4"),
        sample.telemetryPath && sample.telemetryName
          ? loadDemoFile(sample.telemetryPath, sample.telemetryName, "text/csv")
          : Promise.resolve(null),
        sample.groundTruthPath && sample.groundTruthName
          ? loadDemoFile(sample.groundTruthPath, sample.groundTruthName, "application/json")
          : Promise.resolve(null),
      ]);
      setVideo(demoVideo);
      setTelemetry(demoTelemetry ? [demoTelemetry] : []);
      setGroundTruth(demoGroundTruth);
      setSelectedDemo(sample.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the demo sample.");
    } finally {
      setLoadingDemo(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !video || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const previousUrl = sessionStorage.getItem("vlens:video-url");
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      sessionStorage.setItem("vlens:video-url", URL.createObjectURL(video));
      sessionStorage.setItem("vlens:video-name", video.name);
      const incidentId = createIncidentId();
      const uploaded = await uploadIncident(video, telemetry[0], groundTruth ?? undefined);
      // Start the optional IndexedDB playback cache only after fetch has
      // finished reading the File. Concurrent IndexedDB and multipart reads of
      // the same Blob can stall indefinitely in some browsers.
      void saveUploadedVideo(video).catch(() => {
        // The session object URL above remains available as the playback fallback.
      });
      const snapshot = await createIncident({
        incident_id: incidentId,
        video_uri: uploaded.video_uri,
        log_uri: uploaded.log_uri,
        analysis_prompt: telemetry.length
          ? "Analyze the full recording, automatically identify the disengagement event timestamp, and use only observable video and telemetry evidence."
          : "Analyze the full recording, automatically identify the disengagement event timestamp, and use only observable video evidence. Clearly state that telemetry was not provided and do not infer telemetry signals.",
        metadata: {
          timestamp_detection: "automatic",
          telemetry_files: telemetry.map((file) => file.name),
          ground_truth_uri: uploaded.ground_truth_uri,
        },
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
    <section id="upload-evidence" className={`workspace-card${highlighted ? " guide-highlight" : ""}`} aria-labelledby="analysis-title">
      <div className="section-title analysis-section-title">
        <div>
          <p className="eyebrow">{text("New analysis", "Phân tích mới")}</p>
          <h2 id="analysis-title">{text("Upload incident evidence", "Tải lên bằng chứng sự cố")}</h2>
          <p className="section-description">{text("Add the original recording and matching vehicle telemetry to begin a grounded review.", "Thêm video gốc và telemetry tương ứng để bắt đầu rà soát dựa trên bằng chứng.")}</p>
        </div>
      </div>
      <form onSubmit={submit}>
        <div className="upload-grid">
          <FileUploadCard
            kind="video"
            files={video ? [video] : []}
            onChange={(files) => {
              setVideo(files[0] ?? null);
              setSelectedDemo(null);
            }}
          />
          <FileUploadCard
            kind="telemetry"
            files={telemetry}
            onChange={(files) => {
              setTelemetry(files);
              setSelectedDemo(null);
            }}
          />
          <FileUploadCard
            kind="groundTruth"
            files={groundTruth ? [groundTruth] : []}
            onChange={(files) => {
              setGroundTruth(files[0] ?? null);
              setSelectedDemo(null);
            }}
          />
        </div>
        <section className="demo-sample-picker" aria-labelledby="demo-samples-title">
          <div>
            <p className="eyebrow">Dữ liệu mẫu</p>
            <h3 id="demo-samples-title">Chọn một tình huống để bắt đầu nhanh</h3>
          </div>
          <p>Chọn mẫu sẽ điền các tệp phù hợp vào khu vực tải lên ở trên; bạn vẫn có thể thay video hoặc dữ liệu xe.</p>
          <div className="demo-sample-grid">
            {demoSamples.map((sample) => (
              <button
                className={`demo-sample-card${selectedDemo === sample.id ? " selected" : ""}`}
                type="button"
                key={sample.id}
                onClick={() => void selectDemo(sample)}
                disabled={Boolean(loadingDemo) || submitting}
                aria-pressed={selectedDemo === sample.id}
              >
                <span className="demo-sample-status">{sample.id === "with-ground-truth" ? "Có ground truth" : sample.id === "with-log-no-ground-truth" ? "Có log" : "Chỉ video"}</span>
                <strong>{sample.title}</strong>
                <span>{loadingDemo === sample.id ? "Đang nạp dữ liệu mẫu…" : sample.description}</span>
                <small>{sample.detail}</small>
              </button>
            ))}
          </div>
        </section>
        <p className="section-description">
          {text("Only the driving video is required. Vehicle telemetry is optional for this MVP.", "Chỉ bắt buộc video hành trình. Telemetry phương tiện là tùy chọn trong MVP này.")}
        </p>
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
