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
