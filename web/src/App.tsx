import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import PaperSection from "./pages/PaperPage";
import Overview from "./pages/Overview";
import LiveSection from "./pages/LivePage";
import LiveOverview from "./pages/LiveOverview";
import CategoryView from "./pages/CategoryView";
import ControlsPage from "./pages/ControlsPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/paper" replace />} />
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
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/paper" replace />} />
      </Route>
    </Routes>
  );
}
