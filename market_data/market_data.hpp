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
};

// Abstract feed.
class Feed {
public:
    virtual ~Feed() = default;
    virtual std::vector<MarketState> poll() = 0;
};

// Deterministic mock feed seeded for reproducible demos.
class MockFeed : public Feed {
public:
    struct Instrument {
        std::string venue, symbol, market, category;
        double price;
    };

    MockFeed(std::vector<Instrument> instruments, uint64_t seed = 42);
    std::vector<MarketState> poll() override;

private:
    std::vector<Instrument> instruments_;
    std::vector<double> last_prices_;
    std::vector<std::vector<double>> recent_returns_;
    uint64_t rng_;
    double next_uniform();  // xorshift in [0,1)
};

}  // namespace mal::market_data
