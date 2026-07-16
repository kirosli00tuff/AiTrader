// Adaptive real-time layer view: what was seen, what was read, what was done.
//
// The page is built around one honesty rule: show the DROPS, not just the hits.
// A feed view that only listed escalated events would make the layer look busy
// and expensive, and would quietly hide the thing that makes it affordable,
// which is that a free filter throws away the overwhelming majority. So the
// event feed lists everything, dims what was dropped, and says why for each.
//
// The second honesty rule: queued is not applied. The actions panel shows the
// engine's own log next to the request queue, because the engine still has to be
// running, still checks its flag, still re-checks the defensive allowlist, and
// still checks the action's age. A request row is an intention, not an outcome.
//
// Read-only. Times render in the operator's local zone; storage stays UTC.
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState, Empty } from "../components/ui";
import { shortTs, money, num } from "../api/format";
import type {
  AdaptiveEvent, AdaptiveInterpretation, AdaptiveAction, AdaptiveEngineLogRow,
  AdaptiveState,
} from "../api/types";

function AdaptiveDisabled({ state }: { state: AdaptiveState }) {
  return (
    <div className="disabled-state" data-testid="adaptive-disabled">
      <div className="disabled-badge">ADAPTIVE LAYER DISABLED</div>
      <p className="muted">
        The real-time layer is off, so no poll runs, no event is fetched, no
        token is spent, and no action reaches the engine. This is the shipped
        default, not a fault.
      </p>
      <p className="muted small">
        Enable it on the Controls page. It needs a Finnhub key for the feed and
        an Anthropic key for the event reads.
      </p>
      <div className="disabled-preview">
        <div className="panel-subtitle">What would run when enabled</div>
        <ul className="muted small">
          <li>
            Feed: every {state.settings.poll_interval_seconds}s, up to{" "}
            {state.settings.max_symbols_per_poll} symbols (held names first),
            free tier
          </li>
          <li>
            Filter: keywords, sentiment magnitude, and event type, with no model
            involved. The vast majority is dropped for nothing.
          </li>
          <li>
            Reads: at most {state.settings.max_interpretations_per_poll} per
            poll, within {state.budget.daily}/day (about{" "}
            {money(state.budget.est_max_daily)}/day), separate from and additive
            to the discovery and trading budgets
          </li>
          <li>
            Actions: trim, exit, or flag for review only. An event can never open
            or increase a position.
          </li>
        </ul>
      </div>
    </div>
  );
}

function EventRow({ e }: { e: AdaptiveEvent }) {
  // Dropped events are DIMMED, not hidden. They are the cost argument made
  // visible: if this list is mostly grey, the filter is doing its job.
  const dropped = !e.material;
  return (
    <tr className={dropped ? "muted" : undefined}>
      <td className="mono">{shortTs(e.ts)}</td>
      <td>
        {e.symbol || <span className="muted">market</span>}
        {e.held === 1 && <span className="tag tag-core">held</span>}
      </td>
      <td>{e.headline}</td>
      <td className="mono">{num(e.sentiment, 2)}</td>
      <td>
        {e.escalated === 1 ? (
          <span className="tag tag-satellite">read</span>
        ) : (
          <span className="muted small">{e.material_reason}</span>
        )}
      </td>
    </tr>
  );
}

function ClassTag({ cls }: { cls: string | null }) {
  // An aggressive read is tagged as such, and is the interesting case: it is
  // where the operator watches the system decline to act on a bullish model.
  if (cls === "defensive") return <span className="tag tag-warn">defensive</span>;
  if (cls === "aggressive")
    return <span className="tag tag-satellite">aggressive</span>;
  if (cls === "shaping") return <span className="tag tag-core">shaping</span>;
  return <span className="tag">{cls || "none"}</span>;
}

function InterpRow({ i }: { i: AdaptiveInterpretation }) {
  return (
    <tr>
      <td className="mono">{shortTs(i.ts)}</td>
      <td>{i.symbol || <span className="muted">market</span>}</td>
      <td>{i.headline}</td>
      <td>
        <ClassTag cls={i.action_class} /> <span className="mono">{i.action}</span>
      </td>
      <td className="mono">{num(i.severity, 2)}</td>
      <td>
        <span className={i.outcome === "queued" ? "warn" : "muted"}>
          {i.outcome}
        </span>
        {i.outcome_reason && (
          <span className="muted small"> · {i.outcome_reason}</span>
        )}
      </td>
    </tr>
  );
}

