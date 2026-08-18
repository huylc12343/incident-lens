import Image from "next/image";
import { artifactUrl } from "../../lib/incidentApi";
import { secondsToTimestamp } from "../../lib/incidentSession";
import type { ClaimLogSummary } from "../../types/incident";

const chartTitles: Record<string, string> = {
  chart_1: "Tốc độ và acceleration",
  chart_2: "Brake & throttle",
  chart_3: "Phản hồi steering",
  chart_4: "Sự kiện autonomy",
};

function fallbackSeries(item: ClaimLogSummary) {
  return Object.entries(item.metrics).flatMap(([signal, values]) => {
    const names = ["start", "min", "max", "end"];
    const points = names.map((name) => values[name]).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    return points.length >= 2 ? [{ signal, points }] : [];
  }).slice(0, 6);
}

function MiniMetricChart({ signal, points }: { signal: string; points: number[] }) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = Math.max(max - min, 0.0001);
  const coordinates = points.map((value, index) => `${points.length === 1 ? 50 : index / (points.length - 1) * 100},${38 - ((value - min) / range) * 30}`).join(" ");
  return <article className="fallback-metric-chart"><header><strong>{signal.replaceAll("_", " ")}</strong><span>{points.at(-1)?.toFixed(2)}</span></header><svg viewBox="0 0 100 42" preserveAspectRatio="none" aria-label={`${signal} metric trend`}><defs><linearGradient id={`fill-${signal.replaceAll(/[^a-zA-Z0-9]/g, "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#6366f1" stopOpacity=".28"/><stop offset="1" stopColor="#6366f1" stopOpacity="0"/></linearGradient></defs><polygon points={`0,42 ${coordinates} 100,42`} fill={`url(#fill-${signal.replaceAll(/[^a-zA-Z0-9]/g, "")})`} /><polyline points={coordinates} fill="none" stroke="#4f46e5" strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg><footer><span>Min {min.toFixed(2)}</span><span>Max {max.toFixed(2)}</span></footer></article>;
}

function AssessmentContent({ summary }: { summary: string }) {
  const sections = summary.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  return <div className="assessment-content">{sections.map((section, index) => {
    const lines = section.split("\n").filter(Boolean);
    const tableLines = lines.filter((line) => line.trim().startsWith("|"));
    const proseLines = lines.filter((line) => !line.trim().startsWith("|"));
    const tableRows = tableLines.map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
    const tableHeader = tableRows[0] ?? [];
    const tableBody = tableRows.slice(1).filter((row) => !row.every((cell) => /^:?-{3,}:?$/.test(cell)));
    const title = proseLines.length > 1 && proseLines[0].length < 64 ? proseLines.shift() : index === 0 ? "Đối chiếu timestamp" : `Chi tiết đánh giá ${index + 1}`;
    const displayTitle = title ?? `Chi tiết đánh giá ${index + 1}`;
    return <section key={`${displayTitle}-${index}`}><header><span>{String(index + 1).padStart(2, "0")}</span><strong>{displayTitle.replaceAll("**", "")}</strong></header><div>{proseLines.map((line, lineIndex) => <p key={`${line}-${lineIndex}`}>{line.replaceAll("**", "")}</p>)}{tableHeader.length > 0 && <div className="assessment-data-table"><table><thead><tr>{tableHeader.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{cell}</th>)}</tr></thead><tbody>{tableBody.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${cell}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>}</div></section>;
  })}</div>;
}

export function TelemetryPanel({ summaries, selectedClaimId, hasLog, chartUris }: { summaries: ClaimLogSummary[]; selectedClaimId: string; hasLog: boolean; chartUris: Array<{ id: string; uri: string }> }) {
  const selected = summaries.find((summary) => summary.claim_id === selectedClaimId) ?? summaries[0];
  const fallback = selected ? fallbackSeries(selected) : [];
  return (
    <section className="workspace-panel telemetry-chart-section" aria-labelledby="telemetry-title">
      <div className="workspace-panel-heading"><div><p className="eyebrow">Bằng chứng telemetry / log</p><h2 id="telemetry-title">Trạng thái phương tiện và biểu đồ signal</h2></div><span>{chartUris.length || fallback.length} biểu đồ</span></div>
      {!hasLog && <div className="telemetry-empty"><strong>Xác minh chỉ bằng video</strong><p>Sự cố này không có log telemetry.</p></div>}
      {hasLog && !selected && <div className="telemetry-empty"><span className="state-spinner" /><strong>Đang chuẩn bị biểu đồ telemetry</strong><p>Biểu đồ signal sẽ xuất hiện sau khi căn chỉnh log hoàn tất.</p></div>}
      {hasLog && selected && <>
        <div className="telemetry-chart-context"><div><span className="chart-context-dot" /><div><small>Quan sát đã chọn</small><strong>{selected.claim_id}</strong></div></div><time>{secondsToTimestamp(selected.nearest_timestamp_s ?? selected.claim_timestamp_s ?? 0)}</time><span className={selected.within_tolerance ? "aligned" : "out-of-range"}>{selected.within_tolerance ? "Log đã căn chỉnh" : "Ngoài tolerance"}</span></div>
        {chartUris.length > 0 ? <div className="telemetry-chart-grid">{chartUris.map((chart) => <figure key={chart.id}><div><Image unoptimized width={1000} height={480} src={artifactUrl(chart.uri)} alt={`${chartTitles[chart.id] ?? chart.id} telemetry chart`} /></div><figcaption><strong>{chartTitles[chart.id] ?? chart.id.replace("_", " ")}</strong><span>Được tạo từ log sự cố</span></figcaption></figure>)}</div> : <div className="fallback-chart-grid">{fallback.map((series) => <MiniMetricChart key={series.signal} signal={series.signal} points={series.points} />)}</div>}
        <div className="log-assessment chart-log-assessment"><header><div><span aria-hidden="true">AI</span><div><small>Phân tích bằng chứng</small><strong>Đánh giá bằng chứng log</strong></div></div><span className={selected.within_tolerance ? "assessment-verdict aligned" : "assessment-verdict out-of-range"}>{selected.within_tolerance ? "Bằng chứng đã căn chỉnh" : "Cần rà soát căn chỉnh"}</span></header><AssessmentContent summary={selected.summary} /><footer><span className="assessment-source-dot" />Signal đã phân tích: {selected.available_signals.join(", ") || "Không có signal được đặt tên"}</footer></div>
        {summaries.length > 1 && <div className="other-log-assessments"><strong>Các quan sát đã căn chỉnh khác</strong>{summaries.filter((summary) => summary.claim_id !== selected.claim_id).map((summary) => <article key={summary.claim_id}><header><div><span className="other-assessment-dot" /><b>{summary.claim_id}</b></div><time>{secondsToTimestamp(summary.nearest_timestamp_s ?? summary.claim_timestamp_s ?? 0)}</time></header><AssessmentContent summary={summary.summary} /></article>)}</div>}
      </>}
    </section>
  );
}
