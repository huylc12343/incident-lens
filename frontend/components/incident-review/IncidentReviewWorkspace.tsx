"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { artifactUrl, getIncident, reviewIncident } from "../../lib/incidentApi";
import { getEvaluationMismatches } from "../../lib/groundTruthEvaluation";
import { INCIDENT_KEYS } from "../../lib/incidentSession";
import { loadUploadedVideo } from "../../lib/uploadStorage";
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
  const [originalVideoUrl, setOriginalVideoUrl] = useState("");
  const [decisionOpen, setDecisionOpen] = useState(false);

  useEffect(() => {
    const cached = sessionStorage.getItem(INCIDENT_KEYS.snapshot);
    if (cached) try { setSnapshot(JSON.parse(cached) as IncidentSnapshot); } catch { /* ignore stale browser state */ }
  }, []);

  useEffect(() => {
    const id = sessionStorage.getItem(INCIDENT_KEYS.incidentId);
    if (!id) { setError("No active incident. Start an analysis or open one from History."); return; }
    let active = true;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await getIncident(id);
        if (!active) return;
        failures = 0;
        setSnapshot(next);
        sessionStorage.setItem(INCIDENT_KEYS.snapshot, JSON.stringify(next));
        setSelectedClaimId((current) => current || next.claims[0]?.claim_id || "");
        if (["queued", "running"].includes(next.status)) timer = setTimeout(refresh, 1500);
      } catch (cause) {
        if (active) {
          failures += 1;
          setError(cause instanceof Error ? cause.message : "Could not load incident.");
          if (failures < 5) timer = setTimeout(refresh, 3000);
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
  const aiFoundNoIncident = snapshot?.status === "awaiting_review" && report?.type_of_accident === "no_incident";
  const evaluationMismatches = snapshot ? getEvaluationMismatches(snapshot) : [];
  const hasCriticalEvaluationMismatch = evaluationMismatches.some((mismatch) => mismatch.critical);
  const clip = artifactUrl(snapshot?.artifact_uris.incident_clip);
  const telemetryCharts = snapshot ? Object.entries(snapshot.artifact_uris).filter(([key, uri]) => key.startsWith("chart_") && Boolean(uri)).sort(([left], [right]) => left.localeCompare(right)).map(([id, uri]) => ({ id, uri })) : [];

  useEffect(() => {
    if (!aiFoundNoIncident || clip) {
      setOriginalVideoUrl("");
      return;
    }
    let active = true;
    let blobUrl = "";
    const sessionVideoUrl = sessionStorage.getItem("vlens:video-url");
    if (sessionVideoUrl) setOriginalVideoUrl(sessionVideoUrl);
    void loadUploadedVideo().then((video) => {
      if (!active || !video) return;
      blobUrl = URL.createObjectURL(video);
      setOriginalVideoUrl(blobUrl);
    }).catch(() => { /* Session playback remains the fallback when IndexedDB is unavailable. */ });
    return () => {
      active = false;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [aiFoundNoIncident, clip]);

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
            {evaluationMismatches.length > 0 && <section className={`ground-truth-alert ${hasCriticalEvaluationMismatch ? "critical" : "warning"}`} role="alert" aria-labelledby="ground-truth-alert-title"><div><span className="ground-truth-alert-icon" aria-hidden="true">!</span><div><strong id="ground-truth-alert-title">Cần rà soát: Kết luận AI chưa khớp Ground Truth</strong><p>{evaluationMismatches[0].description}{evaluationMismatches.length > 1 ? ` Có thêm ${evaluationMismatches.length - 1} sai lệch cần kiểm tra.` : ""}</p><small>{evaluationMismatches.map((mismatch) => mismatch.label).join(" · ")}</small></div></div><a href="#ground-truth-comparison">Xem đối chiếu</a></section>}
            {aiFoundNoIncident && <section className="ground-truth-alert warning" role="status" aria-live="polite"><div><span className="ground-truth-alert-icon" aria-hidden="true">!</span><div><strong>AI chưa phát hiện sự cố.</strong><p>Vui lòng kiểm tra bằng chứng và xác nhận đóng case nếu đồng ý.</p></div></div><a href="#engineer-review">Mở phần rà soát</a></section>}
              <div className="review-command-bar">
              <div><span className="command-status-dot" /><strong>{snapshot.status === "awaiting_review" ? "Ready for engineer review" : `Workflow: ${snapshot.status}`}</strong><small>{snapshot.claims.length} AI observation(s) · {snapshot.has_log ? "Video + telemetry" : "Video only"}</small></div>
              <div><a className="command-secondary" href="#selected-evidence">Inspect evidence</a><button type="button" className="command-decision" disabled={snapshot.status !== "awaiting_review" || busy} onClick={() => setDecisionOpen(true)}><span aria-hidden="true">☷</span> Make decision</button></div>
              </div>
              {snapshot.status === "failed" && <section className="workspace-panel workspace-state error-state" role="alert"><div><strong>Phân tích không hoàn tất</strong><p>{snapshot.error_message || "Workflow đã dừng trước khi tạo kết quả review."}</p><button type="button" className="command-secondary" onClick={() => router.push("/")}>Quay lại tải lên và thử lại</button></div></section>}
              <div className="incident-review-workspace" id="engineer-review">
              <main className="incident-evidence-column">
                <IncidentClipPlayer clipUrl={clip || originalVideoUrl} isOriginalVideo={aiFoundNoIncident && !clip} noIncident={aiFoundNoIncident} start={report?.incident_window?.t_start} focus={report?.incident_window?.t0} end={report?.incident_window?.t_end} claims={snapshot.claims} selectedId={selectedClaimId} onSelect={selectClaim} videoRef={videoRef} />
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
