// Response types mirroring the FastAPI backend (api_server).
export type Mode = "paper" | "live";
export type Category = "stocks" | "crypto";

export interface Health {
  status: string;
  db_present: boolean;
  engine: {
    db_present: boolean;
    last_event_ts: string | null;
    kill_switch_tripped: boolean;
    running: boolean;
  };
  bridge: { reachable: boolean; url: string; status: string | null };
}

export interface VenueBalance {
  venue: string;
  equity: number;
  cash: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  drawdown_pct: number | null;
  ts: string;
}

export interface Account {
  mode: Mode;
  equity: number;
  cash: number;
  realized_pnl: number;
  unrealized_pnl: number;
  drawdown_pct: number;
  venues: VenueBalance[];
}

export interface Position {
  venue: string;
  symbol: string;
  market?: string | null;
  category?: string | null;
  side: string;
  qty: number;
  avg_price: number;
  notional: number;
  opened_ts: string;
  unrealized_pnl: number | null;
}

export interface Order {
  id: number;
  ts: string;
  venue: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  notional: number;
  mode: string;
  outcome: string | null;
  pnl: number | null;
}

export interface Trade extends Order {
  combined_conf: number | null;
  combined_edge: number | null;
}

export interface EquityPoint { ts: string; equity: number; }
export interface DailyPnl { day: string; pnl: number; }

export interface Pnl {
  mode: Mode;
  equity_curve: EquityPoint[];
  daily_pnl: DailyPnl[];
  win_rate: number;
  wins: number;
  losses: number;
  n_trades: number;
  total_pnl: number;
  equity: number;
  equity_change: number;
  equity_change_pct: number;
  max_drawdown_pct: number;
}

export interface Regime {
  symbol: string;
  regime: string;
  adx: number | null;
  rvol: number | null;
  updated_ts: string;
}

export interface Signal {
  ts: string;
  venue: string | null;
  symbol: string | null;
  factor: string;
  bias: number;
  confidence: number;
  edge: number | null;
  regime: string | null;
}

export interface SignalsResponse { signals: Signal[]; regimes: Regime[]; }

export interface ModelOutput {
  ts: string;
  model: string;
  verdict: string | null;
  confidence: number | null;
  edge: number | null;
  weight: number | null;
}

export interface Council {
  models: Record<string, string>;
  latest: ModelOutput[];
  recent: ModelOutput[];
}

export interface Venue {
  venue: string;
  mode: string | null;
  live_enabled: boolean;
  live_adapter: string | null;
  runtime_mode: string | null;
  credentials_connected: boolean;
  kill_switch_tripped: boolean;
  configured: boolean;
}

export interface Mechanism { name: string; key: string; passed: boolean; detail: string; }

export interface Approval {
  live_enabled: boolean;
  manual_confirmation: boolean;
  last_checked_ts: string | null;
  mechanisms: Mechanism[];
  readiness: unknown;
  all_passed: boolean;
  live_venue: string | null;
}

export interface Credential {
  name: string;
  label: string;
  group: string;
  group_label: string;
  kind: string;
  mode: string | null;
  secret: boolean;
  configured: boolean;
  source: string;
  masked: string;
}

export interface EventRow {
  ts: string;
  kind: string;
  venue: string | null;
  symbol: string | null;
  severity: string;
  message: string;
}

export interface KillState {
  engine_kill_switch_tripped: boolean;
  request: { requested: boolean; reason: string | null; ts: string | null };
}

export interface Snapshot {
  mode: Mode;
  ts: string;
  positions: Position[];
  orders: Order[];
  pnl: Pnl;
  events: EventRow[];
}

// --- Controls page ---------------------------------------------------------
export interface RegistryEntry {
  model_id: string;
  role: string;
  ts: string;
  metrics: Record<string, unknown>;
  notes: string | null;
}

