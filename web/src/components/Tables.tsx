import type { Order, Signal, Trade } from "../api/types";
import { clockTs, money, num } from "../api/format";
import { Empty } from "./ui";

export function OrdersTable({ orders, onSelect }: {
  orders: Order[]; onSelect?: (id: number) => void;
}) {
  if (!orders.length) return <Empty>No open orders.</Empty>;
  return (
    <div className="tbl-scroll">
      <table className="tbl">
        <thead>
          <tr>
            <th>Time</th><th>Symbol</th><th>Side</th><th className="num">Qty</th>
            <th className="num">Price</th><th className="num">Notional</th><th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className={onSelect ? "trow" : ""}
              onClick={onSelect ? () => onSelect(o.id) : undefined}>
              <td className="dim">{clockTs(o.ts)}</td>
              <td className="mono">{o.symbol}</td>
              <td className={o.side === "buy" ? "side-buy" : "side-sell"}>{o.side}</td>
              <td className="num">{num(o.qty)}</td>
              <td className="num">{num(o.price, 2)}</td>
              <td className="num">{money(o.notional)}</td>
              <td className="muted">{o.outcome ?? "open"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ClosedTradesTable({ trades, onSelect }: {
  trades: Trade[]; onSelect?: (id: number) => void;
}) {
  if (!trades.length) return <Empty>No closed trades.</Empty>;
  return (
    <div className="tbl-scroll">
      <table className="tbl">
        <thead>
          <tr>
            <th>Time</th><th>Symbol</th><th>Side</th><th className="num">Qty</th>
            <th className="num">Price</th><th className="num">PnL</th><th>Result</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id} className={onSelect ? "trow" : ""}
              onClick={onSelect ? () => onSelect(t.id) : undefined}>
              <td className="dim">{clockTs(t.ts)}</td>
              <td className="mono">{t.symbol}</td>
              <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{t.side}</td>
              <td className="num">{num(t.qty)}</td>
              <td className="num">{num(t.price, 2)}</td>
              <td className={`num ${(t.pnl ?? 0) >= 0 ? "pos" : "neg"}`}>{money(t.pnl)}</td>
              <td>
                <span className={`tag ${t.outcome === "win" ? "buy" : "sell"}`}>
                  {t.outcome ?? "—"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SignalsTable({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <Empty>No recent signals.</Empty>;
  return (
    <div className="tbl-scroll">
      <table className="tbl">
        <thead>
          <tr>
            <th>Time</th><th>Symbol</th><th>Factor</th><th className="num">Bias</th>
            <th className="num">Conf</th><th className="num">Edge</th><th>Regime</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s, i) => (
            <tr key={i}>
              <td className="dim">{clockTs(s.ts)}</td>
              <td className="mono">{s.symbol ?? "—"}</td>
              <td className="muted">{s.factor}</td>
              <td className={`num ${s.bias >= 0 ? "pos" : "neg"}`}>{s.bias.toFixed(2)}</td>
              <td className="num">{(s.confidence * 100).toFixed(0)}%</td>
              <td className="num">{s.edge != null ? s.edge.toFixed(3) : "—"}</td>
              <td>{s.regime
                ? <span className={`tag ${s.regime}`}>{s.regime.replace("_", " ")}</span>
                : <span className="dim">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
