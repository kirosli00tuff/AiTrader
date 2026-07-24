// The real path never fabricates (2026-07-20).
//
// AlpacaFeed used to advance a quoteless symbol with a deterministic random
// walk "so the engine keeps ticking". That instinct produced the 2026-07-17
// 19-hour silent substitution and the 2026-07-20 fabricated bars for
// venue-unserved symbols (MANA/USD, RUNE/USD), where two unserviceable
// watchlist entries stopped a stack that was trading six symbols correctly.
//
// This file is the mutation killer for the fabrication removal: restore the
// walk fallback and poll() returns fabricated states here. No network is
// needed and nothing binds: the feed targets a closed loopback port, which is
// exactly the bridge-down shape.
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "market_data/market_data.hpp"
#include "signal_engine/strategy.hpp"
#include "test_util.hpp"

using namespace mal::market_data;

int main() {
    std::vector<Instrument> instruments = {
        {"alpaca", "BTC/USD", "BTC/USD", "crypto", 60000.0},
        {"alpaca", "MANA/USD", "MANA/USD", "crypto", 0.0},
    };

    // Port 1 on loopback: nothing listens there, so every poll sees the
    // bridge unreachable. Before 2026-07-20 that meant every symbol walked.
    AlpacaFeed feed(instruments, "127.0.0.1", 1, 42);

    auto first = feed.poll();
    maltest::check(first.empty(),
                   "bridge unreachable: poll yields NO ticks, fabricating "
                   "none (was: a synthetic walk per symbol)");
    maltest::check(!feed.last_poll_was_live(),
                   "a poll with no data does not read as live");

    // Repeated polls stay empty: the old fallback fabricated on EVERY poll,
    // so one accidental pass is not proof.
    for (int i = 0; i < 3; ++i) {
        maltest::check(feed.poll().empty(),
                       "poll " + std::to_string(i + 2) +
                           ": still no fabricated ticks");
    }

    // Adding an instrument mid-run (the discovery onboarding path) must not
    // resurrect fabrication for it either.
    feed.add_instrument({"alpaca", "RUNE/USD", "RUNE/USD", "crypto", 0.0});
    maltest::check(feed.poll().empty(),
                   "an onboarded symbol with no data yields nothing too");

    // The OFFLINE mock feed still produces synthetic states by design: the
    // invariant is a real-path rule, not a ban on offline synthesis.
    MockFeed mock({{"alpaca", "BTC/USD", "BTC/USD", "crypto", 60000.0}}, 42);
    auto mocked = mock.poll();
    maltest::check(!mocked.empty() && mocked[0].data_source == "synthetic",
                   "MockFeed (offline path) still synthesizes, tagged "
                   "synthetic");

    // --- VOLUME IS NOT FABRICATED EITHER (2026-07-21) -----------------------
    // The 2026-07-20 removal took the price walk and left the volume line
    // behind: AlpacaFeed::poll set ms.volume from a uniform draw per tick,
    // the aggregator summed it into every live bar, and the engine persisted
    // it as a real_feed row. Measured: BTC/USD backfill bars average 0.0056
    // and real_feed bars averaged 55,906, statistically identical to SPY and
    // AAPL, and the strategy volume gate decided 3,235 live-bar comparisons
    // at a 49.2 percent pass rate.
    //
    // LEXICAL HALF: the generator must not come back on the real path. The
    // scan is scoped to AlpacaFeed::poll so MockFeed's own (legitimate)
    // synthesis neither satisfies nor trips it.
    {
        std::ifstream fh("market_data/market_data.cpp");
        maltest::check(fh.good(),
                       "market_data.cpp readable (ctest runs from the repo "
                       "root)");
        std::stringstream ss;
        ss << fh.rdbuf();
        const std::string src = ss.str();
        const size_t poll = src.find("AlpacaFeed::poll");
        maltest::check(poll != std::string::npos, "AlpacaFeed::poll found");
        // CODE ONLY. Comment lines are skipped, because the comment right
        // above the fixed line QUOTES the generator it replaced, and a guard
        // a comment can satisfy is a guard that proves nothing. This was
        // caught by the guard failing against its own explanation.
        std::stringstream body(src.substr(poll));
        std::string line, stmt;
        while (std::getline(body, line)) {
            const size_t first = line.find_first_not_of(" \t");
            if (first == std::string::npos) continue;
            if (line.compare(first, 2, "//") == 0) continue;   // a comment
            if (line.find("ms.volume") != std::string::npos) {
                stmt = line;
                break;
            }
        }
        maltest::check(!stmt.empty(),
                       "AlpacaFeed::poll still sets ms.volume explicitly");
        maltest::check(stmt.find("next_uniform") == std::string::npos,
                       "AlpacaFeed::poll builds volume from the RNG again: "
                       "the live volume series is fabricated");
        maltest::check(stmt.find("9000.0") == std::string::npos,
                       "the 1000 + 9000 * uniform volume generator is back on "
                       "the real path");
        // WHOLE-BODY sweep (2026-07-23): with spread REMOVED (no consumer)
        // and imbalance reporting absence, NO code line in AlpacaFeed::poll
        // may draw from the RNG or touch ms.spread at all. This covers the
        // whole fabrication class on the real path, not one field.
        std::stringstream body2(src.substr(poll));
        bool rng_free = true, spread_free = true;
        while (std::getline(body2, line)) {
            const size_t first = line.find_first_not_of(" \t");
            if (first == std::string::npos) continue;
            if (line.compare(first, 2, "//") == 0) continue;   // a comment
            if (line.find("next_uniform") != std::string::npos)
                rng_free = false;
            if (line.find("ms.spread") != std::string::npos)
                spread_free = false;
        }
        maltest::check(rng_free,
                       "AlpacaFeed::poll draws from the RNG somewhere: a "
                       "fabricated market field is back on the real path");
        maltest::check(spread_free,
                       "ms.spread is back in AlpacaFeed::poll: the field was "
                       "removed because nothing consumes it");
    }

    // BEHAVIORAL HALF: a tick carrying no volume must aggregate into a bar
    // carrying no volume. Nothing between the feed and the bars table may
    // invent one, which is what made every real_feed row contaminated.
    {
        mal::strategy::BarAggregator agg(300);
        for (int i = 0; i < 5; ++i)
            agg.add("alpaca|BTC/USD", 1000L + i * 60L, 66000.0 + i, 0.0);
        auto closed = agg.add("alpaca|BTC/USD", 1000L + 600L, 66010.0, 0.0);
        maltest::check(closed.has_value(),
                       "a bar closes after the bucket rolls over");
        maltest::check(closed && closed->volume == 0.0,
                       "a bar built from volume-less ticks carries NO volume: "
                       "nothing between the feed and the bars table invents "
                       "one");
    }

    // --- LIVE BAR VOLUME IS THE VENUE'S OWN, OR ABSENT (2026-07-23) ---------
    // The bridge forwards the venue's latest MINUTE BAR volume beside the
    // trade price, and consume_latest_bar emits each completed venue bar's
    // volume EXACTLY ONCE, at rollover, as last observed. Nothing is counted
    // at first sight (the bar is still forming), nothing is emitted twice,
    // and a poll the venue does not answer emits nothing: a stale or
    // carried-forward volume can never reach a bar.
    {
        LatestBarTrack t;
        maltest::check(consume_latest_bar(t, "", -1.0) == 0.0 && t.ts.empty(),
                       "no venue bar: absence stays absence");
        maltest::check(consume_latest_bar(t, "T1", 100.0) == 0.0,
                       "a forming venue bar is never counted at first sight");
        maltest::check(consume_latest_bar(t, "T1", 150.0) == 0.0,
                       "a still-forming bar is never emitted early (no double "
                       "count)");
        maltest::check(consume_latest_bar(t, "", -1.0) == 0.0,
                       "a poll the venue does not answer emits nothing: no "
                       "carried-forward stale value");
        maltest::check(consume_latest_bar(t, "T2", 30.0) == 150.0,
                       "a completed venue bar's volume is emitted exactly "
                       "once at rollover, as last observed");
        maltest::check(consume_latest_bar(t, "T2", 40.0) == 0.0,
                       "and never re-emitted afterwards");
        maltest::check(consume_latest_bar(t, "T3", 0.0) == 40.0,
                       "the next rollover emits the next bar's volume");
        maltest::check(consume_latest_bar(t, "T4", 10.0) == 0.0,
                       "a genuine zero-volume venue bar (quiet crypto minute) "
                       "contributes zero, never an invented number");
    }

    return maltest::report("feed_no_fabrication");
}
