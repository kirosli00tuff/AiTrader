// Core-satellite sleeve panel: the live quant-core vs research-satellite split
// against target, the drift band, a rebalance-due flag, per-sleeve enable
// toggles, a manual rebalance-now button, and the research thesis feed. All data
// comes from the read-only backend; writes go through the validated control
// endpoints. Never renders a key value.
import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel, DataState } from "./ui";
import { Toggle, ConfirmButton, ArmedToggle } from "./controls";
import { money, sharePct, shortTs } from "../api/format";

export function SleevesPanel() {
  const s = useApi(() => api.sleeves(), 5000);
  const [busy, setBusy] = useState(false);
  const r = useApi(() => api.researchTheses(50), 5000);
  // Discovery feeds candidates to BOTH sleeves, so its state belongs next to the
  // split. Polled slowly: a pass runs hourly at most.
  const d = useApi(() => api.discoveryState(), 30000);

  return (
    <Panel title="Core-satellite sleeves">
      <DataState loading={s.loading} error={s.error}>
        {s.data && (
          <div className="sleeves">
            <div className="sleeve-row">
              <span>quant_core</span>
              <span>{money(s.data.allocation.quant_core)} </span>
              <span className="muted">target {sharePct(s.data.targets.quant_core)}</span>
              <span>{s.data.open_positions.quant_core} pos</span>
              <Toggle on={s.data.enabled.quant_core}
                onToggle={async (next) => { await api.setSleeve("quant_core", next); s.reload(); }} />
            </div>
            {/* The satellite ALLOCATES capital, so it arms before it fires and
                states what it does first. quant_core above keeps a plain toggle:
                it is the core sleeve, always the default home for a position,
                and turning it on starts nothing new. */}
            <ArmedToggle
              testid="toggle-research-satellite"
              label="research_satellite sleeve"
              on={s.data.enabled.research_satellite}
              busy={busy}
              heading="This allocates capital."
              what={`Enabling the sleeve gives research_satellite positions a ${sharePct(s.data.targets.research_satellite)} target of equity, inside a hard cap of ${sharePct(s.data.hard_cap_pct)} (target plus the ${sharePct(s.data.drift_band)} drift band) that it can never exceed, whatever the conviction. Drift past the band trims the overweight sleeve back toward target through the normal RiskGate-approved exit path. The target is a CEILING, not a floor: the sleeve may sit under it. The RiskGate still judges every order. Enabling this satisfies the long-term strategy's sleeve prerequisite; the strategy itself is a separate toggle.`}
              onSet={async (next) => {
                setBusy(true);
                try { await api.setSleeve("research_satellite", next); s.reload(); }
                finally { setBusy(false); }
              }}
            />

            {/* TASK 3 state: allocation against the target when on, and an
                unambiguous "off on purpose" when off. */}
            <div className="sleeve-row" data-testid="satellite-state">
              {s.data.enabled.research_satellite ? (
                <span className="muted small">
                  research_satellite <strong className="ok">ON</strong>
                  {" · "}{money(s.data.allocation.research_satellite)} allocated
                  {" · "}{sharePct(s.data.satellite_share)} of {sharePct(s.data.targets.research_satellite)} target
                  {" · "}cap {sharePct(s.data.hard_cap_pct)}
                  {" · "}{s.data.open_positions.research_satellite} pos
                </span>
              ) : (
                <span className="muted small">
                  research_satellite is <strong>off by choice</strong>. It holds no
                  capital and opens no position. quant_core runs the whole book.
                </span>
              )}
            </div>
            <div className="muted">
              satellite share {sharePct(s.data.satellite_share)} (band ±{sharePct(s.data.drift_band)})
              {s.data.rebalance_due
                ? <strong className="warn"> — REBALANCE DUE</strong>
                : <span className="ok"> — within band</span>}
            </div>
            <ConfirmButton label="Rebalance now" busyLabel="Requesting..."
              onConfirm={async () => { await api.requestRebalance(); s.reload(); }} />
            {s.data.enabled.research_satellite
              && !s.data.research_satellite_config_enabled && (
              <div className="muted small" data-testid="sleeve-config-note">
                The sleeve is on from the control file, which overrides the
                shipped config (off). The engine reads the control file every
                iteration, so this is the state it is running.
              </div>
            )}
            <div className="muted small">
              The satellite target is a CEILING, not a floor. It may sit under it;
              the hard cap is what it can never exceed, whatever the conviction.
            </div>
            {d.data && (
              <div className="muted small" data-testid="sleeve-discovery-line">
                Discovery <strong>{d.data.enabled ? "on" : "off (opt-in)"}</strong>
                {" · "}watchlist {d.data.watchlist_size}/{d.data.watchlist_max}
                {d.data.enabled && (
                  <>
                    {" · "}last pass{" "}
                    {d.data.last_pass.crypto || d.data.last_pass.equity
                      ? shortTs(
                          [d.data.last_pass.crypto, d.data.last_pass.equity]
                            .filter((t): t is string => !!t).sort().slice(-1)[0])
                      : "none yet"}
                    {" · "}discovery budget {d.data.budget.used_today}/
                    {d.data.budget.daily} calls today
                  </>
                )}
                {" · "}both sleeves draw candidates from the watchlist
              </div>
            )}
          </div>
        )}
      </DataState>

      <div className="panel-subtitle">Research theses</div>
      <DataState loading={r.loading} error={r.error}>
        {r.data && (
          r.data.theses.length === 0
            ? <div className="muted">No research passes yet.</div>
            : <ul className="research-feed">
                {r.data.theses.map((t, i) => (
                  <li key={i}>
                    <strong>{t.symbol}</strong> {t.direction}
                    {t.conviction != null && <> conv {t.conviction.toFixed(2)}</>}
                    {t.horizon && <> · {t.horizon}</>}
                    <span className="muted"> [{t.status}]</span>
                    {t.rationale && <div className="muted small">{t.rationale}</div>}
                  </li>
                ))}
              </ul>
        )}
      </DataState>
    </Panel>
  );
}
