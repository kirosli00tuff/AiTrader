// Unit tests for the native strategy layer: indicators, regime classification,
// momentum crossover, and the equities long-only policy. Uses synthetic bar
// fixtures with hand-verified expected outputs (no I/O, no network).
#include "signal_engine/strategy.hpp"

#include <vector>

#include "signal_engine/council_gate.hpp"
#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;
using strategy::Bar;

namespace {

// Build a flat run of `count` bars at `price` with a small +/-1 range so ATR>0.
std::vector<Bar> flat_bars(int count, double price) {
    std::vector<Bar> b;
    for (int i = 0; i < count; ++i)
        b.push_back(Bar{price, price + 1, price - 1, price, 1000});
    return b;
}

// A short strategy config with small periods so crossovers are hand-verifiable.
config::StrategyConfig small_cfg() {
    config::StrategyConfig c;
    c.ema_fast = 3;
    c.ema_slow = 6;
    c.adx_min = 0.0;         // isolate the crossover from the ADX filter
    c.atr_period = 3;
    c.atr_vol_floor = 0.0;
    return c;
}

}  // namespace

int main() {
    // --- Indicators ------------------------------------------------------
    {
        std::vector<double> constant{5, 5, 5, 5, 5};
        check_near(strategy::ema(constant, 3), 5.0, 1e-9, "EMA of constant == constant");
        std::vector<double> ramp{1, 2, 3, 4};
        check_near(strategy::sma(ramp, 2), 3.5, 1e-9, "SMA last-2 of 1..4 == 3.5");
        std::vector<double> rising{1, 2, 3, 4, 5, 6, 7};
        check_near(strategy::rsi(rising, 3), 100.0, 1e-9,
                   "RSI of strictly rising series == 100");
        auto bb = strategy::bollinger(constant, 3, 2.0);
        check_near(bb.mid, 5.0, 1e-9, "Bollinger mid of constant == mean");
        check_near(bb.sd, 0.0, 1e-9, "Bollinger sd of constant == 0");
        auto ab = flat_bars(20, 100.0);
        check(strategy::atr(ab, 3) > 0.0, "ATR positive when bars have range");
    }

    // --- Regime classification ------------------------------------------
    {
        config::StrategyConfig cfg;  // defaults: regime_adx_trend=25
        // Strictly rising bars => pure +DM => ADX -> ~100 => Trending.
        std::vector<Bar> up;
        for (int i = 0; i < 40; ++i) {
            double c = 100 + i;
            up.push_back(Bar{c, c + 0.5, c - 0.5, c, 1000});
        }
        auto rup = strategy::detect_regime(up, cfg);
        check(rup.regime == strategy::Regime::Trending,
              "strong uptrend classified Trending");

        // Flat bars => ADX 0, rvol 0 => Neutral.
        auto flat = flat_bars(40, 100.0);
        auto rflat = strategy::detect_regime(flat, cfg);
        check(rflat.regime == strategy::Regime::Neutral,
              "flat series classified Neutral");
    }

    // --- Momentum crossover (long) --------------------------------------
    {
        auto cfg = small_cfg();
        // 28 flat bars then a jump up on the final bar => fast EMA crosses above
        // slow EMA on the last bar => long entry.
        auto bars = flat_bars(28, 100.0);
        bars.push_back(Bar{100, 121, 100, 120, 5000});
        auto sig = strategy::evaluate_momentum(bars, cfg, /*allow_short=*/false);
        check(sig.has_signal, "momentum fires on upward crossover");
        check(sig.direction == strategy::Direction::Long, "crossover is long");
        check(sig.entry_price == 120.0, "entry at last close");
        check(sig.stop_price < sig.entry_price, "long stop below entry");
        check(sig.target_price > sig.entry_price, "long target above entry");
        check(sig.time_stop_bars == cfg.time_stop_bars, "native time stop set");
    }

    // --- Equities long-only policy --------------------------------------
    {
        auto cfg = small_cfg();
        // Downward crossover on the final bar.
        auto bars = flat_bars(28, 100.0);
        bars.push_back(Bar{100, 100, 79, 80, 5000});
        auto no_short = strategy::evaluate_momentum(bars, cfg, /*allow_short=*/false);
        check(!no_short.has_signal,
              "down-cross yields NO signal when shorting disallowed (equities)");
        auto with_short = strategy::evaluate_momentum(bars, cfg, /*allow_short=*/true);
        check(with_short.has_signal && with_short.direction == strategy::Direction::Short,
              "same down-cross yields a short when shorting allowed");
    }

    // --- Bar aggregation (tick -> closed OHLCV bar) ---------------------
    {
        strategy::BarAggregator agg(300);  // 5-minute buckets
        check(!agg.add("k", 0, 100, 10).has_value(), "first tick opens a bucket");
        check(!agg.add("k", 100, 105, 5).has_value(), "same-bucket tick, no close");
        check(!agg.add("k", 200, 95, 5).has_value(), "same-bucket tick, no close");
        auto closed = agg.add("k", 300, 110, 1);  // crosses into bucket 1
        check(closed.has_value(), "new bucket closes the prior bar");
        check(closed->open == 100 && closed->high == 105 && closed->low == 95 &&
                  closed->close == 95 && closed->volume == 20,
              "closed bar OHLCV aggregated correctly");
        check(!agg.add("k", 250, 999, 1).has_value(),
              "stale out-of-order tick is ignored");
    }

    // --- Native exits (stop / target / time-stop + realized PnL) --------
    {
        strategy::OpenPosition lp;
        lp.direction = strategy::Direction::Long;
        lp.entry_price = 100; lp.qty = 10; lp.stop_price = 90;
        lp.target_price = 130; lp.time_stop_bars = 24; lp.bars_held = 0;

        Bar hit_stop{95, 105, 89, 95, 1000};
        check(strategy::check_exit(lp, hit_stop) == strategy::ExitReason::Stop,
              "long: bar low through stop => Stop");
        check_near(strategy::realized_pnl(lp, strategy::exit_fill_price(
                       lp, strategy::ExitReason::Stop, hit_stop)),
                   -100.0, 1e-9, "long stop realized PnL = -100");

        Bar hit_target{100, 131, 95, 128, 1000};
        check(strategy::check_exit(lp, hit_target) == strategy::ExitReason::Target,
              "long: bar high through target => Target");
        check_near(strategy::realized_pnl(lp, strategy::exit_fill_price(
                       lp, strategy::ExitReason::Target, hit_target)),
                   300.0, 1e-9, "long target realized PnL = +300");

        Bar inside{100, 105, 96, 101, 1000};
        check(strategy::check_exit(lp, inside) == strategy::ExitReason::None,
              "long: price inside band, under time-stop => None");

        lp.bars_held = 24;
        check(strategy::check_exit(lp, inside) == strategy::ExitReason::TimeStop,
              "long: bars_held >= time_stop => TimeStop");
        lp.bars_held = 0;

        Bar both{95, 131, 89, 120, 1000};  // stop AND target within the bar
        check(strategy::check_exit(lp, both) == strategy::ExitReason::Stop,
              "long: stop takes priority over target (risk-first)");

        strategy::OpenPosition sp;
        sp.direction = strategy::Direction::Short;
        sp.entry_price = 100; sp.qty = 10; sp.stop_price = 110;
        sp.target_price = 70; sp.time_stop_bars = 24;
        Bar s_stop{100, 111, 98, 108, 1000};
        check(strategy::check_exit(sp, s_stop) == strategy::ExitReason::Stop,
              "short: bar high through stop => Stop");
        Bar s_target{100, 105, 69, 72, 1000};
        check(strategy::check_exit(sp, s_target) == strategy::ExitReason::Target,
              "short: bar low through target => Target");
        check_near(strategy::realized_pnl(sp, 70.0), 300.0, 1e-9,
                   "short target realized PnL = +300");
    }

    // --- Council cost-control gate --------------------------------------
    {
        namespace se = mal::signal_engine;
        config::CouncilConfig cfg;  // budget 30, cooldown 60min, neutral thr 0.5
        se::CouncilGateState st;
        const std::string sym = "BTC/USD";

        // Strong signal in a trending regime, fresh state => Proceed.
        check(se::decide_council(cfg, st, strategy::Regime::Trending, 0.8, sym,
                                 1000) == se::CouncilDecision::Proceed,
              "council proceeds on strong trending signal");

        // Neutral regime + weak signal => SkipNeutral.
        check(se::decide_council(cfg, st, strategy::Regime::Neutral, 0.3, sym,
                                 1000) == se::CouncilDecision::SkipNeutral,
              "council skips: neutral regime + weak signal");
        // Neutral regime but strong signal => not skipped.
        check(se::decide_council(cfg, st, strategy::Regime::Neutral, 0.7, sym,
                                 1000) == se::CouncilDecision::Proceed,
              "council proceeds: neutral regime but strong signal");

        // Cooldown: after a call at t=1000, a call within 60min is skipped.
        se::record_council_call(st, sym, 1000);
        check(se::decide_council(cfg, st, strategy::Regime::Trending, 0.8, sym,
                                 1000 + 3599) == se::CouncilDecision::SkipCooldown,
              "council skips within per-symbol cooldown");
        check(se::decide_council(cfg, st, strategy::Regime::Trending, 0.8, sym,
                                 1000 + 3600) == se::CouncilDecision::Proceed,
              "council proceeds once cooldown elapsed");
        // A different symbol is unaffected by the first symbol's cooldown.
        check(se::decide_council(cfg, st, strategy::Regime::Trending, 0.8, "SPY",
                                 1000) == se::CouncilDecision::Proceed,
              "cooldown is per-symbol");

        // Budget: exhausting the daily budget => SkipBudget (fresh symbol).
        se::CouncilGateState budget_st;
        budget_st.calls_today = cfg.council_daily_budget;
        check(se::decide_council(cfg, budget_st, strategy::Regime::Trending, 0.8,
                                 "QQQ", 5000) == se::CouncilDecision::SkipBudget,
              "council skips when daily budget exhausted");
        // New UTC day rolls the budget over.
        budget_st.utc_day = "2026-07-02";
        se::reset_if_new_day(budget_st, "2026-07-03");
        check(budget_st.calls_today == 0, "new UTC day resets the daily budget");
        check(se::decide_council(cfg, budget_st, strategy::Regime::Trending, 0.8,
                                 "QQQ", 5000) == se::CouncilDecision::Proceed,
              "council proceeds after daily budget reset");
    }

    // --- Indicator warm-state (Task 1) --------------------------------------
    {
        config::StrategyConfig sc;  // production defaults (ema_slow 100 dominates)
        const int need = strategy::min_bars_to_warm(sc);
        check(need == sc.ema_slow + 2,
              "min_bars_to_warm is the longest lookback (ema_slow + 2)");
        check(!strategy::indicators_warm(need - 1, sc),
              "a symbol reads COLD one bar below the longest lookback");
        check(strategy::indicators_warm(need, sc),
              "a symbol reads WARM once the longest lookback is satisfied");
        auto cold = strategy::indicator_warm_state(sc.bb_period, sc);
        check(cold.bollinger && !cold.ema_slow && !cold.all,
              "at bb_period bars: Bollinger warm, 100-EMA cold, not all warm");
        auto warm = strategy::indicator_warm_state(need, sc);
        check(warm.ema_slow && warm.adx && warm.atr && warm.bollinger &&
                  warm.rsi && warm.volume && warm.rvol && warm.all,
              "at min_bars_to_warm every indicator is warm");
        check(warm.bars == need, "warm-state reports the bar count");
    }

    return report("strategy");
}
