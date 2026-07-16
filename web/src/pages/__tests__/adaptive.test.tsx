// Adaptive real-time layer: toggles, cost warnings, and the event view.
//
// The toggles start a spender and, in one case, let a live event move a
// position. So the tests care most about the ceremony and the honesty: an enable
// arms and states what it starts, a missing prerequisite blocks it with a
// reason, a disable is never blocked, and the page shows what was DROPPED rather
// than only what was acted on.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdaptiveControls } from "../../components/AdaptiveControls";
import AdaptivePage from "../AdaptivePage";
import { setDisplayTimeZone } from "../../api/tz";

const OK_PREREQS = {
  ok: true,
  checks: [
    { key: "finnhub_key", ok: true, label: "Finnhub API key", detail: "resolving" },
    { key: "anthropic_key", ok: true,
      label: "Anthropic API key (event interpretation)", detail: "resolving" },
  ],
};

const BAD_PREREQS = {
  ok: false,
  checks: [
    { key: "finnhub_key", ok: false, label: "Finnhub API key",
      detail: "not configured. Save one in Settings under Discovery data." },
    { key: "anthropic_key", ok: true,
      label: "Anthropic API key (event interpretation)", detail: "resolving" },
  ],
};

const SETTINGS = {
  poll_interval_seconds: 60,
  max_symbols_per_poll: 30,
  news_lookback_minutes: 15,
  adaptive_daily_llm_budget: 20,
  max_interpretations_per_poll: 3,
  action_max_age_seconds: 300,
  materiality_min_sentiment: 0.55,
  action_min_severity: 0.6,
  interpretation_min_relevance: 0.4,
  defensive_trim_fraction: 0.5,
};

const BOUNDS: Record<string, [number, number]> = {
  poll_interval_seconds: [15, 3600],
  max_symbols_per_poll: [1, 60],
  news_lookback_minutes: [1, 240],
  adaptive_daily_llm_budget: [0, 200],
  max_interpretations_per_poll: [0, 20],
  action_max_age_seconds: [30, 3600],
  materiality_min_sentiment: [0, 1],
  action_min_severity: [0, 1],
  interpretation_min_relevance: [0, 1],
  defensive_trim_fraction: [0.01, 1],
};

const STATE = {
  news_feed_enabled: false,
  watchlist_shaping_enabled: false,
  react_defensive_enabled: false,
  last_poll: null as string | null,
  last_poll_status: null as string | null,
  today: {
    events_seen: 0, events_material: 0, events_escalated: 0,
    events_dropped_free: 0, actions_queued: 0, referrals: 0,
  },
  budget: {
    daily: 20, used_today: 0, remaining: 20, est_cost_per_call: 0.02,
    est_spend_today: 0, est_max_daily: 0.4,
  },
  settings: SETTINGS,
  bounds: BOUNDS,
  prerequisites: OK_PREREQS,
  aggressive_entry_path_exists: false as const,
};

const ON = { ...STATE, news_feed_enabled: true };

const mockState = vi.fn();
const mockSetAdaptive = vi.fn();
const mockSetSettings = vi.fn();
const mockEvents = vi.fn();
const mockInterps = vi.fn();
const mockActions = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    adaptiveState: () => mockState(),
    setAdaptive: (f: string, e: boolean) => mockSetAdaptive(f, e),
    setAdaptiveSettings: (s: Record<string, number>) => mockSetSettings(s),
    adaptiveEvents: () => mockEvents(),
    adaptiveInterpretations: () => mockInterps(),
    adaptiveActions: () => mockActions(),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  setDisplayTimeZone("America/Vancouver");
  mockState.mockResolvedValue(STATE);
  mockSetAdaptive.mockResolvedValue({ ok: true });
  mockSetSettings.mockResolvedValue({ ok: true, clamped: {} });
  mockEvents.mockResolvedValue({ events: [], enabled: false });
  mockInterps.mockResolvedValue({ interpretations: [] });
  mockActions.mockResolvedValue({ actions: [], engine_log: [] });
});

