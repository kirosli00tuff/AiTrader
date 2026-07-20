import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BarsResponse, PositionExit } from "../api/types";
import Explain from "./Explain";

const fmt = (v: number | null | undefined, d = 2) =>
  typeof v === "number" ? v.toFixed(d) : "—";

// A quiet inline sparkline from stored closes. No axes, no decoration.
export function Sparkline({ closes }: { closes: number[] }) {
  if (closes.length < 2) return <span className="dim mono">—</span>;
  const w = 120, h = 24;
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = max - min || 1;
  const pts = closes.map((c, i) =>
    `${((i / (closes.length - 1)) * w).toFixed(1)},` +
    `${(h - ((c - min) / span) * h).toFixed(1)}`).join(" ");
  const up = closes[closes.length - 1] >= closes[0];
  return (
    <svg width={w} height={h} className="spark" data-testid="sparkline">
      <polyline points={pts} fill="none"
        stroke={up ? "var(--pos, #3fb68b)" : "var(--neg, #e0565b)"}
        strokeWidth="1.5" />
    </svg>
  );
}

interface SymbolRow {
  symbol: string;
  bars: BarsResponse | null;
}

export default function MarketsPanel({ symbols, positions }: {
  symbols: string[];
  positions: PositionExit[];
}) {
  const [rows, setRows] = useState<SymbolRow[]>([]);

  useEffect(() => {
    let stopped = false;
    const load = () =>
      Promise.all(symbols.map(async (s) => ({
        symbol: s,
        bars: await api.bars(s, 60).catch(() => null),
      }))).then((r) => { if (!stopped) setRows(r); });
    load();
    const t = setInterval(load, 15000); // bars close on minutes, not seconds
    return () => { stopped = true; clearInterval(t); };
  }, [symbols.join(",")]);

  const posBySym = new Map(positions.map((p) => [p.symbol, p]));
  return (
    <div data-testid="markets">
      {rows.length === 0 && (
        <div className="empty" data-testid="markets-empty">
          No symbols to show. The traded universe appears here once the engine
          is running.
        </div>
      )}
      {rows.length > 0 && (
        <table className="tbl markets-tbl">
          <thead>
            <tr>
              <th>symbol</th><th>price</th><th>session</th><th>recent</th>
              <th>position</th><th>entry</th><th>uPnL</th>
              <th>stop / target</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const p = posBySym.get(r.symbol);
              const closes = (r.bars?.bars ?? []).map((b) => b.close);
              return (
                <tr key={r.symbol} data-testid={`market-${r.symbol}`}>
                  <td className="mono">{r.symbol}</td>
                  <td className="mono">{fmt(r.bars?.last_price)}</td>
                  <td className={`mono ${
                    (r.bars?.session_change_pct ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {r.bars?.session_change_pct != null
                      ? `${r.bars.session_change_pct >= 0 ? "+" : ""}${fmt(r.bars.session_change_pct)}%`
                      : "—"}
                  </td>
                  <td><Sparkline closes={closes} /></td>
                  <td className="mono">
                    {p ? `${p.side} ${fmt(p.qty, 4)}` : "—"}
                  </td>
                  <td className="mono">{p ? fmt(p.avg_price) : "—"}</td>
                  <td className={`mono ${(p?.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {p ? fmt(p.unrealized_pnl) : "—"}
                  </td>
                  <td className="mono dim">
                    {p && (p.stop != null || p.target != null)
                      ? `${fmt(p.stop)} / ${fmt(p.target)}`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {positions.length > 0 && (
        <Explain>
          Stop and target are the levels the native strategy logged when it
          opened the position (ATR-derived). The engine works toward them on
          closed bars; exits are never blocked by any advisory layer.
        </Explain>
      )}
    </div>
  );
}
