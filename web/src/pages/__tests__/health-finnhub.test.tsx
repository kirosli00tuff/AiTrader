// The Health view, with the Finnhub row as the case under test.
//
// The view maps whatever the backend returns, so Finnhub renders through the
// same path as every other integration. These pin the three states the operator
// has to tell apart: working (green, with latency), failing (red, with a reason
// naming the fault), and not configured (grey, no fault). The distinction is the
// point of the row. A missing optional key and a rejected key both mean "no
// Finnhub", but only one of them is something to go fix.
//
// The top-strip aggregate is asserted on the BACKEND (tests/test_api_server.py),
// where the summary is computed. StatusBar only renders that summary, and its
// dot math is integration-agnostic, so testing it here would restate the
// backend's semantics against a mock rather than test anything Finnhub-specific.
//
// No real network: the REST client is fully mocked.
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IntegrationCheck, IntegrationState } from "../../api/types";
import HealthPage from "../HealthPage";

const check = (name: string, provider: string, state: IntegrationState,
               reason: string, latency_ms: number | null): IntegrationCheck =>
  ({ name, provider, state, reason, latency_ms });

const OPENAI = check("openai", "OpenAI GPT-5.5", "working", "", 120.5);

const mockIntegrations = vi.fn();

vi.mock("../../api/client", () => ({
  api: { integrations: () => mockIntegrations() },
}));

// Mirrors the backend's own summary math, so a row and the summary never
// disagree in a way the real endpoint could not produce.
const respond = (rows: IntegrationCheck[]) => {
  const configured = rows.filter((r) => r.state !== "not_configured");
  return {
    integrations: rows,
    summary: {
      all_ok: configured.length > 0
        && configured.every((r) => r.state === "working"),
      any_failing: configured.some((r) => r.state === "failing"),
      configured_count: configured.length,
      total: rows.length,
      ts: "2026-07-16T00:00:00Z",
    },
  };
};

const finnhub = (state: IntegrationState, reason: string,
                 latency: number | null) =>
  check("finnhub", "Finnhub (discovery pre-screen)", state, reason, latency);

const view = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

// The row is <td>provider</td> with the name beneath it, so find the provider
// cell and read its whole <tr>. That keeps assertions on the Finnhub row rather
// than on any text that happens to be on the page.
const finnhubRow = async () => {
  const cell = await screen.findByText("Finnhub (discovery pre-screen)");
  const row = cell.closest("tr");
  expect(row).not.toBeNull();
  return row as HTMLTableRowElement;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the Finnhub row in the Health view", () => {
  it("shows working, with its round-trip latency, beside the other rows",
     async () => {
    mockIntegrations.mockResolvedValue(
      respond([OPENAI, finnhub("working", "one quote ok", 87.4)]));
    view(<HealthPage />);

    const row = await finnhubRow();
    expect(row.textContent).toContain("working");
    expect(row.textContent).toContain("87.4 ms");
    expect(row.textContent).toContain("one quote ok");
    expect(row.querySelector(".dot.g")).not.toBeNull();
    // Beside the existing integrations, not instead of them.
    expect(screen.getByText("OpenAI GPT-5.5")).toBeInTheDocument();
  });

  it("shows failing, and says WHY, so a bad key is actionable", async () => {
    mockIntegrations.mockResolvedValue(
      respond([OPENAI, finnhub("failing", "bad key (HTTP 401)", 61.2)]));
    view(<HealthPage />);

    const row = await finnhubRow();
    expect(row.textContent).toContain("failing");
    expect(row.textContent).toContain("bad key (HTTP 401)");
    expect(row.querySelector(".dot.r")).not.toBeNull();
  });

  it("shows a rate limit as its own reason, not as a broken key", async () => {
    // Transient. The operator must not go re-paste a working key over it.
    mockIntegrations.mockResolvedValue(
      respond([finnhub("failing", "rate limited (HTTP 429) after 2 retries",
                       3120.0)]));
    view(<HealthPage />);

    const row = await finnhubRow();
    expect(row.textContent).toContain("rate limited (HTTP 429)");
    expect(row.textContent).not.toContain("bad key");
  });

  it("shows not configured in grey, with no latency and no fault", async () => {
    mockIntegrations.mockResolvedValue(
      respond([OPENAI, finnhub("not_configured", "FINNHUB_API_KEY not set",
                               null)]));
    view(<HealthPage />);

    const row = await finnhubRow();
    expect(row.textContent).toContain("not configured");
    expect(row.querySelector(".dot.d")).not.toBeNull();
    // No key means no call, so there is no round trip to report.
    expect(row.textContent).toContain("—");
    // A missing optional key is not a failure: the page must not say some
    // configured integration is failing on account of it.
    expect(screen.getByText(/All configured integrations pass/))
      .toBeInTheDocument();
  });

  it("never renders a token, whatever the reason carries", async () => {
    // The Finnhub token rides in the query string, unlike every other
    // integration's header auth, so the row is the last place it could surface.
    mockIntegrations.mockResolvedValue(
      respond([finnhub("failing", "network unreachable (URLError)", 12.0)]));
    const { container } = view(<HealthPage />);

    await finnhubRow();
    expect(container.textContent).not.toContain("token=");
  });
});
