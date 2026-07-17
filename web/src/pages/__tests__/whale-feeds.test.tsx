// The two whale sources in Ops, and the Whale Alert row in Health.
//
// THE DEFECT behind this: the health check read the WHALE_ALERT_ENABLED env var,
// which only the bridge is spawned with, so it reported "off" while config said
// on and the key worked. The backend half is asserted in tests/test_api_server.py.
// This is the render half.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { WhaleFeedsPanel } from "../../components/WhaleFeedsPanel";
import HealthPage from "../HealthPage";
import { setDisplayTimeZone } from "../../api/tz";

const FEEDS = {
  sec_edgar: { enabled: true, label: "SEC EDGAR 13F + Form 4",
               detail: "equities, free, keyless, delayed", needs_key: false },
  whale_alert: { enabled: true, keyed: true, label: "Whale Alert (crypto trial)",
                 detail: "crypto on-chain, keyed, opt-in trial", needs_key: true },
  signal_activity: {
    last_ts: "2026-07-17T08:00:00Z", last_24h: 12, total: 2113,
    note: "whale factor signals, combined across both feeds and the offline mock. Raw per-fetch rows are not persisted.",
  },
};

const mockFeeds = vi.fn();
const mockIntegrations = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    whaleFeeds: () => mockFeeds(),
    integrations: () => mockIntegrations(),
  },
}));

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

function row(state: string, reason: string) {
  return {
    integrations: [{ name: "whale_alert", provider: "Whale Alert (crypto trial)",
                     state, reason, latency_ms: state === "working" ? 244.5 : null }],
    summary: { all_ok: state !== "failing", any_failing: state === "failing",
               configured_count: state === "not_configured" ? 0 : 1, total: 1,
               ts: "2026-07-17T08:00:00Z" },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setDisplayTimeZone("America/Vancouver");
  mockFeeds.mockResolvedValue(FEEDS);
  mockIntegrations.mockResolvedValue(row("working", "one tx query ok"));
});

// --- Health view -----------------------------------------------------------

it("shows the Whale Alert row as working with its latency", async () => {
  view(<HealthPage />);
  const cell = await screen.findByText("Whale Alert (crypto trial)");
  const tr = cell.closest("tr")!;
  expect(within(tr).getByText("one tx query ok")).toBeTruthy();
  expect(within(tr).getByText("244.5 ms")).toBeTruthy();
  expect(tr.querySelector(".dot.g")).toBeTruthy();     // green
});

it("shows a failing Whale Alert red with its classified reason", async () => {
  mockIntegrations.mockResolvedValue(row("failing", "bad key (HTTP 401)"));
  view(<HealthPage />);
  const tr = (await screen.findByText("Whale Alert (crypto trial)")).closest("tr")!;
  expect(within(tr).getByText("bad key (HTTP 401)")).toBeTruthy();
  expect(tr.querySelector(".dot.r")).toBeTruthy();     // red
});

it("shows a rate-limited Whale Alert as rate limited, never as a bad key", async () => {
  mockIntegrations.mockResolvedValue(
    row("failing", "rate limited (HTTP 429) after 2 retries"));
  view(<HealthPage />);
  const tr = (await screen.findByText("Whale Alert (crypto trial)")).closest("tr")!;
  expect(within(tr).getByText(/rate limited/)).toBeTruthy();
  expect(within(tr).queryByText(/bad key/)).toBeNull();
});

it("shows an off Whale Alert grey, and it does not count as a failure", async () => {
  mockIntegrations.mockResolvedValue(
    row("not_configured", "whale_alert_enabled is off"));
  view(<HealthPage />);
  const tr = (await screen.findByText("Whale Alert (crypto trial)")).closest("tr")!;
  expect(tr.querySelector(".dot.d")).toBeTruthy();     // grey
  expect(within(tr).getByText("—")).toBeTruthy();      // no latency
});

