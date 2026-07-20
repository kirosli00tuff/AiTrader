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
#include <string>
#include <vector>

#include "market_data/market_data.hpp"
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

    return maltest::report("feed_no_fabrication");
}
