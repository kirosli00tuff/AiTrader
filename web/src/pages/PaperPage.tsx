import { Outlet } from "react-router-dom";
import SubNav from "../components/SubNav";

// Paper section wrapper. Holds the section header, the Overview/Stocks/Crypto
// sub navigation, and the routed subpage. Paper is never locked.
export default function PaperSection() {
  return (
    <div>
      <h1 className="page-title">Paper trading</h1>
      <p className="page-sub">
        Alpaca paper loop, the continuous training environment.
      </p>
      <SubNav base="/paper" />
      <Outlet context={{ locked: false }} />
    </div>
  );
}
