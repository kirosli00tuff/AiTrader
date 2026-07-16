// Discovery funnel view: the latest pass per asset class, rendered as a funnel
// so the cheap-to-expensive narrowing is legible at a glance. The operator
// should be able to confirm in one look that intelligence is spent only at the
// bottom: a wide universe ranked for free, a handful of council calls.
//
// Read-only. Every timestamp renders in the operator's local timezone via
// shortTs; storage stays UTC.
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState, Empty } from "../components/ui";
import { DiscoveryDisabled } from "../components/DiscoveryDisabled";
import { shortTs, money, num } from "../api/format";
import type { DiscoveryPass, DiscoveryDrop } from "../api/types";

const STAGE_LABEL: Record<string, string> = {
  A: "Stage A · free pre-screen",
  B: "Stage B · haiku gate",
  C: "Stage C · four-level",
};

// The four funnel steps, widest first. `cost` states what each step spends, so
// the point of the ordering is on screen rather than implied.
function funnelSteps(p: DiscoveryPass) {
  return [
    { key: "universe", label: "Universe", n: p.universe_count,
      cost: "0 tokens" },
    { key: "finalists", label: "Stage A finalists", n: p.finalists_count,
      cost: "0 tokens (free pre-screen)" },
    { key: "survivors", label: "Stage B survivors", n: p.survivors_count,
      cost: `${p.gate_calls} haiku gate calls` },
    { key: "evaluated", label: "Stage C evaluated", n: p.evaluated_count,
      cost: `${p.council_calls} full council calls` },
  ];
}

function FunnelBars({ pass }: { pass: DiscoveryPass }) {
  const steps = funnelSteps(pass);
  const widest = Math.max(1, ...steps.map((s) => s.n));
  return (
    <div className="funnel" data-testid="funnel">
      {steps.map((s) => (
        <div className="funnel-step" key={s.key}>
          <div className="funnel-label">{s.label}</div>
          <div className="funnel-bar-track">
            <div
              className={`funnel-bar funnel-bar-${s.key}`}
              style={{ width: `${Math.max(2, (s.n / widest) * 100)}%` }}
            >
              <span className="funnel-count">{s.n}</span>
            </div>
          </div>
          <div className="funnel-cost muted">{s.cost}</div>
        </div>
      ))}
    </div>
  );
}

function DropTable({ drops }: { drops: DiscoveryDrop[] }) {
  if (drops.length === 0) {
    return <div className="muted">Nothing dropped this pass.</div>;
  }
  // Group by stage so the operator reads "what fell out where", which is the
  // question this view exists to answer.
  const byStage: Record<string, DiscoveryDrop[]> = {};
  for (const d of drops) (byStage[d.stage] ??= []).push(d);

  return (
    <div className="drops">
      {["A", "B", "C"].filter((s) => byStage[s]?.length).map((stage) => (
        <div key={stage} className="drop-group">
          <div className="drop-stage muted">
            {STAGE_LABEL[stage] ?? stage} · dropped {byStage[stage].length}
          </div>
          <table className="tbl">
            <thead>
              <tr><th>Symbol</th><th>Reason</th><th>Score</th></tr>
            </thead>
            <tbody>
              {byStage[stage].map((d, i) => (
                <tr key={`${d.symbol}-${i}`}>
                  <td>{d.symbol}</td>
                  <td className="muted">{d.reason}</td>
                  <td className="num">{d.score == null ? "—" : num(d.score, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function PassCard({ pass, budget }: {
  pass: DiscoveryPass;
  budget: { daily: number; est_cost_per_call: number } | null;
}) {
  return (
    <Panel title={`${pass.asset_class} · last pass ${shortTs(pass.ts)}`}>
      {pass.status !== "ok" && (
        <div className="muted">
          Pass status <strong>{pass.status}</strong>
          {pass.reason ? `: ${pass.reason}` : ""}
        </div>
      )}
      <FunnelBars pass={pass} />
      <div className="funnel-cost-line">
        <span>
          Cost this pass <strong>{money(pass.est_cost_usd)}</strong>{" "}
          <span className="muted">
            ({pass.council_calls} council{" "}
            {pass.council_calls === 1 ? "call" : "calls"}
            {budget ? ` @ ${money(budget.est_cost_per_call)}/call` : ""})
          </span>
        </span>
        <span className="muted">
          discovery budget left today: {pass.budget_remaining}
          {budget ? ` / ${budget.daily}` : ""} calls
        </span>
      </div>
      {pass.whale_surfaced_count > 0 && (
        <div className="whale-line">
          <span className="tag tag-whale">whale-surfaced</span>
          <span className="muted">
            {pass.whale_surfaced_count} finalist
            {pass.whale_surfaced_count === 1 ? "" : "s"} reached the set because
            of whale activity, and would not have on price and volume alone. The
            same whale data still evaluates survivors in Stage C.
          </span>
        </div>
      )}
      <div className="panel-subtitle">Dropped, with reasons</div>
      <DropTable drops={pass.drops} />
    </Panel>
  );
}

export default function DiscoveryPage() {
  const state = useApi(() => api.discoveryState(), 10000);
  const latest = useApi(() => api.discoveryLatest(), 10000);

  return (
    <div>
      <h1 className="page-title">Discovery funnel</h1>
      <p className="page-sub">
        A curated universe screened cheap to expensive. Stage A ranks everything
        for free, the haiku gate screens the finalists for fractions of a cent,
        and only a handful of survivors reach a full council call.
      </p>

      <DataState loading={state.loading} error={state.error}>
        {state.data && !state.data.enabled && (
          <DiscoveryDisabled state={state.data} />
        )}
      </DataState>

      <DataState loading={latest.loading} error={latest.error}>
        {latest.data && (
          latest.data.passes.length === 0
            ? <Empty>
                No discovery pass recorded yet.
                {state.data?.enabled
                  ? " The first pass runs on the next due cadence (crypto hourly, equities during US hours)."
                  : ""}
              </Empty>
            : latest.data.passes.map((p) => (
                <PassCard key={p.asset_class} pass={p}
                  budget={state.data?.budget ?? null} />
              ))
        )}
      </DataState>
    </div>
  );
}
