import { PipelineStep } from "../types/analysis";
const steps: PipelineStep[] = [
  { label: "Loading Video", state: "completed" }, { label: "Parsing Telemetry", state: "completed" },
  { label: "Extracting Event Window", state: "completed" }, { label: "Analyzing Visual Evidence", state: "active" },
  { label: "Aligning Telemetry Evidence", state: "pending" }, { label: "Preparing Structured Summary", state: "pending" },
];
export function ProcessingPipeline() { return <section className="processing-panel pipeline-panel"><div className="panel-heading"><p className="eyebrow">Evidence Analysis</p><h2>Overall Progress</h2></div><div className="progress-summary"><strong>55%</strong><span>Estimated remaining time<br /><b>1–2 minutes</b></span></div><div className="progress-track"><span style={{ width: "55%" }} /></div><ol className="pipeline">{steps.map((step) => <li className={step.state} key={step.label}><span className="step-symbol">{step.state === "completed" ? "✓" : step.state === "active" ? "●" : "○"}</span><span>{step.label}</span>{step.state === "active" && <small>In progress</small>}</li>)}</ol></section>; }
