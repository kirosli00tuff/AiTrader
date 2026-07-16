// Render tests for the three discovery views, in both the DISABLED and the
// POPULATED state.
//
// The disabled case matters as much as the populated one: discovery ships off,
// so the state an operator sees on day one is the empty one, and it must read as
// deliberate rather than broken.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DiscoveryPage from "../DiscoveryPage";
import WatchlistPage from "../WatchlistPage";
import LongTermPage from "../LongTermPage";
import { setDisplayTimeZone } from "../../api/tz";

// --- fixtures ---------------------------------------------------------------

const STATE_OFF = {
  enabled: false,
  long_term_sleeve_enabled: false,
  last_pass: { crypto: null, equity: null },
  watchlist_size: 0,
  watchlist_max: 40,
  universe: { crypto_active_max: 50, crypto_universe: 55, equity_universe: 119 },
  ceilings: { max_finalists: 12, max_survivors: 5, max_council_calls_per_pass: 5 },
  budget: { daily: 12, used_today: 0, remaining: 12, est_cost_per_call: 0.04,
            est_spend_today: 0 },
  react_layer_built: false,
};

const STATE_ON = {
  ...STATE_OFF,
  enabled: true,
  long_term_sleeve_enabled: true,
  last_pass: { crypto: "2026-07-16T02:00:00Z", equity: "2026-07-16T02:05:00Z" },
  watchlist_size: 2,
  budget: { daily: 12, used_today: 3, remaining: 9, est_cost_per_call: 0.04,
            est_spend_today: 0.12 },
};

const PASS = {
  id: 1,
  ts: "2026-07-16T02:00:00Z",
  asset_class: "crypto",
  universe_count: 50,
  finalists_count: 12,
  survivors_count: 5,
  evaluated_count: 2,
  council_calls: 2,
  gate_calls: 12,
  est_cost_usd: 0.08,
  budget_remaining: 10,
  status: "ok",
  reason: "",
  drops: [
    { symbol: "DOGE/USD", stage: "A", reason: "below_min_score", score: 0.04 },
    { symbol: "ADA/USD", stage: "B", reason: "gate: too quiet", score: 0.33 },
    { symbol: "DOT/USD", stage: "C", reason: "pass_council_ceiling", score: 0.41 },
  ],
};

const WATCHLIST = [
  { symbol: "NVDA", asset_class: "equity", added_ts: "2026-07-15T02:00:00Z",
    updated_ts: "2026-07-16T02:05:00Z", source: "discovery",
    reason: "discovery buy conviction 0.88", sleeve_target: "research_satellite",
    score: 0.88, status: "active" },
  { symbol: "SOL/USD", asset_class: "crypto", added_ts: "2026-07-16T02:00:00Z",
    updated_ts: "2026-07-16T02:00:00Z", source: "discovery",
    reason: "discovery buy conviction 0.82", sleeve_target: "quant_core",
    score: 0.82, status: "active" },
];

const WATCHLIST_EVENTS = [
  { ts: "2026-07-16T02:00:00Z", action: "add", symbol: "SOL/USD",
    source: "discovery", reason: "discovery buy 0.82", applied: 1 },
  { ts: "2026-07-16T02:00:00Z", action: "remove", symbol: "XRP/USD",
    source: "prune", reason: "signal stale", applied: 1 },
  { ts: "2026-07-16T02:01:00Z", action: "add", symbol: "PEPE/USD",
    source: "adaptive_react", reason: "breaking headline", applied: 0 },
];

const LT_POSITION = {
  venue: "alpaca", symbol: "NVDA", category: "equity", side: "buy",
  qty: 10, avg_price: 180, notional: 1800,
  opened_ts: "2026-07-16T02:05:00Z", unrealized_pnl: 150,
  thesis_ts: "2026-07-16T02:05:00Z", direction: "long", conviction: 0.88,
  horizon: "months",
  rationale: "Long-term long on NVDA. Quality 0.71, catalyst earnings.",
  thesis_status: "open", target: 240, invalidation_price: 150,
  invalidation: "close below 150.00 (thesis broken)", entry_price: 180,
  status_vs_thesis: "on thesis",
};

// --- mock client ------------------------------------------------------------

const mockState = vi.fn();
const mockLatest = vi.fn();
const mockWatchlist = vi.fn();
const mockLongterm = vi.fn();
const mockTheses = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    discoveryState: () => mockState(),
    discoveryLatest: () => mockLatest(),
    watchlist: () => mockWatchlist(),
    longtermPositions: () => mockLongterm(),
    researchTheses: () => mockTheses(),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  setDisplayTimeZone("America/Vancouver");
  mockState.mockResolvedValue(STATE_OFF);
  mockLatest.mockResolvedValue({ passes: [], enabled: false });
  mockWatchlist.mockResolvedValue({ watchlist: [], events: [], enabled: false });
  mockLongterm.mockResolvedValue({
    positions: [], enabled: false, strategy_enabled: false,
    sleeve_config_enabled: false, sleeve_toggle_enabled: false });
  mockTheses.mockResolvedValue({ theses: [] });
});

// --- disabled state ---------------------------------------------------------

