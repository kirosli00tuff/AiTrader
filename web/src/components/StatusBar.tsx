import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Account, EngineState, Health, IntegrationsHealth, KillState, Pnl, RunState } from "../api/types";
import { money, pct, signClass } from "../api/format";

// Supervisor lifecycle -> dot color for the compact engine indicator.
const ENG_DOT: Record<string, string> = {
  not_running: "d", starting: "a", warming: "a", running: "g", stopping: "a",
};

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
  const runApi = useApi<RunState>(() => api.runstate(), 8000, []);
  const engApi = useApi<EngineState>(() => api.engineState(), 3000, []);
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [engArm, setEngArm] = useState(false);
  const [engBusy, setEngBusy] = useState(false);

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

  // Supervisor lifecycle, mirrored compactly. Distinct from the kill strip: this
  // is the ordinary Start/Stop, the kill switch below is the safety halt.
  const lifecycle = engApi.data?.state ?? (running ? "running" : "not_running");
  const engCanStart = lifecycle === "not_running";
  const engCanStop = lifecycle === "running" || lifecycle === "warming" || lifecycle === "starting";
  const startEngine = async () => {
    setEngBusy(true);
    try { await api.engineStart(); engApi.reload(); health.reload(); }
    finally { setEngBusy(false); setEngArm(false); }
  };
  const stopEngine = async () => {
    setEngBusy(true);
    try { await api.engineStop(); engApi.reload(); health.reload(); }
    finally { setEngBusy(false); }
  };

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
        <span className={`dot ${ENG_DOT[lifecycle] ?? "d"}`} />
        Engine <b>{lifecycle.replace("_", " ")}</b>
        {engCanStart ? (
          !engArm ? (
            <button className="btn sm" onClick={() => setEngArm(true)}>start</button>
          ) : (
            <>
              <button className="btn sm" disabled={engBusy} onClick={startEngine}>
                {engBusy ? "…" : "go"}
              </button>
              <button className="btn ghost sm" disabled={engBusy} onClick={() => setEngArm(false)}>x</button>
            </>
          )
        ) : engCanStop ? (
          <button className="btn ghost sm" disabled={engBusy} onClick={stopEngine}>stop</button>
        ) : null}
      </div>
      <div className="status-sep" />
      <div className="status-item">Mode <b>{activeView}</b></div>
      <div className="status-sep" />
      <div className="status-item">
        Loop <b className="mono">{runApi.data?.feed_mode ?? "…"}</b>
        <span className="dim" style={{ fontSize: 11 }}>{runApi.data?.clock_mode ?? ""}</span>
      </div>
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
