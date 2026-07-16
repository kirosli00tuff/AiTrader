// Discovery + long-term enable toggles and tunables.
//
// These toggles start spenders, so the tests care most about the ceremony: an
// enable arms and states what it starts before it fires, a missing prerequisite
// blocks it with a reason, and a disable is never blocked.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiscoveryControls } from "../../components/DiscoveryControls";
import { setDisplayTimeZone } from "../../api/tz";

const OK_PREREQS = {
  ok: true,
  checks: [
    { key: "finnhub_key", ok: true, label: "Finnhub API key", detail: "resolving" },
    { key: "bridge", ok: true, label: "Python bridge", detail: "reachable" },
  ],
};

const BAD_PREREQS = {
  ok: false,
  checks: [
    { key: "finnhub_key", ok: false, label: "Finnhub API key",
      detail: "not configured. Save one in Settings under Discovery data." },
    { key: "bridge", ok: true, label: "Python bridge", detail: "reachable" },
  ],
};

const STATE = {
  enabled: false,
  long_term_sleeve_enabled: false,
  last_pass: { crypto: null as string | null, equity: null as string | null },
  watchlist_size: 0,
  watchlist_max: 40,
  universe: { crypto_active_max: 50, crypto_universe: 55, equity_universe: 119 },
  ceilings: { max_finalists: 12, max_survivors: 5, max_council_calls_per_pass: 5 },
  cadence: { crypto_interval_minutes: 60, equity_interval_minutes: 60 },
  stage_a_whale_weight: 0.15,
  budget: { daily: 12, used_today: 0, remaining: 12, est_cost_per_call: 0.04,
            est_spend_today: 0 },
  bounds: {
    discovery_daily_council_budget: [0, 100] as [number, number],
    max_finalists: [1, 50] as [number, number],
    max_survivors: [1, 20] as [number, number],
    max_council_calls_per_pass: [0, 20] as [number, number],
    crypto_interval_minutes: [15, 1440] as [number, number],
    equity_interval_minutes: [15, 1440] as [number, number],
    stage_a_whale_weight: [0, 1] as [number, number],
  },
  prerequisites: OK_PREREQS,
  longterm_prerequisites: OK_PREREQS,
  react_layer_built: false,
};

const mockState = vi.fn();
const mockSetDiscovery = vi.fn();
const mockSetLongTerm = vi.fn();
const mockSetSettings = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    discoveryState: () => mockState(),
    setDiscovery: (e: boolean) => mockSetDiscovery(e),
    setLongTerm: (e: boolean) => mockSetLongTerm(e),
    setDiscoverySettings: (s: Record<string, number>) => mockSetSettings(s),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  setDisplayTimeZone("America/Vancouver");
  mockState.mockResolvedValue(STATE);
  mockSetDiscovery.mockResolvedValue({ ok: true, discovery_enabled: true });
  mockSetLongTerm.mockResolvedValue({ ok: true, long_term_sleeve_enabled: true });
  mockSetSettings.mockResolvedValue({ ok: true, discovery: {}, clamped: {} });
});

describe("enable toggles ask before they spend", () => {
  it("does not fire on the first click: it arms", async () => {
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    // Armed, not fired. Nothing has been turned on yet.
    expect(mockSetDiscovery).not.toHaveBeenCalled();
    expect(screen.getByTestId("toggle-discovery-confirm")).toBeInTheDocument();
  });

  it("states plainly what turning discovery on starts", async () => {
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    const confirm = screen.getByTestId("toggle-discovery-confirm");
    expect(within(confirm).getByText(/This starts spending/)).toBeInTheDocument();
    // The real numbers, not a vague warning.
    expect(confirm.textContent).toContain("hourly funnel passes");
    expect(confirm.textContent).toContain("12 call/day discovery budget");
    expect(confirm.textContent).toContain("separate from and additive to");
    expect(confirm.textContent).toContain("$0.48");   // 12 * $0.04 ceiling
  });

  it("fires only on confirm", async () => {
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(mockSetDiscovery).toHaveBeenCalledWith(true));
  });

  it("cancel disarms without firing", async () => {
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(mockSetDiscovery).not.toHaveBeenCalled();
    expect(screen.queryByTestId("toggle-discovery-confirm")).toBeNull();
  });

  it("states what the long-term sleeve starts, including the hard cap", async () => {
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-longterm");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    const confirm = screen.getByTestId("toggle-longterm-confirm");
    expect(confirm.textContent).toContain("quality and catalyst");
    expect(confirm.textContent).toContain("35 percent of equity");
    expect(confirm.textContent).toContain("can never exceed");
    expect(confirm.textContent).toContain("RiskGate still judges every order");
  });

  it("disables immediately, with no ceremony", async () => {
    mockState.mockResolvedValue({ ...STATE, enabled: true });
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "disable" }));
    // Turning a spender OFF should never need a confirm.
    await waitFor(() => expect(mockSetDiscovery).toHaveBeenCalledWith(false));
  });
});

