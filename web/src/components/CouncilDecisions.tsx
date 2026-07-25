import type { CouncilDecision, CouncilDecisions as Decisions, DecisionProvider } from "../api/types";
import Explain from "./Explain";

const PROVIDER_LABEL: Record<string, string> = {
  llm_primary: "GPT-5.5", llm_secondary: "Claude Opus 4.8",
  llm_tertiary: "Gemini 3.1 Pro", rule_based: "Native strategy",
  dnn_advisory: "DNN advisory", whale_signal: "Whale",
};

const fmt = (v: number | null | undefined, d = 2) =>
  typeof v === "number" ? v.toFixed(d) : "—";

function num(numbers: Record<string, unknown>, k: string): number | null {
  const v = numbers[k];
  return typeof v === "number" ? v : null;
}

// A hold with zero confidence is an abstention: it is scored and logged but
// does not dilute the directional vote.
//
// A FAILED CALL IS NOT AN ABSTENTION (2026-07-25). It also lands as a hold at
// zero confidence, so this predicate alone read 17 failed Gemini calls as
// considered holds. `errored` comes from the council's own per-provider rows
// and is the only thing that can tell them apart.
const isErrored = (p: DecisionProvider) => p.errored === true;
const isAbstention = (p: DecisionProvider) =>
  !isErrored(p) && (p.verdict ?? "hold") === "hold" && (p.confidence ?? 0) === 0;

function Outcome({ d }: { d: CouncilDecision }) {
  if (d.kind === "trade_entry" || d.kind === "trade")
    return <span className="chip chip-ok">acted</span>;
  if (d.kind === "council_skip")
    return <span className="chip chip-dim">gate skipped</span>;
  return <span className="chip chip-block">refused</span>;
}

function FailedBy({ d }: { d: CouncilDecision }) {
  // When a verdict fails, say by how much and on which check.
  const conf = num(d.numbers, "confidence");
  const minConf = num(d.numbers, "min_confidence");
  const agree = num(d.numbers, "agreement");
  const reqAgree = num(d.numbers, "required_agreement");
  const edge = num(d.numbers, "edge");
  const minEdge = num(d.numbers, "min_edge");
  const fails: string[] = [];
  if (conf !== null && minConf !== null && conf < minConf)
    fails.push(`confidence ${fmt(conf)} vs floor ${fmt(minConf)} (short ${fmt(minConf - conf)})`);
  if (agree !== null && reqAgree !== null && agree < reqAgree)
    fails.push(`agreement ${agree} of ${reqAgree} required`);
  if (edge !== null && minEdge !== null && edge < minEdge)
    fails.push(`edge ${fmt(edge, 4)} vs floor ${fmt(minEdge, 4)}`);
  if (!fails.length) return null;
  return <div className="fail-by mono" data-testid="failed-by">failed on {fails.join(" · ")}</div>;
}

function DecisionCard({ d, benched }: { d: CouncilDecision; benched: boolean }) {
  const errored = d.providers.filter(isErrored);
  const abstainedRows = d.providers.filter(isAbstention);
  const directional = d.providers.filter(
    (p) => !isAbstention(p) && !isErrored(p));
  const abstained = abstainedRows.length;
  return (
    <div className="decision" data-testid="decision">
      <div className="decision-head">
        <span className="mono sym-name">{d.symbol || "—"}</span>
        <Outcome d={d} />
        <span className="dim">{d.message}</span>
        <span className="mono dim">{d.ts.slice(11, 19)}</span>
      </div>
      {d.providers.length > 0 && (
        <table className="tbl decision-tbl">
          <thead>
            <tr><th>voice</th><th>direction</th><th>conviction</th><th>edge</th><th>weight</th><th></th></tr>
          </thead>
          <tbody>
            {d.providers.map((p) => (
              <tr key={p.model}>
                <td>{PROVIDER_LABEL[p.model] ?? p.model}
                  {p.model === "dnn_advisory" && benched && (
                    <span className="chip chip-dim" data-testid="dnn-benched"> benched, contributes zero</span>
                  )}
                </td>
                <td className="mono">{p.verdict ?? "—"}</td>
                <td className="mono">{fmt(p.confidence)}</td>
                <td className="mono">{fmt(p.edge, 4)}</td>
                <td className="mono">{fmt(p.weight)}</td>
                <td className="dim">
                  {isErrored(p)
                    ? <span className="chip chip-block" data-testid="provider-errored">call FAILED</span>
                    : isAbstention(p) ? "abstained" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="decision-compose mono dim" data-testid="composition">
        {directional.length} directional · {abstained} abstained
        {errored.length > 0 && ` · ${errored.length} call(s) FAILED`}
        {num(d.numbers, "agreement") !== null &&
          ` · agreement ${num(d.numbers, "agreement")}`}
        {num(d.numbers, "confidence") !== null &&
          ` · composed confidence ${fmt(num(d.numbers, "confidence"))}`}
        {num(d.numbers, "min_confidence") !== null &&
          ` against floor ${fmt(num(d.numbers, "min_confidence"))}`}
      </div>
      <FailedBy d={d} />
    </div>
  );
}

export default function CouncilDecisionsView({ data }: { data: Decisions }) {
  return (
    <div>
      <Explain>
        The council is three independent models scored per evaluation. Holds
        abstain rather than dilute: conviction is computed among directional
        voters only, then judged against the confidence floor and the required
        agreement count. A cheap base-check gate (Claude Haiku) runs first and
        skips setups not worth a full council call. Whale and DNN advisories
        contribute weighted signals and never decide alone
        {data.dnn_benched ? "; the DNN is currently benched and contributes zero "
          + `(${data.dnn_bench_reason})` : ""}.
      </Explain>
      {!data.decisions.length && (
        <div className="empty" data-testid="decisions-empty">
          No council-tier evaluations recorded yet. Small or low-conviction
          entries take the fast tier and never spend a council call.
        </div>
      )}
      {data.decisions.map((d) => (
        <DecisionCard d={d} benched={data.dnn_benched} key={d.id} />
      ))}
    </div>
  );
}
