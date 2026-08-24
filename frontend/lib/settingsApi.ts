import { API_URL } from "./incidentApi";

export type AiSettings = {
  openai_api_key_configured: boolean;
  dashscope_api_key_configured: boolean;
  langsmith_api_key_configured: boolean;
  model_name: string;
  qwen_vlm_model_name: string;
  verification_model_name: string;
  report_model_name: string;
  langsmith_project: string;
  langsmith_tracing: boolean;
  restart_required: boolean;
};

export type AiSettingsUpdate = Pick<AiSettings, "model_name" | "qwen_vlm_model_name" | "verification_model_name" | "report_model_name" | "langsmith_project" | "langsmith_tracing"> & {
  openai_api_key?: string;
  dashscope_api_key?: string;
  langsmith_api_key?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/v1/settings${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail?.message ?? "Không thể cập nhật cấu hình AI.");
  return body as T;
}

export function getAiSettings() { return request<AiSettings>("/ai"); }
export function saveAiSettings(update: AiSettingsUpdate) {
  return request<AiSettings>("/ai", { method: "PUT", body: JSON.stringify(update) });
}