export interface ControlsState {
  layers: Record<string, boolean>;
  layer_sources: Record<string, string>;   // layer -> "mock" | "real"
  source_layers: string[];                  // layers that carry a source axis
  feed_mode: string;                        // runtime loop feed mode
  clock_mode: string;                       // runtime clock mode
  feed_modes: string[];                     // valid feed modes
  clock_modes: string[];                    // valid clock modes
  open_positions: number;                   // open native paper positions
  models: Record<string, boolean>;
  gate_enabled: boolean;
  auto_promote: boolean;
  budget: { council_daily_budget: number; per_symbol_cooldown_minutes: number };
  budget_bounds: { budget: [number, number]; cooldown: [number, number] };
  council_used_today: number;
  rl: { enabled: boolean; min_real_fills: number; real_fills: number; can_enable: boolean };
  regime_pins: Record<string, string>;
  regimes: string[];
  weights: Record<string, number>;
  default_weights: Record<string, number>;
  weight_factors: string[];
  level1: Record<string, number | string | boolean>;
  registry: {
    champion: RegistryEntry | null;
    challenger: RegistryEntry | null;
    can_rollback: boolean;
    can_promote: boolean;
    promote_reason: string;
  };
  whitelist: string[];
  pending_promote: unknown;
  pending_rollback: unknown;
}

export interface ControlResult {
  ok: boolean;
  error?: string;
  [k: string]: unknown;
}

export type IntegrationState = "working" | "failing" | "not_configured";
export interface IntegrationCheck {
  name: string;
  provider: string;
  state: IntegrationState;
  reason: string;
  latency_ms: number | null;
}
export interface IntegrationsHealth {
  integrations: IntegrationCheck[];
  summary: {
    all_ok: boolean;
    any_failing: boolean;
    configured_count: number;
    total: number;
    ts: string | null;
  };
}

export interface SkipRow {
  ts: string; kind: string; symbol: string | null; reason: string; message: string | null;
}

// --- Engine lifecycle (GUI Start/Stop through the supervisor) --------------
export type EngineLifecycle =
  "not_running" | "starting" | "warming" | "running" | "stopping";
export interface EngineWarm { symbol: string; bars: number; warm: boolean; }
export interface EngineLock {
  present: boolean; alive: boolean; stale: boolean;
  engine_pid: number | null; bridge_pid: number | null;
  source: string | null; ts?: string | null;
}
export interface EngineState {
  ok?: boolean;
  error?: string | null;
  note?: string;
  state: EngineLifecycle;
  owned: boolean;
  warm: EngineWarm[];
  all_warm: boolean;
  engine_pid: number | null;
  bridge_pid: number | null;
  bridge_port: number;
  api_port: number;
  interval_seconds: number;
  feed_mode: string;
  clock_mode: string;
  started_ts: string | null;
  lock: EngineLock;
  history: { state?: string; note?: string; ts: string }[];
  whitelist: string[];
}
export interface RunState {
  feed_mode: string; clock_mode: string; market_data_source: string;
  use_real_council: boolean; gate_enabled: boolean; council_mode: string;
  bridge: { reachable: boolean; url: string; status: string | null };
  live_enabled: boolean; layers?: Record<string, boolean>;
  layer_sources?: Record<string, string>; ts: string;
}
export interface DaySummary {
  day: string; trades_today: number; wins_today: number; losses_today: number;
  win_rate_today: number; council_calls_today: number; council_daily_budget: number;
  estimated_spend_today: number;
}
export interface ProviderCostRow {
  provider: string; model: string; balance: number | null; spend: number | null;
  estimated_day: number; estimated_month: number; calls_today: number;
  calls_month: number; status: "live" | "estimated" | "unavailable"; source: string;
}
export interface ProviderCost {
  providers: ProviderCostRow[]; currency: string;
  totals: { estimated_day: number; estimated_month: number }; ts: string;
}
export interface TradeDetail {
  trade: (Trade & { fee?: number; decision_id?: number | null }) | null;
  signals: { ts: string; factor: string; bias: number; confidence: number; edge: number | null }[];
  council: ModelOutput[];
  regime: { regime: string; adx: number | null; rvol: number | null; updated_ts: string } | null;
  events: { ts: string; kind: string; severity: string; message: string }[];
}

