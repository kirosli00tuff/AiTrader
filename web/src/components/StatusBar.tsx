import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Account, Health, Pnl } from "../api/types";
import { money, pct, signClass } from "../api/format";

// Top strip on every page: engine state, active mode, portfolio value, daily
// PnL, kill-switch status (plus the bridge link). Polls /health, /account, and
// /pnl for the paper account, the primary operating book.
export default function StatusBar({ activeView }: { activeView: string }) {
  const health = useApi<Health>(() => api.health(), 4000, []);
  const acct = useApi<Account>(() => api.account("paper"), 6000, []);
  const pnlApi = useApi<Pnl>(() => api.pnl("paper"), 6000, []);

  const eng = health.data?.engine;
  const running = eng?.running ?? false;
  const kill = eng?.kill_switch_tripped ?? false;
  const bridge = health.data?.bridge?.reachable ?? false;
  const equity = acct.data?.equity ?? pnlApi.data?.equity ?? 0;
  const daily = pnlApi.data?.daily_pnl?.length
    ? pnlApi.data.daily_pnl[pnlApi.data.daily_pnl.length - 1].pnl
    : 0;
  const dayPct = pnlApi.data?.equity_change_pct ?? 0;

  return (
    <div className="statusbar">
      <div className="status-item">
        <span className={`dot ${running ? "g" : "d"}`} />
        Engine <b>{running ? "running" : "offline"}</b>
      </div>
      <div className="status-sep" />
      <div className="status-item">Mode <b>{activeView}</b></div>
      <div className="status-sep" />
      <div className="status-item">
        Portfolio <b className="mono">{money(equity)}</b>
      </div>
      <div className="status-item">
        Today
        <b className={`mono ${signClass(daily)}`}>
          {daily >= 0 ? "▲" : "▼"} {money(daily)} ({pct(dayPct)})
        </b>
      </div>
      <div className="status-sep" />
      <div className="status-item">
        <span className={`dot ${kill ? "r" : "g"}`} />
        Kill switch <b>{kill ? "TRIPPED" : "clear"}</b>
      </div>
      <div className="statusbar-spacer" />
      <div className="status-item">
        <span className={`dot ${bridge ? "g" : "d"}`} />
        Bridge <b>{bridge ? "up" : "down"}</b>
      </div>
    </div>
  );
}
