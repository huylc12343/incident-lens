import type { IncidentSnapshot } from "../types/incident";

export function ProcessingPipeline({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const activities = snapshot?.model_activities ?? [];
  const completed = activities.filter((item) => item.status === "completed").length;
  const terminal = snapshot && ["awaiting_review", "approved", "not_incident", "failed"].includes(snapshot.status);
  const progress = terminal ? 100 : activities.length ? Math.max(20, Math.round(completed / activities.length * 100)) : 10;
  const steps: Array<{ label: string; done: boolean; active?: boolean; failed?: boolean }> = [
    { label: "Loading Video", done: true },
    { label: snapshot?.has_log ? "Parsing Telemetry" : "Telemetry not provided", done: Boolean(snapshot) },
    ...activities.map((item) => ({ label: item.description || `${item.step}: ${item.model}`, done: item.status === "completed", failed: item.status === "failed", active: item.status === "running" })),
    { label: "Preparing Structured Summary", done: Boolean(snapshot?.draft_report), active: snapshot?.status === "running" && activities.length > 0 },
  ];
  return <section className="processing-panel pipeline-panel">
    <div className="panel-heading"><p className="eyebrow">Evidence Analysis</p><h2>Overall Progress</h2></div>
    <div className="progress-summary"><strong>{progress}%</strong><span>Workflow status<br /><b>{snapshot?.status ?? "Starting"}</b></span></div>
    <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
    <ol className="pipeline">{steps.map((step, index) => (
      <li className={step.failed ? "failed" : step.done ? "completed" : step.active ? "active" : "pending"} key={`${step.label}-${index}`}>
        <span className="step-symbol">{step.failed ? "✕" : step.done ? "✓" : step.active ? "●" : "○"}</span><span>{step.label}</span>{step.active && <small>In progress</small>}
      </li>
    ))}</ol>
  </section>;
}
