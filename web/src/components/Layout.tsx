import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";
import RunStateBanner from "./RunStateBanner";

export default function Layout() {
  const { pathname } = useLocation();
  const view = pathname.startsWith("/live") ? "Live"
    : pathname.startsWith("/controls") ? "Controls"
    : pathname.startsWith("/health") ? "Health"
    : pathname.startsWith("/settings") ? "Settings"
    : "Paper";
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <StatusBar activeView={view} />
        <RunStateBanner />
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
