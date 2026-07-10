import type { CSSProperties } from "react";
import { useOutletContext } from "react-router-dom";
import type { Approval } from "../api/types";
import { money } from "../api/format";
import { Empty, Panel, Stat } from "../components/ui";

const COLS: CSSProperties = {
  display: "grid", gap: 14,
  gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
};

interface Ctx { locked: boolean; approval: Approval | null; }

export default function LiveOverview() {
  const { approval } = useOutletContext<Ctx>();
  const ap = approval;
  return (
    <div>
      <Panel title="Approval gate — four safety mechanisms"
        style={{ marginBottom: 14 }}>
        {(ap?.mechanisms ?? []).length ? (ap!.mechanisms).map((m) => (
          <div className="mech" key={m.key}>
            <span className="mech-name" style={{ flex: "0 0 220px" }}>{m.name}</span>
            <span className="mech-detail" style={{ flex: 1 }}>{m.detail}</span>
            <span className={m.passed ? "mech-pass" : "mech-fail"}>
              {m.passed ? "PASS" : "BLOCKED"}
            </span>
          </div>
        )) : <Empty>Approval state unavailable.</Empty>}
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Live enabled: <b>{ap?.live_enabled ? "yes" : "no"}</b>
          {" · "}all mechanisms pass: <b>{ap?.all_passed ? "yes" : "no"}</b>
        </div>
      </Panel>

      <Panel style={{ marginBottom: 14 }}>
        <div className="hero">
          <div>
            <div className="hero-label">Live account value</div>
            <div className="hero-value mono">{money(0)}</div>
          </div>
        </div>
      </Panel>

      <div className="stat-row" style={{ marginBottom: 14 }}>
        <Stat label="Daily PnL" value={money(0)} />
        <Stat label="Win rate" value="—" />
        <Stat label="Open positions" value={0} />
        <Stat label="Total P/L" value={money(0)} />
      </div>

      <div style={COLS}>
        <Panel title="Live open positions">
          <Empty>No live positions. Live trading is disabled.</Empty>
        </Panel>
        <Panel title="Live activity">
          <Empty>No live activity. Live trading is disabled.</Empty>
        </Panel>
      </div>
    </div>
  );
}
