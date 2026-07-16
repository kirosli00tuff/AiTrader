import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/paper", label: "Paper", ico: "▦" },
  { to: "/live", label: "Live", ico: "◆" },
  { to: "/controls", label: "Controls", ico: "▤" },
  // Discovery views, read-only. Grouped after Controls because they are where
  // the operator reads what the funnel found, not where anything is changed.
  { to: "/discovery", label: "Discovery", ico: "▽" },
  { to: "/watchlist", label: "Watchlist", ico: "☰" },
  { to: "/longterm", label: "Long-term", ico: "◇" },
  { to: "/health", label: "Health", ico: "✚" },
  { to: "/ops", label: "Ops", ico: "◧" },
  { to: "/settings", label: "Settings", ico: "⚙" },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-dot" />
        <div>
          <div className="brand-name">AiTrader</div>
          <div className="brand-sub">Market AI Lab</div>
        </div>
      </div>
      <nav className="nav">
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
          >
            <span className="nav-ico">{l.ico}</span>
            {l.label}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        Paper-first. Live trading is disabled by default behind the approval
        gate.
      </div>
    </aside>
  );
}
