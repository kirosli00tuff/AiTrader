// Unit tests for Layer-1 RiskGate — the deterministic final-authority gate.
#include "risk/risk_gate.hpp"

#include "config/config.hpp"
#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

static risk::OrderProposal good_order() {
    risk::OrderProposal o;
    o.venue = "alpaca";
    o.symbol = "AAPL";
    o.market = "AAPL";
    o.category = "equity";
    o.side = "buy";
    o.qty = 1;
    o.price = 100;
    o.notional = 100;             // 0.1% of 100k equity (< 0.5% cap)
    o.confidence = 0.80;
    o.edge = 0.05;
    o.model_agreement_count = 3;
    o.signal_age_minutes = 1;
    return o;
}

static risk::PortfolioState clean_state() {
    risk::PortfolioState s;
    s.equity = 100000;
    s.start_of_day_equity = 100000;
    return s;
}

int main() {
    config::RiskConfig limits;  // safe defaults
    risk::RiskGate gate(limits);

    // 1. A clean, high-quality order is allowed.
    {
        auto d = gate.evaluate(good_order(), clean_state());
        check(d.allowed, "clean high-quality order allowed");
        check(d.reason == "OK", "allowed reason is OK");
    }

    // 2. Low confidence is denied.
    {
        auto o = good_order();
        o.confidence = 0.10;
        auto d = gate.evaluate(o, clean_state());
        check(!d.allowed, "low-confidence order denied");
    }

    // 3. Edge below minimum denied.
    {
        auto o = good_order();
        o.edge = 0.0;
        auto d = gate.evaluate(o, clean_state());
        check(!d.allowed, "below-min-edge order denied");
    }

    // 4. Insufficient model agreement denied.
    {
        auto o = good_order();
        o.model_agreement_count = 1;  // need >= 2
        auto d = gate.evaluate(o, clean_state());
        check(!d.allowed, "insufficient agreement denied");
    }

    // 5. Stale signal denied.
    {
        auto o = good_order();
        o.signal_age_minutes = 999;
        auto d = gate.evaluate(o, clean_state());
        check(!d.allowed, "stale signal denied");
    }

    // 6. Per-trade notional cap enforced.
    {
        auto o = good_order();
        o.notional = 100000;  // 100% of equity >> 0.5% cap
        auto d = gate.evaluate(o, clean_state());
        check(!d.allowed, "oversized trade denied");
    }

    // 7. Kill switch tripped => denied regardless of order quality.
    {
        auto s = clean_state();
        s.kill_switch_tripped = true;
        auto d = gate.evaluate(good_order(), s);
        check(!d.allowed, "kill switch blocks all orders");
    }

    // 8. Manual-resume-pending => denied.
    {
        auto s = clean_state();
        s.manual_resume_pending = true;
        auto d = gate.evaluate(good_order(), s);
        check(!d.allowed, "manual-resume-pending blocks orders");
    }

    // 9. Daily loss breach => denied.
    {
        auto s = clean_state();
        s.realized_pnl_today_total = -0.05 * s.equity;  // -5% > 3% limit
        auto d = gate.evaluate(good_order(), s);
        check(!d.allowed, "daily loss breach blocks orders");
    }

    // 10. Consecutive losses at limit => denied.
    {
        auto s = clean_state();
        s.consecutive_losses = 3;
        auto d = gate.evaluate(good_order(), s);
        check(!d.allowed, "max consecutive losses blocks orders");
    }

    // 11. Exposure-per-symbol cap enforced.
    {
        auto s = clean_state();
        s.exposure_per_symbol["AAPL"] = 0.019 * s.equity;
        auto o = good_order();
        o.notional = 0.01 * s.equity;  // would exceed 2% symbol cap
        auto d = gate.evaluate(o, s);
        check(!d.allowed, "symbol exposure cap enforced");
    }

    // 12. KillSwitch state machine: trip latches, manual resume clears.
    {
        risk::KillSwitch ks(true, true);
        check(!ks.tripped(), "kill switch starts untripped");
        check(ks.trip("test"), "kill switch trips");
        check(ks.tripped(), "kill switch latched");
        check(ks.manual_resume_pending(), "manual resume pending after trip");
        check(ks.manual_resume(), "manual resume clears");
        check(!ks.tripped(), "kill switch cleared after resume");
    }

    return report("risk_gate");
}
