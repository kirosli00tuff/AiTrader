import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { ControlsState } from "../api/types";
import { Toggle } from "../components/controls";
import SkipFeed from "../components/SkipFeed";
import DaySummary from "../components/DaySummary";
import ProviderCostPanel from "../components/ProviderCostPanel";
import { Panel } from "../components/ui";

const LAYER_LABEL: Record<string, string> = {
  adaptive: "Adaptive strategy tuner", council: "LLM council",
  dnn_advisory: "DNN advisory", whale: "Whale / smart money",
};

// The same four per-layer toggles the Controls page exposes, on the same
// validated endpoint. Safety renders as a fixed always-on indicator with no
// toggle. Flipping one writes controls.json and takes effect on the engine's
// next iteration. A toggle off removes an advisory input, never safety.
function LayerTogglesPanel() {
  const c = useApi<ControlsState>(() => api.controls(), 0, []);
  const [msg, setMsg] = useState<string | null>(null);
  const d = c.data;
  async function toggle(layer: string, enabled: boolean) {
    const r = await api.setLayer(layer, enabled);
    setMsg(r.ok ? `${layer} ${enabled ? "on" : "off"}. Takes effect next iteration.`
                : (r.error ?? "refused"));
    c.reload();
  }
  return (
    <Panel title="Decision layers">
      <div className="ctrl-row">
        <div className="ctrl-name">Static safety (Layer 1)
          <div className="ctrl-sub">Always on. Final authority. Safety cannot be disabled.</div>
        </div>
        <span className="tag on">ALWAYS ON</span>
      </div>
      {Object.keys(LAYER_LABEL).map((layer) => (
        <div className="ctrl-row" key={layer}>
          <div className="ctrl-name">{LAYER_LABEL[layer]}
            <div className="ctrl-sub">Toggling off removes an advisory input. It never affects safety.</div>
          </div>
          <Toggle on={d?.layers?.[layer] ?? true} onToggle={(nx) => toggle(layer, nx)} />
        </div>
      ))}
      {msg && <div className="callout" style={{ marginTop: 10 }}>{msg}</div>}
    </Panel>
  );
}

export default function OpsPage() {
  return (
    <div>
      <h1 className="page-title">Operations</h1>
      <p className="page-sub">Decision layers, day summary, council skip reasons, and provider spend.</p>
      <div style={{ marginBottom: 14 }}><DaySummary /></div>
      <div className="cols">
        <LayerTogglesPanel />
        <Panel title="Council skip reasons"><SkipFeed /></Panel>
      </div>
      <div className="cols" style={{ marginTop: 14 }}>
        <Panel title="Provider cost"><ProviderCostPanel /></Panel>
      </div>
    </div>
  );
}
