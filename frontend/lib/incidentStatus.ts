import type { IncidentStatus } from "../types/incident";

const labels: Record<IncidentStatus, string> = {
  queued: "Đang xếp hàng — Queued",
  running: "Đang phân tích — Processing",
  awaiting_review: "Chờ rà soát — Awaiting review",
  approved: "Báo cáo đã duyệt — Approved report",
  not_incident: "Đã đóng — Not an incident",
  failed: "Phân tích lỗi — Failed",
  cancelled: "Đã hủy — Cancelled",
};

export const incidentStatusLabel = (status: IncidentStatus) => labels[status];
