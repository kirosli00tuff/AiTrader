// Market AI Lab — native strategy layer.
//
// Two signal factors (trend/momentum + mean reversion) plus a regime detector,
// evaluated ONLY on CLOSED bars (never per tick). Every entry computes its
// native ATR stop / ATR target / time-stop at signal time; those exits execute
// natively with NO council involvement. Pure and deterministic: all functions
// take explicit bar history + config and return plain structs (no I/O, no DB).
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "config/config.hpp"

namespace mal::strategy {

// One closed OHLCV bar (the unit the strategies evaluate on).
struct Bar {
    double open = 0, high = 0, low = 0, close = 0, volume = 0;
};

// Aggregates streaming ticks into fixed-duration OHLCV bars, per key
// (e.g. "venue|symbol"). Deterministic and pure w.r.t. wall-clock: the caller
// supplies each tick's epoch seconds, so bucketing is floor(epoch/bucket_secs).
// add() returns the just-CLOSED bar when a tick opens a new bucket, else
// nullopt. Out-of-order ticks older than the current bucket are ignored.
class BarAggregator {
public:
    explicit BarAggregator(long bucket_seconds) : bucket_seconds_(bucket_seconds) {}
    std::optional<Bar> add(const std::string& key, long epoch_seconds,
                           double price, double volume);

private:
    struct Partial {
        long bucket = -1;
        Bar bar;
    };
    std::map<std::string, Partial> state_;
    long bucket_seconds_;
};

// --- Indicators (pure) ---------------------------------------------------
// Callers must supply sufficient history; helpers return 0 / empty when data is
// insufficient rather than throwing.
std::vector<double> closes_of(const std::vector<Bar>& bars);
std::vector<double> ema_series(const std::vector<double>& xs, int period);
double ema(const std::vector<double>& xs, int period);
double sma(const std::vector<double>& xs, int period);
std::vector<double> rsi_series(const std::vector<double>& closes, int period);
double rsi(const std::vector<double>& closes, int period);
double atr(const std::vector<Bar>& bars, int period);
double adx(const std::vector<Bar>& bars, int period);
double realized_vol(const std::vector<double>& closes, int lookback);
double avg_volume(const std::vector<Bar>& bars, int lookback);

struct Bollinger {
    double mid = 0, upper = 0, lower = 0, sd = 0;
};
Bollinger bollinger(const std::vector<double>& closes, int period, double num_std);

// --- Indicator warm-state (Task 1) ---------------------------------------
// The native strategy needs enough closed bars before every indicator is
// meaningful. On the real paper path the engine refuses to evaluate a symbol
// for entry until it is warm, so a live run never fires on partial data. Warm
// is a function of the bar COUNT alone: each indicator's minimum is its period.
struct WarmState {
    int bars = 0;
    bool ema_slow = false;   // 100-period EMA (momentum cross reads n-1, n-2)
    bool adx = false;        // ADX (Wilder smoothing needs 2*period+1 bars)
    bool atr = false;        // ATR
    bool bollinger = false;  // 20-period Bollinger bands
    bool rsi = false;        // RSI 14 (reversion reads rsi[n-1] and rsi[n-2])
    bool volume = false;     // N-bar average volume
    bool rvol = false;       // realized-vol regime window
    bool trend_ma = false;   // long trend MA (RSI-2 / dual-MA); true when inactive
    bool all = false;        // every indicator above is warm
};

// Minimum closed bars for every listed indicator to be warm. This is the
// longest indicator lookback, so a symbol is warm exactly once it is satisfied.
int min_bars_to_warm(const config::StrategyConfig& cfg);

// Per-indicator warm/cold for a given bar count. Pure: only the count is needed
// because each indicator's requirement is a function of its configured period.
WarmState indicator_warm_state(int bar_count, const config::StrategyConfig& cfg);

// True once bar_count satisfies every indicator lookback (== warm_state.all).
bool indicators_warm(int bar_count, const config::StrategyConfig& cfg);

// --- Regime detection ----------------------------------------------------
enum class Regime { Trending, RangeBound, Neutral };
std::string regime_to_string(Regime r);
// Parse a regime label ("trending" | "range_bound" | "neutral") back to a
// Regime. Used by the operator regime-pin override. Unknown => Neutral.
Regime regime_from_string(const std::string& s);

struct RegimeResult {
    Regime regime = Regime::Neutral;
    double adx = 0;
    double rvol = 0;
};
RegimeResult detect_regime(const std::vector<Bar>& bars,
                           const config::StrategyConfig& cfg);

// The factor the regime selects to LEAD ("momentum" | "reversion" | "blend").
// Trending favors momentum, range-bound favors reversion, neutral blends. The
// engine persists this alongside the regime for the GUI.
std::string active_factor_for(Regime r, const config::StrategyConfig& cfg);

// --- Signals -------------------------------------------------------------
enum class Direction { None, Long, Short };
std::string direction_to_string(Direction d);

struct StrategySignal {
    bool has_signal = false;
    Direction direction = Direction::None;
    std::string factor;        // "momentum" | "reversion"
    double strength = 0.0;     // [0,1]
    double entry_price = 0.0;
    double stop_price = 0.0;   // native ATR stop, set at entry
    double target_price = 0.0; // native target, set at entry
    int time_stop_bars = 0;    // native time stop (bars), set at entry
    std::string rationale;
};

// Strategy A — trend/momentum: EMA fast/slow crossover, ADX filter, ATR vol
// floor. Equities are long-only in paper; `allow_short` gates the short side.
// When cfg.momentum_dual_ma_filter is on, a long also needs price above BOTH the
// medium and long MA (and a positive lookback return when ts_momentum_lookback>0).
// `is_crypto` selects the wider crypto ATR stop; it defaults false (equity stop).
struct EvalTrace;  // forward declaration (defined below)
StrategySignal evaluate_momentum(const std::vector<Bar>& bars,
                                 const config::StrategyConfig& cfg,
                                 bool allow_short, bool is_crypto = false,
                                 EvalTrace* trace = nullptr);

// Strategy B — mean reversion: Bollinger reentry toward the mean, confirmed by
// RSI leaving oversold/overbought AND volume above the N-bar average. `is_crypto`
// selects the wider crypto ATR stop; it defaults false (equity stop).
StrategySignal evaluate_reversion(const std::vector<Bar>& bars,
                                  const config::StrategyConfig& cfg,
                                  bool allow_short, bool is_crypto = false,
                                  EvalTrace* trace = nullptr);

// Strategy B (RSI-2 variant) — Connors RSI-2 mean reversion. Long only. Fires
// only when price is above the long trend MA (dips bought inside an uptrend) and
// RSI-2 is below the entry threshold (crypto vs equity), with an optional
// cross-back confirmation (wait for RSI-2 to tick back above the entry), an ATR
// volatility band (ATR within atr_band_std of its atr_mean_period mean), and a
// volume filter (volume at/above the N-bar average). The stop is a WIDE ATR stop
// (crypto uses crypto_atr_stop_mult), since a tight stop cuts the snapback. The
// engine also exits on the RSI-2 cross above rsi2_exit (see rsi2_exit_triggered).
StrategySignal evaluate_rsi2_reversion(const std::vector<Bar>& bars,
                                       const config::StrategyConfig& cfg,
                                       bool is_crypto,
                                       EvalTrace* trace = nullptr);

// True when the latest RSI-2 has risen at/above cfg.rsi2_exit. The engine checks
// this for an open RSI-2 reversion position as a native exit (ExitReason::Indicator).
bool rsi2_exit_triggered(const std::vector<Bar>& bars,
                         const config::StrategyConfig& cfg);

// --- Entry-decision trace (2026-07-23, RECORDING ONLY) --------------------
// The state of every entry condition at decision time, for the taken AND the
// rejected path. Filled by evaluate() when a trace pointer is supplied; NEVER
// consulted by any decision, so behavior with and without a trace is identical
// by construction (a guard test proves it end to end). first_reject names the
// FIRST condition that refused each factor family; the FULL set is recorded
// too, because knowing only the first hides how close the others were.
struct EvalTrace {
    // Regime + blend.
    std::string regime;
    double adx = 0, rvol = 0;
    double momentum_weight = 0, reversion_weight = 0;
    std::string selected_factor;   // momentum | reversion | none
    // The leading family's first refusal ("" when a signal was produced). The
    // leading family is the regime-weighted heavier one; both families' own
    // rejects are always recorded beside it.
    std::string first_reject;
    std::string momentum_first_reject, reversion_first_reject;
    // Reversion, RSI-2 style.
    bool rsi2_style = false;
    double rsi2 = 0, rsi2_prev = 0, rsi2_entry = 0;
    double trend_ma = 0, trend_dist_pct = 0;
    bool trend_ok = false;
    bool crossback_confirm = false, rsi2_trigger = false;
    double atr_v = 0, atr_mean = 0, atr_sd = 0, atr_z = 0;
    std::string atr_band_edge;     // "low" | "high" | "" (inside the band)
    bool atr_band_ok = true;
    double volume = 0, vol_avg = 0;
    bool volume_present = false, vol_ok = true;
    // Reversion, Bollinger style (swing profile).
    double bb_lower = 0, bb_mid = 0, bb_upper = 0, rsi14 = 0;
    // Momentum.
    double ema_f = 0, ema_s = 0, adx_mom = 0, atr_over_price = 0;
    bool cross_up = false, cross_down = false, adx_ok = false,
         atr_floor_ok = false;
    double mom_medium_ma = 0, mom_long_ma = 0, ts_return = 0;
    bool dual_ma_ok = true;
};

// Prefix ATR series: out[j] == atr(bars[0..j], period) for every j >= period,
// same Wilder recurrence and float-op order as atr(), so a value here is
// bit-identical to the windowed call it replaces. Indices below `period` are
// 0.0 (insufficient history), exactly as atr() reports there.
std::vector<double> atr_series(const std::vector<Bar>& bars, int period);

// Regime-weighted blend of both strategies. `is_crypto` selects the short
// policy (crypto may short only when cfg.crypto_allow_short; equities never).
// The returned signal's `strength` is the regime-WEIGHTED strength, which the
// council neutral-skip gate consumes. `trace`, when supplied, records every
// condition's state at decision time (recording only, never decisive).
struct BlendedDecision {
    RegimeResult regime;
    StrategySignal signal;         // has_signal=false when neither fires
    double momentum_weight = 0.0;
    double reversion_weight = 0.0;
};
BlendedDecision evaluate(const std::vector<Bar>& bars,
                         const config::StrategyConfig& cfg, bool is_crypto,
                         EvalTrace* trace = nullptr);

// --- Native exits --------------------------------------------------------
// Positions opened by the strategy carry their own stop / target / time-stop,
// set at entry. Exits are evaluated natively on each closed bar and executed
// WITHOUT the council. This is pure decision logic; the engine owns execution.
// Indicator = a strategy-signal exit (RSI-2 crossed above its exit threshold).
enum class ExitReason { None, Stop, Target, TimeStop, Indicator };
std::string exit_reason_to_string(ExitReason r);

struct OpenPosition {
    std::string venue, symbol, market, category, factor, opened_ts;
    Direction direction = Direction::None;  // Long | Short
    double entry_price = 0, qty = 0;
    double stop_price = 0, target_price = 0;
    int time_stop_bars = 0;
    int bars_held = 0;                       // incremented by the engine per closed bar
};

// Decide whether an open position must exit given the latest CLOSED bar.
// Risk-first priority: stop is checked before target (assume the adverse level
// could trade first within the bar), then the indicator exit (RSI-2 cross above
// its exit threshold, computed by the engine from bar history and passed as
// `indicator_exit`), then the time-stop. None => stay open. `indicator_exit`
// defaults false, so a caller with no strategy-signal exit is unaffected.
ExitReason check_exit(const OpenPosition& pos, const Bar& latest_bar,
                      bool indicator_exit = false);

// The fill price to book for a given exit: stop_price / target_price for those
// triggers, else the bar close (time-stop or discretionary close).
double exit_fill_price(const OpenPosition& pos, ExitReason reason,
                       const Bar& latest_bar);

// Realized PnL closing at `exit_price` (long: (exit-entry)*qty; short mirror).
double realized_pnl(const OpenPosition& pos, double exit_price);

}  // namespace mal::strategy
