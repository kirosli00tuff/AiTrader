import type { ActivityEvent, SymbolDiagnostics, UniverseState, WatchdogDiagnostics } from "../api/types";
import Explain from "./Explain";

// One plain line per condition, trading literacy assumed, codebase not.
const CONDITION_COPY: Record<string, string> = {
  feed_substitution:
    "A symbol that used to receive real venue data is getting non-real bars. " +
    "This is the emergency: the watchdog restarts the stack for it.",
  symbol_unavailable:
    "The venue has never served this symbol a real bar. Contained: it is " +
    "skipped, never traded, and never a reason to stop the stack.",
  feed_restored: "Real venue data is flowing again for every traded symbol.",
  symbol_available: "The venue started serving this symbol; it is tradeable now.",
  provenance_block:
    "An entry was refused because the current bar's prices are not proven " +
    "real. Exits are never blocked.",
  continuous_start: "The engine started its continuous paper loop.",
  continuous_stop: "The engine stopped cleanly.",
  kill_switch: "The latching kill switch tripped. Manual resume required.",
  watchdog_restart: "The watchdog restarted the stack.",
  engine_supervisor: "The supervisor acted on the engine (start or stop).",
};

function ago(s: number | null): string {
  if (s == null) return "—";
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${(s / 3600).toFixed(1)}h ago`;
}

/** The universe line, and the loud condition when it collapses. The stack can
 *  be perfectly healthy and have nothing it may trade, which is exactly the
 *  state that must never be silent. */
export function UniverseSummary({ universe }: { universe?: UniverseState }) {
  if (!universe || !universe.declared_core?.length) return null;
  return (
    <div data-testid="diag-universe">
      <div className="dim">
        Universe: {universe.symbols.length} tradeable
        {" "}({universe.core.length} core + {universe.periphery.length} periphery)
        {universe.unserviceable.length > 0 && (
          <> · unserviceable: <span className="mono">
            {universe.unserviceable.join(", ")}</span></>
        )}
      </div>
      {universe.degraded && (
        <div className="chip chip-block" data-testid="universe-degraded">
          {universe.degraded_reason} Nothing is fabricated and nothing is
          stopped. Fix the core or the data credentials.
        </div>
      )}
    </div>
  );
}

export function SymbolHealthTable(
  { symbols, universe }: { symbols: SymbolDiagnostics[];
                           universe?: UniverseState }) {
  if (!symbols.length)
    return <div className="empty" data-testid="diag-symbols-empty">
      No symbols known yet. This fills once the database has bars.
    </div>;
  return (
    <>
    <UniverseSummary universe={universe} />
    <table className="tbl" data-testid="diag-symbols">
      <thead>
        <tr><th>symbol</th><th>part</th><th>tradeable</th><th>warm</th>
          <th>last bar</th>
          <th>provenance</th><th>last real bar</th><th>5min bars</th></tr>
      </thead>
      <tbody>
        {symbols.map((s) => (
          <tr key={s.symbol}>
            <td className="mono">{s.symbol}</td>
            <td className="dim">{s.part ?? "—"}</td>
            <td>{s.tradeable
              ? <span className="chip chip-ok">tradeable</span>
              : <span className="chip chip-block" data-testid={`unavailable-${s.symbol}`}>unavailable</span>}
            </td>
            <td>{s.warm == null ? "—" : s.warm
              ? <span className="chip chip-ok">warm</span>
              : <span className="chip chip-dim">cold</span>}
            </td>
            <td className="mono dim">{ago(s.age_seconds)}</td>
            <td className="mono">{s.last_bar_source ?? "—"}</td>
            <td className="mono dim">{s.last_real_ts ?? "never"}</td>
            <td className="mono dim">{s.bars_5min}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  );
}

export function WatchdogTimeline({ diag }: { diag: WatchdogDiagnostics }) {
  const holding = Boolean(diag.state["holding"]);
  return (
    <div data-testid="diag-watchdog">
      {holding && (
        <div className="callout warn" data-testid="watchdog-holding">
          The watchdog is HOLDING: condition {String(diag.state["condition"])}
          {" "}recurred after {String(diag.state["attempts"] ?? "?")} restart
          attempt(s). It leaves the stack as it is until recovery or an
          operator acts.
        </div>
      )}
      {!diag.events.length && (
        <div className="empty" data-testid="watchdog-empty">
          No feed or watchdog conditions recorded. Quiet is the good state.
        </div>
      )}
      {diag.events.map((e: ActivityEvent) => (
        <div className="ev-row" key={e.id} data-testid={`wd-${e.kind}`}>
          <span className="mono dim">{e.ts.slice(0, 19)}</span>
          <span className={`ev-kind mono ${
            e.kind === "feed_substitution" ? "ev-critical"
            : e.kind === "symbol_unavailable" ? "ev-warn" : ""}`}>
            {e.kind}
          </span>
          <span className="ev-msg">{e.message}</span>
          {CONDITION_COPY[e.kind] && (
            <span className="dim ev-copy"> {CONDITION_COPY[e.kind]}</span>
          )}
        </div>
      ))}
    </div>
  );
}

export function BridgeDetail({ bridge }: { bridge: Record<string, unknown> | null }) {
  if (!bridge)
    return <div className="empty" data-testid="bridge-empty">
      Bridge unreachable. Advisory layers and the Alpaca data path run through
      it; the engine keeps its safety spine without it.
    </div>;
  const degraded = (bridge["degraded"] as string[] | undefined) ?? [];
  return (
    <div data-testid="bridge-detail">
      <div className="kv">
        <span>status</span>
        <span className={`mono ${bridge["status"] === "ok" ? "pos" : "neg"}`}>
          {String(bridge["status"] ?? "unknown")}
        </span>
      </div>
      <div className="kv"><span>open file descriptors</span>
        <span className="mono">{String(bridge["fd_count"] ?? "—")}</span></div>
      <div className="kv"><span>fd alarm threshold</span>
        <span className="mono">{String(bridge["fd_warn_threshold"] ?? "—")}</span></div>
      <div className="kv"><span>degraded checks</span>
        <span className="mono">{degraded.length ? degraded.join(", ") : "none"}</span></div>
      <Explain>
        The bridge serves market data and advisory scores. Its health check
        proves capability, not liveness: a fresh file read, a fresh socket,
        and a real quote. A rising fd floor reads as degraded within about an
        hour (the 2026-07-19 keystore leak is the reason this is watched).
      </Explain>
    </div>
  );
}
