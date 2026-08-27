export type IncidentStatus =
  | "queued" | "running" | "awaiting_review" | "approved"
  | "not_incident" | "failed" | "cancelled";

export type Evidence = { evidence_id: string; timestamp_s: number };
export type Claim = {
  claim_id: string;
  text: string;
  timestamp_s: number | null;
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
  operation?: string;
  started_at?: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number; cached_tokens: number; reasoning_tokens: number } | null;
  error_code?: string | null;
  metadata?: Record<string, unknown>;
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
  timestamp_distance_s?: number | null;
  within_tolerance: boolean;
  sample_start_s?: number | null;
  sample_end_s?: number | null;
  sample_count: number;
  available_signals: string[];
  metrics: Record<string, Record<string, string | number | boolean | null>>;
  evidence?: Array<{ evidence_id: string; timestamp_s: number; camera_frame?: string | number | null }>;
  allowed_evidence_ids?: string[];
  summary: string;
};
export type ClaimVerification = {
  claim_id: string;
  status: string;
  reason: string;
  evidence_ids: string[];
};
export type VerificationResult = { has_accident?: boolean | null; results: ClaimVerification[] };
export type LogEvidenceSummary = {
  summary: string;
  metrics: Record<string, string | number | boolean | null>;
  events: Array<Record<string, unknown>>;
  evidence_ids: string[];
  warnings: string[];
  errors: string[];
};
export type DraftReport = {
  general_information?: { incident_id: string; video_uri: string; has_log: boolean; log_uri?: string | null };
  type_of_accident?: string;
  incident_window?: { t_start: number; t0: number; t_end: number };
  summary: string;
  timeline?: { narrative?: string; events?: Array<{ timestamp_s: number; description: string; evidence_ids: string[] }> };
  video_observations?: { narrative?: string; observations?: Array<{ observation_id?: string; timestamp_s?: number; description?: string; evidence_ids?: string[] }> };
  log_findings?: { narrative?: string; claim_summaries?: ClaimLogSummary[]; summary?: LogEvidenceSummary | null };
  alignment?: { narrative?: string; verification?: VerificationResult | null };
  hypothesized_causes?: string;
  evidence_and_warnings?: { warnings?: string[]; evidence?: Array<{ evidence_id?: string; timestamp_s?: number; description?: string }>; artifact_uris?: Record<string, string> };
  review_status?: string;
  [key: string]: unknown;
};
export type GroundTruth = {
  source: "CARLA Incident" | "Human annotation" | "Reviewer verified";
  incident_type?: string | null;
  severity?: string | null;
  timeline?: { t_start?: number | null; t0?: number | null; t_end?: number | null } | null;
};
export type AiGroundTruthEvaluation = {
  overall_accuracy?: number | null;
  incident_type_match?: boolean | null;
  severity_match?: boolean | null;
  t0_delta_s?: number | null;
  timeline_iou?: number | null;
  prediction?: { incident_type?: string | null; severity?: string | null; timeline?: { t_start?: number | null; t0?: number | null; t_end?: number | null } | null } | null;
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
  progress?: { stage: string; message: string; started_at: string } | null;
  warnings: string[];
  ground_truth?: GroundTruth | null;
  ai_evaluation?: AiGroundTruthEvaluation | null;
  error_code?: string | null;
  error_message?: string | null;
  stored_at?: string | null;
};
export type IncidentUploadResponse = { video_uri: string; log_uri: string | null; ground_truth_uri: string | null };
export type IncidentCreateRequest = {
  incident_id: string;
  video_uri: string;
  log_uri?: string | null;
  analysis_prompt: string;
  metadata?: Record<string, unknown>;
};
export type ReviewPayload = {
  action: "approve" | "edit" | "reanalyze" | "not_incident";
  reviewer: string;
  reason?: string;
  feedback?: string;
  target_claim_ids?: string[];
  edits?: {
    summary?: string;
    timeline?: string;
    video_observations?: string;
    log_findings?: string;
    alignment?: string;
    hypothesized_causes?: string;
  };
};
