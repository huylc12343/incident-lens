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
import { ClaimReviewList } from "./ClaimReviewList";
import { GroundTruthComparison } from "./GroundTruthComparison";
import { IncidentHeader } from "./IncidentHeader";
import { IncidentClipPlayer } from "./IncidentClipPlayer";
import { IncidentTimeline } from "./IncidentTimeline";
import { IncidentNavigationSidebar } from "./IncidentNavigationSidebar";
import { ReviewSidebar } from "./ReviewSidebar";
import { TechnicalDetails } from "./TechnicalDetails";
import { TelemetryPanel, telemetryChartArtifacts } from "./TelemetryPanel";

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
        if (["queued", "running"].includes(next.status)) timer = setTimeout(refresh, 3000);
      } catch (cause) {
        if (active) {
          failures += 1;
          setError(cause instanceof Error ? cause.message : "Could not load incident.");
          if (failures < 5) timer = setTimeout(refresh, 5000);
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
    if (videoRef.current && typeof claim.timestamp_s === "number") videoRef.current.currentTime = Math.max(0, claim.timestamp_s - clipStart);
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
  const telemetryCharts = snapshot ? telemetryChartArtifacts(snapshot.artifact_uris) : [];
  const verificationResults = report?.alignment?.verification?.results ?? [];

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
              <div className="review-command-bar">
              <div><span className="command-status-dot" /><strong>{snapshot.status === "awaiting_review" ? "Ready for engineer review" : `Workflow: ${snapshot.status}`}</strong><small>{snapshot.claims.length} nhận định AI · {snapshot.has_log ? "Video + telemetry" : "Video only"}</small></div>
              <div><a className="command-secondary" href="#claims">Xem claims</a><button type="button" className="command-decision" disabled={snapshot.status !== "awaiting_review" || busy} onClick={() => setDecisionOpen(true)}><span aria-hidden="true">☷</span> Make decision</button></div>
              </div>
              {snapshot.status === "failed" && <section className="workspace-panel workspace-state error-state" role="alert"><div><strong>Phân tích không hoàn tất</strong><p>{snapshot.error_message || "Workflow đã dừng trước khi tạo kết quả review."}</p><button type="button" className="command-secondary" onClick={() => router.push("/")}>Quay lại tải lên và thử lại</button></div></section>}
              <div className="incident-review-workspace review-flow-vertical" id="engineer-review">
              <main className="incident-evidence-column">
                <section className="workspace-panel incident-overview-section" id="overview"><div className="workspace-panel-heading"><div><p className="eyebrow">Incident Overview</p><h2>Tổng quan sự cố</h2></div><span>{snapshot.incident_id}</span></div><dl><div><dt>Trạng thái</dt><dd>{snapshot.status}</dd></div><div><dt>Khoảng phân tích</dt><dd>{report?.incident_window ? `${report.incident_window.t_start.toFixed(2)}s → ${report.incident_window.t_end.toFixed(2)}s` : "—"}</dd></div><div><dt>Sự kiện chính</dt><dd>{typeof report?.incident_window?.t0 === "number" ? `${report.incident_window.t0.toFixed(2)}s` : "—"}</dd></div><div><dt>Nguồn dữ liệu</dt><dd>{snapshot.has_log ? "Video + telemetry" : "Video"}</dd></div></dl></section>
                {["queued", "running"].includes(snapshot.status) && <div id="processing-status"><ProcessingPipeline snapshot={snapshot} /></div>}
                <IncidentClipPlayer clipUrl={clip || originalVideoUrl} isOriginalVideo={aiFoundNoIncident && !clip} noIncident={aiFoundNoIncident} start={report?.incident_window?.t_start} focus={report?.incident_window?.t0} end={report?.incident_window?.t_end} claims={snapshot.claims} selectedId={selectedClaimId} onSelect={selectClaim} videoRef={videoRef} />
                <IncidentTimeline report={report} claims={snapshot.claims} onSelect={selectClaim} />
                <TelemetryPanel hasLog={snapshot.has_log} charts={telemetryCharts} />
                <ClaimReviewList claims={snapshot.claims} summaries={snapshot.claim_log_summaries} verificationResults={verificationResults} hasLog={snapshot.has_log} selectedClaimId={selectedClaim?.claim_id} onSelect={selectClaim} />
                <ReviewSidebar snapshot={snapshot} selectedClaim={selectedClaim} busy={busy} error={error} onSelectClaim={selectClaim} onReview={submitReview} />
                <TechnicalDetails snapshot={snapshot} comparison={<GroundTruthComparison snapshot={snapshot} />} />
              </main>
            </div>
            <DecisionModal open={decisionOpen} snapshot={snapshot} selectedClaim={selectedClaim} busy={busy} onClose={() => setDecisionOpen(false)} onReview={submitReview} />
          </>
        )}
      </section>
    </div>
  );
}
