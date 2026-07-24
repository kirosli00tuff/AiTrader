import type { FactorParticipation } from "../api/types";
import Explain from "./Explain";

const fmt = (v: number | null | undefined, d = 3) =>
  typeof v === "number" ? v.toFixed(d) : "—";

// Status → chip class + label. A benched factor, an errored/unreachable
// service, and an operator-chosen mock must each READ DIFFERENTLY from a
// live factor reporting a low value: that distinction being invisible cost
// a structural defect (the fast-tier ceiling).
const STATUS_LABEL: Record<string, string> = {
  live: "LIVE",
  benched: "BENCHED",
  mock_by_choice: "MOCK (operator choice)",
  mock_bridge_down: "MOCK (bridge down)",
  disabled: "DISABLED",
  shipped_off: "SHIPPED OFF",
};

const STATUS_CLASS: Record<string, string> = {
  live: "chip",
  benched: "chip chip-block",
  mock_by_choice: "chip chip-dim",
  mock_bridge_down: "chip chip-block",
  disabled: "chip chip-dim",
  shipped_off: "chip chip-dim",
};

/** Which layers are actually participating, from the backend's derivation of
 * the same sources the engine reads. Renders only; derives nothing. */
export default function FactorParticipationPanel({ data }: {
  data?: FactorParticipation;
}) {
  if (!data) {
    return (
      <div className="empty" data-testid="participation-empty">
        Participation data unavailable (stack down or endpoint unreachable).
      </div>
    );
  }
  return (
    <div data-testid="participation">
      <table className="tbl">
        <thead>
          <tr>
            <th>factor</th><th>participation</th><th>why</th>
            <th>last signal</th><th>confidence</th>
          </tr>
        </thead>
        <tbody>
          {data.factors.map((f) => (
            <tr key={f.factor} data-testid={`fp-${f.factor}`}>
              <td className="mono">{f.factor}</td>
              <td>
                <span className={STATUS_CLASS[f.status] ?? "chip chip-dim"}
                  data-testid={`fp-status-${f.factor}`}>
                  {STATUS_LABEL[f.status] ?? f.status}
                </span>
              </td>
              <td className="dim">{f.reason}</td>
              <td className="mono dim">
                {f.last_signal?.ts ? f.last_signal.ts.slice(5, 16) : "—"}
              </td>
              <td className="mono">{fmt(f.last_signal?.confidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Explain>
        Participation is the engine's reality, not the toggle's intent: a
        BENCHED or bridge-down factor contributes structural zeros and leaves
        the confidence denominator, while a LIVE factor with a low confidence
        is an opinion and stays in it. Derived server-side from the control
        file, the bench state, bridge reachability, and the newest persisted
        signal per factor.
      </Explain>
    </div>
  );
}
