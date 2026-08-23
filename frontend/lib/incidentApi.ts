import type { IncidentCreateRequest, IncidentSnapshot, IncidentUploadResponse, ReviewPayload } from "../types/incident";

// Call FastAPI directly in local development. Incident creation can take
// several minutes and may outlive a Next.js rewrite proxy request.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const INCIDENT_API_PATH = "/api/v1/incidents";
export const INCIDENT_POLL_INTERVAL_MS = 1500;
export const INCIDENT_RETRY_INTERVAL_MS = 3000;

export function isIncidentActive(status?: IncidentSnapshot["status"]) {
  return status === "queued" || status === "running";
}

export function formatIncidentError(errorCode?: string | null, errorMessage?: string | null) {
  if (errorCode && errorMessage) return `${errorCode}: ${errorMessage}`;
  return errorMessage || errorCode || "Incident processing failed.";
}

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => `${item.loc?.join(".") ?? "request"}: ${item.msg}`).join("; ")
      : detail?.message ?? detail ?? `API request failed (${response.status})`;
    throw new Error(String(message));
  }
  return data as T;
}

export async function uploadIncident(video: File, log?: File) {
  const body = new FormData();
  body.append("video", video);
  if (log) body.append("log", log);
  return responseJson<IncidentUploadResponse>(
    await fetch(`${API_URL}${INCIDENT_API_PATH}/uploads`, { method: "POST", body }),
  );
}

export async function createIncident(payload: IncidentCreateRequest) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}${INCIDENT_API_PATH}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }));
}

export async function getIncident(id: string) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}${INCIDENT_API_PATH}/${encodeURIComponent(id)}`, { cache: "no-store" }));
}

export async function listIncidents() {
  return responseJson<{ incident_ids: string[]; count: number }>(
    await fetch(`${API_URL}${INCIDENT_API_PATH}`, { cache: "no-store" }),
  );
}

export async function reviewIncident(id: string, payload: ReviewPayload) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}${INCIDENT_API_PATH}/${encodeURIComponent(id)}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }));
}

export function artifactUrl(uri?: string) {
  if (!uri) return "";
  if (/^https?:\/\//i.test(uri)) return uri;
  const normalized = uri.replace(/\\/g, "/");
  const marker = "/artifacts/";
  const index = normalized.toLowerCase().lastIndexOf(marker);
  return index >= 0 ? `${API_URL}/artifacts/${normalized.slice(index + marker.length)}` : uri;
}
