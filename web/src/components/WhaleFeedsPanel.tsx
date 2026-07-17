// The two whale sources, side by side, so the operator can see which feeds are
// live and which is which. SEC EDGAR covers equities (free, keyless, delayed);
// Whale Alert covers crypto (keyed, opt-in trial).
//
// Read-only. Whether a feed WORKS is a different question, answered by the
// Health view, which makes one real call per integration. This panel answers
// whether it is on, and whether the whale layer is producing anything.
//
// Never renders a key value: the backend reports whether one resolves.
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState } from "./ui";
import { shortTs } from "../api/format";
import type { WhaleFeed } from "../api/types";

function FeedRow({ f, testid }: { f: WhaleFeed; testid: string }) {
  // A feed needing a key that is on but unkeyed cannot work, and says so rather
  // than reading as merely on.
  const unkeyed = f.enabled && f.needs_key && !f.keyed;
  const dot = !f.enabled ? "d" : unkeyed ? "a" : "g";
  return (
    <div className="sleeve-row" data-testid={testid}>
      <span className={`dot ${dot}`} />
      <b>{f.label}</b>
      <span className={f.enabled ? "ok" : "dim"}>
        {f.enabled ? "ON" : "off by choice"}
      </span>
      {unkeyed && <strong className="warn">no key</strong>}
      <span className="muted small">{f.detail}</span>
    </div>
  );
}

export function WhaleFeedsPanel() {
  const w = useApi(() => api.whaleFeeds(), 30000);
  return (
    <Panel title="Whale feeds">
      <DataState loading={w.loading && !w.data} error={w.error}>
        {w.data && (
          <div className="sleeves">
            <FeedRow f={w.data.sec_edgar} testid="feed-sec-edgar" />
            <FeedRow f={w.data.whale_alert} testid="feed-whale-alert" />

            <div className="muted small" data-testid="whale-activity">
              {w.data.signal_activity.total === 0 ? (
                <>No whale signals recorded yet.</>
              ) : (
                <>
                  Whale signals: <strong>{w.data.signal_activity.last_24h}</strong>{" "}
                  in the last 24h, {w.data.signal_activity.total} total
                  {w.data.signal_activity.last_ts && (
                    <> · last {shortTs(w.data.signal_activity.last_ts)}</>
                  )}
                </>
              )}
            </div>
            {/* Say what the number is, so it is never read as a per-feed fetch
                count. The whale layer records one combined score. */}
            <div className="muted small" data-testid="whale-activity-note">
              {w.data.signal_activity.note}
            </div>
            <div className="muted small">
              Whether a feed reaches its API is on the Health page, which makes
              one real call per integration.
            </div>
          </div>
        )}
      </DataState>
    </Panel>
  );
}
