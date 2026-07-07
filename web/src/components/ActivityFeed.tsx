import type { Order, Signal } from "../api/types";
import { clockTs, money } from "../api/format";
import { Empty } from "./ui";

interface FeedRow { ts: string; kind: string; text: string; }

// Merge recent fills and signals into one newest-first feed.
export default function ActivityFeed({ orders, signals }: {
  orders: Order[]; signals: Signal[];
}) {
  const rows: FeedRow[] = [];
  for (const o of orders) {
    rows.push({
      ts: o.ts, kind: "fill",
      text: `${o.side} ${o.symbol} @ ${o.price} (${money(o.notional)})` +
        (o.pnl != null ? ` · pnl ${money(o.pnl)}` : ""),
    });
  }
  for (const s of signals) {
    rows.push({
      ts: s.ts, kind: s.factor,
      text: `${s.symbol ?? "?"} bias ${s.bias.toFixed(2)} · conf ${(s.confidence * 100).toFixed(0)}%`,
    });
  }
  rows.sort((a, b) => (a.ts < b.ts ? 1 : -1));
  const top = rows.slice(0, 18);
  if (!top.length) return <Empty>No recent activity.</Empty>;
  return (
    <div>
      {top.map((r, i) => (
        <div className="feed-item" key={i}>
          <span className="feed-ts">{clockTs(r.ts)}</span>
          <span className="feed-kind">{r.kind}</span>
          <span>{r.text}</span>
        </div>
      ))}
    </div>
  );
}
