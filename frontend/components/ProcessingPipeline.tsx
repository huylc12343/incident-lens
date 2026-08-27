import type { IncidentSnapshot } from "../types/incident";

function DancingText({ children }: { children: string }) {
  return <span className="dancing-text" aria-label={children}>
    <span aria-hidden="true">{Array.from(children).map((character, index) => (
      <span className="dancing-character" style={{ animationDelay: `${index * 45}ms` }} key={`${character}-${index}`}>
        {character === " " ? "\u00a0" : character}
      </span>
    ))}</span>
  </span>;
}

export function ProcessingPipeline({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const activities = snapshot?.model_activities ?? [];
  const successful = snapshot && ["awaiting_review", "approved", "not_incident"].includes(snapshot.status);
  const stopped = snapshot && ["failed", "cancelled"].includes(snapshot.status);
  const currentStage = successful ? "completed" : stopped ? "failed" : snapshot?.progress?.stage ?? "validating";
  const stageOrder = ["upload", "validating", "normalizing", "redacting", "compressing", "vlm", "evidence", "telemetry", "verification", "report", "completed"];
  const currentIndex = currentStage === "failed" ? stageOrder.length - 1 : Math.max(stageOrder.indexOf(currentStage), 1);
  const activity = (step: string) => [...activities].reverse().find((item) => item.step === step);
  const labels: Record<string, string> = {
    upload: "Đã tải video và telemetry lên",
    validating: "Đang kiểm tra dữ liệu đầu vào",
    normalizing: "Đang chuẩn hóa video",
    redacting: "Đang phát hiện và làm mờ mặt, biển số",
    compressing: "Đang nén video đã bảo vệ quyền riêng tư",
    vlm: activity("vlm")?.description ?? "VLM đang phân tích diễn biến video",
    evidence: "Đang chuẩn hóa bằng chứng theo timeline",
    telemetry: snapshot?.has_log ? "Đang phân tích và đồng bộ telemetry" : "Không có telemetry để phân tích",
    verification: activity("verification")?.description ?? "LLM đang kiểm chứng các nhận định",
    report: activity("report")?.description ?? "LLM đang tạo báo cáo sự cố",
    completed: "Phân tích hoàn tất, sẵn sàng để rà soát",
    failed: "Phân tích không hoàn tất",
  };
  const currentActivity = ["vlm", "verification", "report"].includes(currentStage) ? activity(currentStage) : undefined;
  const currentLabel = snapshot?.progress?.message ?? labels[currentStage] ?? labels.validating;
  const currentDetail = currentActivity ? `${currentActivity.provider} · ${currentActivity.model}` : undefined;
  const progress = successful ? 100 : stopped ? Math.round(currentIndex / (stageOrder.length - 1) * 100) : Math.max(5, Math.round(currentIndex / (stageOrder.length - 1) * 100));
  const running = !successful && !stopped;
  return <section className={`processing-panel pipeline-panel ${running ? "is-running" : ""}`} aria-live="polite">
    <div className="panel-heading"><p className="eyebrow">Phân tích bằng chứng</p><h2>Tiến trình tổng thể</h2></div>
    <div className="progress-summary"><strong>{progress}%</strong><span>Trạng thái workflow<br /><b>{running && <i className="running-dot" aria-hidden="true" />}{snapshot?.progress?.message ?? snapshot?.status ?? "Đang khởi động"}</b></span></div>
    <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
    <div className="pipeline current-stage-only">
      <div className={stopped ? "failed" : successful ? "completed" : "active"}>
        <span className="step-symbol" aria-hidden="true">{stopped ? "✕" : successful ? "✓" : "●"}</span>
        <div className="current-stage-copy">
          {running ? <DancingText>{currentLabel}</DancingText> : <span>{currentLabel}</span>}
          {running && <small>{currentDetail ?? "Đang xử lý"}</small>}
        </div>
      </div>
    </div>
  </section>;
}
