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

struct RegimeResult {
    Regime regime = Regime::Neutral;
    double adx = 0;
    double rvol = 0;
};
RegimeResult detect_regime(const std::vector<Bar>& bars,
                           const config::StrategyConfig& cfg);

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
StrategySignal evaluate_momentum(const std::vector<Bar>& bars,
                                 const config::StrategyConfig& cfg,
                                 bool allow_short);

// Strategy B — mean reversion: Bollinger reentry toward the mean, confirmed by
// RSI leaving oversold/overbought AND volume above the N-bar average.
StrategySignal evaluate_reversion(const std::vector<Bar>& bars,
                                  const config::StrategyConfig& cfg,
                                  bool allow_short);

// Regime-weighted blend of both strategies. `is_crypto` selects the short
// policy (crypto may short only when cfg.crypto_allow_short; equities never).
// The returned signal's `strength` is the regime-WEIGHTED strength, which the
// council neutral-skip gate consumes.
struct BlendedDecision {
    RegimeResult regime;
    StrategySignal signal;         // has_signal=false when neither fires
    double momentum_weight = 0.0;
    double reversion_weight = 0.0;
};
BlendedDecision evaluate(const std::vector<Bar>& bars,
                         const config::StrategyConfig& cfg, bool is_crypto);

// --- Native exits --------------------------------------------------------
// Positions opened by the strategy carry their own stop / target / time-stop,
// set at entry. Exits are evaluated natively on each closed bar and executed
// WITHOUT the council. This is pure decision logic; the engine owns execution.
enum class ExitReason { None, Stop, Target, TimeStop };
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
// could trade first within the bar), then the time-stop. None => stay open.
ExitReason check_exit(const OpenPosition& pos, const Bar& latest_bar);

// The fill price to book for a given exit: stop_price / target_price for those
// triggers, else the bar close (time-stop or discretionary close).
double exit_fill_price(const OpenPosition& pos, ExitReason reason,
                       const Bar& latest_bar);

// Realized PnL closing at `exit_price` (long: (exit-entry)*qty; short mirror).
double realized_pnl(const OpenPosition& pos, double exit_price);

}  // namespace mal::strategy
