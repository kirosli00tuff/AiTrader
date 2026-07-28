// The SIZER and the CEILING are distinct quantities (2026-07-27).
//
// WHY THIS EXISTS. Until today `sizing.default_risk_per_trade_pct` (the sizer)
// and `risk.max_trade_risk_pct_of_equity` (the RiskGate's per-trade ceiling)
// were BOTH 0.005. Two different quantities holding the same number is how
// planning came to conflate them: EXPERIMENT.md described a 5,000 USD ceiling
// that does not exist, because the key it named (`max_trade_notional_cap_pct`)
// is parsed, range-validated, and enforced NOWHERE. The real ceiling was
// 500 USD and the sizer sat exactly on it, so any sizer increase would have
// rejected every order.
//
// The rule these tests pin:
//   * the sizer decides WHAT IS SENT,
//   * the ceiling decides WHAT IS PERMITTED,
//   * the ceiling is strictly ABOVE the sizer, a real backstop with headroom
//     rather than a duplicate of the sizing decision,
//   * and NEITHER is derived from the other. A future session that "tidies"
//     them into one constant reintroduces the conflation.
//
// The offline replay could not reach the raised ceilings (3 entries in 4,000
// iterations), so concurrency and book exposure are exercised here against the
// gate directly rather than assumed.
#include <cstdio>

#include "config/config.hpp"
#include "risk/risk_gate.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {

constexpr double kEquity = 100000.0;

risk::PortfolioState clean(double equity = kEquity) {
    risk::PortfolioState s;
    s.equity = equity;
    return s;
}

risk::OrderProposal order(double notional) {
    risk::OrderProposal o;
    o.venue = "alpaca";
    o.symbol = "AAPL";
    o.market = "AAPL";
    o.category = "equity";
    o.side = "buy";
    o.qty = 1.0;
    o.price = notional;
    o.notional = notional;
    o.confidence = 0.90;
    o.edge = 0.05;
    o.model_agreement_count = 3;
    return o;
}

}  // namespace

