"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { saveUploadedVideo } from "../lib/uploadStorage";

export function AnalysisForm() {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null);
  const [telemetry, setTelemetry] = useState<File[]>([]);
  const [toast, setToast] = useState(false);
  const ready = Boolean(video && telemetry.length);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !video || !telemetry.length) return;
    try {
      await saveUploadedVideo(video);
      sessionStorage.removeItem("vlens:video-url");
    } catch {
      const previousUrl = sessionStorage.getItem("vlens:video-url");
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      sessionStorage.setItem("vlens:video-url", URL.createObjectURL(video));
    }
    sessionStorage.setItem("vlens:video-name", video.name);
    sessionStorage.removeItem("vlens:event-timestamp");
    const request = {
      videoFile: video.name,
      telemetryFiles: telemetry.map((file) => file.name),
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
