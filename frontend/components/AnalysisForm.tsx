"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { TimestampInput } from "./TimestampInput";
import { saveUploadedVideo } from "../lib/uploadStorage";
import { INCIDENT_KEYS, isTimestamp } from "../lib/incidentSession";
import { createIncident, uploadIncident } from "../lib/incidentApi";

export function AnalysisForm() {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null);
  const [telemetry, setTelemetry] = useState<File[]>([]);
  const [timestamp, setTimestamp] = useState("");
  const [touched, setTouched] = useState(false);
  const [toast, setToast] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
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
        analysis_prompt: `Analyze the disengagement incident around ${timestamp}. Use only observable video and telemetry evidence.`,
        metadata: { known_timestamp: timestamp, telemetry_files: telemetry.map((file) => file.name) },
      });
      sessionStorage.setItem(INCIDENT_KEYS.timestamp, timestamp);
      sessionStorage.setItem(INCIDENT_KEYS.incidentId, snapshot.incident_id);
      sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(snapshot));
      setToast(true);
      router.push("/processing");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start incident analysis.");
    } finally {
      setSubmitting(false);
    }
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
          <button className="primary-button" type="submit" disabled={!ready || submitting}>
            {submitting ? "Uploading…" : "Analyze Disengagement"} <span>→</span>
          </button>
        </div>
      </form>
      {toast && (
        <div className="toast" role="status">
          <span>✓</span> Analysis request ready.
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
