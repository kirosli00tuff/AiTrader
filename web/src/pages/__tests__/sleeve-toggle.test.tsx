// The research_satellite sleeve enable toggle.
//
// THE DEFECT this covers: the long-term strategy's prerequisite panel demanded
// the research_satellite sleeve be enabled first, and the sleeve toggle that
// existed wrote a control file the engine never read. The panel said so to the
// operator's face ("the toggle here records intent"), and the prerequisite ANDed
// the toggle with a config value no endpoint can write, so the check could not
// be satisfied from the interface at all.
//
// What matters here is the ceremony and the honesty: enabling ALLOCATES capital,
// so it arms and says what it does first, and the panel reports the sleeve's real
// state either way. The backend half (validated write, engine consumption,
// prerequisite) is asserted in tests/test_api_server.py, where it lives.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { SleevesPanel } from "../../components/SleevesPanel";

const SLEEVES = {
  targets: { quant_core: 0.7, research_satellite: 0.3 },
  drift_band: 0.05,
  hard_cap_pct: 0.35,
  allocation: { quant_core: 7000, research_satellite: 2400, invested_total: 9400 },
  satellite_share: 0.2553,
  rebalance_due: false,
  enabled: { quant_core: true, research_satellite: false },
  research_satellite_config_enabled: false,
  open_positions: { quant_core: 4, research_satellite: 2 },
};

const mockSleeves = vi.fn();
const mockSetSleeve = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    sleeves: () => mockSleeves(),
    setSleeve: (s: string, e: boolean) => mockSetSleeve(s, e),
    researchTheses: () => Promise.resolve({ theses: [] }),
    discoveryState: () => Promise.resolve(null),
    requestRebalance: () => Promise.resolve({ ok: true }),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  mockSleeves.mockResolvedValue(SLEEVES);
  mockSetSleeve.mockResolvedValue({ ok: true, sleeve: "research_satellite",
                                    enabled: true });
});

it("renders the research_satellite sleeve toggle", async () => {
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");
  expect(within(box).getByText("research_satellite sleeve")).toBeTruthy();
  // It reports the sleeve's state, not just offering a switch.
  expect(within(box).getByText("off")).toBeTruthy();
  expect(within(box).getByText("enable")).toBeTruthy();
});

it("arms before it fires, and says what enabling the sleeve does", async () => {
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");

  // Arming must not write. An allocation decision is never one click.
  fireEvent.click(within(box).getByText("enable"));
  expect(mockSetSleeve).not.toHaveBeenCalled();

  const confirm = await screen.findByTestId("toggle-research-satellite-confirm");
  const text = confirm.textContent ?? "";
  // The confirm states the allocation plainly, with the real numbers.
  expect(text).toContain("allocates capital");
  expect(text).toContain("30%");        // the configured target
  expect(text).toContain("35%");        // the hard cap it can never exceed
  expect(text).toContain("drift band");
  expect(text).toContain("RiskGate");
  // It must NOT claim to start spending: enabling a sleeve allocates, and a
  // confirm that cries wolf trains the operator to skip reading it.
  expect(text).not.toContain("starts spending");
  // And it tells the operator what this unlocks, since that is why they are here.
  expect(text).toContain("long-term strategy");
});

it("writes through the validated endpoint only after confirm", async () => {
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");
  fireEvent.click(within(box).getByText("enable"));
  fireEvent.click(await within(box).findByText("confirm"));
  await waitFor(() =>
    expect(mockSetSleeve).toHaveBeenCalledWith("research_satellite", true));
});

it("cancel abandons the enable without writing", async () => {
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");
  fireEvent.click(within(box).getByText("enable"));
  fireEvent.click(await within(box).findByText("cancel"));
  expect(mockSetSleeve).not.toHaveBeenCalled();
  expect(screen.queryByTestId("toggle-research-satellite-confirm")).toBeNull();
});

it("a disabled sleeve reads as intentionally off, not as broken", async () => {
  view(<SleevesPanel />);
  const state = await screen.findByTestId("satellite-state");
  expect(state.textContent).toContain("off by choice");
  expect(state.textContent).toContain("holds no capital");
});

it("an enabled sleeve shows its allocation against the 30 percent target", async () => {
  mockSleeves.mockResolvedValue({
    ...SLEEVES, enabled: { quant_core: true, research_satellite: true } });
  view(<SleevesPanel />);
  const state = await screen.findByTestId("satellite-state");
  const text = state.textContent ?? "";
  expect(text).toContain("ON");
  expect(text).toContain("$2,400");     // what it actually holds
  expect(text).toContain("of 30%");     // against the target
  expect(text).toContain("cap 35%");
  expect(text).not.toContain("off by choice");
});

it("disable is immediate: turning a sleeve off never needs a ceremony", async () => {
  mockSleeves.mockResolvedValue({
    ...SLEEVES, enabled: { quant_core: true, research_satellite: true } });
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");
  fireEvent.click(within(box).getByText("disable"));
  await waitFor(() =>
    expect(mockSetSleeve).toHaveBeenCalledWith("research_satellite", false));
});

it("the sleeve toggle is never blocked by a prerequisite", async () => {
  // The sleeve has no prerequisite beyond the engine running: it allocates, it
  // does not call anything. The four-level framework and the bridge are what the
  // long-term STRATEGY needs, and they are checked at that toggle. Gating the
  // sleeve on them would make the enable order circular.
  view(<SleevesPanel />);
  const box = await screen.findByTestId("toggle-research-satellite");
  expect(screen.queryByTestId("toggle-research-satellite-blocked")).toBeNull();
  expect(within(box).getByText("enable")).not.toHaveProperty("disabled", true);
});

it("explains an on-sleeve that overrides a config that ships off", async () => {
  // The old note told the operator the toggle only "records intent". It no
  // longer does: the engine reads the control file every iteration, so the note
  // has to say which source is actually winning.
  mockSleeves.mockResolvedValue({
    ...SLEEVES, enabled: { quant_core: true, research_satellite: true },
    research_satellite_config_enabled: false });
  view(<SleevesPanel />);
  const note = await screen.findByTestId("sleeve-config-note");
  expect(note.textContent).toContain("control file");
  expect(note.textContent).toContain("every iteration");
  expect(note.textContent).not.toContain("records intent");
});
