import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { DiscoveryState, RunState } from "../api/types";

// One-glance banner: loop mode, clock, bridge, real vs mock council, data
// source. Sits under the top strip on every page.
export default function RunStateBanner() {
  const { data } = useApi<RunState>(() => api.runstate(), 8000, []);
  // Discovery + long-term state. Polled slowly: a funnel pass runs hourly at
  // most, so a faster poll would only add DB reads.
  const disc = useApi<DiscoveryState>(() => api.discoveryState(), 30000, []);
  if (!data) return null;
  const bridge = data.bridge?.reachable ?? false;
  const council = data.council_mode;
  const layers = data.layers ?? {};
  const sources = data.layer_sources ?? {};
  // Three-state per level: off / on-mock / on-real. Layers without a source
  // axis (adaptive) show on/off only.
  const state = (k: string): string => {
    if (layers[k] === false) return "off";
    return k in sources ? `on-${sources[k]}` : "on";
  };
  const order = ["council", "dnn_advisory", "whale", "adaptive"];
  const present = order.filter((k) => k in layers);
  const layersLabel = present.length
    ? present.map((k) => `${k.replace("_advisory", "")}:${state(k)}`).join("  ")
    : "all on";
  return (
    <div className="runstate">
      <span className="runstate-item">Loop <b className="mono">{data.feed_mode}</b></span>
      {/* Off is the shipped default, so a grey dot here is expected, not a
          fault. When on, the operator sees the funnel working. */}
      <span className="runstate-item" data-testid="runstate-discovery">
        <span className={`dot ${disc.data?.enabled ? "g" : "d"}`} />
        Discovery <b>{disc.data?.enabled ? "on" : "off"}</b>
        {disc.data?.enabled && (
          <span className="dim" style={{ fontSize: 11 }}>
            {disc.data.budget.used_today}/{disc.data.budget.daily} calls
          </span>
        )}
      </span>
      <span className="runstate-item" data-testid="runstate-longterm">
        <span className={`dot ${disc.data?.long_term_sleeve_enabled ? "g" : "d"}`} />
        Long-term <b>{disc.data?.long_term_sleeve_enabled ? "on" : "off"}</b>
      </span>
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
