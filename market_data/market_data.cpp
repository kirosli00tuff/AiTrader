#include "market_data/market_data.hpp"

#include <cmath>

#include "core/util.hpp"

namespace mal::market_data {

MockFeed::MockFeed(std::vector<Instrument> instruments, uint64_t seed)
    : instruments_(std::move(instruments)), rng_(seed ? seed : 1) {
    for (const auto& i : instruments_) {
        last_prices_.push_back(i.price);
        recent_returns_.emplace_back();
    }
}

double MockFeed::next_uniform() {
    // xorshift64 — deterministic, dependency-free PRNG for reproducible demos.
    rng_ ^= rng_ << 13;
    rng_ ^= rng_ >> 7;
    rng_ ^= rng_ << 17;
    return (rng_ >> 11) * (1.0 / 9007199254740992.0);
}

std::vector<MarketState> MockFeed::poll() {
    std::vector<MarketState> out;
    out.reserve(instruments_.size());
    const std::string ts = util::now_iso8601();
    for (size_t i = 0; i < instruments_.size(); ++i) {
        // Random-walk return with modest drift + symbol-specific vol.
        double shock = (next_uniform() - 0.5) * 0.04;  // +/-2%
        double drift = 0.0005;
        double r = drift + shock;
        double prev = last_prices_[i];
        double price = std::max(0.0001, prev * (1.0 + r));
        last_prices_[i] = price;

        auto& hist = recent_returns_[i];
        hist.push_back(r);
        if (hist.size() > 5) hist.erase(hist.begin());

        double ret5 = 0.0;
        for (double x : hist) ret5 += x;
        double mean = ret5 / static_cast<double>(hist.size());
        double var = 0.0;
        for (double x : hist) var += (x - mean) * (x - mean);
        double vol = std::sqrt(var / std::max<size_t>(1, hist.size()));

        MarketState ms;
        ms.venue = instruments_[i].venue;
        ms.symbol = instruments_[i].symbol;
        ms.market = instruments_[i].market;
        ms.category = instruments_[i].category;
        ms.price = price;
        ms.ret_1 = r;
        ms.ret_5 = ret5;
        ms.volatility = vol;
        ms.spread = price * (0.0005 + 0.001 * next_uniform());
        ms.volume = 1000.0 + 9000.0 * next_uniform();
        ms.order_book_imbalance = (next_uniform() - 0.5) * 2.0;
        ms.ts = ts;
        out.push_back(std::move(ms));
    }
    return out;
}

}  // namespace mal::market_data
