import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  const controls = {
    layers: { adaptive: true, council: true, dnn_advisory: true, whale: true },
    layer_sources: { council: "real", dnn_advisory: "real", whale: "real" },
    source_layers: ["council", "dnn_advisory", "whale"],
    feed_mode: "alpaca_paper", clock_mode: "real",
    feed_modes: ["alpaca_paper", "synthetic_regimes", "replay", "flat_random_walk"],
    clock_modes: ["real", "simulated"], open_positions: 0,
    models: { "gpt-5.5": true, "claude-opus-4-8": true, "gemini-3.1-pro-preview": true },
    gate_enabled: true, auto_promote: false,
    budget: { council_daily_budget: 30, per_symbol_cooldown_minutes: 60 },
    budget_bounds: { budget: [1, 500], cooldown: [0, 1440] },
    council_used_today: 2,
    rl: { enabled: false, min_real_fills: 500, real_fills: 31, can_enable: false },
    regime_pins: {}, regimes: ["trending", "range_bound", "neutral"],
    weights: { rule_based: 0.18, llm_primary: 0.27, llm_secondary: 0.18, llm_tertiary: 0.12, dnn_advisory: 0.15, whale_signal: 0.10 },
    default_weights: { rule_based: 0.18, llm_primary: 0.27, llm_secondary: 0.18, llm_tertiary: 0.12, dnn_advisory: 0.15, whale_signal: 0.10 },
    weight_factors: ["rule_based", "llm_primary", "llm_secondary", "llm_tertiary", "dnn_advisory", "whale_signal"],
    level1: { max_daily_loss_total_pct: 0.03, max_open_positions_total: 5 },
    registry: { champion: { model_id: "dnn-synth-v1", role: "champion", ts: "x", metrics: { validation_sharpe: 0.9 }, notes: "synthetic" }, challenger: null, can_rollback: false, can_promote: false, promote_reason: "no challenger recorded" },
    whitelist: ["BTC/USD", "ETH/USD", "SPY", "QQQ"],
    pending_promote: null, pending_rollback: null,
  };
  const okResult = async () => ({ ok: true });
  return {
    API_BASE: "http://127.0.0.1:8000", WS_BASE: "ws://127.0.0.1:8000",
    api: {
      health: async () => ({ status: "ok", db_present: true, engine: { db_present: true, last_event_ts: "x", kill_switch_tripped: false, running: true }, bridge: { reachable: true, url: "", status: "ok" } }),
      account: async () => ({ mode: "paper", equity: 100120, cash: 90000, realized_pnl: 120, unrealized_pnl: 0, drawdown_pct: -0.2, venues: [] }),
      pnl: async () => pnl,
      positions: async () => ({ mode: "paper", positions: [{ venue: "alpaca", symbol: "SPY", side: "buy", qty: 1, avg_price: 540, notional: 540, opened_ts: "x", unrealized_pnl: 1.25 }] }),
      orders: async () => ({ mode: "paper", orders: [{ id: 1, ts: "2026-07-06T01:00:00Z", venue: "alpaca", symbol: "SPY", side: "buy", qty: 1, price: 540, notional: 540, mode: "paper", outcome: "open", pnl: null }] }),
      trades: async () => ({ mode: "paper", trades: [{ id: 2, ts: "2026-07-06T01:00:00Z", venue: "alpaca", symbol: "SPY", side: "buy", qty: 1, price: 540, notional: 540, mode: "paper", outcome: "win", pnl: 12.5, combined_conf: 0.7, combined_edge: 0.03 }] }),
      signals: async () => ({ signals: [{ ts: "x", venue: "alpaca", symbol: "SPY", factor: "rule_based", bias: 0.4, confidence: 0.7, edge: 0.03, regime: "trending" }], regimes: [{ symbol: "SPY", regime: "trending", adx: 31, rvol: 0.04, updated_ts: "x" }] }),
      council: async () => ({ models: { llm_primary: "gpt-5.5" }, latest: [{ ts: "x", model: "gpt-5.5", verdict: "buy", confidence: 0.7, edge: 0.03, weight: 0.27 }], recent: [] }),
      risk: async () => ({ level1: {}, kill_switch_enabled: true, kill_switch_tripped: false }),
      venues: async () => ({ venues: [{ venue: "alpaca", mode: "paper", live_enabled: false, live_adapter: "none", runtime_mode: "paper", credentials_connected: true, kill_switch_tripped: false, configured: true }] }),
      skips: async () => ({ skips: [] }),
      runstate: async () => ({ feed_mode: "flat_random_walk", clock_mode: "real", market_data_source: "mock", use_real_council: false, gate_enabled: true, council_mode: "mock", bridge: { reachable: false, url: "", status: null }, live_enabled: false, layers: { adaptive: true, council: true, dnn_advisory: true, whale: true }, ts: "x" }),
      daySummary: async () => ({ day: "2026-07-10", trades_today: 0, wins_today: 0, losses_today: 0, win_rate_today: 0, council_calls_today: 0, council_daily_budget: 30, estimated_spend_today: 0 }),
      providerCost: async () => ({ providers: [{ provider: "OpenAI", model: "gpt-5.5", balance: null, spend: null, estimated_day: 0, estimated_month: 0, calls_today: 0, calls_month: 0, status: "estimated", source: "local_estimate" }], currency: "USD", totals: { estimated_day: 0, estimated_month: 0 }, ts: "x" }),
      tradeDetail: async () => ({ trade: null, signals: [], council: [], regime: null, events: [] }),
      integrations: async () => ({
        integrations: [{ name: "openai", provider: "OpenAI GPT-5.5", state: "not_configured", reason: "", latency_ms: null }],
        summary: { all_ok: false, any_failing: false, configured_count: 0, total: 1, ts: "x" },
      }),
      approval: async () => ({ live_enabled: false, manual_confirmation: false, last_checked_ts: "x", mechanisms: [ { name: "Live approval gate passed", key: "approval_gate", passed: false, detail: "d" }, { name: "Live credentials connected", key: "credentials_connected", passed: false, detail: "d" }, { name: "Kill switch clear", key: "kill_switch", passed: true, detail: "d" }, { name: "Live-enabled flag set", key: "live_enabled", passed: false, detail: "d" } ], readiness: null, all_passed: false, live_venue: "ibkr" }),
      credentials: async () => ({ credentials: [ { name: "openai_key", label: "API key", group: "openai", group_label: "OpenAI (GPT-5.5)", kind: "source", mode: null, secret: true, configured: false, source: "missing", masked: "" }, { name: "alpaca_paper_key", label: "API key", group: "alpaca", group_label: "Alpaca", kind: "venue", mode: "paper", secret: true, configured: false, source: "missing", masked: "" } ] }),
      saveCredential: okResult, testConnection: async () => ({ ok: true, message: "ok", source: "env" }),
      kill: async () => ({ engine_kill_switch_tripped: false, request: { requested: false, reason: null, ts: null } }),
      requestKill: async () => ({ ok: true, request: { requested: true, reason: "x", ts: "x" }, engine: { engine_kill_switch_tripped: false, request: { requested: true, reason: "x", ts: "x" } } }),
      engineState: async () => ({
        ok: true, error: null, state: "not_running", owned: false, warm: [],
        all_warm: false, engine_pid: null, bridge_pid: null, bridge_port: 8765,
        api_port: 8000, interval_seconds: 30, feed_mode: "alpaca_paper",
        clock_mode: "real", started_ts: null,
        lock: { present: false, alive: false, stale: false, engine_pid: null, bridge_pid: null, source: null },
        history: [], whitelist: ["BTC/USD", "ETH/USD", "SPY", "QQQ"],
      }),
      engineStart: okResult, engineStop: okResult,
      controls: async () => controls,
      setWeights: okResult, setLayer: okResult, setSource: okResult, setModel: okResult, setRl: okResult,
      setFeedClock: okResult,
      setAutoPromote: okResult, promote: okResult, rollback: okResult, setRegime: okResult, setBudget: okResult,
    },
  };
});

