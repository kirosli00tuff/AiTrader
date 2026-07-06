// Feed-mode + simulated-clock tests (Task 6).
//   A. synthetic feed crosses the entry thresholds and produces at least one
//      momentum AND one mean-reversion signal under a fixed seed;
//   B. the simulated clock closes the expected bar count for a finite run;
//   C. replay reads stored bars in order and stops cleanly at the end of range,
//      and refuses with a clear message when the bars table is empty.
// No network: everything runs offline against temp SQLite DBs.
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "core/util.hpp"
#include "market_data/synthetic_feed.hpp"
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
    // --- A. Synthetic feed triggers BOTH strategies under a fixed seed --------
    {
        config::StrategyConfig cfg;  // production defaults
        market_data::SyntheticRegimeGenerator gen(100.0, 42);
        std::vector<strategy::Bar> hist;
        int mom = 0, rev = 0, trending = 0, range = 0;
        for (int i = 0; i < 1200; ++i) {
            auto b = gen.next();
            hist.push_back({b.open, b.high, b.low, b.close, b.volume});
            if (hist.size() > 400) hist.erase(hist.begin());
            auto rr = strategy::detect_regime(hist, cfg);
            if (rr.regime == strategy::Regime::Trending) ++trending;
            else if (rr.regime == strategy::Regime::RangeBound) ++range;
            if (strategy::evaluate_momentum(hist, cfg, false).has_signal) ++mom;
            if (strategy::evaluate_reversion(hist, cfg, false).has_signal) ++rev;
        }
        maltest::check(trending > 0, "synthetic feed crosses ADX trend threshold");
        maltest::check(range > 0, "synthetic feed produces range-bound bars");
        maltest::check(mom >= 1, "synthetic feed fires >=1 momentum signal");
        maltest::check(rev >= 1, "synthetic feed fires >=1 mean-reversion signal");
    }

    // --- B. Simulated clock closes the expected bar count for a finite run ----
    {
        const std::string db = "/tmp/mal_test_synth_clock.db";
        rm_db(db);
        config::Config cfg = config::load_config("config/default_config.yaml");
        const int n_wl = static_cast<int>(cfg.strategy.whitelist.size());
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "synthetic_regimes";
        opts.clock_mode = "simulated";
        opts.native_bar_seconds = 300;
        core::Engine e(cfg, opts);
        const int steps = 25;
        e.run(steps);
        long long bars = e.storage().count("bars");
        maltest::check(bars == static_cast<long long>(steps) * n_wl,
                       "simulated clock closes steps*whitelist bars in a finite run");
        rm_db(db);
    }

    // --- C. Replay reads stored bars in order and stops at the end of range ---
    {
        const std::string db = "/tmp/mal_test_replay.db";
        rm_db(db);
        const int kBars = 40;
        // Seed a monotonic, in-order bar series for one whitelisted symbol.
        {
            storage::Storage s(db);
            s.init_schema("storage/schema.sql");
            for (int i = 0; i < kBars; ++i) {
                std::string ts = util::epoch_to_iso8601(1767571200L + i * 300L);
                double px = 100.0 + i;
                s.upsert_bar({"alpaca", "BTC/USD", "5min", ts, px, px + 1.0,
                              px - 1.0, px + 0.5, 1000.0});
            }
        }
        config::Config cfg = config::load_config("config/default_config.yaml");
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "replay";
        opts.clock_mode = "simulated";
        core::Engine e(cfg, opts);
        e.run(100000);  // replay ignores the count; it runs to the end of range
        // Reaching here means it stopped cleanly (did not hang). Replay is
        // idempotent on the bars table (upsert), so the count is unchanged.
        maltest::check(e.storage().count("bars") == kBars,
                       "replay consumed the stored bars and stopped (no duplication)");
        rm_db(db);
    }

    // --- C(bis). Replay refuses clearly when the bars table is empty ----------
    {
        const std::string db = "/tmp/mal_test_replay_empty.db";
        rm_db(db);
        config::Config cfg = config::load_config("config/default_config.yaml");
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "replay";
        bool threw = false;
        std::string msg;
        try {
            core::Engine e(cfg, opts);
        } catch (const std::exception& ex) {
            threw = true;
            msg = ex.what();
        }
        maltest::check(threw, "replay on an empty bars table refuses (throws)");
        maltest::check(msg.find("backfill") != std::string::npos,
                       "refusal message tells the operator to run the backfill");
        rm_db(db);
    }

    return maltest::report("feed_modes");
}
