import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// No real network: the stream hook and the REST client are fully mocked.
vi.mock("../../api/useStream", () => ({
  useStream: () => ({ snapshot: null, connected: false }),
}));

vi.mock("../../api/client", () => {
  const pnl = {
    mode: "paper",
    equity_curve: [
      { ts: "2026-07-06T00:00:00Z", equity: 100000 },
      { ts: "2026-07-06T01:00:00Z", equity: 100120 },
    ],
    daily_pnl: [{ day: "2026-07-06", pnl: 8.5 }],
    win_rate: 50, wins: 1, losses: 1, n_trades: 2, total_pnl: 8.5,
    equity: 100120, equity_change: 120, equity_change_pct: 0.12,
    max_drawdown_pct: -0.2,
  };
  return {
    API_BASE: "http://127.0.0.1:8000",
    WS_BASE: "ws://127.0.0.1:8000",
    api: {
      health: async () => ({
        status: "ok", db_present: true,
        engine: { db_present: true, last_event_ts: "x", kill_switch_tripped: false, running: true },
        bridge: { reachable: true, url: "", status: "ok" },
      }),
      account: async () => ({
        mode: "paper", equity: 100120, cash: 90000, realized_pnl: 120,
        unrealized_pnl: 0, drawdown_pct: -0.2, venues: [],
      }),
      pnl: async () => pnl,
      positions: async () => ({
        mode: "paper",
        positions: [{ venue: "alpaca", symbol: "SPY", side: "buy", qty: 1, avg_price: 540, notional: 540, opened_ts: "x", unrealized_pnl: 1.25 }],
      }),
      orders: async () => ({
        mode: "paper",
        orders: [{ id: 1, ts: "2026-07-06T01:00:00Z", venue: "alpaca", symbol: "BTC/USD", side: "buy", qty: 0.01, price: 60000, notional: 600, mode: "paper", outcome: "win", pnl: 12.5 }],
      }),
      signals: async () => ({
        signals: [{ ts: "x", venue: "alpaca", symbol: "BTC/USD", factor: "rule_based", bias: 0.4, confidence: 0.7, edge: 0.03, regime: "trending" }],
        regimes: [{ symbol: "BTC/USD", regime: "trending", adx: 31, rvol: 0.04, updated_ts: "x" }],
      }),
      council: async () => ({
        models: { llm_primary: "gpt-5.5", llm_secondary: "claude-opus-4-8", llm_tertiary: "gemini-3.1-pro", llm_gate: "gemini-3-flash" },
        latest: [{ ts: "x", model: "gpt-5.5", verdict: "buy", confidence: 0.7, edge: 0.03, weight: 0.27 }],
        recent: [],
      }),
      risk: async () => ({ level1: {}, kill_switch_enabled: true, kill_switch_tripped: false }),
      venues: async () => ({
        venues: [{ venue: "alpaca", mode: "paper", live_enabled: false, live_adapter: "none", runtime_mode: "paper", credentials_connected: true, kill_switch_tripped: false, configured: true }],
      }),
      approval: async () => ({
        live_enabled: false, manual_confirmation: false, last_checked_ts: "x",
        mechanisms: [
          { name: "Live approval gate passed", key: "approval_gate", passed: false, detail: "d" },
          { name: "Live credentials connected", key: "credentials_connected", passed: false, detail: "d" },
          { name: "Kill switch clear", key: "kill_switch", passed: true, detail: "d" },
          { name: "Live-enabled flag set", key: "live_enabled", passed: false, detail: "d" },
        ],
        readiness: null, all_passed: false, live_venue: "ibkr",
      }),
      credentials: async () => ({
        credentials: [
          { name: "openai_key", label: "API key", group: "openai", group_label: "OpenAI (GPT-5.5)", kind: "source", mode: null, secret: true, configured: false, source: "missing", masked: "" },
          { name: "alpaca_paper_key", label: "API key", group: "alpaca", group_label: "Alpaca", kind: "venue", mode: "paper", secret: true, configured: false, source: "missing", masked: "" },
        ],
      }),
      saveCredential: async () => ({ ok: true }),
      testConnection: async () => ({ ok: true, message: "ok", source: "env" }),
      kill: async () => ({ engine_kill_switch_tripped: false, request: { requested: false, reason: null, ts: null } }),
      requestKill: async () => ({ ok: true, request: { requested: true, reason: "x", ts: "x" }, engine: { engine_kill_switch_tripped: false, request: { requested: true, reason: "x", ts: "x" } } }),
    },
  };
});

import PaperPage from "../PaperPage";
import LivePage from "../LivePage";
import SettingsPage from "../SettingsPage";

function renderPage(node: ReactElement) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("pages render", () => {
  it("renders the Paper page with equity", async () => {
    renderPage(<PaperPage />);
    expect(await screen.findByText("Paper trading")).toBeInTheDocument();
    expect(await screen.findByText("Total equity")).toBeInTheDocument();
  });

  it("renders the Live page locked with four mechanisms", async () => {
    renderPage(<LivePage />);
    expect(await screen.findByText("Live trading")).toBeInTheDocument();
    expect(await screen.findByText(/Live trading is LOCKED/)).toBeInTheDocument();
    expect(await screen.findByText(/four safety mechanisms/)).toBeInTheDocument();
  });

  it("renders the Settings page with categories", async () => {
    renderPage(<SettingsPage />);
    expect(await screen.findByText("Settings & APIs")).toBeInTheDocument();
    expect(await screen.findByText("LLM council")).toBeInTheDocument();
  });
});
