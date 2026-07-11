import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Category, Mode, Order, SignalsResponse, Trade } from "../api/types";
import { DataState, Empty, Panel } from "../components/ui";
import PositionsTable from "../components/PositionsTable";
import StalenessBadge from "../components/StalenessBadge";
import TradeDetailModal from "../components/TradeDetailModal";
import { ClosedTradesTable, OrdersTable, SignalsTable } from "../components/Tables";

const LABEL: Record<Category, string> = {
  stocks: "Stocks (SPY, QQQ)", crypto: "Crypto (BTC/USD, ETH/USD)",
};

interface Ctx { locked: boolean; }

// Positions, open orders, closed trades, and signals for one category. Live +
// locked zeroes everything. Trade rows are clickable for a detail view.
export default function CategoryView({ mode, category }: {
  mode: Mode; category: Category;
}) {
  const { locked } = useOutletContext<Ctx>();
  const off = mode === "live" && locked;
  const [sel, setSel] = useState<number | null>(null);

  const posApi = useApi(
    () => off ? Promise.resolve({ mode, positions: [] })
              : api.positions(mode, category), off ? 0 : 6000, [mode, category, off]);
  const ordApi = useApi(
    () => off ? Promise.resolve({ mode, orders: [] as Order[] })
              : api.orders(mode, 60, category), off ? 0 : 6000, [mode, category, off]);
  const trdApi = useApi(
    () => off ? Promise.resolve({ mode, trades: [] as Trade[] })
              : api.trades(mode, 100, category), off ? 0 : 6000, [mode, category, off]);
  const sigApi = useApi<SignalsResponse>(
    () => off ? Promise.resolve({ signals: [], regimes: [] })
              : api.signals(category), off ? 0 : 8000, [category, off]);

  const openOrders = (ordApi.data?.orders ?? []).filter((o) => (o.outcome ?? "open") === "open");
  const sigs = sigApi.data?.signals ?? [];

  if (off) {
    return (
      <Panel title={LABEL[category]}>
        <Empty>Live trading is disabled. All {category} data is zeroed.</Empty>
      </Panel>
    );
  }

  return (
    <div className="grid">
      <Panel title={`${LABEL[category]} · positions`}>
        <DataState loading={posApi.loading && !posApi.data} error={posApi.error}>
          <div className="between" style={{ marginBottom: 8 }}>
            <span className="dim" style={{ fontSize: 12 }}>{(posApi.data?.positions ?? []).length} open</span>
            <StalenessBadge ts={(posApi.data?.positions ?? [])[0]?.opened_ts} thresholdSec={180} label="positions" />
          </div>
          <PositionsTable positions={posApi.data?.positions ?? []} />
        </DataState>
      </Panel>
      <Panel title="Open orders">
        <DataState loading={ordApi.loading && !ordApi.data} error={ordApi.error}>
          <OrdersTable orders={openOrders} onSelect={setSel} />
        </DataState>
      </Panel>
      <Panel title="Closed trades">
        <DataState loading={trdApi.loading && !trdApi.data} error={trdApi.error}>
          <ClosedTradesTable trades={trdApi.data?.trades ?? []} onSelect={setSel} />
        </DataState>
      </Panel>
      <Panel title="Signals">
        <DataState loading={sigApi.loading && !sigApi.data} error={sigApi.error}>
          <div className="between" style={{ marginBottom: 8 }}>
            <span className="dim" style={{ fontSize: 12 }}>click a trade row for detail</span>
            <StalenessBadge ts={sigs[0]?.ts} thresholdSec={180} label="signals" />
          </div>
          <SignalsTable signals={sigs} />
        </DataState>
      </Panel>
      {sel != null && <TradeDetailModal tradeId={sel} onClose={() => setSel(null)} />}
    </div>
  );
}
