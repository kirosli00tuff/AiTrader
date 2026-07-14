// Warm-start tests (Task 1/2): the engine seeds native indicators from the
// backfilled bars table on construction, so warm_states() reports a symbol WARM
// once it has >= min_bars_to_warm bars and COLD otherwise. That is what the
// startup block prints and what the real-path warm gate consults before a native
// entry, so a live run never fires on partial data. Offline, temp SQLite DB.
#include <cstdio>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "core/util.hpp"
#include "signal_engine/strategy.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}
}  // namespace

int main() {
    const std::string db = "/tmp/mal_test_warm.db";
    rm_db(db);
    config::Config cfg = config::load_config("config/default_config.yaml");
    const int need = strategy::min_bars_to_warm(cfg.strategy);

    // Seed the bars table the way the Alpaca 5-min backfill does (venue "alpaca",
    // timeframe cfg.strategy.bar_timeframe): BTC/USD gets need+10 bars (warm),
    // SPY gets need-5 (cold), ETH/USD and QQQ get none (cold).
    {
        storage::Storage s(db);
        s.init_schema("storage/schema.sql");
        const std::string& tf = cfg.strategy.bar_timeframe;
        auto seed = [&](const std::string& sym, int n) {
            for (int i = 0; i < n; ++i) {
                std::string ts = util::epoch_to_iso8601(1767571200L + i * 300L);
                double px = 100.0 + i * 0.1;
                s.upsert_bar({"alpaca", sym, tf, ts, px, px + 1.0, px - 1.0,
                              px + 0.2, 1000.0});
            }
        };
        seed("BTC/USD", need + 10);
        seed("SPY", need - 5);
    }

    // Offline construction seeds bar_history_ from the bars table (flat feed so
    // the strict real-path check is a no-op and no network is touched).
    core::EngineOptions opts;
    opts.db_path = db;
    opts.schema_path = "storage/schema.sql";
    opts.feed_mode = "flat_random_walk";
    core::Engine engine(cfg, opts);

    bool btc_warm = false, eth_warm = true, spy_warm = true, qqq_warm = true;
    int btc_bars = 0, spy_bars = 0;
    for (const auto& ws : engine.warm_states()) {
        if (ws.symbol == "BTC/USD") { btc_warm = ws.state.all; btc_bars = ws.state.bars; }
        if (ws.symbol == "ETH/USD") eth_warm = ws.state.all;
        if (ws.symbol == "SPY") { spy_warm = ws.state.all; spy_bars = ws.state.bars; }
        if (ws.symbol == "QQQ") qqq_warm = ws.state.all;
    }
    maltest::check(btc_bars >= need && btc_warm,
                   "BTC/USD seeded above the warm threshold reads WARM");
    maltest::check(spy_bars == need - 5 && !spy_warm,
                   "SPY seeded below the warm threshold reads COLD");
    maltest::check(!eth_warm && !qqq_warm,
                   "un-seeded symbols read COLD (0 bars)");

    // The warm gate the engine consults is exactly this pure predicate, so a
    // cold symbol (SPY here) is never evaluated for a native entry on the real
    // path, and a warm one (BTC/USD) is.
    maltest::check(!strategy::indicators_warm(spy_bars, cfg.strategy),
                   "cold symbol fails the entry warm gate (no entry on partial data)");
    maltest::check(strategy::indicators_warm(btc_bars, cfg.strategy),
                   "warm symbol passes the entry warm gate");

    rm_db(db);
    return maltest::report("warm_start");
}
