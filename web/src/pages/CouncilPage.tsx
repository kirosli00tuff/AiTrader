import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { CouncilDecisions } from "../api/types";
import CouncilDecisionsView from "../components/CouncilDecisions";
import { DataState, Panel } from "../components/ui";

// The clearest window into the engine's thinking: every council-tier
// evaluation as a decision record.
export default function CouncilPage() {
  const d = useApi<CouncilDecisions>(() => api.councilDecisions(40), 5000, []);
  return (
    <div>
      <h1 className="page-title">Council decisions</h1>
      <p className="page-sub">
        Each record shows every provider's read, how the directional votes
        composed, and the exact check a failed verdict failed, by how much.
      </p>
      <DataState loading={d.loading && !d.data} error={d.error}>
        {d.data && (
          <Panel title="Decision records">
            <CouncilDecisionsView data={d.data} />
          </Panel>
        )}
      </DataState>
    </div>
  );
}