// Core-satellite sleeves.
// --- Discovery (read-only views) --------------------------------------------
// Mirrors the api_server discovery endpoints. Every timestamp is ISO-8601 UTC as
// stored; the GUI converts to the operator's local zone at render time via
// shortTs/clockTs. Storage stays UTC.

export interface DiscoveryDrop {
  symbol: string;
  stage: string;              // A | B | C
  reason: string;
  score: number | null;
}

export interface DiscoveryPass {
  id: number;
  ts: string;
  asset_class: string;        // crypto | equity
  universe_count: number;
  finalists_count: number;    // Stage A output
  survivors_count: number;    // Stage B output
  evaluated_count: number;    // Stage C output
  council_calls: number;      // the paid stage
  gate_calls: number;         // the cheap stage
  est_cost_usd: number;
  budget_remaining: number;
  status: string;
  reason: string | null;
  drops: DiscoveryDrop[];
  // Finalists that reached the set BECAUSE of whale activity: they would not
  // have made the cut on price, volume, momentum, and sentiment alone.
  whale_surfaced_count: number;
}

export interface DiscoveryCandidate {
  ts: string;
  symbol: string;
  verdict: string;            // buy | sell | avoid
  direction: string;
  conviction: number | null;
  edge: number | null;
  agreement: number | null;
  size_pct: number | null;    // ADVISORY: the cap and the RiskGate still rule
  horizon: string | null;
  sleeve_target: string | null;
  rationale: string | null;
  asset_class: string;
  // Whale did two jobs: it SURFACED this candidate in Stage A, and it still
  // evaluated it in Stage C at its 0.35 cap. Same data, two questions.
  whale_surfaced: number;
  whale_reason: string | null;
}

export interface DiscoveryState {
  enabled: boolean;
  long_term_sleeve_enabled: boolean;
  last_pass: { crypto: string | null; equity: string | null };
  watchlist_size: number;
  watchlist_max: number;
  universe: {
    crypto_active_max: number;
    crypto_universe: number;
    equity_universe: number;
  };
  ceilings: {
    max_finalists: number;
    max_survivors: number;
    max_council_calls_per_pass: number;
  };
  budget: {
    daily: number;
    used_today: number;
    remaining: number;
    est_cost_per_call: number;
    est_spend_today: number;
  };
  react_layer_built: boolean;
}

export interface WatchlistRow {
  symbol: string;
  asset_class: string | null;
  added_ts: string;
  updated_ts: string;
  source: string;
  reason: string | null;
  sleeve_target: string | null;
  score: number | null;
  status: string;
}

export interface WatchlistEvent {
  ts: string;
  action: string;             // add | remove
  symbol: string;
  source: string;
  reason: string | null;
  applied: number;            // 0 => refused (e.g. a not-yet-enabled source)
}

export interface LongTermPosition {
  venue: string;
  symbol: string;
  category: string | null;
  side: string;
  qty: number;
  avg_price: number;
  notional: number;
  opened_ts: string;
  unrealized_pnl: number;
  thesis_ts: string | null;
  direction: string | null;
  conviction: number | null;
  horizon: string | null;
  rationale: string | null;
  thesis_status: string | null;
  target: number | null;
  invalidation_price: number | null;
  invalidation: string | null;
  entry_price: number | null;
  status_vs_thesis: string;
}

export interface SleeveState {
  targets: { quant_core: number; research_satellite: number };
  drift_band: number;
  hard_cap_pct: number;
  allocation: { quant_core: number; research_satellite: number; invested_total: number };
  satellite_share: number;
  rebalance_due: boolean;
  enabled: { quant_core: boolean; research_satellite: boolean };
  research_satellite_config_enabled: boolean;
  open_positions: { quant_core: number; research_satellite: number };
}
export interface ResearchThesis {
  ts: string;
  symbol: string;
  direction: string;
  conviction: number | null;
  horizon: string | null;
  rationale: string | null;
  status: string;
}
