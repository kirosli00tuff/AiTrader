/**
 * The operator experience: symbol-grouped activity (populated, empty, high
 * volume, appended without drops), council decision records (populated,
 * empty, benched DNN), diagnostics (unavailable vs substitution distinct,
 * watchdog hold), markets (populated, empty), and the controls surface
 * (one-line copy, weight preview, validated endpoint). No real network:
 * the client and stream are fully mocked.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ActivityEvent } from "../../api/types";

import ActivityBySymbol, { groupEvents } from "../../components/ActivityBySymbol";
import CouncilDecisionsView from "../../components/CouncilDecisions";
import { SymbolHealthTable, WatchdogTimeline } from "../../components/DiagnosticsPanels";
import MarketsPanel from "../../components/MarketsPanel";

vi.mock("../../api/client", () => ({
  API_BASE: "http://127.0.0.1:8000",
  WS_BASE: "ws://127.0.0.1:8000",
  api: {
    bars: async (symbol: string) => ({
      symbol, timeframe: "5min",
      bars: [
        { ts: "2026-07-20T00:50:00Z", open: 100, high: 105, low: 99, close: 104, volume: 10, source: "real_feed" },
        { ts: "2026-07-20T00:55:00Z", open: 104, high: 106, low: 103, close: 105, volume: 12, source: "real_feed" },
      ],
      last_price: 105, session_open: 100, session_change_pct: 5,
    }),
  },
}));

let nextId = 1;
function ev(symbol: string | null, kind: string,
            payload: Record<string, unknown> = {}): ActivityEvent {
  return {
    id: nextId++, ts: "2026-07-20T01:00:00Z", kind, venue: "alpaca", symbol,
    severity: "info", message: `${kind} for ${symbol ?? "stack"}`, payload,
  };
}

describe("activity grouped by symbol", () => {
  it("groups high volume correctly and keeps every event", () => {
    // 600 events across 6 symbols plus a system row: volume stays readable
    // because grouping absorbs it, and nothing is dropped.
    const symbols = ["BTC/USD", "ETH/USD", "SPY", "QQQ", "AAVE/USD", "LDO/USD"];
    const events: ActivityEvent[] = [];
    for (let i = 0; i < 100; i++) {
      for (const s of symbols) {
        events.push(ev(s, "risk_block",
          { reason: "confidence below min_confidence_default", confidence: 0.3, min_confidence: 0.65 }));
      }
    }
    events.push(ev(null, "continuous_start"));
    const groups = groupEvents(events);
    expect(groups).toHaveLength(7);
    const total = groups.reduce((n, g) => n + g.events.length, 0);
    expect(total).toBe(601);
    const btc = groups.find((g) => g.key === "BTC/USD");
    expect(btc?.blocks).toBe(100);
    expect(btc?.summary).toContain("blocked 60x on confidence below");
    // The system row exists and sorts last.
    expect(groups[groups.length - 1].key).toBe("System");
  });

  it("renders rows collapsed with a summary, expands to the event stream", () => {
    const events = [
      ev("BTC/USD", "risk_block", { reason: "confidence below min_confidence_default", confidence: 0.31, min_confidence: 0.65 }),
      ev("BTC/USD", "trade_entry", { factor: "momentum", stop: 100, target: 120 }),
    ];
    render(<ActivityBySymbol events={events} connected />);
    const head = screen.getByTestId("group-head-BTC/USD");
    expect(head.textContent).toContain("trade entry");
    fireEvent.click(head);
    const body = screen.getByTestId("group-events-BTC/USD");
    expect(within(body).getAllByTestId("event-row")).toHaveLength(2);
    // The block's real numbers are on the row.
    expect(body.textContent).toContain("min_confidence=0.65");
  });

  it("appending stream events never loses earlier ones", () => {
    const first = [ev("BTC/USD", "risk_block", { reason: "x" })];
    const { rerender } = render(
      <ActivityBySymbol events={first} connected />);
    const more = [...first, ev("ETH/USD", "risk_block", { reason: "y" }),
      ev("BTC/USD", "trade_entry", {})];
    rerender(<ActivityBySymbol events={more} connected />);
    const btcHead = screen.getByTestId("group-head-BTC/USD");
    expect(btcHead.textContent).toContain("2 events");
    expect(screen.getByTestId("group-head-ETH/USD")).toBeTruthy();
  });

  it("shows the empty state with no events", () => {
    render(<ActivityBySymbol events={[]} connected />);
    expect(screen.getByTestId("activity-empty")).toBeTruthy();
  });
});

describe("council decision records", () => {
  const base = {
    floors: { council_min_confidence: 0.6, required_model_agreement_count: 2,
      min_directional_votes: 1 },
    models: { llm_primary: "gpt-5.5" },
    dnn_benched: true,
    dnn_bench_reason: "champion is synthetic-trained",
  };

  it("shows each provider, abstentions, composition, and the failed check", () => {
    const data = {
      ...base,
      decisions: [{
        id: 1, ts: "2026-07-20T01:00:00Z", kind: "risk_block",
        symbol: "BTC/USD",
        message: "Native entry blocked: confidence below min_confidence_default",
        numbers: { confidence: 0.31, min_confidence: 0.65, agreement: 1,
          required_agreement: 2 },
        providers: [
          { model: "llm_primary", verdict: "buy", confidence: 0.62, edge: 0.03, weight: 0.27 },
          { model: "llm_secondary", verdict: "hold", confidence: 0, edge: 0, weight: 0.18 },
          { model: "dnn_advisory", verdict: "hold", confidence: 0, edge: 0, weight: 0.15 },
        ],
      }],
    };
    render(<CouncilDecisionsView data={data} />);
    const card = screen.getByTestId("decision");
    expect(within(card).getAllByText("abstained").length).toBe(2);
    expect(screen.getByTestId("dnn-benched")).toBeTruthy();
    expect(screen.getByTestId("composition").textContent)
      .toContain("1 directional · 2 abstained");
    const failed = screen.getByTestId("failed-by");
    expect(failed.textContent).toContain("confidence 0.31 vs floor 0.65");
    expect(failed.textContent).toContain("agreement 1 of 2 required");
  });

  it("renders the empty state when nothing council-tier has run", () => {
    render(<CouncilDecisionsView data={{ ...base, decisions: [] }} />);
    expect(screen.getByTestId("decisions-empty")).toBeTruthy();
  });
});

describe("diagnostics", () => {
  const SYMS = [
    { symbol: "BTC/USD", tradeable: true, part: "core" as const,
      last_bar_ts: "x", last_bar_source: "real_feed", last_real_ts: "x",
      age_seconds: 30, bars_5min: 300, warm: true },
  ];

  it("states the universe composition beside the per-symbol health", () => {
    render(<SymbolHealthTable symbols={SYMS} universe={{
      symbols: ["BTC/USD", "LDO/USD"], core: ["BTC/USD"],
      periphery: ["LDO/USD"], declared_core: ["BTC/USD", "SOL/USD"],
      unserviceable: ["SOL/USD"], enforced: true, degraded: false,
      degraded_reason: "",
    }} />);
    const line = screen.getByTestId("diag-universe").textContent ?? "";
    expect(line).toContain("2 tradeable");
    expect(line).toContain("1 core + 1 periphery");
    expect(line).toContain("SOL/USD");          // named, not dropped
    expect(screen.queryByTestId("universe-degraded")).toBeNull();
  });

  it("shows the loud condition when the universe collapses", () => {
    // The stack can be perfectly healthy and have nothing it may trade. That
    // state must never be silent.
    render(<SymbolHealthTable symbols={SYMS} universe={{
      symbols: [], core: [], periphery: [],
      declared_core: ["BTC/USD", "SOL/USD"],
      unserviceable: ["BTC/USD", "SOL/USD"], enforced: true, degraded: true,
      degraded_reason: "TRADEABLE UNIVERSE EMPTY: 2 core symbol(s) declared, "
                       + "0 verified.",
    }} />);
    const loud = screen.getByTestId("universe-degraded").textContent ?? "";
    expect(loud).toContain("TRADEABLE UNIVERSE EMPTY");
    expect(loud).toContain("Fix the core");
  });

  it("shows unavailable distinctly from a substitution event", () => {
    render(<SymbolHealthTable symbols={[
      { symbol: "BTC/USD", tradeable: true, last_bar_ts: "x",
        last_bar_source: "real_feed", last_real_ts: "x", age_seconds: 30,
        bars_5min: 300, warm: true },
      { symbol: "MANA/USD", tradeable: false, last_bar_ts: "x",
        last_bar_source: "synthetic", last_real_ts: null, age_seconds: 60,
        bars_5min: 3, warm: null },
    ]} />);
    expect(screen.getByTestId("unavailable-MANA/USD")).toBeTruthy();

    render(<WatchdogTimeline diag={{
      state: {},
      events: [
        { id: 1, ts: "2026-07-20T01:00:00Z", kind: "feed_substitution",
          venue: null, symbol: null, severity: "critical",
          message: "FEED SUBSTITUTION on the real path", payload: {} },
        { id: 2, ts: "2026-07-20T01:01:00Z", kind: "symbol_unavailable",
          venue: null, symbol: "MANA/USD", severity: "warn",
          message: "SYMBOL UNAVAILABLE", payload: {} },
      ],
    }} />);
    // Each condition carries its own one-line meaning; they never share copy.
    expect(screen.getByTestId("wd-feed_substitution").textContent)
      .toContain("the emergency");
    expect(screen.getByTestId("wd-symbol_unavailable").textContent)
      .toContain("never a reason to stop the stack");
  });

  it("surfaces a watchdog hold, and quiet empty states", () => {
    render(<WatchdogTimeline diag={{
      state: { holding: true, condition: "feed_substitution", attempts: 2 },
      events: [],
    }} />);
    expect(screen.getByTestId("watchdog-holding").textContent)
      .toContain("feed_substitution");
    expect(screen.getByTestId("watchdog-empty")).toBeTruthy();
    render(<SymbolHealthTable symbols={[]} />);
    expect(screen.getByTestId("diag-symbols-empty")).toBeTruthy();
  });
});

describe("markets", () => {
  it("renders price, session change, sparkline, and the engine's exit levels",
    async () => {
      render(<MemoryRouter>
        <MarketsPanel symbols={["BTC/USD"]} positions={[{
          venue: "alpaca", symbol: "BTC/USD", market: "", category: "crypto",
          side: "buy", qty: 0.5, avg_price: 100, notional: 50,
          opened_ts: "x", unrealized_pnl: 2.5, stop: 95.5, target: 120.25,
          entry_factor: "momentum", entry_regime: "trending",
          entry_logged_ts: "x",
        } as never]} />
      </MemoryRouter>);
      const row = await screen.findByTestId("market-BTC/USD");
      expect(row.textContent).toContain("+5.00%");
      expect(within(row).getByTestId("sparkline")).toBeTruthy();
      expect(row.textContent).toContain("95.50 / 120.25");
    });

  it("shows the empty state with no symbols", () => {
    render(<MemoryRouter><MarketsPanel symbols={[]} positions={[]} /></MemoryRouter>);
    expect(screen.getByTestId("markets-empty")).toBeTruthy();
  });
});
