import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { DaySummary as DS } from "../api/types";
import { money } from "../api/format";
import { Stat } from "./ui";

// Daily read for paper testing: trades today, win rate today, council calls
// against the budget, and estimated provider spend today.
export default function DaySummary() {
  const { data } = useApi<DS>(() => api.daySummary(), 8000, []);
  const d = data;
  return (
    <div className="stat-row">
      <Stat label="Trades today" value={d?.trades_today ?? 0} />
      <Stat label="Win rate today" value={`${(d?.win_rate_today ?? 0).toFixed(1)}%`} />
      <Stat label="Council calls today"
        value={`${d?.council_calls_today ?? 0} / ${d?.council_daily_budget ?? 0}`} />
      <Stat label="Est. spend today" value={money(d?.estimated_spend_today ?? 0)} />
    </div>
  );
}
