"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUploadCard } from "./FileUploadCard";
import { TimestampInput } from "./TimestampInput";

const isTimestamp = (value: string) => { const match = /^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/.exec(value); return Boolean(match && Number(match[1]) <= 23 && Number(match[2]) <= 59 && Number(match[3]) <= 59); };

export function AnalysisForm() {
  const router = useRouter();
  const [video, setVideo] = useState<File | null>(null); const [telemetry, setTelemetry] = useState<File | null>(null); const [timestamp, setTimestamp] = useState(""); const [touched, setTouched] = useState(false); const [toast, setToast] = useState(false);
  const timestampError = touched && !isTimestamp(timestamp) ? (timestamp ? "Use a valid timestamp in HH:MM:SS.mmm format." : "Event timestamp is required.") : "";
  const ready = Boolean(video && telemetry && isTimestamp(timestamp));
  function submit(event: FormEvent) {
    event.preventDefault(); setTouched(true);
    if (!ready || !video || !telemetry) return;
    const previousUrl = sessionStorage.getItem("vlens:video-url");
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    sessionStorage.setItem("vlens:video-url", URL.createObjectURL(video));
    sessionStorage.setItem("vlens:video-name", video.name);
    sessionStorage.setItem("vlens:event-timestamp", timestamp);
    const request = { videoFile: video.name, telemetryFile: telemetry.name, disengagementTimestamp: timestamp };
    console.log(request); setToast(true);
    window.setTimeout(() => router.push("/processing"), 550);
    /* TODO: Connect this action to the FastAPI analysis endpoint. */
  }
  return <section className="workspace-card" aria-labelledby="analysis-title"><div className="section-title"><div><p className="eyebrow">New review</p><h2 id="analysis-title">Prepare an analysis request</h2></div><span>Required fields marked *</span></div><form onSubmit={submit}><div className="upload-grid"><FileUploadCard kind="video" file={video} onChange={setVideo} /><FileUploadCard kind="telemetry" file={telemetry} onChange={setTelemetry} /></div><TimestampInput value={timestamp} error={timestampError} onChange={(value) => { setTimestamp(value); setTouched(true); }} /><div className="form-footer"><p>Files are used to review this recorded disengagement only.</p><button className="primary-button" type="submit" disabled={!ready}>Analyze Disengagement <span>→</span></button></div></form>{toast && <div className="toast" role="status"><span>✓</span> Analysis request ready.</div>}</section>;
}
