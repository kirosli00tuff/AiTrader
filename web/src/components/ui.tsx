import type { CSSProperties, ReactNode } from "react";
import { money, pct, signClass } from "../api/format";

export function Panel({ title, children, style }: {
  title?: string; children: ReactNode; style?: CSSProperties;
}) {
  return (
    <div className="panel" style={style}>
      {title && <div className="panel-title">{title}</div>}
      {children}
    </div>
  );
}

export function Stat({ label, value, cls }: {
  label: string; value: ReactNode; cls?: string;
}) {
  return (
    <div className="stat">
      <div className={`stat-val ${cls ?? ""}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Change({ value, valuePct }: { value: number; valuePct: number }) {
  return (
    <span className={`change ${signClass(value)}`}>
      {value >= 0 ? "▲" : "▼"} {money(value)} ({pct(valuePct)})
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function DataState({ loading, error, children }: {
  loading: boolean; error: string | null; children: ReactNode;
}) {
  if (error) return <div className="error-box">Could not load: {error}</div>;
  if (loading) {
    return (
      <div className="state-box">
        <span className="spinner" /> Loading…
      </div>
    );
  }
  return <>{children}</>;
}
