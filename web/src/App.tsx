import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import PaperPage from "./pages/PaperPage";
import LivePage from "./pages/LivePage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/paper" replace />} />
        <Route path="/paper" element={<PaperPage />} />
        <Route path="/live" element={<LivePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/paper" replace />} />
      </Route>
    </Routes>
  );
}
