import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { IntegrationsHealth } from "../api/types";
import { DataState, Empty, Panel } from "../components/ui";

const DOT: Record<string, string> = {
  working: "g", failing: "r", not_configured: "d",
};
const LABEL: Record<string, string> = {
  working: "working", failing: "failing", not_configured: "not configured",
};

export default function HealthPage() {
  const h = useApi<IntegrationsHealth>(() => api.integrations(), 0, []);
  const rows = h.data?.integrations ?? [];
  const sum = h.data?.summary;
  return (
    <div>
      <h1 className="page-title">Integration health</h1>
      <p className="page-sub">
        Each row is one real minimal round trip. Read-only, except the Alpaca
        trade-auth check, which authenticates only and never places an order.
        Keys are never shown. A missing optional key reads as not configured.
      </p>
      <div className="between" style={{ marginBottom: 14 }}>
        <div className="muted" style={{ fontSize: 13 }}>
          {sum ? `${sum.configured_count} configured of ${sum.total}. ` +
            (sum.configured_count === 0 ? "None configured."
              : sum.all_ok ? "All configured integrations pass."
                : "Some configured integrations are failing.") : ""}
        </div>
        <button className="btn sm" disabled={h.loading} onClick={h.reload}>
          {h.loading ? "Checking…" : "Refresh"}
        </button>
      </div>
      <Panel title="Integrations">
        <DataState loading={h.loading && !h.data} error={h.error}>
          {rows.length ? (
            <div className="tbl-scroll">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Integration</th><th>State</th>
                    <th className="num">Latency</th><th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.name}>
                      <td>{r.provider}<div className="dim mono" style={{ fontSize: 11 }}>{r.name}</div></td>
                      <td>
                        <span className={`dot ${DOT[r.state] ?? "d"}`} style={{ marginRight: 8 }} />
                        {LABEL[r.state] ?? r.state}
                      </td>
                      <td className="num">{r.latency_ms != null ? `${r.latency_ms} ms` : "—"}</td>
                      <td className="muted" style={{ fontSize: 12 }}>{r.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>No integrations reported.</Empty>}
        </DataState>
      </Panel>
    </div>
  );
}
