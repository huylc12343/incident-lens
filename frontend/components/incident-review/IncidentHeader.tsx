"use client";

import type { IncidentSnapshot } from "../../types/incident";
import { uiText as text } from "../../lib/ui-copy";

export function IncidentHeader({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const ready = snapshot?.status === "awaiting_review";
  return (
    <section className="incident-workspace-header">
      <div>
        <p className="incident-breadcrumb">{text("Incidents", "Sự cố")} <span>›</span> {snapshot?.incident_id ?? text("New incident", "Sự cố mới")}</p>
        <h1>Disengagement</h1>
        <div className="incident-header-chips"><span>{text("Incident", "Sự cố")} #{snapshot?.incident_id ?? text("Starting…", "Đang khởi tạo…")}</span><span className="source-chip">{text("Video evidence", "Bằng chứng video")}</span>{snapshot?.has_log && <span className="source-chip">{text("Telemetry linked", "Đã liên kết telemetry")}</span>}</div>
      </div>
      <div className={`workspace-status ${ready ? "ready" : ""}`}>
        <strong>{ready ? text("Processing complete · Ready for review", "Xử lý hoàn tất · Sẵn sàng rà soát") : snapshot?.status ?? text("Initializing", "Đang khởi tạo")}</strong>
        <small>{snapshot?.claims.length ?? 0} {text("grounded observation(s)", "quan sát có bằng chứng")}</small>
      </div>
    </section>
  );
}