describe("the asymmetry is stated, not buried", () => {
  it("says a live event can only ever make the engine more cautious", async () => {
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("adaptive-asymmetry");
    expect(box.textContent).toContain("more cautious");
    expect(box.textContent).toContain("no toggle for event-driven buying");
    expect(box.textContent).toContain("no such code path");
    // It says WHY, with the actual mechanism, rather than just asserting safety.
    expect(box.textContent).toContain("refer the symbol back through the discovery");
    expect(box.textContent).toContain("RiskGate");
  });

  it("offers exactly three toggles, none of them aggressive", async () => {
    view(<AdaptiveControls />);
    await screen.findByTestId("toggle-adaptive-feed");
    expect(screen.getByTestId("toggle-adaptive-shaping")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-adaptive-react")).toBeInTheDocument();
    // There is no fourth toggle, because there is no fourth capability.
    expect(screen.queryByText(/aggressive react/i)).toBeNull();
    expect(screen.queryByText(/event-driven entry/i)).toBeNull();
  });
});

describe("enable toggles ask before they spend", () => {
  it("does not fire on the first click: it arms", async () => {
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    expect(mockSetAdaptive).not.toHaveBeenCalled();
    expect(screen.getByTestId("toggle-adaptive-feed-confirm")).toBeInTheDocument();
  });

  it("states plainly what turning the feed on starts, and what it costs", async () => {
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    const confirm = screen.getByTestId("toggle-adaptive-feed-confirm");
    expect(confirm.textContent).toContain("every 60s");
    expect(confirm.textContent).toContain("FREE");
    expect(confirm.textContent).toContain("20 read/day");
    expect(confirm.textContent).toContain("separate from and additive to");
    expect(confirm.textContent).toContain("$0.40");
    // Observing is not acting, and the confirm says so.
    expect(confirm.textContent).toContain("opens no position");
  });

  it("states that the react toggle is the one that can move a position", async () => {
    mockState.mockResolvedValue(ON);
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-react");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    const confirm = screen.getByTestId("toggle-adaptive-react-confirm");
    expect(confirm.textContent).toContain(
      "only toggle that lets a live event change a POSITION");
    expect(confirm.textContent).toContain("SHRINK or freeze");
    expect(confirm.textContent).toContain("closes 50%");
    expect(confirm.textContent).toContain("older than 300s is refused");
    expect(confirm.textContent).toContain("never open or increase one");
  });

  it("states that shaping does not open a position", async () => {
    mockState.mockResolvedValue(ON);
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-shaping");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    const confirm = screen.getByTestId("toggle-adaptive-shaping-confirm");
    expect(confirm.textContent).toContain(
      "Adding to the watchlist does not open a position");
    expect(confirm.textContent).toContain("NOT tradeable");
  });

  it("fires only on confirm, with the right flag name", async () => {
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(mockSetAdaptive)
      .toHaveBeenCalledWith("adaptive_news_feed_enabled", true));
  });

  it("cancel disarms without firing", async () => {
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(mockSetAdaptive).not.toHaveBeenCalled();
    expect(screen.queryByTestId("toggle-adaptive-feed-confirm")).toBeNull();
  });

  it("disables immediately, with no ceremony", async () => {
    mockState.mockResolvedValue(ON);
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "disable" }));
    await waitFor(() => expect(mockSetAdaptive)
      .toHaveBeenCalledWith("adaptive_news_feed_enabled", false));
  });
});

describe("prerequisites and ordering", () => {
  it("blocks the feed and says what is missing", async () => {
    mockState.mockResolvedValue({ ...STATE, prerequisites: BAD_PREREQS });
    view(<AdaptiveControls />);
    const blocked = await screen.findByTestId("toggle-adaptive-feed-blocked");
    expect(blocked.textContent).toContain("Finnhub API key");
    expect(blocked.textContent).toContain("Settings under Discovery data");
    const box = screen.getByTestId("toggle-adaptive-feed");
    expect(within(box).getByRole("button", { name: "enable" })).toBeDisabled();
  });

  it("blocks the downstream halves until the feed is on", async () => {
    view(<AdaptiveControls />);
    const react = await screen.findByTestId("toggle-adaptive-react-blocked");
    expect(react.textContent).toContain("news feed must be on first");
    const shaping = screen.getByTestId("toggle-adaptive-shaping-blocked");
    expect(shaping.textContent).toContain("news feed must be on first");
    expect(within(screen.getByTestId("toggle-adaptive-react"))
      .getByRole("button", { name: "enable" })).toBeDisabled();
  });

  it("surfaces a server refusal", async () => {
    mockSetAdaptive.mockResolvedValue({
      ok: false, error: "missing prerequisite: Finnhub API key" });
    view(<AdaptiveControls />);
    const box = await screen.findByTestId("toggle-adaptive-feed");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    expect(await screen.findByTestId("adaptive-msg")).toHaveTextContent(
      /missing prerequisite: Finnhub API key/);
  });
});

describe("settings", () => {
  it("shows current values and the server's own bounds", async () => {
    view(<AdaptiveControls />);
    expect(await screen.findByLabelText("Adaptive budget (reads/day)"))
      .toHaveValue(20);
    expect(screen.getByText(
      /0 to 200 · separate from the discovery and trading budgets/))
      .toBeInTheDocument();
    expect(screen.getByLabelText("Action max age (seconds)")).toHaveValue(300);
    expect(screen.getByText(/30 to 3600 · stale news never moves a position/))
      .toBeInTheDocument();
  });

  it("commits a changed value through the validated endpoint", async () => {
    view(<AdaptiveControls />);
    const f = await screen.findByLabelText("Adaptive budget (reads/day)");
    fireEvent.change(f, { target: { value: "40" } });
    fireEvent.blur(f);
    await waitFor(() => expect(mockSetSettings)
      .toHaveBeenCalledWith({ adaptive_daily_llm_budget: 40 }));
  });

  it("says when the server clamped a value", async () => {
    mockSetSettings.mockResolvedValue({
      ok: true, clamped: { adaptive_daily_llm_budget: 200 } });
    view(<AdaptiveControls />);
    const f = await screen.findByLabelText("Adaptive budget (reads/day)");
    fireEvent.change(f, { target: { value: "9999" } });
    fireEvent.blur(f);
    expect(await screen.findByTestId("adaptive-msg")).toHaveTextContent(
      /clamped to bounds: adaptive_daily_llm_budget=200/);
  });

  it("says Level 1 stays out of reach", async () => {
    view(<AdaptiveControls />);
    expect(await screen.findByText(/Level 1 risk limits are not/))
      .toBeInTheDocument();
  });
});

