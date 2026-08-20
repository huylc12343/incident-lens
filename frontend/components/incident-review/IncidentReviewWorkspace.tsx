"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { artifactUrl, getIncident, reviewIncident } from "../../lib/incidentApi";
import { INCIDENT_KEYS } from "../../lib/incidentSession";
import type { Claim, IncidentSnapshot, ReviewPayload } from "../../types/incident";
import { ProcessingPipeline } from "../ProcessingPipeline";
import { DecisionModal } from "./DecisionModal";
import { EvidenceInspector } from "./EvidenceInspector";
import { GroundTruthComparison } from "./GroundTruthComparison";
import { IncidentHeader } from "./IncidentHeader";
import { IncidentClipPlayer } from "./IncidentClipPlayer";
import { IncidentNavigationSidebar } from "./IncidentNavigationSidebar";
import { ReviewSidebar } from "./ReviewSidebar";
import { TelemetryPanel } from "./TelemetryPanel";

export function IncidentReviewWorkspace() {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [decisionOpen, setDecisionOpen] = useState(false);

  useEffect(() => {
    const cached = sessionStorage.getItem(INCIDENT_KEYS.snapshot);
    if (cached) try { setSnapshot(JSON.parse(cached) as IncidentSnapshot); } catch { /* ignore stale browser state */ }
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
        setSnapshot(next);
        sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
        setSelectedClaimId((current) => current || next.claims[0]?.claim_id || "");
        if (["queued", "running"].includes(next.status)) timer = setTimeout(refresh, 1500);
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Could not load incident.");
          timer = setTimeout(refresh, 3000);
        }
      }
    };
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, []);

  const selectedClaim = useMemo(() => snapshot?.claims.find((claim) => claim.claim_id === selectedClaimId) ?? snapshot?.claims[0], [snapshot, selectedClaimId]);
  const selectClaim = (claim: Claim) => {
    setSelectedClaimId(claim.claim_id);
    const activeReport = snapshot?.final_report ?? snapshot?.draft_report;
    const clipStart = activeReport?.incident_window?.t_start ?? 0;
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, claim.timestamp_s - clipStart);
  };
  const submitReview = async (payload: ReviewPayload) => {
    if (!snapshot) return;
    setBusy(true);
    setError("");
    try {
      const next = await reviewIncident(snapshot.incident_id, payload);
      setSnapshot(next);
      sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
      if (["approved", "not_incident"].includes(next.status)) router.push("/evaluation");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Review request failed.");
    } finally {
      setBusy(false);
    }
  };

  const report = snapshot?.final_report ?? snapshot?.draft_report;
  const clip = artifactUrl(snapshot?.artifact_uris.incident_clip);
  const telemetryCharts = snapshot ? Object.entries(snapshot.artifact_uris).filter(([key, uri]) => key.startsWith("chart_") && Boolean(uri)).sort(([left], [right]) => left.localeCompare(right)).map(([id, uri]) => ({ id, uri })) : [];

  return (
    <div className="incident-review-frame">
      <IncidentNavigationSidebar snapshot={snapshot} />
      <section className="incident-review-content">
        <IncidentHeader snapshot={snapshot} />
        {!snapshot ? (
          <section className={`workspace-panel workspace-state ${error ? "error-state" : "loading-state"}`} role={error ? "alert" : "status"}>
            {!error && <span className="state-spinner" aria-hidden="true" />}
            <div><strong>{error ? "Incident workspace unavailable" : "Preparing incident workspace"}</strong><p>{error || "Synchronizing the latest analysis and evidence…"}</p></div>
          </section>
        ) : (
          <>
            <div className="review-command-bar">
              <div><span className="command-status-dot" /><strong>{snapshot.status === "awaiting_review" ? "Ready for engineer review" : `Workflow: ${snapshot.status}`}</strong><small>{snapshot.claims.length} AI observation(s) · {snapshot.has_log ? "Video + telemetry" : "Video only"}</small></div>
              <div><a className="command-secondary" href="#selected-evidence">Inspect evidence</a><button type="button" className="command-decision" disabled={snapshot.status !== "awaiting_review" || busy} onClick={() => setDecisionOpen(true)}><span aria-hidden="true">☷</span> Make decision</button></div>
            </div>
            <div className="incident-review-workspace" id="engineer-review">
              <main className="incident-evidence-column">
                <IncidentClipPlayer clipUrl={clip} start={report?.incident_window?.t_start} focus={report?.incident_window?.t0} end={report?.incident_window?.t_end} claims={snapshot.claims} selectedId={selectedClaim?.claim_id ?? ""} onSelect={selectClaim} videoRef={videoRef} />
                <TelemetryPanel summaries={snapshot.claim_log_summaries} selectedClaimId={selectedClaim?.claim_id ?? ""} hasLog={snapshot.has_log} chartUris={telemetryCharts} comparison={<GroundTruthComparison snapshot={snapshot} />} />
                <div className="evidence-presentation-stack" id="selected-evidence"><EvidenceInspector snapshot={snapshot} claim={selectedClaim} /></div>
              </main>
              <div className="incident-decision-column">
                {["queued", "running"].includes(snapshot.status) && <div id="processing-status"><ProcessingPipeline snapshot={snapshot} /></div>}
                <ReviewSidebar snapshot={snapshot} selectedClaim={selectedClaim} busy={busy} error={error} onSelectClaim={selectClaim} onReview={submitReview} />
              </div>
            </div>
            <DecisionModal open={decisionOpen} snapshot={snapshot} selectedClaim={selectedClaim} busy={busy} onClose={() => setDecisionOpen(false)} onReview={submitReview} />
          </>
        )}
      </section>
    </div>
  );
}
