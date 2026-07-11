import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { SkipRow } from "../api/types";
import { clockTs } from "../api/format";
import { Empty } from "./ui";

const REASON: Record<string, string> = {
  skip_neutral: "neutral regime", skip_cooldown: "per-symbol cooldown",
  skip_budget: "daily budget spent", risk_precheck: "risk pre-check block",
  market_hours: "outside market hours", council_skip: "council skip",
};

// Rolling feed of recent council skips from the event log. Shows whether the
// bot is evaluating or sitting idle by design.
export default function SkipFeed() {
  const { data } = useApi<{ skips: SkipRow[] }>(() => api.skips(30), 8000, []);
  const rows = data?.skips ?? [];
  if (!rows.length) {
    return <Empty>No recent council skips. The bot is evaluating, or the log has none.</Empty>;
  }
  return (
    <div>
      {rows.map((r, i) => (
        <div className="feed-item" key={i}>
          <span className="feed-ts">{clockTs(r.ts)}</span>
          <span className="feed-kind">{r.symbol ?? "-"}</span>
          <span>{REASON[r.reason] ?? r.reason}</span>
        </div>
      ))}
    </div>
  );
}
