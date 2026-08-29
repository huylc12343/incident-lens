import type { Claim } from "../types/incident";

export function orderClaimsByTimeline(claims: Claim[]): Claim[] {
  return [...claims].sort((left, right) => {
    const leftTimestamp = typeof left.timestamp_s === "number" ? left.timestamp_s : Number.POSITIVE_INFINITY;
    const rightTimestamp = typeof right.timestamp_s === "number" ? right.timestamp_s : Number.POSITIVE_INFINITY;
    return leftTimestamp - rightTimestamp || left.claim_id.localeCompare(right.claim_id);
  });
}
