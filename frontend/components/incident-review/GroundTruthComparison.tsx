import { secondsToTimestamp } from "../../lib/incidentSession";
import type { IncidentSnapshot } from "../../types/incident";

const noData = "Không có dữ liệu";
const value = (item?: string | number | null) => item === undefined || item === null || item === "" ? noData : item;
const time = (item?: number | null) => typeof item === "number" ? secondsToTimestamp(item) : noData;
const verdict = (match?: boolean | null) => match === true ? "Khớp" : match === false ? "Không khớp" : noData;

export function GroundTruthComparison({ snapshot }: { snapshot: IncidentSnapshot }) {
  const truth = snapshot.ground_truth;
  const evaluation = snapshot.ai_evaluation;
  if (!truth) return null;
  const prediction = evaluation?.prediction;
  const truthTimeline = truth.timeline;
  const predictionTimeline = prediction?.timeline;

  return <section className="workspace-panel ground-truth-comparison" id="ground-truth-comparison" aria-labelledby="ground-truth-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">ĐÁNH GIÁ CHẤT LƯỢNG AI</p><h2 id="ground-truth-title">Đối chiếu với Ground Truth</h2><p className="comparison-subtitle">So sánh kết quả AI với annotation hoặc nhãn mô phỏng đã xác nhận.</p></div><span className="ground-truth-source">{truth.source}</span></div>
    {!evaluation && <p className="comparison-empty">Có Ground Truth nhưng chưa có kết quả dự đoán AI hợp lệ để đối chiếu.</p>}
    <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Trường</th><th>Kết quả AI</th><th>Ground Truth</th><th>Đánh giá</th></tr></thead><tbody>
      <tr><th>Loại sự cố</th><td>{value(prediction?.incident_type)}</td><td>{value(truth.incident_type)}</td><td>{verdict(evaluation?.incident_type_match)}</td></tr>
      <tr><th>Mức độ</th><td>{value(prediction?.severity)}</td><td>{value(truth.severity)}</td><td>{verdict(evaluation?.severity_match)}</td></tr>
      <tr><th>Bắt đầu</th><td>{time(predictionTimeline?.t_start)}</td><td>{time(truthTimeline?.t_start)}</td><td>{noData}</td></tr>
      <tr><th>Sự kiện chính t0</th><td>{time(predictionTimeline?.t0)}</td><td>{time(truthTimeline?.t0)}</td><td>{typeof evaluation?.t0_delta_s === "number" ? `Sai lệch ${evaluation.t0_delta_s.toFixed(2)}s` : noData}</td></tr>
      <tr><th>Kết thúc</th><td>{time(predictionTimeline?.t_end)}</td><td>{time(truthTimeline?.t_end)}</td><td>{typeof evaluation?.timeline_iou === "number" ? `IoU ${Math.round(evaluation.timeline_iou * 100)}%` : noData}</td></tr>
    </tbody></table></div>
    <div className="comparison-timeline" aria-label="So sánh timeline"><div><strong>Ground Truth</strong><span className="timeline-track"><i className="truth-range" /><b title="t0 Ground Truth" /></span></div><div><strong>Dự đoán AI</strong><span className="timeline-track"><i className="prediction-range" /><b title="t0 Dự đoán AI" /></span></div><small>Marker tròn biểu thị sự kiện chính t0.</small></div>
  </section>;
}
