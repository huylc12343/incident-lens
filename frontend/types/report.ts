export type ReportObservationStatus = "Accepted" | "Edited" | "Rejected";
export interface ReportObservation { id: string; timestamp: string; observation: string; source: "Video" | "Telemetry"; reference: string; status: ReportObservationStatus; }
export interface ReviewedReport { reviewId: string; recordedDisengagementTimestamp: string; reviewStatus: "approved" | "pending_review" | "rejected"; reviewedBy: string; reviewedAt: string; reviewDuration: string; edited: boolean; observations: ReportObservation[]; }
