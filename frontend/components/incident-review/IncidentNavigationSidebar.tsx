"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { IncidentSnapshot } from "../../types/incident";
import { incidentStatusLabel } from "../../lib/incidentStatus";

const NavIcon = ({ children }: { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">{children}</svg>
);

export function IncidentNavigationSidebar({ snapshot }: { snapshot: IncidentSnapshot | null }) {
  const pathname = usePathname();
  const pending = snapshot?.status === "awaiting_review";
  const running = snapshot?.status === "queued" || snapshot?.status === "running";
  const reportActive = pathname === "/report";
  return (
    <aside className="incident-navigation-sidebar" aria-label="Incident workspace navigation">
      <div className="incident-nav-main">
        <div className="unit-identity">
          <span className={`unit-status-dot ${running ? "running" : ""}`} aria-hidden="true" />
          <div><strong>IncidentLens</strong><small>Autonomous Unit 04</small></div>
        </div>
        <Link className="new-analysis-link" href="/">
          <span aria-hidden="true">＋</span> New analysis
        </Link>
        <div className="incident-side-links" role="navigation" aria-label="Review sections">
          <Link className={!reportActive ? "active" : ""} href="/processing#engineer-review">
            <NavIcon><path d="m5 12 4 4L19 6M4 3h16v18H4z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" /></NavIcon>
            <span>Review</span>{pending && <b>1</b>}
          </Link>
          <Link className={reportActive ? "active" : ""} href="/report">
            <NavIcon><path d="M6 3h9l3 3v15H6zM9 10h6M9 14h6M9 18h4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></NavIcon>
            <span>Reports</span>
          </Link>
        </div>
      </div>
      <div className="incident-nav-footer">
        <Link href="/#recent-reviews">
          <NavIcon><path d="M4 6h16M4 12h16M4 18h10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></NavIcon>
          <span>Logs &amp; history</span>
        </Link>
        <div className="incident-nav-health"><span /> {snapshot ? incidentStatusLabel(snapshot.status) : "API connected"}</div>
      </div>
    </aside>
  );
}
