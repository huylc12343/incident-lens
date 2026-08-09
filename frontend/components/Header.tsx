import Link from "next/link";
const Icon = ({ children }: { children: React.ReactNode }) => <svg viewBox="0 0 24 24" aria-hidden="true">{children}</svg>;

export function Header({ active = "home", processing = false }: { active?: "home" | "history" | "settings"; processing?: boolean }) {
  return <header className="topbar"><div className="nav-inner">
    <Link className="brand" href="/" aria-label="VLens home"><span className="brand-mark"><span /></span><span><strong>VLens</strong><small>Disengagement Review Assistant</small></span></Link>
    <nav aria-label="Main navigation"><Link className={active === "home" ? "active" : ""} href="/">Home</Link><Link className={active === "history" ? "active" : ""} href="/#recent-reviews">History</Link><a className={active === "settings" ? "active" : ""} href="#settings">Settings</a></nav>
    <div className="nav-actions">{processing && <span className="header-status">Processing</span>}<button className="icon-button" aria-label="Notifications"><Icon><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></Icon></button><button className="icon-button" aria-label="Help"><Icon><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M9.7 9a2.5 2.5 0 1 1 4.2 1.8c-1.2 1.05-1.9 1.5-1.9 3.2M12 17h.01" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></Icon></button><span className="avatar" aria-label="User account">PT</span></div>
  </div></header>;
}
