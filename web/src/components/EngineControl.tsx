import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { EngineState, EngineLifecycle } from "../api/types";
import { Panel } from "./ui";

// Lifecycle -> dot color and label. The kill switch is deliberately NOT here:
// Start/Stop are ordinary lifecycle controls, the kill switch is the safety
// halt and lives on its own always-visible control.
const DOT: Record<EngineLifecycle, string> = {
  not_running: "d", starting: "a", warming: "a", running: "g", stopping: "a",
};
const LABEL: Record<EngineLifecycle, string> = {
  not_running: "Not running", starting: "Starting…", warming: "Warming",
  running: "Running", stopping: "Stopping…",
};

// Start Paper Trading and Stop, driven by the supervisor lifecycle. Start runs
// the warmed sequence (backfill, warm-verify, bridge, engine), Stop is a
// graceful shutdown of what the supervisor started. Start is disabled while
// already running or starting, and takes a confirm step. A strict-mode failure
// (an unreachable on-real layer) surfaces loudly with what is missing.
export default function EngineControl() {
  const e = useApi<EngineState>(() => api.engineState(), 2500, []);
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const d = e.data;
  const st: EngineLifecycle = d?.state ?? "not_running";
  const canStart = st === "not_running";
  const canStop = st === "running" || st === "warming" || st === "starting";

  async function start() {
    setBusy(true);
    try {
      const r = await api.engineStart();
      setMsg(r.ok === false ? (r.error ?? "start refused") : "Start requested. Warming indicators…");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "start failed");
    } finally {
      setBusy(false);
      setArming(false);
      e.reload();
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await api.engineStop();
      setMsg("Stop requested. Graceful shutdown of the bridge and engine.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "stop failed");
    } finally {
      setBusy(false);
      e.reload();
    }
  }

  return (
    <Panel title="Paper trading engine">
      <div className="ctrl-row">
        <div className="ctrl-name">
          <span className={`dot ${DOT[st]}`} /> <b>{LABEL[st]}</b>
          <div className="ctrl-sub">
            feed <b className="mono">{d?.feed_mode ?? "alpaca_paper"}</b> · clock{" "}
            <b>{d?.clock_mode ?? "real"}</b>
            {st === "running" && d?.owned === false && " · started outside the GUI"}
          </div>
        </div>
        <div className="ctrl-actions">
          {canStart ? (
            !arming ? (
              <button className="btn" disabled={busy}
                onClick={() => { setArming(true); setMsg(null); }}>
                Start paper trading
              </button>
            ) : (
              <>
                <button className="btn" disabled={busy} onClick={start}>
                  {busy ? "Starting…" : "Confirm start"}
                </button>
                <button className="btn ghost" disabled={busy}
                  onClick={() => setArming(false)}>Cancel</button>
              </>
            )
          ) : (
            <button className="btn ghost" disabled>Start paper trading</button>
          )}
          <button className="btn danger" disabled={busy || !canStop} onClick={stop}>
            Stop
          </button>
        </div>
      </div>

      {(st === "warming" || st === "starting") && (d?.warm?.length ?? 0) > 0 && (
        <div className="callout" style={{ marginTop: 10 }}>
          Warming indicators from the backfill:
          <div style={{ marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap" }}>
            {d!.warm.map((w) => (
              <span key={w.symbol} className="mono" style={{ fontSize: 12 }}>
                <span className={`dot ${w.warm ? "g" : "a"}`} /> {w.symbol} {w.bars} bars
              </span>
            ))}
          </div>
        </div>
      )}

      {d?.error && st === "not_running" && (
        <div className="callout warn" style={{ marginTop: 10 }}>
          Start failed: {d.error}
        </div>
      )}

      <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        Start runs the warmed sequence: backfill real bars, verify indicators
        warm, bring up the bridge with the real council, then the engine on
        feed_mode alpaca_paper, clock real, health checked between steps. A
        second start is refused while one runs, a stale lock from a crashed run
        clears on the next start. Stop is a graceful shutdown of what it started.
        The kill switch is separate and always available, it halts the engine
        directly and never routes through this control.
      </p>
      {msg && <div className="callout" style={{ marginTop: 8 }}>{msg}</div>}
    </Panel>
  );
}
