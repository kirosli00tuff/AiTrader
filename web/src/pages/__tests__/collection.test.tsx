// The collection landing view.
//
// The first tests are the ones that matter: the rendered page must contain no
// outcome quantity. The backend refuses to send one, and these assert the page
// would not display one even if a future payload carried it.
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import CollectionPage from "../CollectionPage";
import App from "../../App";
import { api } from "../../api/client";

const mockMonitor = vi.spyOn(api, "collectionMonitor");

// Every outcome quantity, named here so the test is a second opinion rather
// than a mirror of the backend's own list.
const OUTCOME_FIELDS = [
  "ret_intraday", "ret_1session", "ret_2session", "ret_5session",
  "ret_10session", "bench_1session", "excess_1session", "net_bp",
  "cost_bp_round_trip", "anchor_price",
];

const PAYLOAD = {
  generated_utc: "2026-03-05T22:31:00Z",
  db_present: true,
  outcome_columns_excluded: OUTCOME_FIELDS,
  exclusion_note: "The holdout is evaluated ONCE, at stage 4.",
  progress: {
    day_clusters: 2, cluster_floor: 60, hard_stop: 120,
    clusters_to_floor: 58, clusters_to_hard_stop: 118,
    meets_cluster_floor: false, at_hard_stop: false,
    judged: 5, judged_target: 1000, scored_directional: 4,
    first_session: "2026-03-02", last_session: "2026-03-03",
    per_stratum: [
      { stratum: "S1", day_clusters: 2, judged: 3, cluster_floor: 30, meets_floor: false },
      { stratum: "S3", day_clusters: 1, judged: 1, cluster_floor: 30, meets_floor: false },
    ],
  },
  run_health: {
    log_present: true, runs_recorded: 2,
    last_run: { started_utc: "2026-03-05T22:30:00Z", action: "collected",
                target: "2026-03-05", formation: "2026-01-02", exit_code: 0,
                gaps: [] },
    recent_runs: [], gaps: [] as string[], gap_count: 0,
    timer: { known: true, timer_active: true, next_fire_utc: "2026-03-06T22:30:00Z",
             unit_failed: false, last_trigger_utc: null, error: null },
    calendar: { known: true, sessions_behind: 1, next_expected: "2026-03-04" },
  },
  composition: {
    total_rows: 8,
    states: { judged: 5, no_news: 1, excluded_pre_call: 1, model_failed: 1 },
    excluded_pre_call_by_error_class: { duplicate_headline: 1 },
    model_failed_by_error_class: { timeout: 1 },
    source_failed_fraction: 0, source_failed_critical: false,
    day_excluded_risk: false, excluded_outcomes: {},
    non_collection_rows: { demonstration: 1 },
  },
  judgment: {
    positive: 2, negative: 2, neutral: 1, directional: 4,
    neutral_rate: 0.2, neutral_reportable_failure_bar: 0.8,
    neutral_rate_reportable_failure: false,
    minority_share: 0.5, minority_share_floor: 0.1,
    mixed_day_clusters: 2, mixed_cluster_floor: 30, null_informative: false,
    per_stratum: [],
  },
  strength: {
    histogram: { 2: 1, 3: 2, 4: 1 }, scored_directional: 4,
    distinct_values: 3, unparseable: 0, neutral_strength_anomalies: 0,
    degenerate: false,
  },
  spend: {
    total_usd: 0.002775, calls: 5, per_call: 0.000555,
    measured_per_call: 0.000555, per_call_drift_pct: 0,
    per_session: [{ session: "2026-03-03", usd: 0.001665, calls: 3 }],
  },
  alarms: [] as { level: string; code: string; message: string }[],
};

const view = (ui: ReactElement) =>
  render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  mockMonitor.mockResolvedValue(structuredClone(PAYLOAD) as never);
});

it("renders no outcome quantity anywhere on the page", async () => {
  view(<CollectionPage />);
  await screen.findByText("Progress");
  const text = document.body.textContent ?? "";
  // The excluded-columns line NAMES them deliberately, so it is removed before
  // the check: the page must not show an outcome as a value, while still being
  // able to state which ones it refuses to show.
  const note = screen.getByTestId("exclusion-note").textContent ?? "";
  const withoutNote = text.replace(note, "");
  for (const field of OUTCOME_FIELDS) {
    expect(withoutNote).not.toContain(field);
  }
});