describe("discovery views, disabled state", () => {
  it("says discovery is off deliberately, not broken", async () => {
    view(<DiscoveryPage />);
    const box = await screen.findByTestId("discovery-disabled");
    expect(within(box).getByText(/DISCOVERY DISABLED/)).toBeTruthy();
    expect(within(box).getByText(/shipped default, not a fault/)).toBeTruthy();
    // It names the exact key to flip, so the operator is not left guessing.
    expect(within(box).getByText("discovery.discovery_enabled")).toBeTruthy();
  });

  it("shows what would run when enabled, from real config values", async () => {
    view(<DiscoveryPage />);
    const box = await screen.findByTestId("discovery-disabled");
    expect(within(box).getByText(/55 crypto curated/)).toBeTruthy();
    expect(within(box).getByText(/119 equities/)).toBeTruthy();
    expect(within(box).getByText(/12 finalists/)).toBeTruthy();
    expect(within(box).getByText(/12 discovery council calls\/day/)).toBeTruthy();
  });

  it("states the react layer is not built", async () => {
    view(<DiscoveryPage />);
    const box = await screen.findByTestId("discovery-disabled");
    expect(within(box).getByText(/news-react layer is not built/)).toBeTruthy();
    expect(
      within(box).getByText(/No entry is ever taken on a raw headline/)).toBeTruthy();
  });

  it("renders an empty funnel without a pass, and no error", async () => {
    view(<DiscoveryPage />);
    expect(await screen.findByText(/No discovery pass recorded yet/)).toBeTruthy();
    expect(screen.queryByText(/Could not load/)).toBeNull();
  });

  it("watchlist shows the disabled state and an empty list", async () => {
    view(<WatchlistPage />);
    expect(await screen.findByTestId("discovery-disabled")).toBeTruthy();
    expect(screen.getByText(/Nothing on the watchlist/)).toBeTruthy();
  });

  it("long-term names BOTH flags a hold needs", async () => {
    view(<LongTermPage />);
    const box = await screen.findByTestId("longterm-disabled");
    expect(within(box).getByText(/LONG-TERM SLEEVE DISABLED/)).toBeTruthy();
    // Two distinct flags, both shown, because both must hold.
    expect(within(box).getByText("sleeves.research_satellite_enabled")).toBeTruthy();
    expect(within(box).getByText("discovery.long_term_sleeve_enabled")).toBeTruthy();
    expect(within(box).getByText(/ceiling, not a floor/)).toBeTruthy();
  });
});

// --- populated state --------------------------------------------------------

describe("discovery funnel view, populated", () => {
  beforeEach(() => {
    mockState.mockResolvedValue(STATE_ON);
    mockLatest.mockResolvedValue({ passes: [PASS], enabled: true });
  });

  it("renders the funnel narrowing with every stage count", async () => {
    view(<DiscoveryPage />);
    const funnel = await screen.findByTestId("funnel");
    // universe 50 -> finalists 12 -> survivors 5 -> evaluated 2.
    expect(within(funnel).getByText("50")).toBeTruthy();
    expect(within(funnel).getByText("12")).toBeTruthy();
    expect(within(funnel).getByText("5")).toBeTruthy();
    expect(within(funnel).getByText("2")).toBeTruthy();
  });

  it("states what each stage costs, so the narrowing reads as cost control", async () => {
    view(<DiscoveryPage />);
    const funnel = await screen.findByTestId("funnel");
    expect(within(funnel).getByText("0 tokens (free pre-screen)")).toBeTruthy();
    expect(within(funnel).getByText("12 haiku gate calls")).toBeTruthy();
    expect(within(funnel).getByText("2 full council calls")).toBeTruthy();
  });

  it("shows the pass cost against the discovery budget", async () => {
    view(<DiscoveryPage />);
    expect(await screen.findByText(/\$0\.08/)).toBeTruthy();
    expect(
      screen.getByText(/discovery budget left today: 10 \/ 12 calls/)).toBeTruthy();
  });

  it("lists every drop with its stage and reason", async () => {
    view(<DiscoveryPage />);
    expect(await screen.findByText("below_min_score")).toBeTruthy();
    expect(screen.getByText("gate: too quiet")).toBeTruthy();
    expect(screen.getByText("pass_council_ceiling")).toBeTruthy();
    expect(screen.getByText(/Stage A · free pre-screen · dropped 1/)).toBeTruthy();
    expect(screen.getByText(/Stage B · haiku gate · dropped 1/)).toBeTruthy();
    expect(screen.getByText(/Stage C · four-level · dropped 1/)).toBeTruthy();
  });

  it("renders the pass time in the operator local timezone", async () => {
    view(<DiscoveryPage />);
    // 2026-07-16T02:00:00Z is 7:00 PM PDT on 2026-07-15 in America/Vancouver.
    await waitFor(() => expect(screen.getByText(/7:00 PM PDT/)).toBeTruthy());
  });
});

