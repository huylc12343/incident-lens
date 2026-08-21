import type { IncidentSnapshot } from "../types/incident";

export type EvaluationMismatch = {
  field: "incident_type" | "severity" | "t0" | "timeline";
  label: string;
  description: string;
  critical: boolean;
};

const normalize = (value?: string | null) => value?.trim().toLocaleLowerCase("vi") ?? "";

export function getEvaluationMismatches(snapshot: IncidentSnapshot): EvaluationMismatch[] {
  const truth = snapshot.ground_truth;
  const evaluation = snapshot.ai_evaluation;
  const prediction = evaluation?.prediction;
  if (!truth || !evaluation || !prediction) return [];

  const mismatches: EvaluationMismatch[] = [];
  const typeMismatch = evaluation.incident_type_match === false || (evaluation.incident_type_match === undefined && normalize(prediction.incident_type) && normalize(truth.incident_type) && normalize(prediction.incident_type) !== normalize(truth.incident_type));
  const severityMismatch = evaluation.severity_match === false || (evaluation.severity_match === undefined && normalize(prediction.severity) && normalize(truth.severity) && normalize(prediction.severity) !== normalize(truth.severity));
  const calculatedT0Delta = typeof evaluation.t0_delta_s === "number" ? evaluation.t0_delta_s : typeof prediction.timeline?.t0 === "number" && typeof truth.timeline?.t0 === "number" ? Math.abs(prediction.timeline.t0 - truth.timeline.t0) : null;
  const timelineMismatch = typeof evaluation.timeline_iou === "number" && evaluation.timeline_iou < .7;

  if (typeMismatch) mismatches.push({ field: "incident_type", label: "Loại sự cố không khớp", description: `AI dự đoán “${prediction.incident_type ?? "Không có dữ liệu"}”, trong khi Ground Truth ghi nhận “${truth.incident_type ?? "Không có dữ liệu"}”.`, critical: true });
  if (severityMismatch) mismatches.push({ field: "severity", label: "Mức độ không khớp", description: `AI: “${prediction.severity ?? "Không có dữ liệu"}”; Ground Truth: “${truth.severity ?? "Không có dữ liệu"}”.`, critical: false });
  if (calculatedT0Delta !== null && calculatedT0Delta > .5) mismatches.push({ field: "t0", label: "Sai lệch mốc t0", description: `Mốc t0 của AI lệch ${calculatedT0Delta.toFixed(2)} giây so với Ground Truth.`, critical: true });
  if (timelineMismatch) mismatches.push({ field: "timeline", label: "Timeline không khớp", description: `Timeline IoU chỉ đạt ${Math.round((evaluation.timeline_iou ?? 0) * 100)}%, cần kiểm tra lại cửa sổ sự cố.`, critical: false });
  return mismatches;
}
