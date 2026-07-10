import { NavLink } from "react-router-dom";

// Overview / Stocks / Crypto tabs for a Paper or Live section. The Overview
// link matches the section root only (end), the others their own paths.
export default function SubNav({ base }: { base: string }) {
  const tabs = [
    { to: base, label: "Overview", end: true },
    { to: `${base}/stocks`, label: "Stocks", end: false },
    { to: `${base}/crypto`, label: "Crypto", end: false },
  ];
  return (
    <div className="subnav">
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end}
          className={({ isActive }) => (isActive ? "active" : "")}>
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}