describe("watchlist view, populated", () => {
  beforeEach(() => {
    mockState.mockResolvedValue(STATE_ON);
    mockWatchlist.mockResolvedValue({
      watchlist: WATCHLIST, events: WATCHLIST_EVENTS, enabled: true });
  });

  it("shows why each instrument is on the list and its sleeve target", async () => {
    view(<WatchlistPage />);
    const table = await screen.findByTestId("watchlist-table");
    expect(within(table).getByText("NVDA")).toBeTruthy();
    expect(within(table).getByText("discovery buy conviction 0.88")).toBeTruthy();
    // Sleeve target reads as a plain word, not a raw enum.
    expect(within(table).getByText("long-term")).toBeTruthy();
    expect(within(table).getByText("quant")).toBeTruthy();
  });

  it("shows the list against its cap", async () => {
    view(<WatchlistPage />);
    expect(await screen.findByText(/On the list \(2 \/ 40 max\)/)).toBeTruthy();
  });

  it("shows recent adds and prunes so the list looks alive", async () => {
    view(<WatchlistPage />);
    const feed = await screen.findByTestId("watchlist-events");
    expect(within(feed).getByText(/\+ SOL\/USD/)).toBeTruthy();
    expect(within(feed).getByText(/- XRP\/USD/)).toBeTruthy();
    expect(within(feed).getByText(/signal stale/)).toBeTruthy();
  });

  it("shows a REFUSED event from the not-yet-enabled react source", async () => {
    view(<WatchlistPage />);
    const feed = await screen.findByTestId("watchlist-events");
    // Visible, not hidden: a silently dropped event would be worse.
    expect(within(feed).getByText(/REFUSED \(source not enabled\)/)).toBeTruthy();
    expect(within(feed).getByText(/adaptive_react/)).toBeTruthy();
  });

  it("renders added and last-confirmed times in the local timezone", async () => {
    view(<WatchlistPage />);
    const table = await screen.findByTestId("watchlist-table");
    // 2026-07-16T02:05:00Z -> 7:05 PM PDT on 2026-07-15.
    await waitFor(() =>
      expect(within(table).getByText(/7:05 PM PDT/)).toBeTruthy());
  });
});

describe("long-term sleeve view, populated", () => {
  beforeEach(() => {
    mockLongterm.mockResolvedValue({
      positions: [LT_POSITION], enabled: true, strategy_enabled: true,
      sleeve_config_enabled: true, sleeve_toggle_enabled: true });
    mockTheses.mockResolvedValue({ theses: [{
      ts: "2026-07-16T02:05:00Z", symbol: "NVDA", direction: "long",
      conviction: 0.88, horizon: "months",
      rationale: "Quality 0.71, catalyst earnings.", status: "open" }] });
  });

  it("renders the full thesis so the operator reads WHY it is held", async () => {
    view(<LongTermPage />);
    expect(await screen.findByText(/NVDA · long/)).toBeTruthy();
    expect(screen.getByText("0.88")).toBeTruthy();          // conviction
    expect(screen.getByText("months")).toBeTruthy();        // horizon
    expect(screen.getByText(/close below 150\.00 \(thesis broken\)/)).toBeTruthy();
    expect(screen.getByText(/Long-term long on NVDA/)).toBeTruthy();
  });

  it("shows entry date, target, and current PnL", async () => {
    view(<LongTermPage />);
    await screen.findByText(/NVDA · long/);
    expect(screen.getByText(/held since/)).toBeTruthy();
    expect(screen.getByText("$240.00")).toBeTruthy();        // target
    expect(screen.getByText("$150.00")).toBeTruthy();        // unrealized pnl
  });

  it("shows where the position sits against its thesis", async () => {
    view(<LongTermPage />);
    expect(await screen.findByText("on thesis")).toBeTruthy();
  });

  it("renders the research feed of recent theses", async () => {
    view(<LongTermPage />);
    const feed = await screen.findByTestId("research-feed");
    expect(within(feed).getByText("NVDA")).toBeTruthy();
    expect(within(feed).getByText(/Quality 0\.71/)).toBeTruthy();
  });

  it("says so when a thesis predates the long-term strategy", async () => {
    // A thesis from the original council path carries no levels. The view must
    // say that rather than invent a target the engine is not holding.
    mockLongterm.mockResolvedValue({
      positions: [{ ...LT_POSITION, target: null, invalidation_price: null,
                    invalidation: null }],
      enabled: true, strategy_enabled: true, sleeve_config_enabled: true,
      sleeve_toggle_enabled: true });
    view(<LongTermPage />);
    expect(await screen.findByText(/predates the long-term strategy/)).toBeTruthy();
  });
});

// --- no key leaks -----------------------------------------------------------

describe("discovery views never render a credential", () => {
  it("renders named fields, never a raw payload dump", async () => {
    const canary = "CANARY-VIEW-KEY-MUST-NOT-APPEAR-9z8y";
    mockState.mockResolvedValue(STATE_ON);
    mockLatest.mockResolvedValue({
      passes: [{ ...PASS, rationale: canary, secret_field: canary }],
      enabled: true });
    const { container } = view(<DiscoveryPage />);
    await screen.findByTestId("funnel");
    // The view renders specific named fields only, so an unexpected key in a
    // payload can never reach the DOM.
    expect(container.textContent).not.toContain(canary);
  });
});
