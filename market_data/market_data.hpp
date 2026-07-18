// Market AI Lab — market data ingestion abstraction.
//
// Production would stream from venue feeds; for the offline demo we provide a
// deterministic MockFeed producing realistic-looking market states (price walk,
// volatility, spread, volume) so the whole pipeline runs with no live keys.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace mal::market_data {

// A snapshot of one tradable instrument's state.
struct MarketState {
    std::string venue;
    std::string symbol;
    std::string market;    // for prediction markets / pairs
    std::string category;  // e.g. crypto, equity, politics
    double price = 0.0;
    double ret_1 = 0.0;    // last-interval return
    double ret_5 = 0.0;    // 5-interval return
    double volatility = 0.0;
    double spread = 0.0;
    double volume = 0.0;
    double order_book_imbalance = 0.0;  // [-1,1]
    std::string ts;
    // Where this tick's price came from: "real_feed" (live venue quote) or
    // "synthetic" (mock feed, or the per-symbol walk fallback when a live quote
    // is missing). Set by every feed. Empty means the source could not be
    // established, which downstream reads as unknown, NEVER as real. See
    // core/provenance.hpp.
    std::string data_source;
};

// Shared instrument descriptor used by the feeds.
struct Instrument {
    std::string venue, symbol, market, category;
    double price;
};

// Abstract feed.
class Feed {
public:
    virtual ~Feed() = default;
    virtual std::vector<MarketState> poll() = 0;
    // Add an instrument to the polled universe mid-run.
    //
    // Discovery needs this: a surfaced symbol the feed never polls closes no
    // bars, so it never warms and can never trade. It would be NAMED and nothing
    // more. Adding rather than rebuilding the feed keeps the existing symbols'
    // last-price and return state intact, which a rebuild would reset.
    //
    // Default no-op, so a feed with a fixed universe stays correct by doing
    // nothing. Adding an instrument only widens what is POLLED. It grants no
    // permission: the whitelist, the warm gate, and the RiskGate all still judge
    // the symbol exactly as they judge a configured one.
    virtual void add_instrument(const Instrument&) {}
};

// Deterministic mock feed seeded for reproducible demos.
class MockFeed : public Feed {
public:
    using Instrument = mal::market_data::Instrument;

    MockFeed(std::vector<Instrument> instruments, uint64_t seed = 42);
    std::vector<MarketState> poll() override;
    void add_instrument(const Instrument& i) override;

private:
    std::vector<Instrument> instruments_;
    std::vector<double> last_prices_;
    std::vector<std::vector<double>> recent_returns_;
    uint64_t rng_;
    double next_uniform();  // xorshift in [0,1)
};

// Real-time Alpaca market-data feed.
//
// Polls latest prices for the configured instruments from the Python bridge
// (`POST /marketdata/alpaca`), which calls the Alpaca market-data REST API using
// the resolved paper/data credentials. This needs only a paper/data key — NOT a
// live brokerage account — so it works for a Canada-based user.
//
// Resilience: if the bridge is unreachable or a symbol has no quote (offline /
// no key / network error), the feed advances that symbol with a small
// deterministic random walk from its last price so the engine keeps ticking. A
// one-time notice is emitted on the first such fallback. `last_poll_was_live()`
// reports whether the most recent poll contained any real Alpaca data.
class AlpacaFeed : public Feed {
public:
    using Instrument = mal::market_data::Instrument;

    AlpacaFeed(std::vector<Instrument> instruments, std::string bridge_host,
               int bridge_port, uint64_t seed = 42);
    std::vector<MarketState> poll() override;
    void add_instrument(const Instrument& i) override;

    bool last_poll_was_live() const { return last_poll_live_; }

private:
    double next_uniform();

    std::vector<Instrument> instruments_;
    std::vector<double> last_prices_;
    std::vector<std::vector<double>> recent_returns_;
    std::string bridge_host_;
    int bridge_port_;
    uint64_t rng_;
    bool last_poll_live_ = false;
    bool warned_fallback_ = false;
};

}  // namespace mal::market_data
