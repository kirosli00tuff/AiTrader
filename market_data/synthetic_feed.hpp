// Market AI Lab — deterministic multi-regime synthetic bar generator.
//
// The flat random-walk MockFeed rarely crosses the native strategies' ADX /
// realized-vol entry thresholds, so the offline loop generates near-zero native
// fills. This generator instead emits closed OHLCV bars that walk through a
// warmup, a trending leg, a range-bound leg, and a downtrend leg (repeating), so
// BOTH the momentum (EMA cross + ADX filter) and the mean-reversion (Bollinger
// reentry + RSI + volume) strategies actually enter. It is pure and fully
// deterministic under `seed` so tests reproduce exact bars and fills.
//
// This is an OFFLINE training/testing aid only. It has nothing to do with live
// trading: Alpaca remains a paper + market-data venue with no live path.
#pragma once

#include <cstdint>

namespace mal::market_data {

// One generated closed bar. Plain struct so this header stays dependency-free
// (the engine/tests convert to strategy::Bar).
struct OhlcvBar {
    double open = 0, high = 0, low = 0, close = 0, volume = 0;
};

// Regime the generator is currently emitting (surfaced for tests/telemetry).
enum class SynthPhase { Warmup, Uptrend, Range, Downtrend };

class SyntheticRegimeGenerator {
public:
    SyntheticRegimeGenerator(double start_price, uint64_t seed);

    // Emit the next closed bar, advancing the internal regime schedule.
    OhlcvBar next();

    long bars_emitted() const { return count_; }
    SynthPhase phase() const { return phase_; }

private:
    double u();  // xorshift64 uniform in [0,1)

    double price_;
    double range_center_ = 0.0;  // center the range leg mean-reverts toward
    uint64_t rng_;
    long count_ = 0;
    long phase_bar_ = 0;         // bars emitted so far in the current phase
    SynthPhase phase_ = SynthPhase::Warmup;
};

}  // namespace mal::market_data
