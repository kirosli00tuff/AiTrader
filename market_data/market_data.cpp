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
    if (!bridge_ok && !warned_fallback_) {
        std::cerr << "[market_data] Alpaca feed: bridge unavailable; using "
                     "deterministic walk fallback (offline-safe)\n";
        warned_fallback_ = true;
    }

    std::vector<MarketState> out;
    out.reserve(instruments_.size());
    const std::string ts = util::now_iso8601();
    for (size_t i = 0; i < instruments_.size(); ++i) {
        double prev = last_prices_[i];
        double price = prev;
        bool live = false;
        if (bridge_ok) {
            double q = bridge::json_get_number(*resp, instruments_[i].symbol,
                                               -1.0);
            if (q > 0.0) {
                price = q;
                live = true;
                any_live = true;
            }
        }
        if (!live) {
            // Fallback: small deterministic random walk from the last price so
            // the engine keeps ticking even when a quote is missing.
            double shock = (next_uniform() - 0.5) * 0.04;
            price = std::max(0.0001, prev * (1.0 + 0.0005 + shock));
        }

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
        out.push_back(std::move(ms));
    }
    last_poll_live_ = any_live;
    return out;
}

}  // namespace mal::market_data
