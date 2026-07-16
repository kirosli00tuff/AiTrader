// Adaptive real-time layer: three enable toggles and the cost tunables.
//
// These toggles start a spender AND, in one case, let a live event move a
// position. So each enable ARMS before it fires and states plainly what it
// starts, with real numbers. Same posture as the kill switch and the discovery
// toggles: an action with consequences asks twice. Disable is immediate, because
// turning a spender off must never need a ceremony.
//
// The panel states the asymmetry permanently, not only in the confirm text: an
// operator looking at a toggle labelled "defensive react" should be able to see,
// without opening a doc, that there is no aggressive counterpart and why. The
// claim renders from `aggressive_entry_path_exists` reported by the server
// rather than being hardcoded here, so it cannot quietly drift from the code.
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState } from "./ui";
import { shortTs, money } from "../api/format";
import type { AdaptiveState, PrereqCheckRow } from "../api/types";

function PrereqList({ checks }: { checks: PrereqCheckRow[] }) {
  return (
    <ul className="prereq-list" data-testid="adaptive-prereq-list">
      {checks.map((c) => (
        <li key={c.key} className={c.ok ? "ok" : "warn"}>
          <span className={`dot ${c.ok ? "g" : "a"}`} />
          <b>{c.label}</b> <span className="muted">{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function ArmedToggle({ on, label, what, blocked, blockedWhy, busy, onSet,
                       testid }: {
  on: boolean;
  label: string;
  what: string;
  blocked: boolean;
  blockedWhy: ReactNode;
  busy: boolean;
  onSet: (next: boolean) => void;
  testid: string;
}) {
  const [armed, setArmed] = useState(false);
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

      {armed && (
        <div className="disc-confirm" data-testid={`${testid}-confirm`}>
          <b>This starts spending.</b> {what}
        </div>
      )}

      {blocked && !on && (
        <div className="disc-blocked" data-testid={`${testid}-blocked`}>
          <b>Cannot enable yet.</b> {blockedWhy}
        </div>
      )}
    </div>
  );
}

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

export function AdaptiveControls() {
  const d = useApi<AdaptiveState>(() => api.adaptiveState(), 10000);
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
    <Panel title="Adaptive real-time layer">
      <DataState loading={d.loading && !d.data} error={d.error}>
        {d.data && (
          <div className="disc-controls">
            {/* The guarantee, stated up front and rendered from server data. */}
            {!d.data.aggressive_entry_path_exists && (
              <p className="muted small" data-testid="adaptive-asymmetry">
                A live event can only ever make this engine <b>more cautious</b>:
                trim, exit, or flag for review. There is no toggle for
                event-driven buying because there is no such code path. A bullish
                headline can only refer the symbol back through the discovery
                funnel, where Stage A, Stage B, the four levels, and the RiskGate
                all still have to agree. A misread headline costs a screening
                slot, never a position.
              </p>
            )}

            <ArmedToggle
              testid="toggle-adaptive-feed"
              label="News + event feed (observe)"
              on={d.data.news_feed_enabled}
              blocked={!d.data.prerequisites.ok}
              blockedWhy={<PrereqList checks={d.data.prerequisites.checks} />}
              busy={busy}
              what={`This starts polling Finnhub every ${d.data.settings.poll_interval_seconds}s for news on held positions, watchlist names, and the general market. The feed itself is FREE (Finnhub free tier) and a no-LLM filter drops the vast majority for nothing. Only an escalated event is read by a model, within a ${d.data.budget.daily} read/day budget that is separate from and additive to BOTH the discovery and trading budgets (at most about ${money(d.data.budget.est_max_daily)}/day). Observing changes nothing on its own: it opens no position and closes none.`}
              onSet={(next) => run(() =>
                api.setAdaptive("adaptive_news_feed_enabled", next))}
            />

            <ArmedToggle
              testid="toggle-adaptive-shaping"
              label="Watchlist shaping (safe half)"
              on={d.data.watchlist_shaping_enabled}
              blocked={!d.data.news_feed_enabled}
              blockedWhy={<>The news feed must be on first. Shaping reacts to
                polled events, so with no feed there is nothing to react to.</>}
              busy={busy}
              what="This lets a read change what the system LOOKS AT, never what it holds. It can refer a symbol to the discovery funnel and it can prune the watchlist. A referral is NOT tradeable: it lands as referred and becomes tradeable only if a later funnel pass ranks it, gates it, and evaluates it through the four levels. Adding to the watchlist does not open a position. No new spend beyond the reads the feed already budgets for."
              onSet={(next) => run(() =>
                api.setAdaptive("adaptive_watchlist_shaping_enabled", next))}
            />

            <ArmedToggle
              testid="toggle-adaptive-react"
              label="Defensive react (react half)"
              on={d.data.react_defensive_enabled}
              blocked={!d.data.news_feed_enabled}
              blockedWhy={<>The news feed must be on first. A defensive action
                comes from an event, so with no feed none is ever queued.</>}
              busy={busy}
              what={`This is the only toggle that lets a live event change a POSITION, and it can only ever SHRINK or freeze one. A read above severity ${d.data.settings.action_min_severity} may queue a trim (closes ${Math.round((d.data.settings.defensive_trim_fraction ?? 0.5) * 100)}% of the position), a full exit, or a flag for review, which the engine applies through the same native exit path it already uses. An action older than ${d.data.settings.action_max_age_seconds}s is refused, so stale news cannot move a position after a restart. It can never open or increase one. No new spend beyond the reads the feed already budgets for.`}
              onSet={(next) => run(() =>
                api.setAdaptive("adaptive_react_defensive_enabled", next))}
            />

            {msg && (
              <div className="disc-msg warn" data-testid="adaptive-msg">{msg}</div>
            )}

            <div className="disc-state muted small" data-testid="adaptive-state">
              {d.data.news_feed_enabled ? (
                <>
                  Last poll:{" "}
                  {d.data.last_poll ? shortTs(d.data.last_poll) : "none yet"}
                  {" · "}today {d.data.today.events_seen} events seen,{" "}
                  {d.data.today.events_dropped_free} dropped free,{" "}
                  {d.data.today.events_escalated} read
                  {" · "}budget {d.data.budget.used_today}/{d.data.budget.daily}{" "}
                  reads ({money(d.data.budget.est_spend_today)} est)
                </>
              ) : (
                <>Adaptive layer is off. No poll runs, no event is fetched, no
                   token is spent, and no action reaches the engine.</>
              )}
            </div>

            <div className="panel-subtitle">Adaptive settings</div>
            <p className="muted small" style={{ marginTop: 0 }}>
              Cost, cadence, and thresholds only. Every value is clamped
              server-side. Level 1 risk limits are not reachable from here and
              stay read-only.
            </p>
            <div className="disc-fields">
              <BoundedNumber label="Adaptive budget (reads/day)"
                value={d.data.settings.adaptive_daily_llm_budget}
                bounds={d.data.bounds.adaptive_daily_llm_budget}
                hint="separate from the discovery and trading budgets"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { adaptive_daily_llm_budget: v }))} />
              <BoundedNumber label="Poll interval (seconds)"
                value={d.data.settings.poll_interval_seconds}
                bounds={d.data.bounds.poll_interval_seconds}
                hint="free tier"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { poll_interval_seconds: v }))} />
              <BoundedNumber label="Symbols per poll"
                value={d.data.settings.max_symbols_per_poll}
                bounds={d.data.bounds.max_symbols_per_poll}
                hint="held names first"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { max_symbols_per_poll: v }))} />
              <BoundedNumber label="Reads per poll"
                value={d.data.settings.max_interpretations_per_poll}
                bounds={d.data.bounds.max_interpretations_per_poll}
                hint="one storm cannot spend the day"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { max_interpretations_per_poll: v }))} />
              <BoundedNumber label="Materiality sentiment floor"
                value={d.data.settings.materiality_min_sentiment}
                bounds={d.data.bounds.materiality_min_sentiment}
                step={0.05}
                hint="free filter; lower reads more"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { materiality_min_sentiment: v }))} />
              <BoundedNumber label="Action severity floor"
                value={d.data.settings.action_min_severity}
                bounds={d.data.bounds.action_min_severity}
                step={0.05}
                hint="below this an event causes nothing"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { action_min_severity: v }))} />
              <BoundedNumber label="Action max age (seconds)"
                value={d.data.settings.action_max_age_seconds}
                bounds={d.data.bounds.action_max_age_seconds}
                hint="stale news never moves a position"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { action_max_age_seconds: v }))} />
              <BoundedNumber label="Trim fraction"
                value={d.data.settings.defensive_trim_fraction}
                bounds={d.data.bounds.defensive_trim_fraction}
                step={0.05}
                hint="what a trim closes"
                onCommit={(v) => run(() => api.setAdaptiveSettings(
                  { defensive_trim_fraction: v }))} />
            </div>
          </div>
        )}
      </DataState>
    </Panel>
  );
}
