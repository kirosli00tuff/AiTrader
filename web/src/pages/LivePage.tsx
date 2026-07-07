import type { CSSProperties } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Account, Approval, Pnl } from "../api/types";
import { money } from "../api/format";
import { DataState, Empty, Panel, Stat } from "../components/ui";

const COLS: CSSProperties = {
  display: "grid", gap: 14,
  gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
};

// Same skeleton as Paper, but locked. Reads approval state and reports it.
// No control here can enable live. When locked (always this session) the
// trading data is zeroed.
export default function LivePage() {
  const approvalApi = useApi<Approval>(() => api.approval(), 6000, []);
  const acct = useApi<Account>(() => api.account("live"), 8000, []);
  const pnlApi = useApi<Pnl>(() => api.pnl("live"), 8000, []);
  const ap = approvalApi.data;
  const locked = !(ap?.all_passed ?? false);
  const equity = locked ? 0 : acct.data?.equity ?? 0;

  return (
    <div>
      <h1 className="page-title">Live trading</h1>
      <p className="page-sub">
        IBKR live venue. Disabled by default behind the approval gate. This page
        reads and reports gate state. It cannot enable live.
      </p>

      <div className="locked-banner" style={{ marginBottom: 14 }}>
        <span className="lock-ico">{locked ? "🔒" : "●"}</span>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>
            {locked ? "Live trading is LOCKED" : "Live trading ENABLED"}
          </div>
          <div className="muted" style={{ fontSize: 13 }}>
            {locked
              ? "All trading data is zeroed. Enabling live is a backend gate action outside this GUI."
              : "Every live order still routes through the deterministic RiskGate."}
          </div>
        </div>
      </div>

      <Panel title="Approval gate — four safety mechanisms"
        style={{ marginBottom: 14 }}>
        <DataState loading={approvalApi.loading && !ap} error={approvalApi.error}>
          {(ap?.mechanisms ?? []).map((m) => (
            <div className="mech" key={m.key}>
              <span className="mech-name">{m.name}</span>
              <span className="mech-detail" style={{ flex: 1 }}>{m.detail}</span>
              <span className={m.passed ? "mech-pass" : "mech-fail"}>
                {m.passed ? "PASS" : "BLOCKED"}
              </span>
            </div>
          ))}
          <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Live enabled: <b>{ap?.live_enabled ? "yes" : "no"}</b>
            {" · "}all mechanisms pass: <b>{ap?.all_passed ? "yes" : "no"}</b>
          </div>
        </DataState>
      </Panel>

      <Panel style={{ marginBottom: 14 }}>
        <div className="hero">
          <div>
            <div className="hero-label">Live account value</div>
            <div className="hero-value mono">{money(equity)}</div>
          </div>
        </div>
      </Panel>

      <div className="stat-row" style={{ marginBottom: 14 }}>
        <Stat label="Daily PnL" value={money(0)} />
        <Stat label="Win rate"
          value={locked ? "—" : `${(pnlApi.data?.win_rate ?? 0).toFixed(1)}%`} />
        <Stat label="Open positions" value={0} />
        <Stat label="Total P/L"
          value={money(locked ? 0 : pnlApi.data?.total_pnl ?? 0)} />
      </div>

      <div style={COLS}>
        <Panel title="Live open positions">
          <Empty>No live positions. Live trading is disabled.</Empty>
        </Panel>
        <Panel title="Live activity">
          <Empty>No live activity. Live trading is disabled.</Empty>
        </Panel>
      </div>
    </div>
  );
}