// The "never renders the key" assertion lives in tests/test_api_server.py
// (test_whale_alert_health_never_returns_the_key), NOT here, and deliberately.
//
// It was here first, asserting the DOM lacked "api_key=" against a mock that had
// no key in it: an assertion that could not fail. Making it real (mocking a
// reason that CARRIES a keyed URL) fails, because HealthPage renders the reason
// verbatim, which is correct: the guard is the backend classifying its own
// failures into fixed phrases so a key never reaches `reason` at all. That
// backend test raises an HTTPError whose URL contains the key and asserts the
// response does not, which is the same claim at the layer that can actually
// enforce it. Masking in the UI would only hide a backend bug behind a mangled
// string.

// --- Ops panel -------------------------------------------------------------

it("shows both whale feeds side by side, so the operator sees which is which",
   async () => {
  view(<WhaleFeedsPanel />);
  const sec = await screen.findByTestId("feed-sec-edgar");
  const wa = await screen.findByTestId("feed-whale-alert");
  expect(within(sec).getByText("SEC EDGAR 13F + Form 4")).toBeTruthy();
  expect(within(wa).getByText("Whale Alert (crypto trial)")).toBeTruthy();
  expect(within(sec).getByText("ON")).toBeTruthy();
  expect(within(wa).getByText("ON")).toBeTruthy();
});

it("reads a disabled feed as intentionally off, not as broken", async () => {
  mockFeeds.mockResolvedValue({
    ...FEEDS, whale_alert: { ...FEEDS.whale_alert, enabled: false } });
  view(<WhaleFeedsPanel />);
  const wa = await screen.findByTestId("feed-whale-alert");
  expect(within(wa).getByText("off by choice")).toBeTruthy();
  expect(wa.querySelector(".dot.d")).toBeTruthy();     // grey, not red
});

it("flags an OFF feed that has no key, so the prerequisite is visible first", async () => {
  // The operator deciding whether to enable it is exactly who needs to know a
  // key is missing. Showing this only when enabled hid it from them until after
  // they turned it on and restarted.
  mockFeeds.mockResolvedValue({
    ...FEEDS, whale_alert: { ...FEEDS.whale_alert, enabled: false, keyed: false } });
  view(<WhaleFeedsPanel />);
  const wa = await screen.findByTestId("feed-whale-alert");
  expect(within(wa).getByText("off by choice")).toBeTruthy();
  expect(within(wa).getByText("no key")).toBeTruthy();
  // Still grey, not amber: it is off by choice, and the key is a note not a fault.
  expect(wa.querySelector(".dot.d")).toBeTruthy();
});

it("flags an enabled feed that has no key, since it cannot work", async () => {
  mockFeeds.mockResolvedValue({
    ...FEEDS, whale_alert: { ...FEEDS.whale_alert, enabled: true, keyed: false } });
  view(<WhaleFeedsPanel />);
  const wa = await screen.findByTestId("feed-whale-alert");
  expect(within(wa).getByText("no key")).toBeTruthy();
  expect(wa.querySelector(".dot.a")).toBeTruthy();     // amber
});

it("shows recent whale-signal activity with its last timestamp", async () => {
  view(<WhaleFeedsPanel />);
  const a = await screen.findByTestId("whale-activity");
  expect(a.textContent).toContain("12");        // last 24h
  expect(a.textContent).toContain("2113");      // total, unformatted
});

it("says what the activity count actually is, so it is not read as fetches",
   async () => {
  // whale_activity (raw per-fetch rows) is empty by design. The number is the
  // combined whale FACTOR's signals, and the panel has to say so or the operator
  // reads it as "Whale Alert fetched 12 times".
  view(<WhaleFeedsPanel />);
  const note = await screen.findByTestId("whale-activity-note");
  expect(note.textContent).toContain("combined across both feeds");
  expect(note.textContent).toContain("not persisted");
});

it("reads zero activity as none yet rather than a broken feed", async () => {
  mockFeeds.mockResolvedValue({
    ...FEEDS, signal_activity: { ...FEEDS.signal_activity, last_24h: 0, total: 0,
                                 last_ts: null } });
  view(<WhaleFeedsPanel />);
  const a = await screen.findByTestId("whale-activity");
  expect(a.textContent).toContain("No whale signals recorded yet");
});
