// Typed REST client for the AiTrader backend. All calls hit the loopback API.
// The WebSocket stream lives in useStream.ts.
import type {
  Account, Approval, Category, ControlResult, ControlsState, Council,
  Credential, EngineState, Health, IntegrationsHealth, KillState, Mode, Order, Pnl, Position, SignalsResponse,
  Trade, Venue, DaySummary, ProviderCost, RunState, SkipRow, TradeDetail,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`${path} failed: HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} failed: HTTP ${res.status}`);
  return (await res.json()) as T;
}

const cat = (c?: Category) => (c ? `&category=${c}` : "");

export const api = {
  health: () => get<Health>("/health"),
  account: (mode: Mode) => get<Account>(`/account?mode=${mode}`),
  positions: (mode: Mode, category?: Category) =>
    get<{ mode: Mode; positions: Position[] }>(
      `/positions?mode=${mode}${cat(category)}`),
  orders: (mode: Mode, limit = 50, category?: Category) =>
    get<{ mode: Mode; orders: Order[] }>(
      `/orders?mode=${mode}&limit=${limit}${cat(category)}`),
  trades: (mode: Mode, limit = 200, category?: Category) =>
    get<{ mode: Mode; trades: Trade[] }>(
      `/trades?mode=${mode}&limit=${limit}${cat(category)}`),
  pnl: (mode: Mode) => get<Pnl>(`/pnl?mode=${mode}`),
  signals: (category?: Category) =>
    get<SignalsResponse>(`/signals${category ? `?category=${category}` : ""}`),
  council: () => get<Council>("/council"),
  risk: () => get<{ level1: Record<string, unknown>; kill_switch_enabled: boolean; kill_switch_tripped: boolean }>("/risk"),
  venues: () => get<{ venues: Venue[] }>("/venues"),
  approval: () => get<Approval>("/approval"),
  integrations: () => get<IntegrationsHealth>("/health/integrations"),
  skips: (limit = 50) => get<{ skips: SkipRow[] }>(`/skips?limit=${limit}`),
  runstate: () => get<RunState>("/runstate"),
  daySummary: () => get<DaySummary>("/day_summary"),
  providerCost: () => get<ProviderCost>("/providers/cost"),
  tradeDetail: (id: number) => get<TradeDetail>(`/trade/${id}`),
  credentials: () => get<{ credentials: Credential[] }>("/credentials"),
  saveCredential: (name: string, value: string) =>
    post<{ ok: boolean; name?: string; status?: Credential; error?: string }>(
      "/credentials", { name, value }),
  testConnection: (group: string, mode?: string) =>
    post<{ ok: boolean; message: string; source: string }>(
      `/credentials/test?group=${group}${mode ? `&mode=${mode}` : ""}`, {}),
  kill: () => get<KillState>("/kill"),
  requestKill: (reason: string) =>
    post<{ ok: boolean; request: KillState["request"]; engine: KillState }>(
      "/kill", { requested: true, reason }),

  // --- Engine lifecycle (supervisor). Stop is a graceful shutdown, NOT the
  // kill switch, which stays on the /kill path above and is independent.
  engineState: () => get<EngineState>("/engine/state"),
  engineStart: () => post<EngineState>("/engine/start", {}),
  engineStop: () => post<EngineState>("/engine/stop", {}),

  // --- Controls -------------------------------------------------------------
  controls: () => get<ControlsState>("/controls"),
  setWeights: (weights: Record<string, number>) =>
    post<ControlResult>("/controls/weights", { weights }),
  setLayer: (layer: string, enabled: boolean) =>
    post<ControlResult>("/controls/layer", { layer, enabled }),
  setSource: (layer: string, source: "mock" | "real") =>
    post<ControlResult>("/controls/source", { layer, source }),
  setFeedClock: (feed_mode: string, clock_mode: string) =>
    post<ControlResult>("/controls/feed_clock", { feed_mode, clock_mode }),
  setModel: (model: string, enabled: boolean) =>
    post<ControlResult>("/controls/model", { model, enabled }),
  setRl: (enabled: boolean) => post<ControlResult>("/controls/rl", { enabled }),
  setAutoPromote: (enabled: boolean) =>
    post<ControlResult>("/controls/auto_promote", { enabled }),
  promote: () => post<ControlResult>("/controls/promote", {}),
  rollback: () => post<ControlResult>("/controls/rollback", {}),
  setRegime: (symbol: string, regime: string | null) =>
    post<ControlResult>("/controls/regime", { symbol, regime }),
  setBudget: (council_daily_budget: number, per_symbol_cooldown_minutes: number) =>
    post<ControlResult>("/controls/budget",
      { council_daily_budget, per_symbol_cooldown_minutes }),
};
