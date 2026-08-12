"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { artifactUrl, getIncident } from "../lib/incidentApi";
import { INCIDENT_KEYS, secondsToTimestamp } from "../lib/incidentSession";
import { loadUploadedVideo } from "../lib/uploadStorage";
import type { IncidentSnapshot } from "../types/incident";
import { VideoEvidencePlayer } from "./VideoEvidencePlayer";
import { ProcessingPipeline } from "./ProcessingPipeline";

export function ProcessingContent() {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [error, setError] = useState("");
  const [videoName, setVideoName] = useState("front_camera.mp4");
  const [eventTimestamp, setEventTimestamp] = useState("Detecting automatically…");

  useEffect(() => {
    setVideoName(sessionStorage.getItem("vlens:video-name") ?? "front_camera.mp4");
    setEventTimestamp(sessionStorage.getItem(INCIDENT_KEYS.timestamp) ?? "Detecting automatically…");
    let objectUrl = "";
    loadUploadedVideo().then((file) => {
      if (file) { objectUrl = URL.createObjectURL(file); setVideoUrl(objectUrl); }
    }).catch(() => undefined);
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, []);

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident. Start a new analysis first."); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await getIncident(id);
        if (!active) return;
        setSnapshot(next);
        const report = next.draft_report ?? next.final_report;
        const incidentWindow = report?.incident_window as { t0?: number } | undefined;
        const detectedTimestamp = incidentWindow?.t0 ?? next.claims[0]?.timestamp_s;
        if (detectedTimestamp !== undefined) {
          const formatted = secondsToTimestamp(detectedTimestamp);
          setEventTimestamp(formatted);
          sessionStorage.setItem(INCIDENT_KEYS.timestamp, formatted);
        }
        sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
        if (next.status === "awaiting_review") { router.push("/review"); return; }
        if (["approved", "not_incident"].includes(next.status)) { router.push("/evaluation"); return; }
        if (!['failed', 'cancelled'].includes(next.status)) timer = setTimeout(poll, 1500);
      } catch (cause) {
        if (active) { setError(cause instanceof Error ? cause.message : "Could not load incident."); timer = setTimeout(poll, 3000); }
      }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [router]);

  const clip = artifactUrl(snapshot?.artifact_uris.incident_clip);
  const playableVideo = clip || videoUrl;
  return (
    <>
      <section className="context-bar">
        <div><span>Analyzing video</span><strong>{videoName}</strong></div>
        <div><span>Detected event timestamp</span><strong>{eventTimestamp}</strong></div>
        <div><span>Workflow status</span><strong>{snapshot?.status ?? "queued"} <i>·</i> {snapshot?.claims.length ?? 0} claims</strong></div>
        <p>Visual and telemetry evidence is analyzed by the incident workflow. This page updates automatically.</p>
      </section>
      <div className="processing-layout">
        <div className="processing-main">
          <VideoEvidencePlayer videoUrl={playableVideo} videoName={videoName} videoRef={videoRef} />
          <section className="processing-panel"><div className="panel-heading"><p className="eyebrow">Visual observations</p><h2>Grounded evidence</h2><p>Claims generated from the uploaded recording and linked to timestamps.</p></div><div className="review-observations">
            {snapshot?.claims.length ? snapshot.claims.map((claim) => <article key={claim.claim_id}><div><strong>{claim.claim_id}</strong><span>{secondsToTimestamp(claim.timestamp_s)}</span></div><p>{claim.text}</p><small>Evidence: <b>{claim.evidence.map((item) => item.evidence_id).join(", ") || "Pending"}</b> · {claim.verification_status}</small></article>) : <article><div><strong>AI</strong><span>Working</span></div><p>Evidence analysis is in progress.</p><small>Claims will appear here as soon as they are available.</small></article>}
          </div></section>
          {error && <p role="alert" className="form-error">{error}</p>}
          {snapshot?.status === "failed" && <p role="alert" className="form-error">{snapshot.error_code}: {snapshot.error_message}</p>}
        </div>
        <aside className="processing-sidebar">
          <ProcessingPipeline snapshot={snapshot} />
          <section className="processing-panel sources-panel"><p className="eyebrow">Evidence sources</p><ul><li>✓ <span>Video loaded</span></li><li>{snapshot?.has_log ? "✓" : "○"} <span>Telemetry {snapshot?.has_log ? "loaded" : "not provided"}</span></li></ul></section>
          <Link className="back-home" href="/">← Back to Home</Link>
          {snapshot?.status === "awaiting_review" && <Link className="approve-action processing-review-link" href="/review">Review structured summary →</Link>}
          <button type="button" className="background-button" onClick={() => window.location.assign("/")}>Run in background</button>
        </aside>
      </div>
    </>
  );
}
