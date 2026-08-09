import { ReviewStatus } from "../types/review";
export function StatusBadge({ status }: { status: ReviewStatus }) { return <span className={`status ${status.toLowerCase().replace(" ", "-")}`}>{status}</span>; }
