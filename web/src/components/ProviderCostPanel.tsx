import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { ProviderCost } from "../api/types";
import { money } from "../api/format";
import { DataState, Empty } from "./ui";

const DOT: Record<string, string> = { live: "g", estimated: "a", unavailable: "d" };

// Provider cost. Balance where a provider exposes it, else provider spend, else
// local estimate. Estimated is always shown and labeled. No key value is shown.
export default function ProviderCostPanel() {
  const c = useApi<ProviderCost>(() => api.providerCost(), 0, []);
  const rows = c.data?.providers ?? [];
  return (
    <div>
      <div className="between" style={{ marginBottom: 10 }}>
        <span className="muted" style={{ fontSize: 12 }}>
          Balance where exposed, else provider spend, else local estimate. Estimated always shown.
        </span>
        <button className="btn sm" disabled={c.loading} onClick={c.reload}>
          {c.loading ? "…" : "Refresh"}
        </button>
      </div>
      <DataState loading={c.loading && !c.data} error={c.error}>
        {rows.length ? (
          <div className="tbl-scroll">
            <table className="tbl">
              <thead>
                <tr><th>Provider</th><th>Reported</th><th className="num">Est. today</th>
                  <th className="num">Est. month</th><th>Source</th></tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const rep = p.balance != null ? { l: "balance", v: money(p.balance) }
                    : p.spend != null ? { l: "spend", v: money(p.spend) }
                      : { l: "estimated", v: "—" };
                  return (
                    <tr key={p.provider}>
                      <td>{p.provider}<div className="dim mono" style={{ fontSize: 11 }}>{p.model}</div></td>
                      <td><span className={`dot ${DOT[p.status] ?? "d"}`} style={{ marginRight: 8 }} />{rep.l}: {rep.v}</td>
                      <td className="num">{money(p.estimated_day)}</td>
                      <td className="num">{money(p.estimated_month)}</td>
                      <td className="muted" style={{ fontSize: 12 }}>{p.status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <Empty>No provider cost data.</Empty>}
      </DataState>
      {c.data && (
        <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
          Estimated totals: today {money(c.data.totals.estimated_day)}, month {money(c.data.totals.estimated_month)}.
        </div>
      )}
    </div>
  );
}
