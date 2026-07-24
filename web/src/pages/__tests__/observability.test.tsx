/**
 * The three observability views (2026-07-24): position health banner,
 * near-miss view, factor participation. Each renders honestly against empty
 * and degraded data (absent reads as absent, no exception), and the two
 * blind spots that cost defects are visible: a past-stop position is
 * unmissable, and a benched factor reads differently from a live one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FactorParticipationPanel from "../../components/FactorParticipationPanel";
import MarketsPanel from "../../components/MarketsPanel";
import NearMissPanel from "../../components/NearMissPanel";
import type { NearMisses, PositionExit } from "../../api/types";

vi.mock("../../api/client", () => ({
  API_BASE: "http://127.0.0.1:8000",
  WS_BASE: "ws://127.0.0.1:8000",
  api: { bars: async () => ({ symbol: "X", timeframe: "5min", bars: [],
                              last_price: null, session_open: null,
                              session_change_pct: null }) },
}));

const ethPastStop: PositionExit = {
  venue: "alpaca", symbol: "ETH/USD", market: "ETH/USD", category: "crypto",
  side: "buy", qty: 0.17, avg_price: 2030.69, notional: 350,
  opened_ts: "2026-07-17T07:00:10Z", unrealized_pnl: 0,
  stop: 1993.66, target: 2086.23, entry_factor: "momentum",
  entry_regime: "trending", entry_logged_ts: "2026-07-17T07:00:10Z",
  health: {
    last_price: 1868.0, last_price_ts: "2026-07-23T00:00:00Z",
    unmanageable_reason: null, missing_exit_state: false,
    past_stop: true, past_stop_pct: 6.3,
    past_target: false, past_target_pct: null,
    time_stop_overdue: false, time_stop_overdue_bars: null,
    managed: true,
  },
} as unknown as PositionExit;

describe("position health", () => {
  it("makes a past-stop position unmissable, with its numbers", () => {
    render(<MarketsPanel symbols={[]} positions={[ethPastStop]} />);
    const alert = screen.getByTestId("position-alert-ETH/USD");
    expect(alert).toHaveTextContent(/PAST STOP by 6.3%/);
    expect(alert).toHaveTextContent(/1993.66/);
  });

  it("renders empty positions without an exception", () => {
    render(<MarketsPanel symbols={[]} positions={[]} />);
    expect(screen.getByTestId("markets-empty")).toBeInTheDocument();
  });
});

describe("near misses", () => {
  const data: NearMisses = {
    window_hours: 24, entered: 1, min_confidence: 0.65,
    by_reject: [{ first_reject: "risk_gate:confidence", n: 27 }],
    by_symbol: [{ symbol: "ETH/USD", n: 12 }],
    rows: [{
      id: 1, ts: "2026-07-23T10:00:00Z", symbol: "ETH/USD",
      regime: "trending", factor: "reversion",
      first_reject: "risk_gate:confidence", tier: "fast",
      confidence: 0.488, edge: 0.03,
      state: { rsi2: 9.1 }, distances: { confidence_gap: -0.162 },
      factors: [{ factor: "rule_based", bias: 0.5, confidence: 0.88,
                  edge: 0.07 }],
    }],
  };

  it("shows the dominating refusal condition at a glance", () => {
    render(<NearMissPanel data={data} windowHours={24} onWindow={() => {}} />);
    expect(screen.getByTestId("nearmiss-by-reject"))
      .toHaveTextContent(/risk_gate:confidence: 27/);
    expect(screen.getByTestId("nm-row-1")).toHaveTextContent(/-0.1620/);
  });

  it("renders an empty window honestly (no data is not no rejections)", () => {
    render(<NearMissPanel data={{ ...data, rows: [], by_reject: [],
                                  by_symbol: [], entered: 0 }}
             windowHours={24} onWindow={() => {}} />);
    expect(screen.getByTestId("nearmiss-none")).toBeInTheDocument();
  });

  it("renders a down stack honestly", () => {
    render(<NearMissPanel data={undefined} windowHours={24}
             onWindow={() => {}} />);
    expect(screen.getByTestId("nearmiss-empty")).toBeInTheDocument();
  });
});

describe("factor participation", () => {
  it("a benched factor reads differently from a live low-confidence one", () => {
    render(<FactorParticipationPanel data={{
      bridge_reachable: true, dnn_benched: true, dnn_bench_reason: "pending",
      factors: [
        { factor: "whale_signal", status: "live",
          reason: "real service reachable",
          last_signal: { ts: "2026-07-23T10:00:00Z", confidence: 0.518 } },
        { factor: "dnn_advisory", status: "benched",
          reason: "benched pending real training", last_signal: {} },
        { factor: "llm_primary", status: "mock_bridge_down",
          reason: "bridge unreachable", last_signal: {} },
      ],
    }} />);
    expect(screen.getByTestId("fp-status-whale_signal"))
      .toHaveTextContent("LIVE");
    expect(screen.getByTestId("fp-status-dnn_advisory"))
      .toHaveTextContent("BENCHED");
    expect(screen.getByTestId("fp-status-llm_primary"))
      .toHaveTextContent(/MOCK \(bridge down\)/);
  });

  it("renders a down stack honestly", () => {
    render(<FactorParticipationPanel data={undefined} />);
    expect(screen.getByTestId("participation-empty")).toBeInTheDocument();
  });
});
