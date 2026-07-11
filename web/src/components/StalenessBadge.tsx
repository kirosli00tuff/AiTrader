import { useEffect, useState } from "react";

// Age of the last update for a feed-dependent panel. Fresh reads look normal,
// a stale one past the threshold shows a warning color. Catches a dead bridge
// or a stalled feed before stale data reads as a calm market.
export default function StalenessBadge({ ts, thresholdSec = 120, label = "updated" }: {
  ts: string | null | undefined; thresholdSec?: number; label?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);
  if (!ts) return <span className="stale-badge dim">no data</span>;
  const t = new Date(ts.endsWith("Z") ? ts : `${ts}Z`).getTime();
  if (Number.isNaN(t)) return <span className="stale-badge dim">—</span>;
  const age = Math.max(0, Math.round((now - t) / 1000));
  const stale = age > thresholdSec;
  const txt = age < 60 ? `${age}s` : age < 3600 ? `${Math.round(age / 60)}m` : `${Math.round(age / 3600)}h`;
  return (
    <span className={`stale-badge ${stale ? "stale" : "fresh"}`} title={ts}>
      {label} {txt} ago
    </span>
  );
}
