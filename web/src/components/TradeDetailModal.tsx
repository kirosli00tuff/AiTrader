import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TradeDetail } from "../api/types";
import { clockTs, money, num } from "../api/format";

// Trade debugging view: entry, sizing, regime, factors that fired, council
// verdict at entry, and related entry/exit events. Read-only.
export default function TradeDetailModal({ tradeId, onClose }: {
  tradeId: number; onClose: () => void;
}) {
  const [d, setD] = useState<TradeDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.tradeDetail(tradeId).then((x) => { if (alive) setD(x); })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [tradeId]);
  const t = d?.trade;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="between" style={{ marginBottom: 12 }}>
          <b>Trade detail{t ? ` — ${t.symbol}` : ""}</b>
          <button className="btn ghost sm" onClick={onClose}>Close</button>
        </div>
        {err && <div className="error-box">{err}</div>}
        {!d ? <div className="state-box"><span className="spinner" /> Loading…</div>
          : !t ? <div className="empty">Trade not found.</div> : (
            <div className="grid" style={{ gap: 12 }}>
              <div>
                <div className="panel-title">Order and sizing</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  {clockTs(t.ts)} · {t.side} {num(t.qty)} @ {num(t.price, 2)} · notional {money(t.notional)} · {t.mode}
                  {" · outcome "}{t.outcome ?? "open"}{t.pnl != null ? ` · pnl ${money(t.pnl)}` : ""}
                </div>
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>
                  gate confidence {t.combined_conf != null ? t.combined_conf.toFixed(2) : "—"}, edge {t.combined_edge != null ? t.combined_edge.toFixed(3) : "—"}
                </div>
              </div>
              <div>
                <div className="panel-title">Regime</div>
                {d.regime ? <span className={`tag ${d.regime.regime}`}>{d.regime.regime.replace("_", " ")}</span> : <span className="dim">—</span>}
              </div>
              <div>
                <div className="panel-title">Factors that fired</div>
                {d.signals.length ? (
                  <div className="tbl-scroll"><table className="tbl"><tbody>
                    {d.signals.map((s, i) => (
                      <tr key={i}>
                        <td className="muted">{s.factor}</td>
                        <td className={`num ${s.bias >= 0 ? "pos" : "neg"}`}>{s.bias.toFixed(2)}</td>
                        <td className="num">{(s.confidence * 100).toFixed(0)}%</td>
                        <td className="num">{s.edge != null ? s.edge.toFixed(3) : "—"}</td>
                      </tr>
                    ))}
                  </tbody></table></div>
                ) : <span className="dim">no signals recorded</span>}
              </div>
              <div>
                <div className="panel-title">Council verdict at entry</div>
                {d.council.length ? d.council.map((m, i) => (
                  <div className="mech" key={i}>
                    <span className="mech-name mono">{m.model}</span>
                    <span className={`tag ${m.verdict ?? "neutral_v"}`}>{m.verdict ?? "—"}</span>
                  </div>
                )) : <span className="dim">no verdicts</span>}
              </div>
              <div>
                <div className="panel-title">Entry and exit events</div>
                {d.events.length ? d.events.slice(0, 8).map((e, i) => (
                  <div className="feed-item" key={i}>
                    <span className="feed-ts">{clockTs(e.ts)}</span>
                    <span className="feed-kind">{e.kind}</span>
                    <span>{e.message}</span>
                  </div>
                )) : <span className="dim">no events</span>}
              </div>
            </div>
          )}
      </div>
    </div>
  );
}
