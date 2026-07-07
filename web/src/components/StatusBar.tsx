import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Health } from "../api/types";

// Top bar: engine state, active view, kill-switch status, bridge link. Polls
// /health so it reflects the engine without a page reload.
export default function StatusBar({ activeView }: { activeView: string }) {
  const { data } = useApi<Health>(() => api.health(), 4000, []);
  const eng = data?.engine;
  const running = eng?.running ?? false;
  const kill = eng?.kill_switch_tripped ?? false;
  const bridge = data?.bridge?.reachable ?? false;
  return (
    <div className="statusbar">
      <div className="status-item">
        <span className={`dot ${running ? "g" : "d"}`} />
        Engine <b>{running ? "running" : "offline"}</b>
      </div>
      <div className="status-item">
        View <b>{activeView}</b>
      </div>
      <div className="status-item">
        <span className={`dot ${kill ? "r" : "g"}`} />
        Kill switch <b>{kill ? "TRIPPED" : "clear"}</b>
      </div>
      <div className="statusbar-spacer" />
      <div className="status-item">
        <span className={`dot ${bridge ? "g" : "d"}`} />
        Bridge <b>{bridge ? "up" : "down"}</b>
      </div>
    </div>
  );
}
