"use client";

import Link from "next/link";
import Image from "next/image";
import { uiText as text } from "../lib/ui-copy";
const Icon = ({ children }: { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    {children}
  </svg>
);

export function Header({
  active = "home",
  processing = false,
  onQuickGuide,
}: {
  active?: "home" | "history" | "settings";
  processing?: boolean;
  onQuickGuide?: () => void;
}) {
  const openQuickGuide = () => {
    if (onQuickGuide) {
      onQuickGuide();
      return;
    }
    window.location.assign("/#upload-evidence");
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
          <Link className={active === "home" ? "active" : ""} href="/">
            {text("Dashboard", "Tổng quan")}
          </Link>
          <Link
            className={active === "history" ? "active" : ""}
            href="/#recent-reviews"
          >
            {text("History", "Lịch sử")}
          </Link>
          <a className={active === "settings" ? "active" : ""} href="#settings">
            {text("Settings", "Cài đặt")}
          </a>
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
          <button className="quick-guide-button" type="button" onClick={openQuickGuide} aria-label={text("Quick guide", "Hướng dẫn nhanh")}>
            ?
          </button>
          <span className="avatar" aria-label={text("User account", "Tài khoản người dùng")}>
            PT
          </span>
        </div>
      </div>
    </header>
  );
}