import App from "../../App";

function at(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe("pages render", () => {
  it("renders the Paper overview with equity", async () => {
    at("/paper");
    expect(await screen.findByText("Paper trading")).toBeInTheDocument();
    expect(await screen.findByText("Total equity")).toBeInTheDocument();
  });

  it("renders the Paper Stocks subpage", async () => {
    at("/paper/stocks");
    expect(await screen.findByText(/Stocks \(SPY, QQQ\)/)).toBeInTheDocument();
    expect(await screen.findByText("Open orders")).toBeInTheDocument();
  });

  it("renders the Paper Crypto subpage", async () => {
    at("/paper/crypto");
    expect(await screen.findByText(/Crypto \(BTC\/USD, ETH\/USD\)/)).toBeInTheDocument();
  });

  it("renders the Live section locked with four mechanisms", async () => {
    at("/live");
    expect(await screen.findByText("Live trading")).toBeInTheDocument();
    expect(await screen.findByText(/Live trading is LOCKED/)).toBeInTheDocument();
    expect(await screen.findByText(/four safety mechanisms/)).toBeInTheDocument();
  });

  it("renders the Live Crypto subpage zeroed", async () => {
    at("/live/crypto");
    expect(await screen.findByText(/All crypto data is zeroed/)).toBeInTheDocument();
  });

  it("renders the Controls page with weights and read-only Level 1", async () => {
    at("/controls");
    expect(await screen.findByText("Ensemble weights (by layer)")).toBeInTheDocument();
    expect(await screen.findByText("Level 1 risk limits (read-only)")).toBeInTheDocument();
    expect(await screen.findByText(/ALWAYS ON/)).toBeInTheDocument();
    expect(await screen.findByText("Feed & clock (runtime loop mode)")).toBeInTheDocument();
    // Every layer control states what it does in one line.
    expect(await screen.findByText(/Off freezes the weights/)).toBeInTheDocument();
  });

  it("layer toggles hit the validated endpoint, weight changes preview first", async () => {
    const { api } = await import("../../api/client");
    const layerSpy = vi.spyOn(api, "setLayer");
    const weightSpy = vi.spyOn(api, "setWeights");
    at("/controls");
    await screen.findByText("Ensemble weights (by layer)");
    // Toggle a decision layer: exactly one validated POST, no other path.
    const row = (await screen.findByText("Adaptive strategy tuner")).closest(".ctrl-row")!;
    fireEvent.click(within(row as HTMLElement).getByRole("button"));
    await waitFor(() => expect(layerSpy).toHaveBeenCalledWith("adaptive", false));
    // Move a weight slider: a preview appears and nothing posts until confirm.
    const slider = document.querySelector('input[type="range"]:not([disabled])')!;
    fireEvent.change(slider, { target: { value: "0.5" } });
    expect(await screen.findByTestId("weight-preview")).toBeInTheDocument();
    expect(weightSpy).not.toHaveBeenCalled();
  });

  it("renders the Health page with integrations", async () => {
    at("/health");
    expect(await screen.findByText("Integration health")).toBeInTheDocument();
    expect(await screen.findByText("Integrations")).toBeInTheDocument();
  });

  it("renders the Ops page", async () => {
    at("/ops");
    expect(await screen.findByText("Operations")).toBeInTheDocument();
    expect(await screen.findByText("Council skip reasons")).toBeInTheDocument();
    expect(await screen.findByText("Decision layers")).toBeInTheDocument();
    expect(await screen.findByText(/ALWAYS ON/)).toBeInTheDocument();
  });

  it("renders the Ops engine Start/Stop controls with a lifecycle state", async () => {
    at("/ops");
    // The supervisor Start/Stop panel and its lifecycle label render.
    expect(await screen.findByText("Paper trading engine")).toBeInTheDocument();
    expect(await screen.findByText("Not running")).toBeInTheDocument();
    expect(await screen.findByText("Start paper trading")).toBeInTheDocument();
    // The kill switch stays a separate control in the top strip, not replaced
    // by the stop button.
    expect(await screen.findByText("Kill")).toBeInTheDocument();
  });

  it("surfaces a failed GUI start reason on the Ops page", async () => {
    const mod = await import("../../api/client");
    const orig = mod.api.engineState;
    // A start that failed and returned to not_running, carrying the reason.
    (mod.api as unknown as { engineState: () => Promise<unknown> }).engineState =
      async () => ({
        ok: false, error: "bridge failed health check: on-real layer whale not ready",
        state: "not_running", owned: false, warm: [], all_warm: false,
        engine_pid: null, bridge_pid: null, bridge_port: 8765, api_port: 8000,
        interval_seconds: 30, feed_mode: "alpaca_paper", clock_mode: "real",
        started_ts: null,
        lock: { present: false, alive: false, stale: false, engine_pid: null, bridge_pid: null, source: null },
        history: [], whitelist: ["BTC/USD"],
      });
    try {
      at("/ops");
      const callout = await screen.findByText(/^Start failed:/);
      expect(callout).toHaveTextContent("bridge failed health check");
    } finally {
      (mod.api as unknown as { engineState: unknown }).engineState = orig;
    }
  });

  it("renders the Settings page with categories", async () => {
    at("/settings");
    expect(await screen.findByText("Settings & APIs")).toBeInTheDocument();
    expect(await screen.findByText("LLM council")).toBeInTheDocument();
  });
});
