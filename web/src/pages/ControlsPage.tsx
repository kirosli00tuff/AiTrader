import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { ControlResult, ControlsState, RegistryEntry } from "../api/types";
import { DataState, Panel } from "../components/ui";
import { ConfirmButton, Slider, Toggle, SourceToggle } from "../components/controls";
import { SleevesPanel } from "../components/SleevesPanel";
import { DiscoveryControls } from "../components/DiscoveryControls";
import { AdaptiveControls } from "../components/AdaptiveControls";

const FACTOR_LABEL: Record<string, string> = {
  rule_based: "Native rule-based", llm_primary: "GPT-5.5", llm_secondary: "Claude Opus 4.8",
  llm_tertiary: "Gemini 3.1 Pro", dnn_advisory: "DNN advisory", whale_signal: "Whale",
};
const WEIGHT_GROUPS: { label: string; factors: string[] }[] = [
  { label: "Native strategy", factors: ["rule_based"] },
  { label: "LLM council", factors: ["llm_primary", "llm_secondary", "llm_tertiary"] },
  { label: "DNN advisory", factors: ["dnn_advisory"] },
  { label: "Whale", factors: ["whale_signal"] },
];
const LAYER_LABEL: Record<string, string> = {
  adaptive: "Adaptive strategy tuner", council: "LLM council",
  dnn_advisory: "DNN advisory", whale: "Whale / smart money",
};
const MODEL_LABEL: Record<string, string> = {
  "gpt-5.5": "OpenAI GPT-5.5", "claude-opus-4-8": "Anthropic Claude Opus 4.8",
  "gemini-3.1-pro-preview": "Google Gemini 3.1 Pro",
};

