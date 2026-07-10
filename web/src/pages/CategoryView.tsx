import { useOutletContext } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Category, Mode, Order, SignalsResponse, Trade } from "../api/types";
import { DataState, Empty, Panel } from "../components/ui";
import PositionsTable from "../components/PositionsTable";
import { ClosedTradesTable, OrdersTable, SignalsTable } from "../components/Tables";

const LABEL: Record<Category, string> = { stocks: "Stocks (SPY, QQQ)", crypto: "Crypto (BTC/USD, ETH/USD)" };

interface Ctx { locked: boolean; }

// Positions, open orders, closed trades, and signals for one category. Live +
// locked zeroes everything (no fetch); paper (and any unlocked live) fetches
// the category-filtered slices server-side.
export default function CategoryView({ mode, category }: {
  mode: Mode; category: Category;
}) {
  const { locked } = useOutletContext<Ctx>();
  const off = mode === "live" && locked;

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
          <PositionsTable positions={posApi.data?.positions ?? []} />
        </DataState>
      </Panel>
      <Panel title="Open orders">
        <DataState loading={ordApi.loading && !ordApi.data} error={ordApi.error}>
          <OrdersTable orders={openOrders} />
        </DataState>
      </Panel>
      <Panel title="Closed trades">
        <DataState loading={trdApi.loading && !trdApi.data} error={trdApi.error}>
          <ClosedTradesTable trades={trdApi.data?.trades ?? []} />
        </DataState>
      </Panel>
      <Panel title="Signals">
        <DataState loading={sigApi.loading && !sigApi.data} error={sigApi.error}>
          <SignalsTable signals={sigApi.data?.signals ?? []} />
        </DataState>
      </Panel>
    </div>
  );
}
