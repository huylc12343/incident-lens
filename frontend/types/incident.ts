export type IncidentStatus =
  | "queued" | "running" | "awaiting_review" | "approved"
  | "not_incident" | "failed" | "cancelled";

export type Evidence = { evidence_id: string; timestamp_s: number };
export type Claim = {
  claim_id: string;
  text: string;
  timestamp_s: number;
  evidence: Evidence[];
  verification_status: string;
};
export type ModelActivity = {
  activity_id: string;
  step: string;
  description: string;
  provider: string;
  model: string;
  status: "running" | "completed" | "failed" | "skipped";
  error_code?: string | null;
};
export type ReviewAudit = {
  action: string;
  reviewer: string;
  reason?: string | null;
  feedback?: string | null;
  target_claim_ids: string[];
};
export type ClaimLogSummary = {
  claim_id: string;
  claim_timestamp_s?: number | null;
  nearest_timestamp_s?: number | null;
  within_tolerance: boolean;
  sample_count: number;
  available_signals: string[];
  metrics: Record<string, Record<string, string | number | boolean | null>>;
  summary: string;
};
export type DraftReport = {
  summary: string;
  timeline?: { narrative?: string; events?: Array<{ timestamp_s: number; description: string; evidence_ids: string[] }> };
  video_observations?: { narrative?: string; observations?: unknown[] };
  log_findings?: { narrative?: string };
  alignment?: { narrative?: string };
  hypothesized_causes?: string;
  evidence_and_warnings?: { warnings?: string[] };
  review_status?: string;
  [key: string]: unknown;
};
export type IncidentSnapshot = {
  incident_id: string;
  status: IncidentStatus;
  has_log: boolean;
  video_summary: string;
  artifact_uris: Record<string, string>;
  claims: Claim[];
  claim_log_summaries: ClaimLogSummary[];
  conflict_claim_ids: string[];
  auto_reanalysis_count: number;
  manual_reanalysis_count: number;
  draft_report: DraftReport | null;
  final_report: DraftReport | null;
  review_audit: ReviewAudit[];
  model_activities: ModelActivity[];
  warnings: string[];
  error_code?: string | null;
  error_message?: string | null;
};
export type ReviewPayload = {
  action: "approve" | "edit" | "reanalyze" | "not_incident";
  reviewer: string;
  reason?: string;
  feedback?: string;
  target_claim_ids?: string[];
  edits?: Record<string, string>;
};
