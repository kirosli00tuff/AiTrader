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
        // Swing (dual-MA off, bollinger reversion) is unchanged: the trend MA
        // never gates warmth, so trend_ma is true and min stays ema_slow+2.
        check(warm.trend_ma, "swing profile: trend_ma warm flag is true (inactive)");
    }

    // --- Regime selects the leading factor (Task 3) -------------------------
    {
        config::StrategyConfig cfg;  // trending 0.70/0.30, range 0.30/0.70, neutral 0.50/0.50
        check(strategy::active_factor_for(strategy::Regime::Trending, cfg) == "momentum",
              "trending regime leads with momentum");
        check(strategy::active_factor_for(strategy::Regime::RangeBound, cfg) == "reversion",
              "range-bound regime leads with reversion");
        check(strategy::active_factor_for(strategy::Regime::Neutral, cfg) == "blend",
              "neutral regime blends (equal weights)");
    }

    // --- Momentum dual-MA trend filter (Task 2) -----------------------------
    {
        auto cfg = small_cfg();
        cfg.momentum_dual_ma_filter = true;
        cfg.momentum_medium_ma = 3;
        cfg.momentum_long_ma = 6;
        cfg.ts_momentum_lookback = 0;
        // Flat then a jump up: crossover fires AND price is above both MAs.
        auto up = flat_bars(28, 100.0);
        up.push_back(Bar{100, 121, 100, 120, 5000});
        auto sig_up = strategy::evaluate_momentum(up, cfg, /*allow_short=*/false);
        check(sig_up.has_signal && sig_up.direction == strategy::Direction::Long,
              "dual-MA momentum fires when price is above both MAs");
        // A crossover where price sits BELOW the long MA is blocked by the filter.
        // High plateau then a decline to a low crossover point.
        std::vector<Bar> down;
        for (int i = 0; i < 20; ++i) down.push_back(Bar{150, 150.5, 149.5, 150, 1000});
        for (int i = 0; i < 8; ++i) {
            double c = 150 - (i + 1) * 6.0;  // fall from 150 toward ~102
            down.push_back(Bar{c + 6, c + 0.5, c - 0.5, c, 1000});
        }
        down.push_back(Bar{102, 105, 101, 104, 5000});  // small uptick (cross up), price << long MA
        auto sig_dn = strategy::evaluate_momentum(down, cfg, /*allow_short=*/false);
        check(!sig_dn.has_signal,
              "dual-MA momentum blocked when price is below the long MA");
    }

    // --- Connors RSI-2 reversion (Task 1) -----------------------------------
    // Build a clear uptrend (price above the trend MA), a sharp pullback that
    // drops RSI-2 below the entry threshold, then a bounce (RSI-2 crosses back).
    auto rsi2_cfg = []() {
        config::StrategyConfig c;
        c.reversion_style = "rsi2";
        c.rsi2_period = 2;
        c.rsi2_entry_crypto = 20.0;
        c.rsi2_entry_equity = 20.0;
        c.rsi2_exit = 60.0;
        c.rsi2_crossback_confirm = true;
        c.trend_ma_period = 20;
        c.atr_mean_period = 10;
        c.atr_band_std = 8.0;   // wide, does not gate
        c.atr_period = 14;
        c.vol_lookback = 20;
        return c;
    };
    // Uptrend then pullback then bounce. Returns the bar vector.
    auto rsi2_bars = [](double bounce_vol) {
        std::vector<Bar> b;
        for (int i = 0; i < 28; ++i) {
            double c = 100 + i;                 // 100..127 uptrend
            b.push_back(Bar{c - 1, c + 0.5, c - 1.0, c, 1000});
        }
        b.push_back(Bar{127, 127, 123.5, 124, 1000});  // pullback
        b.push_back(Bar{124, 124, 120.5, 121, 1000});  // deeper pullback (RSI-2 low)
        b.push_back(Bar{121, 123.5, 121, 123, bounce_vol});  // bounce (RSI-2 crosses back)
        return b;
    };
    {
        auto cfg = rsi2_cfg();
        auto bars = rsi2_bars(1000);
        auto sig = strategy::evaluate_rsi2_reversion(bars, cfg, /*is_crypto=*/true);
        check(sig.has_signal && sig.direction == strategy::Direction::Long,
              "RSI-2 fires long on a dip inside an uptrend with cross-back");
        check(sig.stop_price < sig.entry_price, "RSI-2 long stop below entry (wide ATR)");
        check(sig.target_price > sig.entry_price, "RSI-2 target above entry");

        // Trend filter: the SAME dip below the trend MA does NOT fire (long only
        // inside a confirmed uptrend).
        std::vector<Bar> downtrend;
        for (int i = 0; i < 28; ++i) {
            double c = 160 - i;                 // 160..133 downtrend
            downtrend.push_back(Bar{c + 1, c + 1.0, c - 0.5, c, 1000});
        }
        downtrend.push_back(Bar{133, 133, 129.5, 130, 1000});
        downtrend.push_back(Bar{130, 130, 126.5, 127, 1000});
        downtrend.push_back(Bar{127, 129.5, 127, 129, 1000});  // bounce but price < trend MA
        auto no_sig = strategy::evaluate_rsi2_reversion(downtrend, cfg, /*is_crypto=*/true);
        check(!no_sig.has_signal,
              "RSI-2 does not fire when price is below the trend MA");

        // Volume filter: a below-average bounce volume gates the entry.
        auto low_vol = strategy::evaluate_rsi2_reversion(rsi2_bars(50), cfg, true);
        check(!low_vol.has_signal, "RSI-2 gated on below-average volume");

        // UNKNOWN volume does NOT gate (2026-07-21). A bar reporting no
        // volume is unmeasured, not low: the live Alpaca path has no venue
        // volume, and this check used to run against a uniform random draw.
        // The distinction is the whole fix, so both directions are pinned
        // here: 50 is a real below-average reading and still gates, 0 is an
        // absent reading and must not.
        auto unknown_vol = strategy::evaluate_rsi2_reversion(rsi2_bars(0), cfg, true);
        check(unknown_vol.has_signal,
              "RSI-2 fires when the bar reports NO volume: absent is not "
              "below-average, and gating on absence is gating on nothing");

        // Cross-back confirmation: with confirm OFF, entry may fire on the deep
        // pullback bar itself (RSI-2 already below the threshold), a different
        // trigger than the confirmed cross-back.
        auto cfg_no_confirm = rsi2_cfg();
        cfg_no_confirm.rsi2_crossback_confirm = false;
        auto bars_pullback = rsi2_bars(1000);
        bars_pullback.pop_back();  // drop the bounce; end on the deep pullback bar
        auto without = strategy::evaluate_rsi2_reversion(bars_pullback, cfg_no_confirm, true);
        auto with = strategy::evaluate_rsi2_reversion(bars_pullback, rsi2_cfg(), true);
        check(without.has_signal && !with.has_signal,
              "cross-back confirm gates the un-confirmed dip (fires only without confirm)");
    }

    // --- RSI-2 native exit (Task 1) -----------------------------------------
    {
        auto cfg = rsi2_cfg();
        // A strictly rising tail pushes RSI-2 high => exit triggers.
        std::vector<Bar> rising;
        for (int i = 0; i < 10; ++i) {
            double c = 100 + i * 2;
            rising.push_back(Bar{c - 1, c + 0.5, c - 1, c, 1000});
        }
        check(strategy::rsi2_exit_triggered(rising, cfg),
              "RSI-2 exit triggers when RSI-2 rises above the exit threshold");
        // A falling tail keeps RSI-2 low => no exit.
        std::vector<Bar> falling;
        for (int i = 0; i < 10; ++i) {
            double c = 120 - i * 2;
            falling.push_back(Bar{c + 1, c + 1, c - 0.5, c, 1000});
        }
        check(!strategy::rsi2_exit_triggered(falling, cfg),
              "RSI-2 exit does not trigger while RSI-2 stays low");
        // check_exit routes an indicator exit after stop/target, before time-stop.
        strategy::OpenPosition pos;
        pos.direction = strategy::Direction::Long;
        pos.entry_price = 100; pos.stop_price = 90; pos.target_price = 200;
        pos.time_stop_bars = 100; pos.bars_held = 1;
        Bar inside{100, 101, 99, 100, 1000};
        check(strategy::check_exit(pos, inside, /*indicator_exit=*/true) ==
                  strategy::ExitReason::Indicator,
              "check_exit returns Indicator when the RSI-2 exit fires");
        check(strategy::check_exit(pos, inside, /*indicator_exit=*/false) ==
                  strategy::ExitReason::None,
              "check_exit stays open with no indicator exit and stop/target not hit");
    }

    // --- Blend selects RSI-2 (engine's evaluate() path) ---------------------
    {
        auto cfg = rsi2_cfg();  // reversion_style rsi2
        cfg.momentum_enabled = true;  // both factors active; blend must pick RSI-2
        auto bars = rsi2_bars(1500);
        auto d = strategy::evaluate(bars, cfg, /*is_crypto=*/true);
        check(d.signal.has_signal, "evaluate() with rsi2 style produces a signal");
        check(d.signal.factor == "reversion",
              "evaluate() selects the RSI-2 reversion factor on a dip in an uptrend");
        check(d.signal.direction == strategy::Direction::Long,
              "the selected RSI-2 signal is long");
    }

    // --- Two-tier routing (Task 5) ------------------------------------------
    {
        config::CouncilConfig co;  // swing defaults: 0.0 / 0.0
        check(signal_engine::decide_tier(co, /*notional=*/50.0, /*equity=*/100000.0,
                                         /*conviction=*/0.1) ==
                  signal_engine::Tier::Council,
              "swing (0/0 thresholds): no real entry is fast-tiered");
        // active_quant thresholds: small + low-conviction => Fast, else Council.
        co.fast_tier_max_notional_pct = 0.01;   // 1% of equity
        co.fast_tier_max_conviction = 0.6;
        check(signal_engine::decide_tier(co, 500.0, 100000.0, 0.3) ==
                  signal_engine::Tier::Fast,
              "small + low-conviction entry takes the fast tier");
        check(signal_engine::decide_tier(co, 5000.0, 100000.0, 0.3) ==
                  signal_engine::Tier::Council,
              "large entry takes the council tier");
        check(signal_engine::decide_tier(co, 500.0, 100000.0, 0.9) ==
                  signal_engine::Tier::Council,
              "high-conviction entry takes the council tier");
    }

    // --- Spend ceiling (Task 9) ---------------------------------------------
    {
        config::CouncilConfig co;
        co.council_est_cost_per_call_usd = 0.5;
        signal_engine::CouncilGateState st;
        // Disabled ceilings (0.0): never reached.
        st.calls_today = 100; st.calls_month = 1000;
        check(!signal_engine::spend_ceiling_reached(co, st),
              "spend ceiling disabled at 0.0 is never reached");
        // Daily ceiling $1 at $0.5/call: reached at 2 calls, not at 1.
        co.council_daily_spend_ceiling_usd = 1.0;
        st.calls_today = 1; st.calls_month = 1;
        check(!signal_engine::spend_ceiling_reached(co, st),
              "one call below the daily ceiling is allowed");
        st.calls_today = 2;
        check(signal_engine::spend_ceiling_reached(co, st),
              "the daily spend ceiling forces fast tier when reached");
        // Monthly ceiling independently.
        config::CouncilConfig cm;
        cm.council_est_cost_per_call_usd = 0.5;
        cm.council_monthly_spend_ceiling_usd = 100.0;
        signal_engine::CouncilGateState sm;
        sm.calls_today = 0; sm.calls_month = 200;  // 200*0.5 = 100 >= 100
        check(signal_engine::spend_ceiling_reached(cm, sm),
              "the monthly spend ceiling forces fast tier when reached");
    }

    return report("strategy");
}