describe("prerequisite warnings", () => {
  it("blocks enable and says what is missing", async () => {
    mockState.mockResolvedValue({ ...STATE, prerequisites: BAD_PREREQS });
    view(<DiscoveryControls />);
    const blocked = await screen.findByTestId("toggle-discovery-blocked");
    expect(within(blocked).getByText(/Cannot enable yet/)).toBeInTheDocument();
    expect(blocked.textContent).toContain("Finnhub API key");
    // It tells the operator where to go, rather than just refusing.
    expect(blocked.textContent).toContain("Settings under Discovery data");
    // And the enable button cannot be pressed into a broken state.
    const box = screen.getByTestId("toggle-discovery");
    expect(within(box).getByRole("button", { name: "enable" })).toBeDisabled();
  });

  it("shows no block when every prerequisite is met", async () => {
    view(<DiscoveryControls />);
    await screen.findByTestId("toggle-discovery");
    expect(screen.queryByTestId("toggle-discovery-blocked")).toBeNull();
  });

  it("surfaces a server refusal", async () => {
    mockSetDiscovery.mockResolvedValue({
      ok: false, error: "missing prerequisite: Python bridge" });
    view(<DiscoveryControls />);
    const box = await screen.findByTestId("toggle-discovery");
    fireEvent.click(within(box).getByRole("button", { name: "enable" }));
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    // The server is the authority: even if the GUI thought it was fine, a
    // refusal is shown rather than swallowed.
    expect(await screen.findByTestId("disc-msg")).toHaveTextContent(
      /missing prerequisite: Python bridge/);
  });
});

describe("settings controls", () => {
  it("shows current values and the server's own bounds", async () => {
    view(<DiscoveryControls />);
    const budget = await screen.findByLabelText("Discovery budget (calls/day)");
    expect(budget).toHaveValue(12);
    expect(screen.getByText(/0 to 100 · separate from the trading budget/))
      .toBeInTheDocument();
    expect(await screen.findByLabelText("Whale surfacing weight"))
      .toHaveValue(0.15);
    expect(screen.getByText(/0 to 1 · 0 disables surfacing/)).toBeInTheDocument();
  });

  it("commits a changed value through the validated endpoint", async () => {
    view(<DiscoveryControls />);
    const f = await screen.findByLabelText("Stage A finalists");
    fireEvent.change(f, { target: { value: "20" } });
    fireEvent.blur(f);
    await waitFor(() =>
      expect(mockSetSettings).toHaveBeenCalledWith({ max_finalists: 20 }));
  });

  it("does not post when the value did not change", async () => {
    view(<DiscoveryControls />);
    const f = await screen.findByLabelText("Stage A finalists");
    fireEvent.blur(f);
    expect(mockSetSettings).not.toHaveBeenCalled();
  });

  it("says when the server clamped a value", async () => {
    mockSetSettings.mockResolvedValue({
      ok: true, discovery: {}, clamped: { max_finalists: 50 } });
    view(<DiscoveryControls />);
    const f = await screen.findByLabelText("Stage A finalists");
    fireEvent.change(f, { target: { value: "9999" } });
    fireEvent.blur(f);
    // Never silently show a different number than the operator typed.
    expect(await screen.findByTestId("disc-msg")).toHaveTextContent(
      /clamped to bounds: max_finalists=50/);
  });

  it("says Level 1 stays out of reach", async () => {
    view(<DiscoveryControls />);
    expect(await screen.findByText(/Level 1 risk limits are not/))
      .toBeInTheDocument();
  });
});

describe("state visibility", () => {
  it("reads calm when off", async () => {
    view(<DiscoveryControls />);
    const s = await screen.findByTestId("disc-state");
    expect(s.textContent).toContain("Discovery is off");
    expect(s.textContent).toContain("no council call is spent");
  });

  it("shows it working when on", async () => {
    mockState.mockResolvedValue({
      ...STATE, enabled: true, watchlist_size: 3,
      last_pass: { crypto: "2026-07-16T02:00:00Z", equity: null },
      budget: { ...STATE.budget, used_today: 4, est_spend_today: 0.16 },
    });
    view(<DiscoveryControls />);
    const s = await screen.findByTestId("disc-state");
    // Last pass in the operator's local zone, budget against its ceiling.
    expect(s.textContent).toContain("7:00 PM PDT");
    expect(s.textContent).toContain("budget 4/12 calls today");
    expect(s.textContent).toContain("$0.16");
    expect(s.textContent).toContain("watchlist 3/40");
  });

  it("states the react layer is not built", async () => {
    view(<DiscoveryControls />);
    expect(await screen.findByText(/news-react layer is not built/))
      .toBeInTheDocument();
  });
});
