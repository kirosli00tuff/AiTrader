// Market AI Lab — market data ingestion abstraction.
//
// Production would stream from venue feeds; for the offline demo we provide a
// deterministic MockFeed producing realistic-looking market states (price walk,
// volatility, spread, volume) so the whole pipeline runs with no live keys.
#pragma once

#include <cstdint>
#include <set>
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

// THE effective market-data source, resolved in ONE place (2026-07-21).
//
// CLI override wins, else config, and feed_mode alpaca_paper FORCES the online
// Alpaca feed because that mode IS the real path. The Engine applied that last
// rule and the startup banner did not, so a run whose config says
// `market_data.source: mock` printed "source: mock" while the very next
// `continuous_start` event it wrote recorded "source=alpaca". A startup line
// that lies about the data source is how a mock run gets mistaken for a real
// one, so the rule is a pure function both callers use rather than a
// convention each has to remember.
inline std::string resolve_source(const std::string& cli_override,
                                  const std::string& config_source,
                                  const std::string& feed_mode) {
    if (feed_mode == "alpaca_paper") return "alpaca";
    return !cli_override.empty() ? cli_override : config_source;
}

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
// THIS FEED NEVER FABRICATES (2026-07-20). If the bridge is unreachable or a
// symbol has no quote, that symbol yields NO tick this poll. The old
// deterministic-walk fallback fabricated prices in live clothing: it produced
// the 2026-07-17 19-hour silent substitution and the 2026-07-20 synthetic bars
// for venue-unserved symbols (MANA/USD, RUNE/USD). No data is recorded as no
// data: one notice per symbol on first unavailability, one on a dead bridge.
// Every tick this feed emits is a real venue quote (`data_source` real_feed).
// `last_poll_was_live()` reports whether the most recent poll contained any
// real Alpaca data.
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
    bool warned_no_bridge_ = false;
    // Symbols already warned unavailable, so the notice fires once per symbol
    // per outage rather than once per poll. Cleared when data returns.
    std::set<std::string> unavailable_warned_;
};

}  // namespace mal::market_data
