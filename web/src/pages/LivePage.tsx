import { Outlet } from "react-router-dom";
import SubNav from "../components/SubNav";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Approval } from "../api/types";

// Live section wrapper. Mirrors Paper but stays LOCKED by default. It reads and
// reports the approval gate state. No control here can enable live.
export default function LiveSection() {
  const approvalApi = useApi<Approval>(() => api.approval(), 6000, []);
  const ap = approvalApi.data;
  const locked = !(ap?.all_passed ?? false);
  return (
    <div>
      <h1 className="page-title">Live trading</h1>
      <p className="page-sub">
        IBKR live venue. Disabled by default behind the approval gate. This
        section reads and reports gate state. It cannot enable live.
      </p>
      <div className="locked-banner" style={{ marginBottom: 16 }}>
        <span className="lock-ico">{locked ? "🔒" : "●"}</span>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {locked ? "Live trading is LOCKED" : "Live trading ENABLED"}
          </div>
          <div className="muted" style={{ fontSize: 13 }}>
            {locked
              ? "All trading data is zeroed. Enabling live is a backend gate action outside this GUI."
              : "Every live order still routes through the deterministic RiskGate."}
          </div>
        </div>
      </div>
      <SubNav base="/live" />
      <Outlet context={{ locked, approval: ap ?? null }} />
    </div>
  );
}
