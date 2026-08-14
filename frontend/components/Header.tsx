import Link from "next/link";
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
  return (
    <header className="topbar">
      <div className="nav-inner">
        <Link className="brand" href="/" aria-label="IncidentLens home">
          <span className="brand-mark incident-lens-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" fill="none" stroke="currentColor" strokeWidth="1.8"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg></span>
          <span>
            <strong>IncidentLens</strong>
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
          <button className="icon-button" aria-label={text("Help", "Trợ giúp")}>
            <Icon>
              <circle
                cx="12"
                cy="12"
                r="9"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              />
              <path
                d="M9.7 9a2.5 2.5 0 1 1 4.2 1.8c-1.2 1.05-1.9 1.5-1.9 3.2M12 17h.01"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </Icon>
          </button>
          <span className="avatar" aria-label={text("User account", "Tài khoản người dùng")}>
            PT
          </span>
        </div>
      </div>
    </header>
  );
}
