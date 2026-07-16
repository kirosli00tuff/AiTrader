// Dynamic watchlist view: the narrow end of the funnel, and the list both
// sleeves draw entry candidates from.
//
// The recent-events feed matters as much as the list itself: a view that only
// shows current state looks static, and the operator cannot tell a living list
// from a stuck one. Showing adds and prunes as they happen makes it visibly
// alive.
//
// Read-only. Times render in the operator's local zone; storage stays UTC.
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState, Empty } from "../components/ui";
import { DiscoveryDisabled } from "../components/DiscoveryDisabled";
import { shortTs, num } from "../api/format";
import type { WatchlistEvent } from "../api/types";

function SleeveTag({ sleeve }: { sleeve: string | null }) {
  const long = sleeve === "research_satellite";
  return (
    <span className={`tag ${long ? "tag-satellite" : "tag-core"}`}>
      {long ? "long-term" : "quant"}
    </span>
  );
}

function EventRow({ e }: { e: WatchlistEvent }) {
  // A refused event (applied 0) is shown, not hidden. Today that means an event
  // from the reserved react source, which is not enabled yet. A silently dropped
  // event would be worse than a visible refusal.
  const refused = e.applied === 0;
  return (
    <li className={refused ? "muted" : undefined}>
      <span className="mono feed-ts">{shortTs(e.ts)}</span>{" "}
      <strong className={e.action === "add" ? "ok" : "warn"}>
        {e.action === "add" ? "+" : "-"} {e.symbol}
      </strong>{" "}
      <span className="muted">
        {e.reason}
        {e.source !== "discovery" && e.source !== "prune" && ` · ${e.source}`}
        {refused && " · REFUSED (source not enabled)"}
      </span>
    </li>
  );
}

export default function WatchlistPage() {
  const state = useApi(() => api.discoveryState(), 10000);
  const wl = useApi(() => api.watchlist(), 10000);

  return (
    <div>
      <h1 className="page-title">Dynamic watchlist</h1>
      <p className="page-sub">
        The narrow end of the funnel. Discovery adds instruments that survive to
        Stage C, and entries prune when a signal goes stale or a thesis breaks.
        Both sleeves draw entry candidates from this list.
      </p>

      <DataState loading={state.loading} error={state.error}>
        {state.data && !state.data.enabled && (
          <DiscoveryDisabled state={state.data} />
        )}
      </DataState>

      <DataState loading={wl.loading} error={wl.error}>
        {wl.data && (
          <>
            <Panel
              title={`On the list (${wl.data.watchlist.length}${
                state.data ? ` / ${state.data.watchlist_max} max` : ""})`}
            >
              {wl.data.watchlist.length === 0 ? (
                <Empty>
                  Nothing on the watchlist.
                  {state.data?.enabled
                    ? " Discovery adds instruments as they survive to Stage C."
                    : ""}
                </Empty>
              ) : (
                <table className="tbl" data-testid="watchlist-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Sleeve</th>
                      <th>Why it is on the list</th>
                      <th>Added</th>
                      <th>Last confirmed</th>
                      <th>Score</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wl.data.watchlist.map((w) => (
                      <tr key={w.symbol}>
                        <td><strong>{w.symbol}</strong></td>
                        <td><SleeveTag sleeve={w.sleeve_target} /></td>
                        <td className="muted">
                          {w.reason ?? "—"}
                          {/* The reason string carries the whale attribution the
                              runner wrote, so an operator can tell a whale-found
                              name from a technical one at a glance. */}
                          {(w.reason ?? "").includes("whale") && (
                            <span className="tag tag-whale">whale</span>
                          )}
                        </td>
                        <td className="mono">{shortTs(w.added_ts)}</td>
                        <td className="mono">{shortTs(w.updated_ts)}</td>
                        <td className="num">
                          {w.score == null ? "—" : num(w.score, 2)}
                        </td>
                        <td><span className="tag on">{w.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            <Panel title="Recent adds and prunes">
              {wl.data.events.length === 0 ? (
                <Empty>No watchlist activity yet.</Empty>
              ) : (
                <ul className="feed" data-testid="watchlist-events">
                  {wl.data.events.map((e, i) => (
                    <EventRow key={`${e.ts}-${e.symbol}-${i}`} e={e} />
                  ))}
                </ul>
              )}
            </Panel>
          </>
        )}
      </DataState>
    </div>
  );
}
