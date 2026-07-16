// The disabled state for every discovery view.
//
// Discovery ships OFF. An empty page with no explanation reads as broken, which
// is the wrong signal: nothing is wrong, the feature is deliberately off. This
// says so, shows what WOULD run when enabled (so the operator can sanity-check
// the universe and ceilings before opting in), and names the exact config key to
// flip. Enabling is a deliberate operator action, so this component never offers
// a button to do it: discovery has no write path.
import type { DiscoveryState } from "../api/types";

export function DiscoveryDisabled({ state }: { state: DiscoveryState }) {
  return (
    <div className="disabled-state" data-testid="discovery-disabled">
      <div className="disabled-badge">DISCOVERY DISABLED</div>
      <p className="muted">
        The discovery funnel is off, so no pass runs, nothing is fetched, and no
        council call is spent. The engine trades the fixed whitelist exactly as
        before. This is the shipped default, not a fault.
      </p>
      <p className="muted small">
        Enable it in <code>config/default_config.yaml</code> under{" "}
        <code>discovery.discovery_enabled</code>. It needs a{" "}
        <code>FINNHUB_API_KEY</code> (Settings, or env) for the free pre-screen.
      </p>
      <div className="disabled-preview">
        <div className="panel-subtitle">What would run when enabled</div>
        <ul className="muted small">
          <li>
            Universe: {state.universe.crypto_universe} crypto curated, refreshed
            daily to the top {state.universe.crypto_active_max} by liquidity ·{" "}
            {state.universe.equity_universe} equities, stable curated list
          </li>
          <li>
            Funnel: universe to {state.ceilings.max_finalists} finalists (free),
            to {state.ceilings.max_survivors} survivors (haiku gate), to at most{" "}
            {state.ceilings.max_council_calls_per_pass} council calls per pass
          </li>
          <li>
            Budget: {state.budget.daily} discovery council calls/day, separate
            from and additive to the trading budget
          </li>
          <li>
            Long-term sleeve strategy:{" "}
            {state.long_term_sleeve_enabled ? "enabled" : "disabled (opt-in)"}
          </li>
        </ul>
      </div>
      {!state.react_layer_built && (
        <p className="muted small">
          The real-time news-react layer is not built. Discovery uses
          pre-computed sentiment as a cheap number only. No entry is ever taken
          on a raw headline.
        </p>
      )}
    </div>
  );
}
