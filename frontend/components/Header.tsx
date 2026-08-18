"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { uiText as text } from "../lib/ui-copy";
const Icon = ({ children }: { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    {children}
  </svg>
);

export function Header({
  active = "home",
  processing = false,
}: {
  active?: "home" | "history" | "settings";
  processing?: boolean;
}) {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isLightOptionDark, setIsLightOptionDark] = useState(false);

  useEffect(() => {
    if (!isSettingsOpen) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsSettingsOpen(false);
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isSettingsOpen]);

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
          <button className="icon-button notification-button" aria-label={text("Notifications", "Thông báo")}>
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
              <button className="settings-support-option" type="button">{text("Support", "Hỗ trợ")}</button>
              <button className="settings-history-option" type="button">{text("History", "Lịch sử")}</button>
              <button
                className={`settings-light-option${isLightOptionDark ? " is-black" : ""}`}
                type="button"
                aria-pressed={isLightOptionDark}
                onClick={() => setIsLightOptionDark((current) => !current)}
              >
                {text("Light", "Ánh sáng")}
              </button>
              <button className="settings-logout-option" type="button">{text("Log out", "Đăng xuất")}</button>
            </div>
          </section>
        </div>
      )}
    </header>
  );
}
