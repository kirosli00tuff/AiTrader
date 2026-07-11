import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Account, Health, IntegrationsHealth, KillState, Pnl } from "../api/types";
import { money, pct, signClass } from "../api/format";

// Top strip on every page: engine state, active mode, portfolio value, daily
// PnL, kill-switch status (plus the bridge link). Polls /health, /account, and
// /pnl for the paper account, the primary operating book.
export default function StatusBar({ activeView }: { activeView: string }) {
  const health = useApi<Health>(() => api.health(), 4000, []);
  const acct = useApi<Account>(() => api.account("paper"), 6000, []);
  const pnlApi = useApi<Pnl>(() => api.pnl("paper"), 6000, []);
  // Integration health aggregate. Polled slowly (120s): with keys present each
  // poll is a few minimal round trips, with no keys it makes no external call.
  const integ = useApi<IntegrationsHealth>(() => api.integrations(), 120000, []);
  const killApi = useApi<KillState>(() => api.kill(), 6000, []);
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);

  const eng = health.data?.engine;
  const running = eng?.running ?? false;
  const kill = eng?.kill_switch_tripped ?? false;
  const bridge = health.data?.bridge?.reachable ?? false;
  const equity = acct.data?.equity ?? pnlApi.data?.equity ?? 0;
  const daily = pnlApi.data?.daily_pnl?.length
    ? pnlApi.data.daily_pnl[pnlApi.data.daily_pnl.length - 1].pnl
    : 0;
  const dayPct = pnlApi.data?.equity_change_pct ?? 0;
  const sum = integ.data?.summary;
  const configured = sum?.configured_count ?? 0;
  // green only when every configured integration passes, amber when any
  // configured one fails, grey when none configured (missing optional key is
  // not a failure).
  const apisDot = configured === 0 ? "d" : sum?.all_ok ? "g" : "a";
  const apisLabel = configured === 0 ? "none" : sum?.all_ok ? "ok" : "issues";
  const tripped = kill || (killApi.data?.engine_kill_switch_tripped ?? false);
  const confirmKill = async () => {
    setBusy(true);
    try {
      await api.requestKill("operator halt from status strip");
      killApi.reload();
    } finally {
      setBusy(false);
      setArming(false);
    }
  };

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
      <div className="status-item kill-strip">
        <span className={`dot ${tripped ? "r" : "g"}`} />
        Kill <b>{tripped ? "TRIPPED" : "armed"}</b>
        {tripped ? (
          <span className="dim" style={{ fontSize: 11 }}>manual resume required</span>
        ) : !arming ? (
          <button className="btn danger sm" onClick={() => setArming(true)}>halt</button>
        ) : (
          <>
            <button className="btn danger sm" disabled={busy} onClick={confirmKill}>
              {busy ? "…" : "confirm"}
            </button>
            <button className="btn ghost sm" disabled={busy} onClick={() => setArming(false)}>x</button>
          </>
        )}
      </div>
      <div className="status-sep" />
      <div className="status-item">
        <span className={`dot ${apisDot}`} />
        APIs <b>{apisLabel}</b>
      </div>
      <div className="statusbar-spacer" />
      <div className="status-item">
        <span className={`dot ${bridge ? "g" : "d"}`} />
        Bridge <b>{bridge ? "up" : "down"}</b>
      </div>
    </div>
  );
}
