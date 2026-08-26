"use client";

import Image from "next/image";
import { artifactUrl } from "../../lib/incidentApi";

const chartDefinitions: Array<{ keys: string[]; title: string }> = [
  { keys: ["chart_1", "chart_speed_acceleration", "speed_acceleration_chart"], title: "Speed / acceleration" },
  { keys: ["chart_2", "chart_brake_throttle", "brake_throttle_chart"], title: "Brake / throttle" },
  { keys: ["chart_3", "chart_steering", "steering_chart"], title: "Steering" },
  { keys: ["chart_4", "chart_autonomy_events", "autonomy_events_chart"], title: "Autonomy / disengagement" },
];

export function telemetryChartArtifacts(artifactUris: Record<string, string>) {
  return chartDefinitions.flatMap((definition) => {
    const key = definition.keys.find((candidate) => Boolean(artifactUris[candidate]));
    return key ? [{ id: key, title: definition.title, uri: artifactUris[key] }] : [];
  });
}

export function TelemetryPanel({ hasLog, charts }: { hasLog: boolean; charts: Array<{ id: string; title: string; uri: string }> }) {
  if (!hasLog) return null;
  return <section className="workspace-panel telemetry-chart-section" id="telemetry" aria-labelledby="telemetry-title">
    <div className="workspace-panel-heading"><div><p className="eyebrow">Telemetry Charts</p><h2 id="telemetry-title">Dữ liệu phương tiện theo thời gian</h2></div><span>{charts.length} chart</span></div>
    {charts.length > 0 ? <div className="telemetry-chart-grid">{charts.map((chart) => <figure key={chart.id}><div><Image unoptimized width={1000} height={480} src={artifactUrl(chart.uri)} alt={`${chart.title} telemetry chart`} /></div><figcaption><strong>{chart.title}</strong><span>Dữ liệu do backend tạo từ telemetry log</span></figcaption></figure>)}</div> : <div className="telemetry-empty"><strong>Chưa có telemetry chart</strong><p>Backend chưa cung cấp chart artifact hoặc time-series đủ để vẽ biểu đồ. Các aggregate metrics hiện có chỉ được hiển thị trong chi tiết của từng claim.</p></div>}
  </section>;
}
