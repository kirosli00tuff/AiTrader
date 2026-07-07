import type { CSSProperties } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useStream } from "../api/useStream";
import type { Account, Council, Pnl, Position, SignalsResponse } from "../api/types";
import { money, num, signClass } from "../api/format";
import { Change, DataState, Empty, Panel, Stat } from "../components/ui";
import EquityChart from "../components/EquityChart";
import PositionsTable from "../components/PositionsTable";
import ActivityFeed from "../components/ActivityFeed";
import CouncilPanel from "../components/CouncilPanel";
import KillSwitch from "../components/KillSwitch";

const COLS: CSSProperties = {
  display: "grid", gap: 14,
  gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
};

export default function PaperPage() {
  const { snapshot, connected } = useStream("paper");
  const acct = useApi<Account>(() => api.account("paper"), 6000, []);
  const pnlApi = useApi<Pnl>(() => api.pnl("paper"), 6000, []);
  const posApi = useApi(() => api.positions("paper"), 6000, []);
  const ordApi = useApi(() => api.orders("paper", 40), 6000, []);
  const sigApi = useApi<SignalsResponse>(() => api.signals(), 8000, []);
  const councilApi = useApi<Council>(() => api.council(), 12000, []);
  const killApi = useApi(() => api.kill(), 6000, []);

  const pnl = snapshot?.pnl ?? pnlApi.data;
  const positions: Position[] =
    snapshot?.positions ?? posApi.data?.positions ?? [];
  const orders = snapshot?.orders ?? ordApi.data?.orders ?? [];
  const signals = sigApi.data?.signals ?? [];
  const regimes = sigApi.data?.regimes ?? [];

  const equity = acct.data?.equity ?? pnl?.equity ?? 0;
  const daily = pnl?.daily_pnl?.length
    ? pnl.daily_pnl[pnl.daily_pnl.length - 1].pnl
    : 0;
  const winRate = pnl?.win_rate ?? 0;

  return (
    <div>
      <h1 className="page-title">Paper trading</h1>
      <p className="page-sub">
        Alpaca paper loop, the continuous training environment. Updates{" "}
        {connected ? "live over the stream" : "on a poll"}.
      </p>

      <Panel style={{ marginBottom: 14 }}>
        <div className="hero">
          <div>
            <div className="hero-label">Total equity</div>
            <div className="hero-value mono">{money(equity)}</div>
          </div>
          <div>
            <div className="hero-label">Today</div>
            <Change value={daily} valuePct={pnl?.equity_change_pct ?? 0} />
          </div>
        </div>
      </Panel>

      <div className="stat-row" style={{ marginBottom: 14 }}>
        <Stat label="Daily PnL" value={money(daily)} cls={signClass(daily)} />
        <Stat label="Win rate" value={`${winRate.toFixed(1)}%`} />
        <Stat label="Closed trades" value={num(pnl?.n_trades ?? 0, 0)} />
        <Stat label="Open positions" value={positions.length} />
        <Stat label="Total P/L" value={money(pnl?.total_pnl ?? 0)}
          cls={signClass(pnl?.total_pnl ?? 0)} />
        <Stat label="Max drawdown"
          value={`${(pnl?.max_drawdown_pct ?? 0).toFixed(2)}%`}
          cls={(pnl?.max_drawdown_pct ?? 0) < 0 ? "neg" : ""} />
      </div>

      <Panel title="Portfolio value" style={{ marginBottom: 14 }}>
        <DataState loading={pnlApi.loading && !pnl} error={pnlApi.error}>
          <EquityChart points={pnl?.equity_curve ?? []} />
        </DataState>
      </Panel>

      <div style={COLS}>
        <Panel title="Open positions">
          <DataState loading={posApi.loading && !posApi.data} error={posApi.error}>
            <PositionsTable positions={positions} />
          </DataState>
        </Panel>
        <Panel title="Recent activity">
          <DataState loading={ordApi.loading && !ordApi.data} error={ordApi.error}>
            <ActivityFeed orders={orders} signals={signals} />
          </DataState>
        </Panel>
      </div>

      <div style={{ ...COLS, marginTop: 14 }}>
        <Panel title="Per-symbol regime">
          <DataState loading={sigApi.loading && !sigApi.data} error={sigApi.error}>
            {regimes.length ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {regimes.map((r) => (
                  <div key={r.symbol}
                    style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="mono">{r.symbol}</span>
                    <span className={`tag ${r.regime}`}>
                      {r.regime.replace("_", " ")}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>No regime labels yet.</Empty>
            )}
          </DataState>
        </Panel>
        <Panel title="Council verdicts">
          <DataState loading={councilApi.loading && !councilApi.data}
            error={councilApi.error}>
            <CouncilPanel council={councilApi.data} />
          </DataState>
        </Panel>
      </div>

      <Panel title="Kill switch" style={{ marginTop: 14 }}>
        <KillSwitch state={killApi.data} onChange={killApi.reload} />
      </Panel>
    </div>
  );
}