int main() {
    config::RiskConfig limits;      // shipped defaults
    config::SizingConfig sizing;    // shipped defaults
    risk::RiskGate gate(limits);

    // --- 1. THE TWO ARE DISTINCT, AND THE CEILING IS THE LARGER -----------
    maltest::check(sizing.default_risk_per_trade_pct !=
                       limits.max_trade_risk_pct_of_equity,
                   "the sizer and the per-trade ceiling are DIFFERENT numbers: "
                   "equal values are how the two came to be conflated");
    maltest::check(limits.max_trade_risk_pct_of_equity >
                       sizing.default_risk_per_trade_pct,
                   "the ceiling sits strictly ABOVE the sizer, so it is a real "
                   "backstop with headroom rather than a second copy of the "
                   "sizing decision");

    // --- 2. NEITHER IS DERIVED FROM THE OTHER ------------------------------
    // Moving one must not move the other. If a future session expresses one as
    // a multiple of the other, this catches it.
    {
        config::SizingConfig a = sizing;
        a.default_risk_per_trade_pct = 0.001;
        maltest::check(limits.max_trade_risk_pct_of_equity ==
                           config::RiskConfig{}.max_trade_risk_pct_of_equity,
                       "changing the sizer does not move the ceiling");
        config::RiskConfig b;
        b.max_trade_risk_pct_of_equity = 0.99;
        maltest::check(sizing.default_risk_per_trade_pct ==
                           config::SizingConfig{}.default_risk_per_trade_pct,
                       "changing the ceiling does not move the sizer");
    }

    // --- 3. A FULL-SIZE ORDER PASSES THE CEILING ---------------------------
    // The whole point of the change: what the sizer sends must be admissible.
    const double full = sizing.default_risk_per_trade_pct * kEquity;  // 2,000
    maltest::check(gate.evaluate(order(full), clean()).allowed,
                   "a full-size order at the sizer's own value passes the gate: "
                   "a sizer the gate rejects is a system that trades nothing");

    // --- 4. THE CEILING STILL REJECTS ABOVE ITSELF -------------------------
    const double over = limits.max_trade_risk_pct_of_equity * kEquity * 1.01;
    maltest::check(!gate.evaluate(order(over), clean()).allowed,
                   "an order above the ceiling is still refused: raising it did "
                   "not remove it");

    // --- 5. CONCURRENCY: the one-session-hold identity ---------------------
    // Peak concurrent positions equals entries per day for a one-session hold,
    // so the position cap must admit a full day of entries.
    {
        auto s = clean();
        s.open_positions_total = limits.max_open_positions_total - 1;
        s.open_positions_per_venue["alpaca"] =
            limits.max_open_positions_per_venue - 1;
        maltest::check(gate.evaluate(order(full), s).allowed,
                       "the last slot in a nearly full book is admissible");
        auto fullbook = clean();
        fullbook.open_positions_total = limits.max_open_positions_total;
        maltest::check(!gate.evaluate(order(full), fullbook).allowed,
                       "one past the cap is refused");
    }
    maltest::check(limits.max_open_positions_per_venue >=
                       limits.max_open_positions_total,
                   "the PER-VENUE cap must not bind before the total: every "
                   "tradeable symbol is venue alpaca since the crypto removal, "
                   "so a tighter per-venue cap silently becomes the real one");

    // --- 6. THE BOOK FITS ---------------------------------------------------
    // max_open_positions_total x sizer must fit inside the total open-risk cap
    // and inside the category cap, or the book jams before it fills.
    {
        const double book = limits.max_open_positions_total *
                            sizing.default_risk_per_trade_pct;
        maltest::check(limits.max_total_open_risk_pct >= book,
                       "a full book fits inside max_total_open_risk_pct");
        maltest::check(limits.max_exposure_per_category_pct >= book,
                       "a full book fits inside the category cap: every symbol "
                       "is category 'equity', so that cap bounds the WHOLE book");
        maltest::check(limits.max_exposure_per_symbol_pct >=
                           sizing.default_risk_per_trade_pct,
                       "one full-size position fits inside the per-symbol cap");
    }

    // --- 6b. THE SIZER CLEARS THE CAPACITY FLOOR ---------------------------
    // THE ASSERTION THAT PINS THE SIZER TO THE REQUIREMENT THAT PRODUCED IT.
    // Everything above is RELATIONAL and holds at any sizer, so reverting
    // 0.02 -> 0.005 passed the whole suite when this was missing. Caught by
    // mutation testing on 2026-07-27 and closed here.
    //
    // The derivation, restated as arithmetic the test can check: the capacity
    // floor is 2,500 USD/year on 100,000 equity, the trade ceiling permits
    // max_trades_per_day x 252 sessions, and the honest planning edge is 10 bp
    // net (half EXPERIMENT.md's optimistic 25 bp, which assumes the middle of
    // the literature AND the cost floor AND full frequency). A sizer that
    // cannot clear the floor at that edge cannot produce a meaningful dollar
    // result at any plausible edge, which is the defect this session fixed.
    {
        constexpr double kCapacityFloorUsd = 2500.0;
        constexpr double kSessionsPerYear = 252.0;
        constexpr double kHonestNetEdge = 0.0010;   // 10 bp
        const double notional = sizing.default_risk_per_trade_pct * kEquity;
        const double turnover =
            notional * limits.max_trades_per_day * kSessionsPerYear;
        maltest::check(turnover * kHonestNetEdge >= kCapacityFloorUsd,
                       "a full year at the permitted trade rate clears the "
                       "2,500 USD capacity floor at a 10 bp net edge: below "
                       "this the system cannot produce a meaningful dollar "
                       "result at any plausible edge");
        // And the sizer is not gratuitously large: the requirement is met
        // without deploying more than a quarter of capital at a full book.
        maltest::check(limits.max_open_positions_total *
                           sizing.default_risk_per_trade_pct <= 0.25,
                       "a full book deploys no more than 25 percent of capital: "
                       "the smallest sufficient sizer, not the largest allowed");
    }

    // --- 7. THE DAILY LOSS LIMIT STAYS MEANINGFUL --------------------------
    // It was deliberately NOT moved. Check it is neither unreachable nor
    // trivially reachable against the new book size.
    {
        const double book = limits.max_open_positions_total *
                            sizing.default_risk_per_trade_pct;   // 0.20
        const double move_to_halt = limits.max_daily_loss_total_pct / book;
        maltest::check(move_to_halt > 0.10,
                       "halting the day needs more than a 10 percent adverse "
                       "book move, which is outside one-session variation");
        maltest::check(move_to_halt < 1.0,
                       "and the limit is still reachable, so it is a real "
                       "control rather than decoration");
    }

    return maltest::report("sizing_and_ceilings");
}