describe("state visibility", () => {
  it("reads calm when off", async () => {
    view(<AdaptiveControls />);
    const s = await screen.findByTestId("adaptive-state");
    expect(s.textContent).toContain("Adaptive layer is off");
    expect(s.textContent).toContain("no token is spent");
  });

  it("shows it working when on", async () => {
    mockState.mockResolvedValue({
      ...ON,
      last_poll: "2026-07-16T02:00:00Z",
      today: { ...ON.today, events_seen: 120, events_dropped_free: 117,
               events_escalated: 3 },
      budget: { ...ON.budget, used_today: 3, est_spend_today: 0.06 },
    });
    view(<AdaptiveControls />);
    const s = await screen.findByTestId("adaptive-state");
    expect(s.textContent).toContain("7:00 PM PDT");  // operator's local zone
    expect(s.textContent).toContain("120 events seen");
    expect(s.textContent).toContain("117 dropped free");
    expect(s.textContent).toContain("budget 3/20");
  });
});

describe("the page shows what was dropped, not just what was acted on", () => {
  it("reads calm and explains itself when off", async () => {
    view(<AdaptivePage />);
    const box = await screen.findByTestId("adaptive-disabled");
    expect(box.textContent).toContain("no token is spent");
    expect(box.textContent).toContain("shipped default, not a fault");
    // It says what WOULD run, so the operator can sanity-check before opting in.
    expect(box.textContent).toContain("never open or increase a position");
  });

  it("lists dropped events with their reason, alongside the escalated ones",
     async () => {
    mockState.mockResolvedValue(ON);
    mockEvents.mockResolvedValue({
      enabled: true,
      events: [
        { id: 2, ts: "2026-07-16T09:31:00Z", published_ts: null, symbol: "SPY",
          headline: "Trading halted amid fraud probe", source: "Reuters",
          category: "company", sentiment: -0.8, event_type: "halt", held: 1,
          material: 1, material_reason: "keyword:fraud", escalated: 1 },
        { id: 1, ts: "2026-07-16T09:30:00Z", published_ts: null, symbol: "SPY",
          headline: "Shares drift in quiet trade", source: "Reuters",
          category: "company", sentiment: 0.02, event_type: null, held: 0,
          material: 0, material_reason: "no_trigger", escalated: 0 },
      ],
    });
    view(<AdaptivePage />);
    expect(await screen.findByText("Trading halted amid fraud probe"))
      .toBeInTheDocument();
    // The dropped one is SHOWN, with why. Hiding it would hide the cost story.
    expect(screen.getByText("Shares drift in quiet trade")).toBeInTheDocument();
    expect(screen.getByText("no_trigger")).toBeInTheDocument();
    expect(screen.getByText(/Most of this list should be dim/))
      .toBeInTheDocument();
  });

  it("shows an aggressive read being declined", async () => {
    mockState.mockResolvedValue(ON);
    mockInterps.mockResolvedValue({
      interpretations: [{
        id: 1, event_id: 1, ts: "2026-07-16T09:31:00Z", symbol: "TSLA",
        relevance: 0.9, direction: "bullish", severity: 0.8, action: "open",
        action_class: "aggressive", rationale: "takeover rumor",
        model: "claude-haiku-4-5", est_cost_usd: 0.02, outcome: "referred",
        outcome_reason: "offered to the funnel",
        headline: "Takeover rumor lifts shares",
      }],
    });
    view(<AdaptivePage />);
    // The model said buy; the system referred it instead. That is the whole
    // design, visible on one row.
    expect(await screen.findByText("aggressive")).toBeInTheDocument();
    expect(screen.getByText("referred")).toBeInTheDocument();
    expect(screen.getByText(/offered to the funnel/)).toBeInTheDocument();
  });

  it("separates a queued action from what the engine actually did", async () => {
    mockState.mockResolvedValue(ON);
    mockActions.mockResolvedValue({
      actions: [{
        id: 1, ts: "2026-07-16T09:31:00Z", event_id: 1, symbol: "SPY",
        action: "exit", reason: "trading halted", severity: 0.95,
        source: "adaptive_react",
      }],
      engine_log: [{
        ts: "2026-07-16T09:31:05Z", type: "adaptive_defensive", symbol: "SPY",
        severity: "warn",
        message: "Adaptive exit SPY qty=5.000000 pnl=-12.500000: trading halted",
        payload: null,
      }],
    });
    view(<AdaptivePage />);
    expect(await screen.findByText("exit")).toBeInTheDocument();
    expect(screen.getByText(/Queued is not applied/)).toBeInTheDocument();
    expect(screen.getByText(/What the engine did/)).toBeInTheDocument();
    expect(screen.getByText(/Adaptive exit SPY/)).toBeInTheDocument();
  });
});
