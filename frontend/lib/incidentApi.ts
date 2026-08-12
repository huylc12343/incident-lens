import type { IncidentSnapshot, ReviewPayload } from "../types/incident";

// Use the Next.js same-origin proxy by default. This also works when the UI is
// opened from another device, where `localhost` would refer to that device.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/backend").replace(/\/$/, "");

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
  return responseJson<{ video_uri: string; log_uri: string | null }>(
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
