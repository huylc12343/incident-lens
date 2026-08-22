import type { IncidentSnapshot, ReviewPayload } from "../types/incident";

// Call FastAPI directly in local development. Incident creation can take
// several minutes and may outlive a Next.js rewrite proxy request.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

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

export async function uploadIncident(video: File, log?: File, groundTruth?: File) {
  const body = new FormData();
  body.append("video", video);
  if (log) body.append("log", log);
  if (groundTruth) body.append("ground_truth", groundTruth);
  return responseJson<{ video_uri: string; log_uri: string | null; ground_truth_uri: string | null }>(
    await fetch(`${API_URL}/api/v1/incidents/uploads`, { method: "POST", body }),
  );
}

export async function createIncident(payload: Record<string, unknown>) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}/api/v1/incidents`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }));
}

export async function getIncident(id: string) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}/api/v1/incidents/${encodeURIComponent(id)}`, { cache: "no-store" }));
}

export async function listIncidents() {
  return responseJson<{ incident_ids: string[]; count: number }>(
    await fetch(`${API_URL}/api/v1/incidents`, { cache: "no-store" }),
  );
}

export async function reviewIncident(id: string, payload: ReviewPayload) {
  return responseJson<IncidentSnapshot>(await fetch(`${API_URL}/api/v1/incidents/${encodeURIComponent(id)}/review`, {
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
