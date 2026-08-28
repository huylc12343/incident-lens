import type { IncidentSnapshot } from "../types/incident";
import { createIncident } from "./incidentApi";
import { processingPath } from "./incidentSession";

type SubmissionDependencies = {
  create?: typeof createIncident;
  beforeNavigate?: (snapshot: IncidentSnapshot) => void;
  navigate: (path: string) => void;
};

export async function createIncidentAndNavigate(
  payload: Record<string, unknown>,
  { create = createIncident, beforeNavigate, navigate }: SubmissionDependencies,
) {
  const snapshot = await create(payload);
  beforeNavigate?.(snapshot);
  navigate(processingPath(snapshot.incident_id));
  return snapshot;
}
