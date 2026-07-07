import type { Council } from "../api/types";
import { Empty } from "./ui";

function tagFor(verdict: string | null): string {
  return verdict ? verdict : "neutral_v";
}

// Latest per-model verdicts plus a simple ensemble leaning from signed weight.
export default function CouncilPanel({ council }: { council: Council | null }) {
  const latest = council?.latest ?? [];
  if (!latest.length) return <Empty>No council verdicts yet.</Empty>;
  return (
    <div>
      {latest.map((m, i) => (
        <div className="mech" key={i}>
          <span className="mech-name mono">{m.model}</span>
          <span className={`tag ${tagFor(m.verdict)}`}>{m.verdict ?? "—"}</span>
          <span className="mech-detail">
            conf {m.confidence != null ? `${(m.confidence * 100).toFixed(0)}%` : "—"}
            {" · "}w {m.weight != null ? m.weight.toFixed(2) : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}
