#include "market_data/synthetic_feed.hpp"

#include <algorithm>
#include <cmath>

namespace mal::market_data {

namespace {
// Phase lengths in bars. Warmup runs once (>= 30 as required so ADX is usable),
// then the loop cycles uptrend -> range -> downtrend forever.
constexpr long kWarmupLen = 60;
constexpr long kUpLen = 150;    // long enough for an EMA20/EMA100 cross-up
constexpr long kRangeLen = 200;
constexpr long kDownLen = 150;  // EMA20/EMA100 cross-down (momentum short: gated)
// Reversion setups are seeded on this cadence inside the range leg.
constexpr long kRangeSubcycle = 20;
}  // namespace

SyntheticRegimeGenerator::SyntheticRegimeGenerator(double start_price,
                                                   uint64_t seed)
    : price_(start_price > 0 ? start_price : 100.0), rng_(seed ? seed : 1) {}

double SyntheticRegimeGenerator::u() {
    // xorshift64 — same deterministic PRNG the MockFeed uses.
    rng_ ^= rng_ << 13;
    rng_ ^= rng_ >> 7;
    rng_ ^= rng_ << 17;
    return (rng_ >> 11) * (1.0 / 9007199254740992.0);
}

OhlcvBar SyntheticRegimeGenerator::next() {
    const double open = price_;
    double r = 0.0;           // this bar's return
    double intrabar = 0.0015;  // wick size as a fraction of price
    double vol = 1000.0 + 1500.0 * u();
    bool vol_spike = false;

    switch (phase_) {
        case SynthPhase::Warmup:
            r = (u() - 0.5) * 0.004;            // +/-0.2%, flat-ish baseline
            break;
        case SynthPhase::Uptrend:
            r = 0.006 + (u() - 0.5) * 0.004;    // +0.6%/bar persistent drift
            intrabar = 0.0025;
            break;
        case SynthPhase::Downtrend:
            r = -0.006 + (u() - 0.5) * 0.004;   // -0.6%/bar persistent drift
            intrabar = 0.0025;
            break;
        case SynthPhase::Range: {
            const long s = phase_bar_ % kRangeSubcycle;
            if (s == 0 || s == 1 || s == 2) {
                // Three sharp down bars drive close below the lower Bollinger
                // band and RSI into oversold.
                r = -0.03 + (u() - 0.5) * 0.004;
                intrabar = 0.004;
            } else if (s == 3) {
                // Recovery back inside the band with a volume spike: the
                // mean-reversion long trigger (RSI leaves oversold too).
                r = 0.075 + (u() - 0.5) * 0.006;
                intrabar = 0.004;
                vol_spike = true;
            } else {
                // Gentle mean reversion toward the leg center (choppy: keeps ADX
                // low so the regime reads range-bound, not trending).
                const double pull = range_center_ > 0.0
                    ? 0.30 * (range_center_ - price_) / price_ : 0.0;
                r = pull + (u() - 0.5) * 0.006;
                intrabar = 0.002;
            }
            break;
        }
    }

    const double close = std::max(0.0001, open * (1.0 + r));
    const double hi = std::max(open, close);
    const double lo = std::min(open, close);
    const double wick = close * intrabar;

    OhlcvBar b;
    b.open = open;
    b.close = close;
    b.high = hi + wick * (0.5 + u());
    b.low = std::max(0.0001, lo - wick * (0.5 + u()));
    b.volume = vol_spike ? vol * 5.0 : vol;

    price_ = close;
    ++count_;
    ++phase_bar_;

    // Advance the phase schedule (warmup once, then cycle).
    const auto advance = [&](SynthPhase nxt) {
        phase_ = nxt;
        phase_bar_ = 0;
        if (nxt == SynthPhase::Range) range_center_ = price_;
    };
    switch (phase_) {
        case SynthPhase::Warmup:
            if (phase_bar_ >= kWarmupLen) advance(SynthPhase::Uptrend);
            break;
        case SynthPhase::Uptrend:
            if (phase_bar_ >= kUpLen) advance(SynthPhase::Range);
            break;
        case SynthPhase::Range:
            if (phase_bar_ >= kRangeLen) advance(SynthPhase::Downtrend);
            break;
        case SynthPhase::Downtrend:
            if (phase_bar_ >= kDownLen) advance(SynthPhase::Uptrend);
            break;
    }
    return b;
}

}  // namespace mal::market_data