it("never renders an outcome value even if the payload carries one", async () => {
  // Defence in depth: the component reads named fields only, so an extra key
  // in the payload cannot reach the DOM.
  const leaky = structuredClone(PAYLOAD) as Record<string, unknown>;
  (leaky.progress as Record<string, unknown>).excess_1session = 0.4242;
  (leaky.progress as Record<string, unknown>).net_bp = 91.7;
  mockMonitor.mockResolvedValue(leaky as never);
  view(<CollectionPage />);
  await screen.findByText("Progress");
  const text = document.body.textContent ?? "";
  expect(text).not.toContain("0.4242");
  expect(text).not.toContain("91.7");
});

it("shows progress against the registered floors", async () => {
  view(<CollectionPage />);
  expect(await screen.findByText(/Day clusters/)).toBeTruthy();
  expect(screen.getByText("/ 60")).toBeTruthy();
  expect(screen.getByText("/ 1000")).toBeTruthy();
  expect(screen.getByText(/58 more trading sessions/)).toBeTruthy();
});

it("shows each stratum against the 30-cluster E-test floor", async () => {
  view(<CollectionPage />);
  const s1 = await screen.findByTestId("stratum-S1");
  expect(s1.textContent).toContain("/ 30");
  expect(s1.textContent).toContain("below the 30-cluster floor");
});

it("reports a clear state when there are no alarms", async () => {
  view(<CollectionPage />);
  expect(await screen.findByTestId("alarms-clear")).toBeTruthy();
});

it("surfaces an unrecoverable gap as a critical alarm", async () => {
  const gapped = structuredClone(PAYLOAD);
  gapped.run_health.gaps = ["2026-03-04"];
  gapped.run_health.gap_count = 1;
  gapped.alarms = [{
    level: "critical", code: "gap_unrecoverable",
    message: "Session 2026-03-04 completed and was never collected. UNRECOVERABLE by design.",
  }];
  mockMonitor.mockResolvedValue(gapped as never);
  view(<CollectionPage />);
  const alarm = await screen.findByTestId("alarm-gap_unrecoverable");
  expect(alarm.textContent).toContain("CRITICAL");
  expect(alarm.textContent).toContain("UNRECOVERABLE");
  expect((await screen.findByTestId("gap-summary")).textContent)
    .toContain("2026-03-04");
});

it("surfaces a failed timer unit as a critical alarm", async () => {
  const failed = structuredClone(PAYLOAD);
  failed.run_health.timer.unit_failed = true;
  failed.alarms = [{
    level: "critical", code: "unit_failed",
    message: "news-collect.service is in the failed state.",
  }];
  mockMonitor.mockResolvedValue(failed as never);
  view(<CollectionPage />);
  const alarm = await screen.findByTestId("alarm-unit_failed");
  expect(alarm.textContent).toContain("CRITICAL");
  expect(screen.getByText("FAILED")).toBeTruthy();
});

it("shows the minority share against its uninformative floor", async () => {
  view(<CollectionPage />);
  const share = await screen.findByTestId("minority-share");
  expect(share.textContent).toContain("50.0%");
  expect(share.textContent).toContain("floor 10%");
});

it("keeps the two failure states apart rather than summing them", async () => {
  view(<CollectionPage />);
  await screen.findByText("Sample composition");
  expect(screen.getByText(/excluded_pre_call by error class/)).toBeTruthy();
  expect(screen.getByText(/model_failed by error class/)).toBeTruthy();
  expect(screen.getByText(/Never summed with the above/)).toBeTruthy();
});

it("names the rows that cannot count toward the sample", async () => {
  view(<CollectionPage />);
  await screen.findByText(/rows that cannot count/);
  expect(screen.getByText("demonstration")).toBeTruthy();
});

it("is the landing view, so the daily check is opening a tab", async () => {
  // Routed at "/", which is what makes it the default rather than a
  // destination the operator has to remember to navigate to.
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Collection" }))
    .toBeTruthy();
});
