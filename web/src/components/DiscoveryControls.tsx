// Discovery + long-term sleeve enable toggles and tunables.
//
// These two toggles START SPENDERS. Discovery begins hourly funnel passes that
// make Finnhub and council calls; the long-term sleeve begins evaluating and
// holding research positions. So each one arms before it fires, and the confirm
// states plainly what it is about to start. That is the same posture as the kill
// switch and the engine start: an action with consequences asks twice.
//
// Every write goes through the validated control endpoint. The server clamps
// every number into its own bounds, re-applies the funnel narrowing rule, and
// refuses an enable whose prerequisites are missing. Nothing here can reach a
// Level-1 risk value, and nothing here can enable live.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState } from "./ui";
import { shortTs, money } from "../api/format";
import type { DiscoveryState, Prereqs } from "../api/types";

function PrereqList({ prereqs }: { prereqs: Prereqs }) {
  return (
    <ul className="prereq-list" data-testid="prereq-list">
      {prereqs.checks.map((c) => (
        <li key={c.key} className={c.ok ? "ok" : "warn"}>
          <span className={`dot ${c.ok ? "g" : "a"}`} />
          <b>{c.label}</b> <span className="muted">{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

// An enable that arms, states what it starts, then fires. Disable is immediate:
// turning a spender OFF should never need a ceremony.
function ArmedToggle({ on, label, what, prereqs, busy, onSet, testid }: {
  on: boolean;
  label: string;
  what: string;
  prereqs: Prereqs;
  busy: boolean;
  onSet: (next: boolean) => void;
  testid: string;
}) {
  const [armed, setArmed] = useState(false);
  const blocked = !prereqs.ok;

  return (
    <div className="disc-toggle" data-testid={testid}>
      <div className="disc-toggle-head">
        <span className={`dot ${on ? "g" : "d"}`} />
        <b>{label}</b>
        <span className={on ? "ok" : "dim"}>{on ? "ON" : "off"}</span>
        {on ? (
          <button className="btn ghost sm" disabled={busy}
            onClick={() => onSet(false)}>
            disable
          </button>
        ) : !armed ? (
          <button className="btn sm" disabled={busy || blocked}
            onClick={() => setArmed(true)}>
            enable
          </button>
        ) : (
          <>
            <button className="btn sm" disabled={busy}
              onClick={() => { onSet(true); setArmed(false); }}>
              {busy ? "…" : "confirm"}
            </button>
            <button className="btn ghost sm" disabled={busy}
              onClick={() => setArmed(false)}>
              cancel
            </button>
          </>
        )}
      </div>

      {/* The confirm states plainly what turning this on does, before it does
          it. An operator should never learn what a toggle spends afterwards. */}
      {armed && (
        <div className="disc-confirm" data-testid={`${testid}-confirm`}>
          <b>This starts spending.</b> {what}
        </div>
      )}

      {blocked && !on && (
        <div className="disc-blocked" data-testid={`${testid}-blocked`}>
          <b>Cannot enable yet.</b> Missing prerequisites:
          <PrereqList prereqs={prereqs} />
        </div>
      )}
    </div>
  );
}

// A bounded number the server clamps. The input shows the server's own bounds so
// the GUI never keeps a second copy of a limit that could drift from it.
function BoundedNumber({ label, value, bounds, step, hint, onCommit }: {
  label: string;
  value: number;
  bounds: [number, number] | undefined;
  step?: number;
  hint?: string;
  onCommit: (v: number) => void;
}) {
  const [v, setV] = useState(String(value));
  useEffect(() => { setV(String(value)); }, [value]);
  const [lo, hi] = bounds ?? [0, 0];
  return (
    <label className="disc-field">
      <span className="disc-field-label">{label}</span>
      <input type="number" value={v} min={lo} max={hi} step={step ?? 1}
        aria-label={label}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          const n = Number(v);
          if (Number.isFinite(n) && n !== value) onCommit(n);
          else setV(String(value));
        }} />
      <span className="muted small">
        {lo} to {hi}{hint ? ` · ${hint}` : ""}
      </span>
    </label>
  );
}

export function DiscoveryControls() {
  const d = useApi<DiscoveryState>(() => api.discoveryState(), 10000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const run = async (fn: () => Promise<{ ok: boolean; error?: string;
                                         clamped?: Record<string, number> }>) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      if (!r.ok) setMsg(r.error ?? "refused");
      else if (r.clamped && Object.keys(r.clamped).length) {
        // Say when the server did not honor a value as sent, rather than
        // quietly showing a different number than the operator typed.
        setMsg("clamped to bounds: " +
               Object.entries(r.clamped).map(([k, v]) => `${k}=${v}`).join(", "));
      }
      d.reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Discovery + long-term sleeve">
      <DataState loading={d.loading && !d.data} error={d.error}>
        {d.data && (
          <div className="disc-controls">
            <ArmedToggle
              testid="toggle-discovery"
              label="Discovery funnel"
              on={d.data.enabled}
              prereqs={d.data.prerequisites}
              busy={busy}
              what={`Discovery starts hourly funnel passes (crypto around the clock, equities during US hours). Each pass makes free Finnhub calls over the ${d.data.universe.crypto_universe} crypto and ${d.data.universe.equity_universe} equity universe, cheap Haiku gate calls on ${d.data.ceilings.max_finalists} finalists, and up to ${d.data.ceilings.max_council_calls_per_pass} full council calls on survivors, within a ${d.data.budget.daily} call/day discovery budget that is separate from and additive to the trading budget (at most about ${money(d.data.budget.daily * d.data.budget.est_cost_per_call)}/day).`}
              onSet={(next) => run(() => api.setDiscovery(next))}
            />

            <ArmedToggle
              testid="toggle-longterm"
              label="Long-term sleeve strategy"
              on={d.data.long_term_sleeve_enabled}
              prereqs={d.data.longterm_prerequisites}
              busy={busy}
              what="The long-term sleeve begins screening on quality and catalyst, running the full four levels in long-horizon mode, and holding research positions within the research_satellite hard cap (30 percent target plus the 5 percent band, so 35 percent of equity, which it can never exceed). Positions are held long term and exit on target or thesis invalidation, never on a short-term signal. The RiskGate still judges every order."
              onSet={(next) => run(() => api.setLongTerm(next))}
            />

            {msg && (
              <div className="disc-msg warn" data-testid="disc-msg">{msg}</div>
            )}

            {/* State visibility: when on, the operator sees it working. */}
            <div className="disc-state muted small" data-testid="disc-state">
              {d.data.enabled ? (
                <>
                  Last pass: crypto{" "}
                  {d.data.last_pass.crypto ? shortTs(d.data.last_pass.crypto)
                                           : "none yet"}
                  {" · "}equity{" "}
                  {d.data.last_pass.equity ? shortTs(d.data.last_pass.equity)
                                           : "none yet"}
                  {" · "}budget {d.data.budget.used_today}/{d.data.budget.daily}{" "}
                  calls today ({money(d.data.budget.est_spend_today)} est)
                  {" · "}watchlist {d.data.watchlist_size}/{d.data.watchlist_max}
                </>
              ) : (
                <>Discovery is off. No pass runs, nothing is fetched, and no
                   council call is spent.</>
              )}
            </div>

            <div className="panel-subtitle">Discovery settings</div>
            <p className="muted small" style={{ marginTop: 0 }}>
              Cost and cadence only. Every value is clamped server-side, and the
              funnel is always forced to narrow (survivors at most finalists,
              council calls at most survivors). Level 1 risk limits are not
              reachable from here and stay read-only.
            </p>
            <div className="disc-fields">
              <BoundedNumber label="Discovery budget (calls/day)"
                value={d.data.budget.daily}
                bounds={d.data.bounds.discovery_daily_council_budget}
                hint="separate from the trading budget"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { discovery_daily_council_budget: v }))} />
              <BoundedNumber label="Stage A finalists"
                value={d.data.ceilings.max_finalists}
                bounds={d.data.bounds.max_finalists}
                hint="free pre-screen output"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { max_finalists: v }))} />
              <BoundedNumber label="Stage B survivors"
                value={d.data.ceilings.max_survivors}
                bounds={d.data.bounds.max_survivors}
                hint="gate output"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { max_survivors: v }))} />
              <BoundedNumber label="Stage C council calls per pass"
                value={d.data.ceilings.max_council_calls_per_pass}
                bounds={d.data.bounds.max_council_calls_per_pass}
                hint="the only paid stage"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { max_council_calls_per_pass: v }))} />
              <BoundedNumber label="Crypto cadence (minutes)"
                value={d.data.cadence.crypto_interval_minutes}
                bounds={d.data.bounds.crypto_interval_minutes}
                hint="24/7"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { crypto_interval_minutes: v }))} />
              <BoundedNumber label="Equity cadence (minutes)"
                value={d.data.cadence.equity_interval_minutes}
                bounds={d.data.bounds.equity_interval_minutes}
                hint="US hours only"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { equity_interval_minutes: v }))} />
              <BoundedNumber label="Whale surfacing weight"
                value={d.data.stage_a_whale_weight}
                bounds={d.data.bounds.stage_a_whale_weight}
                step={0.05}
                hint="0 disables surfacing; Level 4 evaluation is unaffected"
                onCommit={(v) => run(() => api.setDiscoverySettings(
                  { stage_a_whale_weight: v }))} />
            </div>

            <p className="muted small">
              Discovery uses pre-computed sentiment as a cheap number only. The
              real-time news-react layer is{" "}
              {d.data.react_layer_built ? "built and has its own toggles below"
                                        : "not built"}
              , and either way no entry is ever taken on a raw headline: an
              event can refer a candidate into this funnel, never past it.
            </p>
          </div>
        )}
      </DataState>
    </Panel>
  );
}