function metric(m: Record<string, unknown>, k: string): string {
  const v = m[k];
  if (v === undefined || v === null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  return String(v);
}

function RegistryCard({ title, e }: { title: string; e: RegistryEntry | null }) {
  return (
    <div style={{ flex: 1, minWidth: 220 }}>
      <div className="ctrl-sub" style={{ marginBottom: 4 }}>{title}</div>
      {e ? (
        <div>
          <div className="mono" style={{ fontSize: 13 }}>{e.model_id}</div>
          <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>
            sharpe {metric(e.metrics, "validation_sharpe")}
            {" · "}mdd {metric(e.metrics, "max_drawdown")}
            {" · "}n {metric(e.metrics, "n_samples")}
            {" · "}{metric(e.metrics, "provenance")}
          </div>
        </div>
      ) : <div className="dim" style={{ fontSize: 12 }}>none</div>}
    </div>
  );
}

export default function ControlsPage() {
  const c = useApi<ControlsState>(() => api.controls(), 0, []);
  const [w, setW] = useState<Record<string, number> | null>(null);
  const [budget, setBudget] = useState<{ b: number; c: number } | null>(null);
  const [fc, setFc] = useState<{ feed: string; clock: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (c.data && w === null) setW({ ...c.data.weights });
    if (c.data && budget === null)
      setBudget({ b: c.data.budget.council_daily_budget, c: c.data.budget.per_symbol_cooldown_minutes });
  }, [c.data, w, budget]);

  const d = c.data;
  async function act(run: () => Promise<ControlResult>) {
    const r = await run();
    setMsg(r.ok ? "Applied." : (r.error ?? "Refused by the server."));
    c.reload();
  }

  return (
    <div>
      <h1 className="page-title">Controls</h1>
      <p className="page-sub">
        Every change is validated and clamped server-side and recorded to the
        event log. No client value is trusted. Level 1 risk limits are read-only
        here.
      </p>
      {msg && <div className="callout" style={{ marginBottom: 14 }}>{msg}</div>}
      <SleevesPanel />
      <DiscoveryControls />
      <AdaptiveControls />

      <DataState loading={c.loading && !d} error={c.error}>
        {d && (
          <div className="grid">
            {/* --- Weight sliders by layer --- */}
            <Panel title="Ensemble weights (by layer)">
              {WEIGHT_GROUPS.map((g) => (
                <div key={g.label}>
                  <div className="group-label">{g.label}</div>
                  {g.factors.map((f) => (
                    <div className="slider-row" key={f}>
                      <span>{FACTOR_LABEL[f] ?? f}</span>
                      <Slider value={w?.[f] ?? d.weights[f] ?? 0}
                        onChange={(v) => setW((p) => ({ ...(p ?? d.weights), [f]: v }))} />
                      <span className="slider-val">{((w?.[f] ?? d.weights[f] ?? 0)).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              ))}
              <div className="group-label">RL advisory (deferred)</div>
              <div className="slider-row">
                <span className="dim">rl_advisory</span>
                <Slider value={0} disabled onChange={() => {}} />
                <span className="slider-val dim">0.00</span>
              </div>
              <div className="callout" style={{ margin: "10px 0" }}>
                Weights are normalized to sum 1 server-side. RL advisory stays at
                0 and out of normalization until it is enabled past its fill gate.
              </div>
              <div className="flex" style={{ marginTop: 6 }}>
                <ConfirmButton label="Apply weights" busyLabel="Applying…"
                  onConfirm={async () => { if (w) await act(() => api.setWeights(w)); setW(null); }} />
                <button className="btn ghost sm"
                  onClick={() => { act(() => api.setWeights(d.default_weights)); setW(null); }}>
                  Reset to defaults
                </button>
              </div>
            </Panel>

            {/* --- Layer toggles --- */}
            <Panel title="Decision layers">
              <div className="ctrl-row">
                <div className="ctrl-name">
                  Static safety (Layer 1)
                  <div className="ctrl-sub">Always on, always real. Final authority. No off switch, no mock.</div>
                </div>
                <span className="tag on">ALWAYS ON · REAL</span>
              </div>
              {Object.keys(LAYER_LABEL).map((layer) => {
                const on = d.layers[layer] ?? true;
                const hasSource = (d.source_layers ?? []).includes(layer);
                const src = d.layer_sources?.[layer] ?? "real";
                return (
                  <div className="ctrl-row" key={layer}>
                    <div className="ctrl-name">{LAYER_LABEL[layer]}
                      {hasSource && (
                        <div className="ctrl-sub">State: {!on ? "off" : `on-${src}`}</div>
                      )}
                    </div>
                    <div className="ctrl-actions">
                      {hasSource && (
                        <SourceToggle source={src} disabled={!on}
                          onSelect={(nx) => act(() => api.setSource(layer, nx))} />
                      )}
                      <Toggle on={on}
                        onToggle={(nx) => act(() => api.setLayer(layer, nx))} />
                    </div>
                  </div>
                );
              })}
            </Panel>

            {/* --- Feed & clock (runtime loop mode) --- */}
            <Panel title="Feed & clock (runtime loop mode)">
              <div className="callout warn" style={{ marginBottom: 12 }}>
                Switching the feed changes the whole loop. A switch away from
                alpaca_paper while a position is open is refused, so it never
                orphans that position, close it or let native exits flatten it
                first. Switching into alpaca_paper re-arms the warm-start gate.
                {" "}<b>{d.open_positions ?? 0}</b> open position(s) now.
              </div>
              <div className="ctrl-row">
                <div className="ctrl-name">Feed mode
                  <div className="ctrl-sub">Current: <b className="mono">{d.feed_mode ?? "alpaca_paper"}</b></div>
                </div>
                <select className="input" style={{ width: 180 }}
                  value={fc?.feed ?? d.feed_mode ?? "alpaca_paper"}
                  onChange={(e) => setFc({ feed: e.target.value, clock: fc?.clock ?? d.clock_mode ?? "real" })}>
                  {(d.feed_modes ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="ctrl-row">
                <div className="ctrl-name">Clock mode
                  <div className="ctrl-sub">Current: <b>{d.clock_mode ?? "real"}</b></div>
                </div>
                <select className="input" style={{ width: 180 }}
                  value={fc?.clock ?? d.clock_mode ?? "real"}
                  onChange={(e) => setFc({ feed: fc?.feed ?? d.feed_mode ?? "alpaca_paper", clock: e.target.value })}>
                  {(d.clock_modes ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="flex" style={{ marginTop: 10 }}>
                <ConfirmButton label="Apply feed/clock" busyLabel="Switching…"
                  onConfirm={async () => {
                    const feed = fc?.feed ?? d.feed_mode ?? "alpaca_paper";
                    const clock = fc?.clock ?? d.clock_mode ?? "real";
                    await act(() => api.setFeedClock(feed, clock));
                    setFc(null);
                  }} />
              </div>
            </Panel>

            {/* --- Council model toggles --- */}
            <Panel title="Council models + base-check gate">
              {Object.keys(MODEL_LABEL).map((m) => (
                <div className="ctrl-row" key={m}>
                  <div className="ctrl-name">{MODEL_LABEL[m]}<div className="ctrl-sub mono">{m}</div></div>
                  <Toggle on={d.models[m] ?? true}
                    onToggle={(nx) => act(() => api.setModel(m, nx))} />
                </div>
              ))}
              <div className="ctrl-row">
                <div className="ctrl-name">Claude Haiku 4.5 base-check gate
                  <div className="ctrl-sub">Cheap pre-council screen. Off runs the full council on every candidate.</div>
                </div>
                <Toggle on={d.gate_enabled}
                  onToggle={(nx) => act(() => api.setModel("gate", nx))} />
              </div>
            </Panel>

            {/* --- Champion / challenger --- */}
            <Panel title="Champion / challenger (dnn_advisory)">
              <div className="flex wrap" style={{ gap: 24, marginBottom: 12 }}>
                <RegistryCard title="CHAMPION" e={d.registry.champion} />
                <RegistryCard title="CHALLENGER" e={d.registry.challenger} />
              </div>
              <div className="ctrl-row">
                <div className="ctrl-name">Auto-promote a better challenger
                  <div className="ctrl-sub">Default off. Promotion stays manual and gated.</div>
                </div>
                <Toggle on={d.auto_promote}
                  onToggle={(nx) => act(() => api.setAutoPromote(nx))} />
              </div>
              <div className="flex" style={{ marginTop: 10 }}>
                <ConfirmButton label="Promote challenger" busyLabel="Recording…"
                  disabled={!d.registry.can_promote}
                  onConfirm={() => act(() => api.promote())} />
                <ConfirmButton label="Rollback champion" busyLabel="Recording…" danger
                  disabled={!d.registry.can_rollback}
                  onConfirm={() => act(() => api.rollback())} />
              </div>
              <div className="ctrl-sub" style={{ marginTop: 8 }}>
                {d.registry.can_promote ? "Challenger meets promotion criteria." : d.registry.promote_reason}
              </div>
            </Panel>

            {/* --- RL enable --- */}
            <Panel title="RL advisory enable (deferred)">
              <div className="ctrl-row">
                <div className="ctrl-name">Enable RL advisory
                  <div className="ctrl-sub">
                    Real closed fills {d.rl.real_fills} / {d.rl.min_real_fills} gate.
                    No synthetic-data training path. The server refuses enable below the gate.
                  </div>
                </div>
                <Toggle on={d.rl.enabled} disabled={!d.rl.can_enable}
                  onToggle={(nx) => act(() => api.setRl(nx))} />
              </div>
              {!d.rl.can_enable && (
                <div className="callout warn" style={{ marginTop: 8 }}>
                  Locked: {d.rl.real_fills} of {d.rl.min_real_fills} required real fills.
                </div>
              )}
            </Panel>

            {/* --- Regime override --- */}
            <Panel title="Regime override (test only)">
              <div className="ctrl-sub" style={{ marginBottom: 8 }}>
                Pin a symbol's regime for testing. Clear returns it to auto detection.
              </div>
              {d.whitelist.map((sym) => (
                <div className="ctrl-row" key={sym}>
                  <div className="ctrl-name mono">{sym}
                    {d.regime_pins[sym] && <span className="tag range_bound" style={{ marginLeft: 8 }}>pinned</span>}
                  </div>
                  <select className="input" style={{ width: 150 }}
                    value={d.regime_pins[sym] ?? ""}
                    onChange={(e) => act(() => api.setRegime(sym, e.target.value || null))}>
                    <option value="">auto</option>
                    {d.regimes.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
                  </select>
                  <button className="btn ghost sm" disabled={!d.regime_pins[sym]}
                    onClick={() => act(() => api.setRegime(sym, null))}>Clear pin</button>
                </div>
              ))}
            </Panel>

            {/* --- Budget dial --- */}
            <Panel title="Council budget">
              <div className="slider-row">
                <span>Daily budget</span>
                <Slider min={d.budget_bounds.budget[0]} max={d.budget_bounds.budget[1]} step={1}
                  value={budget?.b ?? d.budget.council_daily_budget}
                  onChange={(v) => setBudget((p) => ({ b: v, c: p?.c ?? d.budget.per_symbol_cooldown_minutes }))} />
                <span className="slider-val">{budget?.b ?? d.budget.council_daily_budget}</span>
              </div>
              <div className="slider-row">
                <span>Cooldown (min)</span>
                <Slider min={d.budget_bounds.cooldown[0]} max={d.budget_bounds.cooldown[1]} step={5}
                  value={budget?.c ?? d.budget.per_symbol_cooldown_minutes}
                  onChange={(v) => setBudget((p) => ({ b: p?.b ?? d.budget.council_daily_budget, c: v }))} />
                <span className="slider-val">{budget?.c ?? d.budget.per_symbol_cooldown_minutes}</span>
              </div>
              <div className="between" style={{ marginTop: 10 }}>
                <span className="ctrl-sub">Council calls used today: {d.council_used_today} / {d.budget.council_daily_budget}</span>
                <button className="btn sm"
                  onClick={() => { if (budget) act(() => api.setBudget(budget.b, budget.c)); }}>
                  Apply budget
                </button>
              </div>
            </Panel>

            {/* --- Level 1 read-only --- */}
            <Panel title="Level 1 risk limits (read-only)">
              <div className="callout warn" style={{ marginBottom: 12 }}>
                Change risk limits through config or the Dash L1 editor, never through this page.
              </div>
              <div className="tbl-scroll">
                <table className="tbl">
                  <thead><tr><th>Limit</th><th className="num">Value</th></tr></thead>
                  <tbody>
                    {Object.entries(d.level1).map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted">{k}</td>
                        <td className="num">{String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        )}
      </DataState>
    </div>
  );
}
