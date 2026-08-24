"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearDemoSession } from "../lib/auth";
import { getAiSettings, saveAiSettings, type AiSettings } from "../lib/settingsApi";
import { uiText as text } from "../lib/ui-copy";
const Icon = ({ children }: { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    {children}
  </svg>
);

export function Header({
  processing = false,
}: {
  processing?: boolean;
}) {
  const router = useRouter();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isLightOptionDark, setIsLightOptionDark] = useState(false);
  const [isAiSettingsOpen, setIsAiSettingsOpen] = useState(false);
  const [aiSettings, setAiSettings] = useState<AiSettings | null>(null);
  const [openAiKey, setOpenAiKey] = useState("");
  const [dashscopeKey, setDashscopeKey] = useState("");
  const [langsmithKey, setLangsmithKey] = useState("");
  const [settingsMessage, setSettingsMessage] = useState("");
  const [featureMessage, setFeatureMessage] = useState("");
  const [isSavingSettings, setIsSavingSettings] = useState(false);

  useEffect(() => {
    if (!isSettingsOpen) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsSettingsOpen(false);
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isSettingsOpen]);

  const handleLogout = () => {
    clearDemoSession();
    setIsSettingsOpen(false);
    router.replace("/login");
  };

  const showComingSoon = () => {
    setFeatureMessage("Tính năng sắp được triển khai.");
    window.setTimeout(() => setFeatureMessage(""), 2800);
  };

  const loadAiSettings = async () => {
    setSettingsMessage("");
    try { setAiSettings(await getAiSettings()); }
    catch (error) { setSettingsMessage(error instanceof Error ? error.message : "Không thể tải cấu hình AI."); }
  };

  const saveSettings = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!aiSettings) return;
    setIsSavingSettings(true);
    setSettingsMessage("");
    try {
      await saveAiSettings({
        model_name: aiSettings.model_name,
        qwen_vlm_model_name: aiSettings.qwen_vlm_model_name,
        verification_model_name: aiSettings.verification_model_name,
        report_model_name: aiSettings.report_model_name,
        langsmith_project: aiSettings.langsmith_project,
        langsmith_tracing: aiSettings.langsmith_tracing,
        openai_api_key: openAiKey || undefined,
        dashscope_api_key: dashscopeKey || undefined,
        langsmith_api_key: langsmithKey || undefined,
      });
      setOpenAiKey(""); setDashscopeKey(""); setLangsmithKey("");
      setSettingsMessage("Đã lưu. Khởi động lại backend để áp dụng model và API key mới.");
    } catch (error) { setSettingsMessage(error instanceof Error ? error.message : "Không thể lưu cấu hình AI."); }
    finally { setIsSavingSettings(false); }
  };

  return (
    <header className="topbar">
      <div className="nav-inner">
        <Link className="brand" href="/" aria-label="VLens home">
          <span className="brand-mark"><Image src="/images/logo.png" alt="VLens" width={34} height={34} priority /></span>
          <span>
            <strong>VLens</strong>
            <small>{text("Forensic Review Workspace", "Không gian rà soát sự cố")}</small>
          </span>
        </Link>
        <nav aria-label={text("Main navigation", "Điều hướng chính")}>
        </nav>
        <div className="nav-actions">
          {processing && <span className="header-status">{text("Incident Review", "Rà soát sự cố")}</span>}
          <button className="icon-button notification-button" type="button" onClick={showComingSoon} aria-label={text("Notifications", "Thông báo")}>
            <Icon>
              <path
                d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </Icon>
            <span className="notification-dot" />
          </button>
          <button
            className="settings-trigger-button"
            type="button"
            onClick={() => setIsSettingsOpen(true)}
            aria-label={text("Settings", "Cài đặt")}
          >
            <Image src="/images/settings.png" alt="" width={22} height={22} />
          </button>
          <span className="avatar" aria-label={text("User account", "Tài khoản người dùng")}>
            PT
          </span>
        </div>
      </div>
      {isSettingsOpen && (
        <div
          className="settings-modal-backdrop"
          role="presentation"
          onMouseDown={() => setIsSettingsOpen(false)}
        >
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-modal-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="settings-modal-header">
              <h2 id="settings-modal-title">{text("Settings", "Cài đặt")}</h2>
              <button
                className="settings-modal-close"
                type="button"
                onClick={() => setIsSettingsOpen(false)}
                aria-label={text("Close settings", "Đóng cài đặt")}
              >
                <Image src="/images/cancel.png" alt="" width={27} height={27} />
              </button>
            </div>
            <div className="settings-modal-options">
              <button className="settings-ai-option" type="button" onClick={() => setIsAiSettingsOpen((current) => !current)}>
                {text("AI configuration", "Cấu hình AI")}
              </button>
              {isAiSettingsOpen && (
                <form className="ai-settings-form" onSubmit={saveSettings}>
                  <p>API key chỉ được gửi tới backend để lưu trong Docker volume; không hiển thị lại sau khi lưu.</p>
                  {!aiSettings ? (
                    <button type="button" onClick={loadAiSettings}>Tải cấu hình</button>
                  ) : (
                    <>
                      <label>OpenAI API key <small>{aiSettings.openai_api_key_configured ? "Đã cấu hình" : "Chưa cấu hình"}</small><input type="password" value={openAiKey} onChange={(event) => setOpenAiKey(event.target.value)} placeholder="Giữ nguyên nếu để trống" autoComplete="new-password" /></label>
                      <label>DashScope API key <small>{aiSettings.dashscope_api_key_configured ? "Đã cấu hình" : "Chưa cấu hình"}</small><input type="password" value={dashscopeKey} onChange={(event) => setDashscopeKey(event.target.value)} placeholder="Giữ nguyên nếu để trống" autoComplete="new-password" /></label>
                      <label>LangSmith API key <small>{aiSettings.langsmith_api_key_configured ? "Đã cấu hình" : "Chưa cấu hình"}</small><input type="password" value={langsmithKey} onChange={(event) => setLangsmithKey(event.target.value)} placeholder="Tuỳ chọn — chỉ dùng tracing" autoComplete="new-password" /></label>
                      <label>Qwen VLM (phân tích video)<select value={aiSettings.qwen_vlm_model_name} onChange={(event) => setAiSettings({ ...aiSettings, qwen_vlm_model_name: event.target.value })}><option value="qwen3-vl-flash">qwen3-vl-flash</option><option value="qwen3-vl-plus">qwen3-vl-plus</option></select></label>
                      <label>OpenAI LLM (verification)<select value={aiSettings.verification_model_name} onChange={(event) => setAiSettings({ ...aiSettings, verification_model_name: event.target.value })}><option value="gpt-4o-mini">gpt-4o-mini</option><option value="gpt-4.1-mini">gpt-4.1-mini</option><option value="gpt-4o">gpt-4o</option><option value="gpt-5-mini">gpt-5-mini</option></select></label>
                      <label>OpenAI LLM (report)<select value={aiSettings.report_model_name} onChange={(event) => setAiSettings({ ...aiSettings, report_model_name: event.target.value })}><option value="gpt-4o-mini">gpt-4o-mini</option><option value="gpt-4.1-mini">gpt-4.1-mini</option><option value="gpt-4o">gpt-4o</option><option value="gpt-5-mini">gpt-5-mini</option></select></label>
                      <label>General OpenAI model<input value={aiSettings.model_name} onChange={(event) => setAiSettings({ ...aiSettings, model_name: event.target.value })} /></label>
                      <label>LangSmith project<input value={aiSettings.langsmith_project} onChange={(event) => setAiSettings({ ...aiSettings, langsmith_project: event.target.value })} /></label>
                      <label className="ai-settings-checkbox"><input type="checkbox" checked={aiSettings.langsmith_tracing} onChange={(event) => setAiSettings({ ...aiSettings, langsmith_tracing: event.target.checked })} /> Bật LangSmith tracing</label>
                      <button type="submit" disabled={isSavingSettings}>{isSavingSettings ? "Đang lưu…" : "Lưu cấu hình AI"}</button>
                    </>
                  )}
                  {settingsMessage && <p className="ai-settings-message" role="status">{settingsMessage}</p>}
                </form>
              )}
              <button className="settings-support-option" type="button" onClick={showComingSoon}>{text("Support", "Hỗ trợ")}</button>
              <button className="settings-history-option" type="button" onClick={showComingSoon}>{text("History", "Lịch sử")}</button>
              <button
                className={`settings-light-option${isLightOptionDark ? " is-black" : ""}`}
                type="button"
                aria-pressed={isLightOptionDark}
                onClick={() => { setIsLightOptionDark((current) => !current); showComingSoon(); }}
              >
                {text("Light", "Ánh sáng")}
              </button>
              <button className="settings-logout-option" type="button" onClick={handleLogout}>{text("Log out", "Đăng xuất")}</button>
            </div>
          </section>
        </div>
      )}
      {featureMessage && <div className="feature-coming-soon" role="status" aria-live="polite">{featureMessage}</div>}
    </header>
  );
}
