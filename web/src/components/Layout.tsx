import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";

export default function Layout() {
  const { pathname } = useLocation();
  const view = pathname.startsWith("/live")
    ? "Live"
    : pathname.startsWith("/settings")
      ? "Settings"
      : "Paper";
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <StatusBar activeView={view} />
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
