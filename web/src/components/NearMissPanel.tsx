import { useState } from "react";
import type { NearMisses } from "../api/types";
import Explain from "./Explain";

const fmt = (v: number | null | undefined, d = 3) =>
  typeof v === "number" ? v.toFixed(d) : "—";

/** Rejected entry candidates: what fired and did not enter, the first
 * refusing condition, the full set, and the distance from firing. Every
 * number is server-computed; this renders and never derives. This is the
 * view that would have shown the fast-tier ceiling without a diagnostic
 * session. */
export default function NearMissPanel({ data, windowHours, onWindow }: {
  data?: NearMisses;
  windowHours: number;
  onWindow: (h: number) => void;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const rows = data?.rows ?? [];
  return (
    <div data-testid="nearmiss">
      <div className="row-between">
        <span className="dim">
          {data
            ? `${rows.length} rejected, ${data.entered} entered in the last `
            : "window: "}
          {[24, 72, 168].map((h) => (
            <button key={h}
              className={`chip ${h === windowHours ? "" : "chip-dim"}`}
              onClick={() => onWindow(h)} data-testid={`nm-window-${h}`}>
              {h}h
            </button>
          ))}
        </span>
      </div>
      {!data && (
        <div className="empty" data-testid="nearmiss-empty">
          Near-miss data unavailable (stack down or endpoint unreachable).
          Nothing is derived client-side, so nothing is shown.
        </div>
      )}
      {data && rows.length === 0 && (
        <div className="empty" data-testid="nearmiss-none">
          No rejected candidates recorded in this window. Recording started
          2026-07-23; an empty window before that date means no data, not no
          rejections.
        </div>
      )}
      {data && data.by_reject.length > 0 && (
        <div data-testid="nearmiss-by-reject" style={{ margin: "6px 0" }}>
          <span className="dim">by first refusing condition: </span>
          {data.by_reject.map((r) => (
            <span className="chip chip-dim mono" key={r.first_reject ?? "none"}>
              {r.first_reject ?? "unknown"}: {r.n}
            </span>
          ))}
          <span className="dim"> · by symbol: </span>
          {data.by_symbol.slice(0, 8).map((s) => (
            <span className="chip chip-dim mono" key={s.symbol}>
              {s.symbol}: {s.n}
            </span>
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <table className="tbl">
          <thead>
            <tr>
              <th>ts</th><th>symbol</th><th>first reject</th><th>tier</th>
              <th>confidence</th><th>gap to floor</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <>
                <tr key={r.id} data-testid={`nm-row-${r.id}`}>
                  <td className="mono dim">{r.ts.slice(5, 16)}</td>
                  <td className="mono">{r.symbol}</td>
                  <td className="mono">{r.first_reject ?? "—"}</td>
                  <td className="mono dim">{r.tier || "—"}</td>
                  <td className="mono">{fmt(r.confidence)}</td>
                  <td className={`mono ${
                    (r.distances.confidence_gap ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {fmt(r.distances.confidence_gap ?? null, 4)}
                  </td>
                  <td>
                    <button className="chip chip-dim"
                      onClick={() => setOpen(open === r.id ? null : r.id)}>
                      {open === r.id ? "close" : "conditions"}
                    </button>
                  </td>
                </tr>
                {open === r.id && (
                  <tr key={`${r.id}-detail`}>
                    <td colSpan={7}>
                      <div className="mono dim" data-testid={`nm-detail-${r.id}`}
                        style={{ whiteSpace: "pre-wrap", fontSize: "0.85em" }}>
                        distances: {JSON.stringify(r.distances)}{"\n"}
                        factors: {r.factors.length
                          ? r.factors.map((f) =>
                              `${f.factor}=${fmt(f.confidence)}`).join(", ")
                          : "composition never ran (rejected earlier)"}{"\n"}
                        full state: {JSON.stringify(r.state)}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      )}
      {data && (
        <Explain>
          A rejection here is a candidate the strategy evaluated and refused,
          with the condition that refused it first and how close every other
          condition was. A single condition refusing everything in the window
          is the fast-tier-ceiling shape. The confidence gap is composed
          confidence minus the unchanged Level 1 floor
          {data.min_confidence != null ? ` (${data.min_confidence})` : ""}.
        </Explain>
      )}
    </div>
  );
}
