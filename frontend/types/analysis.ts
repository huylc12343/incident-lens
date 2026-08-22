export type PipelineState = "completed" | "active" | "pending";
export interface PipelineStep { label: string; state: PipelineState; }
export interface Observation { id: string; timestamp: string; description: string; evidence: string; }
export interface TelemetryPoint { timestamp: string; speed: number; brake: string; steering: string; recorded?: boolean; }

export interface AnalysisData {
  analysisId: string;
  status: "processing";
  progress: number;
  currentStep: string;
  recordedTimestamp: string;
  analysisWindow: { start: string; end: string };
  observations: Observation[];
  telemetryEvidence: TelemetryPoint[];
}
