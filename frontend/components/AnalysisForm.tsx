"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { TimestampInput } from "./TimestampInput";
import { saveUploadedVideo } from "../lib/uploadStorage";
import { INCIDENT_KEYS, isTimestamp } from "../lib/incidentSession";

export function AnalysisForm() {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null);
  const [telemetry, setTelemetry] = useState<File[]>([]);
  const [timestamp, setTimestamp] = useState("");
  const [touched, setTouched] = useState(false);
  const [toast, setToast] = useState(false);
  const timestampError =
    touched && !isTimestamp(timestamp)
      ? timestamp
        ? "Use a valid timestamp in HH:MM:SS.mmm format."
        : "Known event timestamp is required."
      : "";
  const ready = Boolean(video && telemetry.length && isTimestamp(timestamp));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!ready || !video || !telemetry.length) return;
    const previousUrl = sessionStorage.getItem("vlens:video-url");
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    sessionStorage.setItem("vlens:video-url", URL.createObjectURL(video));
    try {
      await saveUploadedVideo(video);
    } catch {
      // The session object URL above remains available as the playback fallback.
    }
    sessionStorage.setItem("vlens:video-name", video.name);
    sessionStorage.setItem(INCIDENT_KEYS.timestamp, timestamp);
    sessionStorage.setItem(INCIDENT_KEYS.incidentId, `DG-${Date.now()}`);
    const request = {
      videoFile: video.name,
      telemetryFiles: telemetry.map((file) => file.name),
      knownTimestamp: timestamp,
    };
    console.log(request);
    setToast(true);
    window.setTimeout(() => router.push("/processing"), 550);
    /* TODO: Connect this action to the FastAPI analysis endpoint. */
  }
  return (
    <section className="workspace-card" aria-labelledby="analysis-title">
      <div className="section-title">
        <div>
          <p className="eyebrow">New review</p>
          <h2 id="analysis-title">Prepare an analysis request</h2>
        </div>
        <TimestampInput
          value={timestamp}
          error={timestampError}
          onChange={(value) => {
            setTimestamp(value);
            setTouched(true);
          }}
        />
        <span>Required fields marked *</span>
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
        <div className="form-footer">
          <p>Files are used to review this recorded disengagement only.</p>
          <button className="primary-button" type="submit" disabled={!ready}>
            Analyze Disengagement <span>→</span>
          </button>
        </div>
      </form>
      {toast && (
        <div className="toast" role="status">
          <span>✓</span> Analysis request ready.
        </div>
      )}
    </section>
  );
}
