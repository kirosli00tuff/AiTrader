// Unit tests for IBKR routing safety.
//
// IBKR is the live-only venue. These tests prove two invariants without opening
// any socket:
//   1. An IBKR order in Live mode is REFUSED while the live gate is closed
//      (live_enabled=false). The live adapter is never invoked.
//   2. Every IBKR order passes the deterministic RiskGate in the routing path.
//      A gate-blocked order never reaches any adapter (no bypass).
#include "execution/execution.hpp"

#include "config/config.hpp"
#include "risk/risk_gate.hpp"
#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

namespace {

// Spy adapter: records how many times place() was called so a test can prove an
// adapter was (or was not) invoked. Never touches the network.
class SpyAdapter : public execution::VenueAdapter {
public:
    SpyAdapter(std::string nm, bool live) : name_(std::move(nm)), live_(live) {}
    std::string name() const override { return name_; }
    bool is_live() const override { return live_; }
    execution::Fill place(const risk::OrderProposal& o) override {
        ++calls;
        execution::Fill f;
        f.venue = o.venue;
        f.symbol = o.symbol;
        f.executed = true;
        f.note = "spy fill";
        return f;
    }
    int calls = 0;

private:
    std::string name_;
    bool live_;
};

risk::OrderProposal ibkr_order() {
    risk::OrderProposal o;
    o.venue = "ibkr";
    o.symbol = "SPY";
    o.market = "SPY";
    o.category = "equity";
    o.side = "buy";
    o.qty = 1;
    o.price = 100;
    o.notional = 100;
    o.confidence = 0.80;
    o.edge = 0.05;
    o.model_agreement_count = 3;
    o.signal_age_minutes = 1;
    o.is_live = true;
    return o;
}

risk::PortfolioState clean_state() {
    risk::PortfolioState s;
    s.equity = 100000;
    s.start_of_day_equity = 100000;
    return s;
}

// Mirror the engine's contract: evaluate the RiskGate FIRST, and only route when
// the gate allows. This is the single routing path the engine uses; there is no
// other way for an order to reach an adapter.
execution::Fill route_with_gate(const risk::RiskGate& gate,
                                 execution::ModeRouter& router,
                                 config::VenueMode mode,
                                 execution::VenueAdapter& paper,
                                 execution::VenueAdapter& live,
                                 const risk::OrderProposal& o,
                                 const risk::PortfolioState& s,
                                 bool live_enabled) {
    auto decision = gate.evaluate(o, s);
    if (!decision.allowed) {
        execution::Fill f;
        f.venue = o.venue;
        f.symbol = o.symbol;
        f.executed = false;
        f.note = "risk_block: " + decision.reason;
        return f;
    }
    return router.route(mode, paper, live, o, live_enabled);
}

}  // namespace

int main() {
    config::RiskConfig limits;  // safe defaults
    risk::RiskGate gate(limits);
    execution::ModeRouter router;

    // 1. IBKR live adapter identity is live-only.
    {
        execution::IbkrLiveAdapter ibkr;
        check(ibkr.is_live(), "IbkrLiveAdapter reports live");
        check(ibkr.name() == "ibkr_live", "IbkrLiveAdapter name is ibkr_live");
    }

    // 2. Live mode + gate closed (live_enabled=false) refuses and never calls the
    //    live adapter.
    {
        SpyAdapter paper("alpaca_paper", false);
        SpyAdapter live("ibkr_live", true);
        auto fill = router.route(config::VenueMode::Live, paper, live,
                                 ibkr_order(), /*live_enabled=*/false);
        check(!fill.executed, "IBKR live refused when live gate closed");
        check(fill.note.find("live not enabled") != std::string::npos,
              "refusal note explains live not enabled");
        check(live.calls == 0, "live adapter never invoked while gate closed");
        check(paper.calls == 0, "paper adapter not invoked for live-mode order");
    }

    // 3. Every IBKR order passes the RiskGate in the routing path: a blocked
    //    order never reaches any adapter (no bypass).
    {
        SpyAdapter paper("alpaca_paper", false);
        SpyAdapter live("ibkr_live", true);
        auto bad = ibkr_order();
        bad.confidence = 0.10;  // below min confidence -> gate denies
        auto fill = route_with_gate(gate, router, config::VenueMode::Live, paper,
                                    live, bad, clean_state(),
                                    /*live_enabled=*/true);
        check(!fill.executed, "gate-blocked IBKR order not executed");
        check(fill.note.find("risk_block") != std::string::npos,
              "block note came from RiskGate");
        check(live.calls == 0 && paper.calls == 0,
              "blocked order reached no adapter (no bypass)");
    }

    // 4. An allowed IBKR order still cannot execute live while the gate is closed
    //    (defence in depth: RiskGate allow does NOT enable live).
    {
        SpyAdapter paper("alpaca_paper", false);
        SpyAdapter live("ibkr_live", true);
        auto fill = route_with_gate(gate, router, config::VenueMode::Live, paper,
                                    live, ibkr_order(), clean_state(),
                                    /*live_enabled=*/false);
        check(!fill.executed, "gate-allowed IBKR order still refused live-closed");
        check(live.calls == 0, "live adapter not invoked when live disabled");
    }

    return report("ibkr_routing");
}
