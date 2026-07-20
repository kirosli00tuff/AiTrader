import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Health, SymbolDiagnostics, WatchdogDiagnostics } from "../api/types";
import { BridgeDetail, SymbolHealthTable, WatchdogTimeline } from "../components/DiagnosticsPanels";
import Explain from "../components/Explain";
import { DataState, Panel } from "../components/ui";

// What used to need a terminal: per-symbol data health, bridge capability
// detail, and the watchdog's actions with their reasons.
export default function DiagnosticsPage() {
  const sym = useApi<{ symbols: SymbolDiagnostics[] }>(
    () => api.diagSymbols(), 5000, []);
  const wd = useApi<WatchdogDiagnostics>(() => api.diagWatchdog(), 5000, []);
  const health = useApi<Health>(() => api.health(), 5000, []);
  return (
    <div>
      <h1 className="page-title">Diagnostics</h1>
      <p className="page-sub">
        Data health per symbol, bridge capability, and every watchdog action
        with what triggered it. Two conditions look similar and are not:
        symbol unavailable is contained, feed substitution is the emergency.
      </p>
      <Panel title="Symbols">
        <Explain>
          Tradeable means the venue has served the symbol at least one real
          bar. A symbol without that history is unavailable: never evaluated,
          never fabricated for, never a reason to stop the stack. Warm means
          enough closed bars for the native indicators.
        </Explain>
        <DataState loading={sym.loading && !sym.data} error={sym.error}>
          {sym.data && <SymbolHealthTable symbols={sym.data.symbols} />}
        </DataState>
      </Panel>
      <Panel title="Bridge">
        <DataState loading={health.loading && !health.data} error={health.error}>
          {health.data && (
            <BridgeDetail
              bridge={(health.data.bridge as unknown as Record<string, unknown>) ?? null} />
          )}
        </DataState>
      </Panel>
      <Panel title="Watchdog and feed conditions">
        <DataState loading={wd.loading && !wd.data} error={wd.error}>
          {wd.data && <WatchdogTimeline diag={wd.data} />}
        </DataState>
      </Panel>
    </div>
  );
}
