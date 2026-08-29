import { describe, expect, it } from "vitest";
import { orderClaimsByTimeline } from "./claimOrdering";
import type { Claim } from "../types/incident";

const claim = (claim_id: string, timestamp_s: number | null): Claim => ({
  claim_id,
  timestamp_s,
  text: claim_id,
  evidence: [],
  verification_status: "unverified",
});

describe("orderClaimsByTimeline", () => {
  it("orders claims chronologically without mutating the backend order", () => {
    const claims = [claim("claim_1", 10.8), claim("claim_2", 9), claim("claim_3", 11.5)];

    expect(orderClaimsByTimeline(claims).map((item) => item.claim_id)).toEqual([
      "claim_2",
      "claim_1",
      "claim_3",
    ]);
    expect(claims.map((item) => item.claim_id)).toEqual(["claim_1", "claim_2", "claim_3"]);
  });

  it("places claims without timestamps after timed claims", () => {
    const claims = [claim("claim_1", null), claim("claim_2", 9)];
    expect(orderClaimsByTimeline(claims).map((item) => item.claim_id)).toEqual(["claim_2", "claim_1"]);
  });
});
