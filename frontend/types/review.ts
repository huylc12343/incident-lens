export type ReviewStatus = "Processing" | "Pending Review" | "Approved" | "Rejected";

export interface Review {
  id: string;
  timestamp: string;
  date: string;
  status: ReviewStatus;
  action: "Review" | "View";
}
