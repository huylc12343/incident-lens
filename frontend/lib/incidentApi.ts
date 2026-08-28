import type { IncidentSnapshot, ReviewPayload } from "../types/incident";

// Call FastAPI directly in local development. Incident creation can take
// several minutes and may outlive a Next.js rewrite proxy request.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const ERROR_BODY_LIMIT = 2_000;

type ApiErrorDetail = {
  code?: string;
  message?: string;
  request_id?: string;
  stage?: string;
};

class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly responseWasStructured = false,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

function requestId() {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function responsePreview(body: string, contentType: string) {
  if (!body.trim()) return "(response body trống)";
  const normalized = contentType.includes("text/html")
    ? body.replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ")
    : body;
  const compact = normalized.replace(/\s+/g, " ").trim();
  return compact.length > ERROR_BODY_LIMIT ? `${compact.slice(0, ERROR_BODY_LIMIT)}…` : compact;
}

async function apiFetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${path}`;
  const method = init.method ?? "GET";
  const clientRequestId = requestId();
  const startedAt = performance.now();
  let response: Response;

  try {
    response = await fetch(url, {
      ...init,
      headers: { "X-Request-ID": clientRequestId, ...init.headers },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    const duration = Math.round(performance.now() - startedAt);
    const reason = cause instanceof Error ? cause.message : String(cause);
    throw new ApiRequestError([
      "Không nhận được phản hồi từ API.",
      `Request: ${method} ${path}`,
      `Request ID: ${clientRequestId}`,
      `Thời gian: ${duration} ms`,
      `Lỗi mạng: ${reason}`,
    ].join("\n"));
  }

  const duration = Math.round(performance.now() - startedAt);
  const contentType = response.headers.get("content-type") ?? "không xác định";
  const serverRequestId = response.headers.get("x-request-id") ?? clientRequestId;
  const body = await response.text();
  let data: unknown = null;
  if (body) {
    try { data = JSON.parse(body); } catch { /* Proxy có thể trả HTML hoặc plain text. */ }
  }

  if (!response.ok) {
    const root = data && typeof data === "object" ? data as { detail?: unknown } : null;
    const detail = root?.detail;
    const structured = detail && typeof detail === "object" && !Array.isArray(detail) ? detail as ApiErrorDetail : null;
    const validationMessage = Array.isArray(detail)
      ? detail.map((item) => `${item?.loc?.join(".") ?? "request"}: ${item?.msg ?? "invalid value"}`).join("; ")
      : null;
    const message = structured?.message ?? validationMessage ?? (typeof detail === "string" ? detail : null)
      ?? `API trả về ${response.status} ${response.statusText || "Unknown Error"}`;
    const diagnostics = [
      message,
      `Request: ${method} ${path}`,
      `Status: ${response.status} ${response.statusText || "Unknown Error"}`,
      `Request ID: ${structured?.request_id ?? serverRequestId}`,
      `Thời gian: ${duration} ms`,
      `Content-Type: ${contentType}`,
    ];
    if (structured?.code) diagnostics.push(`Mã lỗi: ${structured.code}`);
    if (structured?.stage) diagnostics.push(`Giai đoạn: ${structured.stage}`);
    if (!structured?.message && !validationMessage) diagnostics.push(`Response: ${responsePreview(body, contentType)}`);
    throw new ApiRequestError(diagnostics.join("\n"), response.status, Boolean(structured || validationMessage));
  }

  if (data === null) {
    throw new ApiRequestError([
      "API trả về dữ liệu không phải JSON.",
      `Request: ${method} ${path}`,
      `Status: ${response.status} ${response.statusText}`,
      `Request ID: ${serverRequestId}`,
      `Content-Type: ${contentType}`,
      `Response: ${responsePreview(body, contentType)}`,
    ].join("\n"), response.status);
  }
  return data as T;
}

export async function uploadIncident(video: File, log?: File, groundTruth?: File, signal?: AbortSignal) {
  const body = new FormData();
  body.append("video", video);
  if (log) body.append("log", log);
  if (groundTruth) body.append("ground_truth", groundTruth);
  return apiFetchJson<{ video_uri: string; log_uri: string | null; ground_truth_uri: string | null }>(
    "/api/v1/incidents/uploads", { method: "POST", body, signal },
  );
}

export async function createIncident(payload: Record<string, unknown>, signal?: AbortSignal) {
  try {
    return await apiFetchJson<IncidentSnapshot>("/api/v1/incidents", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    const incidentId = typeof payload.incident_id === "string" ? payload.incident_id.trim() : "";
    const recoverable = cause instanceof ApiRequestError
      && (!cause.status || (cause.status >= 500 && !cause.responseWasStructured));
    if (!incidentId || !recoverable) throw cause;

    // Next.js may close its rewrite request after ~30 seconds while FastAPI
    // continues the workflow. Recover the registered incident instead of
    // showing a false 500 error to the user.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (signal?.aborted) throw new DOMException("The operation was aborted.", "AbortError");
      try {
        return await getIncident(incidentId, signal);
      } catch (recoveryError) {
        const notFound = recoveryError instanceof ApiRequestError && recoveryError.status === 404;
        if (!notFound || attempt === 3) throw cause;
        await waitForRecovery(1_000, signal);
      }
    }
    throw cause;
  }
}

function waitForRecovery(milliseconds: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("The operation was aborted.", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function getIncident(id: string, signal?: AbortSignal) {
  return apiFetchJson<IncidentSnapshot>(`/api/v1/incidents/${encodeURIComponent(id)}`, { cache: "no-store", signal });
}

export async function listIncidents() {
  return apiFetchJson<{ incident_ids: string[]; count: number }>("/api/v1/incidents", { cache: "no-store" });
}

export async function deleteIncident(id: string) {
  return apiFetchJson<{ incident_id: string; deleted: boolean }>(
    `/api/v1/incidents/${encodeURIComponent(id)}`, { method: "DELETE" },
  );
}

export async function reviewIncident(id: string, payload: ReviewPayload) {
  return apiFetchJson<IncidentSnapshot>(`/api/v1/incidents/${encodeURIComponent(id)}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

export function artifactUrl(uri?: string) {
  if (!uri) return "";
  if (/^https?:\/\//i.test(uri)) return uri;
  const normalized = uri.replace(/\\/g, "/");
  const marker = "/artifacts/";
  const index = normalized.toLowerCase().lastIndexOf(marker);
  return index >= 0 ? `${API_URL}/artifacts/${normalized.slice(index + marker.length)}` : uri;
}
