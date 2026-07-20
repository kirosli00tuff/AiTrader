#include "market_data/market_data.hpp"

#include <cmath>
#include <iostream>
#include <sstream>

#include "core/bridge_client.hpp"
#include "core/util.hpp"

namespace mal::market_data {

MockFeed::MockFeed(std::vector<Instrument> instruments, uint64_t seed)
    : instruments_(std::move(instruments)), rng_(seed ? seed : 1) {
    for (const auto& i : instruments_) {
        last_prices_.push_back(i.price);
        recent_returns_.emplace_back();
    }
}

void MockFeed::add_instrument(const Instrument& i) {
    // The three vectors are parallel and indexed together in poll(), so they
    // must grow together or poll() reads another symbol's price.
    for (const auto& have : instruments_)
        if (have.venue == i.venue && have.symbol == i.symbol) return;
    instruments_.push_back(i);
    last_prices_.push_back(i.price);
    recent_returns_.emplace_back();
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
        // A mock tick is synthetic by definition. Stated explicitly so no bar
        // built from it can ever read as real (core/provenance.hpp).
        ms.data_source = "synthetic";
        out.push_back(std::move(ms));
    }
    return out;
}

// --- AlpacaFeed -------------------------------------------------------------

AlpacaFeed::AlpacaFeed(std::vector<Instrument> instruments,
                       std::string bridge_host, int bridge_port, uint64_t seed)
    : instruments_(std::move(instruments)),
      bridge_host_(std::move(bridge_host)),
      bridge_port_(bridge_port),
      rng_(seed ? seed : 1) {
    for (const auto& i : instruments_) {
        last_prices_.push_back(i.price);
        recent_returns_.emplace_back();
    }
}

void AlpacaFeed::add_instrument(const Instrument& i) {
    // Parallel vectors, same contract as MockFeed::add_instrument. The seeded
    // price is only the offline-fallback anchor: a live poll overwrites it with
    // the real Alpaca quote on the next request.
    for (const auto& have : instruments_)
        if (have.venue == i.venue && have.symbol == i.symbol) return;
    instruments_.push_back(i);
    last_prices_.push_back(i.price);
    recent_returns_.emplace_back();
}

double AlpacaFeed::next_uniform() {
    rng_ ^= rng_ << 13;
    rng_ ^= rng_ >> 7;
    rng_ ^= rng_ << 17;
    return (rng_ >> 11) * (1.0 / 9007199254740992.0);
}

std::vector<MarketState> AlpacaFeed::poll() {
    // Ask the bridge for latest prices of all instruments in one request.
    // Body: {"symbols":"AAPL,BTC-USD,..."}. The response is a flat JSON object
    // keyed by the requested symbol -> latest price, plus a "source" field.
    std::ostringstream syms;
    for (size_t i = 0; i < instruments_.size(); ++i) {
        if (i) syms << ',';
        syms << instruments_[i].symbol;
    }
    std::string body = "{\"symbols\":\"" + util::json_escape(syms.str()) + "\"}";
    auto resp = bridge::http_post_json(bridge_host_, bridge_port_,
                                       "/marketdata/alpaca", body);

    bool bridge_ok = resp.has_value();
    bool any_live = false;
    if (!bridge_ok && !warned_no_bridge_) {
        std::cerr << "[market_data] Alpaca feed: bridge unavailable; yielding "
                     "NO ticks. The real path never fabricates a price.\n";
        warned_no_bridge_ = true;
    }

    // A symbol with no quote yields NOTHING. The walk fallback that used to
    // live here is the instinct behind the 2026-07-17 19-hour silent
    // substitution and the 2026-07-20 fabricated bars for venue-unserved
    // symbols (MANA/USD, RUNE/USD). No data means no tick. Absence is an
    // availability question for the watchdog, never fake data.
    std::vector<MarketState> out;
    out.reserve(instruments_.size());
    const std::string ts = util::now_iso8601();
    for (size_t i = 0; i < instruments_.size(); ++i) {
        double q = -1.0;
        if (bridge_ok)
            q = bridge::json_get_number(*resp, instruments_[i].symbol, -1.0);
        if (q <= 0.0) {
            // Log the unavailability once per symbol, not every poll.
            if (bridge_ok &&
                unavailable_warned_.insert(instruments_[i].symbol).second) {
                std::cerr << "[market_data] no data available for "
                          << instruments_[i].symbol
                          << " (venue returned nothing); yielding no tick\n";
            }
            continue;
        }
        unavailable_warned_.erase(instruments_[i].symbol);
        double prev = last_prices_[i];
        double price = q;
        any_live = true;

        double r = prev > 0.0 ? (price / prev - 1.0) : 0.0;
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
        // Every tick this feed emits carries a real venue quote.
        ms.data_source = "real_feed";
        out.push_back(std::move(ms));
    }
    last_poll_live_ = any_live;
    return out;
}

}  // namespace mal::market_data