export default function AdaptivePage() {
  const state = useApi<AdaptiveState>(() => api.adaptiveState(), 10000);
  const events = useApi(() => api.adaptiveEvents(), 10000);
  const interps = useApi(() => api.adaptiveInterpretations(), 10000);
  const actions = useApi(() => api.adaptiveActions(), 10000);

  return (
    <div className="page">
      <h1 className="page-title">Adaptive real-time layer</h1>
      <p className="page-sub">
        Reads live events, and is allowed to be careful. A live event can trim,
        exit, or flag a position. It can never open or increase one: a bullish
        read is referred back through the discovery funnel and the RiskGate.
      </p>

      <DataState loading={state.loading && !state.data} error={state.error}>
        {state.data && !state.data.news_feed_enabled && (
          <AdaptiveDisabled state={state.data} />
        )}
        {state.data && state.data.news_feed_enabled && (
          <>
            <Panel title="Today">
              <div className="disc-state muted small" data-testid="adaptive-today">
                Last poll:{" "}
                {state.data.last_poll ? shortTs(state.data.last_poll)
                                      : "none yet"}
                {" · "}{state.data.today.events_seen} events seen
                {" · "}<b>{state.data.today.events_dropped_free} dropped free</b>
                {" · "}{state.data.today.events_escalated} read by a model
                {state.data.today.events_unread_budget > 0 && (
                  <span className="warn">
                    {" · "}{state.data.today.events_unread_budget} material but
                    unread (budget)
                  </span>
                )}
                {" · "}budget {state.data.budget.used_today}/
                {state.data.budget.daily} (
                {money(state.data.budget.est_spend_today)} est)
              </div>
            </Panel>

            <Panel title="Event feed">
              <p className="muted small" style={{ marginTop: 0 }}>
                Everything the feed saw. Dimmed rows were dropped by the free
                filter with no model involved and no token spent, and the reason
                is shown for each. Most of this list should be dim.
              </p>
              <DataState loading={events.loading && !events.data}
                error={events.error}>
                {events.data?.events.length ? (
                  <div className="tbl-scroll">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Time</th><th>Symbol</th><th>Headline</th>
                          <th>Sentiment</th><th>Filter</th>
                        </tr>
                      </thead>
                      <tbody>
                        {events.data.events.map((e) => (
                          <EventRow key={e.id} e={e} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>No events seen yet.</Empty>
                )}
              </DataState>
            </Panel>

            <Panel title="Interpretations (the only paid stage)">
              <p className="muted small" style={{ marginTop: 0 }}>
                What a model said about each escalated event, and what came of
                it. An aggressive read shows here as referred: the system
                declined to act on it and handed the symbol to the funnel.
              </p>
              <DataState loading={interps.loading && !interps.data}
                error={interps.error}>
                {interps.data?.interpretations.length ? (
                  <div className="tbl-scroll">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Time</th><th>Symbol</th><th>Headline</th>
                          <th>Read</th><th>Severity</th><th>Outcome</th>
                        </tr>
                      </thead>
                      <tbody>
                        {interps.data.interpretations.map((i) => (
                          <InterpRow key={i.id} i={i} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>Nothing has been escalated to a model yet.</Empty>
                )}
              </DataState>
            </Panel>

            <Panel title="Defensive actions">
              <p className="muted small" style={{ marginTop: 0 }}>
                Only ever trim, exit, or flag for review. Queued is not applied:
                the engine still checks its own flag, re-checks that the action
                is defensive, and refuses anything older than{" "}
                {state.data.settings.action_max_age_seconds}s. What it actually
                did is below.
              </p>
              <DataState loading={actions.loading && !actions.data}
                error={actions.error}>
                {actions.data?.actions.length ? (
                  <div className="tbl-scroll">
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Time</th><th>Symbol</th><th>Action</th>
                          <th>Severity</th><th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {actions.data.actions.map((a: AdaptiveAction) => (
                          <tr key={a.id}>
                            <td className="mono">{shortTs(a.ts)}</td>
                            <td>{a.symbol}</td>
                            <td>
                              <span className="tag tag-warn">{a.action}</span>
                            </td>
                            <td className="mono">{num(a.severity, 2)}</td>
                            <td className="muted">{a.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>No defensive action has been queued.</Empty>
                )}

                {actions.data?.engine_log.length ? (
                  <>
                    <div className="panel-subtitle">What the engine did</div>
                    <ul className="feed">
                      {actions.data.engine_log.map(
                        (l: AdaptiveEngineLogRow, idx: number) => (
                          <li key={idx}
                            className={l.type === "adaptive_defensive"
                                         ? undefined : "muted"}>
                            <span className="mono feed-ts">{shortTs(l.ts)}</span>{" "}
                            {l.message}
                          </li>
                        ))}
                    </ul>
                  </>
                ) : null}
              </DataState>
            </Panel>
          </>
        )}
      </DataState>
    </div>
  );
}
