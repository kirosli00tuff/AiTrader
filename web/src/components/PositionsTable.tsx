import type { Position } from "../api/types";
import { money, num } from "../api/format";
import { Empty } from "./ui";

export default function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty>No open positions.</Empty>;
  return (
    <div className="tbl-scroll">
      <table className="tbl">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Venue</th>
            <th>Side</th>
            <th className="num">Qty</th>
            <th className="num">Avg price</th>
            <th className="num">Notional</th>
            <th className="num">Unreal. PnL</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p, i) => (
            <tr key={`${p.venue}-${p.symbol}-${i}`}>
              <td>{p.symbol}</td>
              <td className="muted">{p.venue}</td>
              <td className={p.side === "buy" ? "side-buy" : "side-sell"}>{p.side}</td>
              <td className="num">{num(p.qty)}</td>
              <td className="num">{num(p.avg_price, 2)}</td>
              <td className="num">{money(p.notional)}</td>
              <td className={`num ${(p.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                {money(p.unrealized_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
