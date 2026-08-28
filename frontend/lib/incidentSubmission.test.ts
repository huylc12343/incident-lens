import { describe, expect, it, vi } from "vitest";
import type { IncidentSnapshot } from "../types/incident";
import { createIncidentAndNavigate } from "./incidentSubmission";

const queuedSnapshot = {
  incident_id: "INC/CLIENT 1",
  status: "queued",
  has_log: false,
  video_summary: "",
  artifact_uris: {},
  claims: [],
  claim_log_summaries: [],
  conflict_claim_ids: [],
  auto_reanalysis_count: 0,
  manual_reanalysis_count: 0,
  draft_report: null,
  final_report: null,
  review_audit: [],
  model_activities: [],
  warnings: [],
} satisfies IncidentSnapshot;

describe("createIncidentAndNavigate", () => {
  it("redirects to the incident-specific processing route after create succeeds", async () => {
    const navigate = vi.fn();
    const beforeNavigate = vi.fn();
    const create = vi.fn().mockResolvedValue(queuedSnapshot);

    await createIncidentAndNavigate(
      { incident_id: queuedSnapshot.incident_id },
      { create, beforeNavigate, navigate },
    );

    expect(beforeNavigate).toHaveBeenCalledWith(queuedSnapshot);
    expect(navigate).toHaveBeenCalledWith("/processing/INC%2FCLIENT%201");
  });

  it("does not redirect when create genuinely fails", async () => {
    const navigate = vi.fn();
    const beforeNavigate = vi.fn();
    const create = vi.fn().mockRejectedValue(new Error("create failed"));

    await expect(createIncidentAndNavigate(
      { incident_id: "INC-FAILED" },
      { create, beforeNavigate, navigate },
    )).rejects.toThrow("create failed");

    expect(beforeNavigate).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });
});
