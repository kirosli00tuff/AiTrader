import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CollectionPage from "./pages/CollectionPage";
import OperatorPage from "./pages/OperatorPage";
import CouncilPage from "./pages/CouncilPage";
import DiagnosticsPage from "./pages/DiagnosticsPage";
import PaperSection from "./pages/PaperPage";
import Overview from "./pages/Overview";
import LiveSection from "./pages/LivePage";
import LiveOverview from "./pages/LiveOverview";
import CategoryView from "./pages/CategoryView";
import ControlsPage from "./pages/ControlsPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import WatchlistPage from "./pages/WatchlistPage";
import AdaptivePage from "./pages/AdaptivePage";
import LongTermPage from "./pages/LongTermPage";
import HealthPage from "./pages/HealthPage";
import OpsPage from "./pages/OpsPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* COLLECTION IS THE FRONT DOOR. A missed session is unrecoverable,
            so the daily check must be opening a tab rather than remembering to
            navigate. The operator surface keeps its own route. */}
        <Route index element={<CollectionPage />} />
        <Route path="operator" element={<OperatorPage />} />
        <Route path="council" element={<CouncilPage />} />
        <Route path="diagnostics" element={<DiagnosticsPage />} />
        <Route path="paper" element={<PaperSection />}>
          <Route index element={<Overview />} />
          <Route path="stocks" element={<CategoryView mode="paper" category="stocks" />} />
          <Route path="crypto" element={<CategoryView mode="paper" category="crypto" />} />
        </Route>
        <Route path="live" element={<LiveSection />}>
          <Route index element={<LiveOverview />} />
          <Route path="stocks" element={<CategoryView mode="live" category="stocks" />} />
          <Route path="crypto" element={<CategoryView mode="live" category="crypto" />} />
        </Route>
        <Route path="controls" element={<ControlsPage />} />
        {/* Discovery views: read-only. No control lives on these routes. */}
        <Route path="discovery" element={<DiscoveryPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        {/* Adaptive layer: read-only. Its toggles live on Controls,
            with the rest of the enable surface. */}
        <Route path="adaptive" element={<AdaptivePage />} />
        <Route path="longterm" element={<LongTermPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="ops" element={<OpsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
