// Long-term sleeve view (research_satellite), deliberately distinct from the
// quant core.
//
// This is where the operator reads WHY the engine holds each long-term position.
// A quant-core row is a number; a satellite row is an argument. So the thesis is
// rendered in full and readable, not truncated into a table cell: direction,
// conviction, target, horizon, invalidation, entry date, current PnL, and where
// the position sits against its thesis.
//
// Read-only. Times render in the operator's local zone; storage stays UTC.
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState, Empty } from "../components/ui";
import { shortTs, money, num, signClass } from "../api/format";
import type { LongTermPosition } from "../api/types";

function StatusTag({ status }: { status: string }) {
  const cls =
    status === "target reached" ? "tag-ok"
      : status === "invalidated" ? "tag-warn"
        : status === "on thesis" ? "tag-active"
          : "tag-muted";
  return <span className={`tag ${cls}`}>{status}</span>;
}

function ThesisCard({ p }: { p: LongTermPosition }) {
  const hasThesis = p.direction != null;
  return (
    <Panel title={`${p.symbol} · ${p.direction ?? "no thesis"}`}>
      <div className="thesis-head">
        <StatusTag status={p.status_vs_thesis} />
        <span className="muted">held since {shortTs(p.opened_ts)}</span>
      </div>

      <div className="thesis-grid">
        <div>
          <div className="muted small">Conviction</div>
          <div>{p.conviction == null ? "—" : num(p.conviction, 2)}</div>
        </div>
        <div>
          <div className="muted small">Horizon</div>
          <div>{p.horizon ?? "—"}</div>
        </div>
        <div>
          <div className="muted small">Entry</div>
          <div>{money(p.avg_price)}</div>
        </div>
        <div>
          <div className="muted small">Target</div>
          <div>{p.target == null ? "—" : money(p.target)}</div>
        </div>
        <div>
          <div className="muted small">Unrealized</div>
          <div className={signClass(p.unrealized_pnl)}>
            {money(p.unrealized_pnl)}
          </div>
        </div>
        <div>
          <div className="muted small">Size</div>
          <div>{num(p.qty, 4)} · {money(p.notional)}</div>
        </div>
      </div>

      {p.invalidation ? (
        <div className="thesis-invalidation">
          <div className="muted small">Invalidation</div>
          <div>
            {p.invalidation}
            {p.invalidation_price != null && (
              <span className="muted"> ({money(p.invalidation_price)})</span>
            )}
          </div>
        </div>
      ) : hasThesis ? (
        // A thesis written before the long-term strategy carries no levels. Say
        // that, rather than invent a number the engine is not actually holding.
        <div className="muted small">
          No invalidation level recorded: this thesis predates the long-term
          strategy. The position exits on its native stop or target.
        </div>
      ) : null}

      {p.rationale && (
        <div className="thesis-rationale">
          <div className="muted small">Thesis</div>
          <p>{p.rationale}</p>
        </div>
      )}
    </Panel>
  );
}

export default function LongTermPage() {
  const lt = useApi(() => api.longtermPositions(), 10000);
  const theses = useApi(() => api.researchTheses(25), 10000);

  return (
    <div>
      <h1 className="page-title">Long-term sleeve</h1>
      <p className="page-sub">
        The research_satellite sleeve: fewer, larger, longer-held positions from
        a quality-and-catalyst screen plus a council thesis. Held long term and
        exited on target or thesis invalidation, never on a short-term signal.
      </p>

      <DataState loading={lt.loading} error={lt.error}>
        {lt.data && !lt.data.enabled && (
          <div className="disabled-state" data-testid="longterm-disabled">
            <div className="disabled-badge">LONG-TERM SLEEVE DISABLED</div>
            <p className="muted">
              No long-term position can open. This is the shipped default, not a
              fault. A long-term hold needs BOTH the sleeve and the strategy:
            </p>
            <ul className="muted small">
              <li>
                <code>sleeves.research_satellite_enabled</code>:{" "}
                <strong>{lt.data.sleeve_config_enabled ? "on" : "off"}</strong>{" "}
                (the sleeve)
              </li>
              <li>
                <code>discovery.long_term_sleeve_enabled</code>:{" "}
                <strong>{lt.data.strategy_enabled ? "on" : "off"}</strong>{" "}
                (the strategy)
              </li>
            </ul>
            <p className="muted small">
              The sleeve earns a wider allocation only through paper results. Its
              30 percent is a ceiling, not a floor, and the hard cap refuses any
              position past it regardless of conviction.
            </p>
          </div>
        )}
      </DataState>

      <DataState loading={lt.loading} error={lt.error}>
        {lt.data && (
          lt.data.positions.length === 0
            ? <Empty>
                No open long-term positions.
                {lt.data.enabled
                  ? " The sleeve opens one only above its conviction threshold and within its hard cap."
                  : ""}
              </Empty>
            : lt.data.positions.map((p) => (
                <ThesisCard key={`${p.venue}-${p.symbol}`} p={p} />
              ))
        )}
      </DataState>

      <Panel title="Research feed · recent long-term theses">
        <DataState loading={theses.loading} error={theses.error}>
          {theses.data && (
            theses.data.theses.length === 0
              ? <Empty>No research passes yet.</Empty>
              : <ul className="feed" data-testid="research-feed">
                  {theses.data.theses.map((t, i) => (
                    <li key={i}>
                      <span className="mono feed-ts">{shortTs(t.ts)}</span>{" "}
                      <strong>{t.symbol}</strong> {t.direction}
                      {t.conviction != null && (
                        <> · conv {t.conviction.toFixed(2)}</>
                      )}
                      {t.horizon && <> · {t.horizon}</>}
                      <span className="muted"> [{t.status}]</span>
                      {t.rationale && (
                        <div className="muted small">{t.rationale}</div>
                      )}
                    </li>
                  ))}
                </ul>
          )}
        </DataState>
      </Panel>
    </div>
  );
}
