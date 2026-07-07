import { useState } from "react";
import { api } from "../api/client";
import type { KillState } from "../api/types";

// Prominent kill-switch control with a confirm step. Records a durable halt
// request through the backend. It can only stop trading, never weaken safety.
export default function KillSwitch({ state, onChange }: {
  state: KillState | null; onChange: () => void;
}) {
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const tripped = state?.engine_kill_switch_tripped ?? false;
  const requested = state?.request?.requested ?? false;

  const confirm = async () => {
    setBusy(true);
    try {
      await api.requestKill("operator halt from GUI");
      setMsg("Halt request recorded.");
      onChange();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
      setArming(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span className={`dot ${tripped ? "r" : "g"}`} />
        <b>{tripped ? "Kill switch TRIPPED — trading halted" : "Kill switch clear"}</b>
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
        Records a durable operator halt request. Safety-positive: it can only
        stop trading, never weaken the RiskGate.
        {requested && " A halt request is currently on file."}
      </p>
      {!arming ? (
        <button className="btn danger" onClick={() => { setArming(true); setMsg(null); }}>
          Request halt
        </button>
      ) : (
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn danger" disabled={busy} onClick={confirm}>
            {busy ? "Recording…" : "Confirm halt"}
          </button>
          <button className="btn ghost" disabled={busy} onClick={() => setArming(false)}>
            Cancel
          </button>
        </div>
      )}
      {msg && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{msg}</div>}
    </div>
  );
}
