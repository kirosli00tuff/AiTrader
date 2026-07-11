import SkipFeed from "../components/SkipFeed";
import DaySummary from "../components/DaySummary";
import ProviderCostPanel from "../components/ProviderCostPanel";
import { Panel } from "../components/ui";

// Operations page: day summary, council skip reasons, and provider cost. The
// run-state banner is global (under the top strip on every page).
export default function OpsPage() {
  return (
    <div>
      <h1 className="page-title">Operations</h1>
      <p className="page-sub">Day summary, council skip reasons, and provider spend.</p>
      <div style={{ marginBottom: 14 }}><DaySummary /></div>
      <div className="cols">
        <Panel title="Council skip reasons"><SkipFeed /></Panel>
        <Panel title="Provider cost"><ProviderCostPanel /></Panel>
      </div>
    </div>
  );
}
