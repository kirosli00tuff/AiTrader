import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { RunState } from "../api/types";

// One-glance banner: loop mode, clock, bridge, real vs mock council, data
// source. Sits under the top strip on every page.
export default function RunStateBanner() {
  const { data } = useApi<RunState>(() => api.runstate(), 8000, []);
  if (!data) return null;
  const bridge = data.bridge?.reachable ?? false;
  const council = data.council_mode;
  const layers = data.layers ?? {};
  const offLayers = Object.entries(layers).filter(([, v]) => !v).map(([k]) => k);
  const layersLabel = offLayers.length ? `${offLayers.join(", ")} OFF` : "all on";
  return (
    <div className="runstate">
      <span className="runstate-item">Loop <b className="mono">{data.feed_mode}</b></span>
      <span className="runstate-item">Clock <b>{data.clock_mode}</b></span>
      <span className="runstate-item">Data <b>{data.market_data_source}</b></span>
      <span className="runstate-item"><span className={`dot ${bridge ? "g" : "r"}`} /> Bridge <b>{bridge ? "up" : "down"}</b></span>
      <span className="runstate-item">
        <span className={`dot ${council === "real" ? "g" : "a"}`} /> Council <b>{council}</b>
      </span>
      <span className="runstate-item">Layers <b>{layersLabel}</b></span>
      <span className="runstate-item dim">live {data.live_enabled ? "ENABLED" : "off"}</span>
    </div>
  );
}
