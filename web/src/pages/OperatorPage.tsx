import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useActivity } from "../api/useActivity";
import { useApi } from "../api/useApi";
import type { Health, Pnl, PositionExit, SymbolDiagnostics, WatchlistRow } from "../api/types";
import ActivityBySymbol from "../components/ActivityBySymbol";
import MarketsPanel from "../components/MarketsPanel";
import Explain from "../components/Explain";
import { Panel } from "../components/ui";

const fmt = (v: number | null | undefined, d = 2) =>
  typeof v === "number" ? v.toFixed(d) : "—";

// The main screen answers, in order: what is it doing right now, how is it
// performing, what is it about to do, is it healthy.
export default function OperatorPage() {
  const { events, connected } = useActivity();
  const pnl = useApi<Pnl>(() => api.pnl("paper"), 5000, []);
  const health = useApi<Health>(() => api.health(), 5000, []);
  const diag = useApi<{ symbols: SymbolDiagnostics[] }>(
    () => api.diagSymbols(), 10000, []);
  const exits = useApi<{ mode: string; positions: PositionExit[] }>(
    () => api.positionExits("paper"), 5000, []);
  const wl = useApi<{ watchlist: WatchlistRow[]; enabled: boolean }>(
    () => api.watchlist(20, 0), 15000, []);

  const symbols = (diag.data?.symbols ?? []).map((s) => s.symbol);
  const unavailable = (diag.data?.symbols ?? []).filter((s) => !s.tradeable);
  const p = pnl.data;
  const h = health.data;

  return (
    <div data-testid="operator-page">
      <h1 className="page-title">Operator</h1>

      {/* 1. What is it doing right now */}
      <Panel title="Live activity, grouped by symbol">
        <ActivityBySymbol events={events} connected={connected} />
      </Panel>

      {/* 2. How is it performing */}
      <Panel title="Performance">
        {p ? (
          <div className="stat-strip" data-testid="performance">
            <div className="kv"><span>equity</span>
              <span className="mono">{fmt(p.equity)}</span></div>
            <div className="kv"><span>change</span>
              <span className={`mono ${p.equity_change >= 0 ? "pos" : "neg"}`}>
                {fmt(p.equity_change)} ({fmt(p.equity_change_pct)}%)</span></div>
            <div className="kv"><span>closed trades</span>
              <span className="mono">{p.n_trades}</span></div>
            <div className="kv"><span>win rate</span>
              <span className="mono">{fmt(p.win_rate, 1)}%</span></div>
            <div className="kv"><span>max drawdown</span>
              <span className="mono">{fmt(p.max_drawdown_pct)}%</span></div>
          </div>
        ) : <div className="empty">No performance data yet.</div>}
      </Panel>

      {/* 3. What is it about to do */}
      <Panel title="Working and watching">
        <MarketsPanel symbols={symbols} positions={exits.data?.positions ?? []} />
        {(wl.data?.watchlist ?? []).length > 0 && (
          <div style={{ marginTop: 8 }} data-testid="watchlist-chips">
            <span className="dim">Discovery watchlist: </span>
            {(wl.data?.watchlist ?? []).map((r) => (
              <span className="chip chip-dim mono" key={r.symbol}>{r.symbol}</span>
            ))}
            <Explain>
              The discovery funnel screens a wide universe cheap-to-expensive
              each hour; survivors join this watchlist and trade exactly like
              configured symbols. See the Discovery page for each pass as a
              narrative.
            </Explain>
          </div>
        )}
      </Panel>

      {/* 4. Is it healthy */}
      <Panel title="Health">
        {h ? (
          <div className="stat-strip" data-testid="health-strip">
            <div className="kv"><span>engine</span>
              <span className={`mono ${h.engine?.running ? "pos" : "neg"}`}>
                {h.engine?.running ? "running" : "down"}</span></div>
            <div className="kv"><span>bridge</span>
              <span className={`mono ${h.bridge?.status === "ok" ? "pos" : "neg"}`}>
                {String(h.bridge?.status ?? "down")}</span></div>
            <div className="kv"><span>kill switch</span>
              <span className={`mono ${h.engine?.kill_switch_tripped ? "neg" : "pos"}`}>
                {h.engine?.kill_switch_tripped ? "TRIPPED" : "armed"}</span></div>
            <div className="kv"><span>unavailable symbols</span>
              <span className="mono" data-testid="unavailable-count">
                {unavailable.length
                  ? unavailable.map((s) => s.symbol).join(", ")
                  : "none"}</span></div>
            <Link to="/diagnostics" className="btn ghost sm">Diagnostics</Link>
            <Link to="/controls" className="btn ghost sm">Controls</Link>
          </div>
        ) : <div className="empty">Health unreadable. Is the backend up?</div>}
      </Panel>
    </div>
  );
}
