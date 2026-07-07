// Typed REST client for the AiTrader backend. All calls hit the loopback API.
// The WebSocket stream lives in useStream.ts.
import type {
  Account, Approval, Council, Credential, Health, KillState, Mode, Order,
  Pnl, Position, SignalsResponse, Trade, Venue,
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

export const api = {
  health: () => get<Health>("/health"),
  account: (mode: Mode) => get<Account>(`/account?mode=${mode}`),
  positions: (mode: Mode) =>
    get<{ mode: Mode; positions: Position[] }>(`/positions?mode=${mode}`),
  orders: (mode: Mode, limit = 50) =>
    get<{ mode: Mode; orders: Order[] }>(`/orders?mode=${mode}&limit=${limit}`),
  trades: (mode: Mode, limit = 200) =>
    get<{ mode: Mode; trades: Trade[] }>(`/trades?mode=${mode}&limit=${limit}`),
  pnl: (mode: Mode) => get<Pnl>(`/pnl?mode=${mode}`),
  signals: () => get<SignalsResponse>("/signals"),
  council: () => get<Council>("/council"),
  risk: () => get<{ level1: Record<string, unknown>; kill_switch_enabled: boolean; kill_switch_tripped: boolean }>("/risk"),
  venues: () => get<{ venues: Venue[] }>("/venues"),
  approval: () => get<Approval>("/approval"),
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
};
