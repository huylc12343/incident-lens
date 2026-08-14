"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { artifactUrl, getIncident, reviewIncident } from "../../lib/incidentApi";
import { INCIDENT_KEYS } from "../../lib/incidentSession";
import { loadUploadedVideo } from "../../lib/uploadStorage";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";
import { VideoEvidencePlayer } from "../VideoEvidencePlayer";
import { ProcessingPipeline } from "../ProcessingPipeline";
import { EvidenceInspector } from "./EvidenceInspector";
import { IncidentHeader } from "./IncidentHeader";
import { IncidentTimeline } from "./IncidentTimeline";
import { ReviewSidebar } from "./ReviewSidebar";
import { TelemetryPanel } from "./TelemetryPanel";

export function IncidentReviewWorkspace() {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState("");
  const [originalVideoUrl, setOriginalVideoUrl] = useState("");
  const [videoName, setVideoName] = useState("front_camera.mp4");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setVideoName(sessionStorage.getItem("vlens:video-name") ?? "front_camera.mp4");
    const cached = sessionStorage.getItem(INCIDENT_KEYS.snapshot);
    if (cached) try { setSnapshot(JSON.parse(cached) as IncidentSnapshot); } catch { /* ignore stale browser state */ }
    let objectUrl = "";
    loadUploadedVideo().then((file) => { if (file) { objectUrl = URL.createObjectURL(file); setOriginalVideoUrl(objectUrl); } }).catch(() => undefined);
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, []);

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident. Start an analysis or open one from History."); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await getIncident(id);
        if (!active) return;
        setSnapshot(next); sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
        setSelectedClaimId((current) => current || next.claims[0]?.claim_id || "");
        if (["queued", "running"].includes(next.status)) timer = setTimeout(refresh, 1500);
      } catch (cause) { if (active) { setError(cause instanceof Error ? cause.message : "Could not load incident."); timer = setTimeout(refresh, 3000); } }
    };
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, []);

  const selectedClaim = useMemo(() => snapshot?.claims.find((claim) => claim.claim_id === selectedClaimId) ?? snapshot?.claims[0], [snapshot, selectedClaimId]);
  const selectClaim = (claim: Claim) => { setSelectedClaimId(claim.claim_id); if (videoRef.current) videoRef.current.currentTime = claim.timestamp_s; };
  const submitReview = async (payload: ReviewPayload) => {
    if (!snapshot) return;
    setBusy(true); setError("");
    try {
      const next = await reviewIncident(snapshot.incident_id, payload);
      setSnapshot(next); sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
      if (["approved", "not_incident"].includes(next.status)) router.push("/evaluation");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Review request failed."); }
    finally { setBusy(false); }
  };

  const report = snapshot?.final_report ?? snapshot?.draft_report;
  const fullVideo = originalVideoUrl || artifactUrl(snapshot?.artifact_uris.normalized_video);
  const clip = artifactUrl(snapshot?.artifact_uris.incident_clip);
  return (
    <>
      <IncidentHeader snapshot={snapshot} />
      {!snapshot ? <section className="workspace-panel"><p>{error || "Loading incident workspace…"}</p></section> : (
        <div className="incident-review-workspace">
          <main className="incident-evidence-column">
            <VideoEvidencePlayer videoUrl={fullVideo} videoName={videoName} videoRef={videoRef} />
            <IncidentTimeline claims={snapshot.claims} selectedId={selectedClaim?.claim_id ?? ""} onSelect={selectClaim} />
            <TelemetryPanel summaries={snapshot.claim_log_summaries} selectedClaimId={selectedClaim?.claim_id ?? ""} hasLog={snapshot.has_log} />
            <div className="evidence-detail-grid">
              <section className="workspace-panel incident-clip-card"><div className="workspace-panel-heading"><div><p className="eyebrow">Detected window</p><h2>Incident clip</h2></div><span>{report?.incident_window ? `${report.incident_window.t_start.toFixed(1)}s–${report.incident_window.t_end.toFixed(1)}s` : "Pending"}</span></div>{clip ? <video controls preload="metadata" src={clip} /> : <p>Clip generation is in progress.</p>}</section>
              <EvidenceInspector snapshot={snapshot} claim={selectedClaim} />
            </div>
          </main>
          <div className="incident-decision-column">
            {["queued", "running"].includes(snapshot.status) && <ProcessingPipeline snapshot={snapshot} />}
            <ReviewSidebar snapshot={snapshot} selectedClaim={selectedClaim} busy={busy} error={error} onReview={submitReview} />
          </div>
        </div>
      )}
    </>
  );
}
