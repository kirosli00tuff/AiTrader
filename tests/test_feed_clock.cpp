// Feed/clock runtime-toggle tests (Task 3). read_feed_clock resolves each mode
// from controls.json and keeps the launch fallback on a missing/invalid value
// (so a missing file never forces an offline run onto the live feed), and
// feed_switch_orphans_position enforces the open-position safety rule: a switch
// AWAY from alpaca_paper with an open position is blocked, never orphaned.
// Pure, header-only. No network, no engine.
#include <cstdio>
#include <fstream>
#include <string>

#include "core/feed_clock.hpp"
#include "test_util.hpp"

using namespace mal::core;

int main() {
    const FeedClock live{"alpaca_paper", "real"};

    // Missing file => keep the launch fallback.
    FeedClock miss = read_feed_clock("/tmp/mal_no_such_fc_XYZ.json", live);
    maltest::check(miss.feed_mode == "alpaca_paper" && miss.clock_mode == "real",
                   "missing controls.json keeps the launch feed/clock");

    // Each valid feed mode resolves.
    const char* modes[] = {"alpaca_paper", "synthetic_regimes", "replay",
                           "flat_random_walk"};
    for (const char* m : modes) {
        const std::string p = std::string("/tmp/mal_fc_") + m + ".json";
        { std::ofstream o(p);
          o << R"({"feed_mode":")" << m << R"(","clock_mode":"simulated"})"; }
        FeedClock fc = read_feed_clock(p, live);
        maltest::check(fc.feed_mode == m && fc.clock_mode == "simulated",
                       std::string("feed/clock toggle resolves mode ") + m);
        std::remove(p.c_str());
    }

    // Invalid feed => keep the fallback feed; a valid clock still applies.
    const std::string bad = "/tmp/mal_fc_bad.json";
    { std::ofstream o(bad);
      o << R"({"feed_mode":"bogus","clock_mode":"simulated"})"; }
    FeedClock bfc = read_feed_clock(bad, live);
    maltest::check(bfc.feed_mode == "alpaca_paper",
                   "invalid feed_mode falls back to the launch feed");
    maltest::check(bfc.clock_mode == "simulated",
                   "a valid clock_mode still applies when the feed is invalid");
    std::remove(bad.c_str());

    maltest::check(is_valid_feed_mode("replay") && !is_valid_feed_mode("nope"),
                   "is_valid_feed_mode allow-lists the four modes");
    maltest::check(is_valid_clock_mode("simulated") && !is_valid_clock_mode("x"),
                   "is_valid_clock_mode allow-lists real/simulated");

    // Open-position safety rule: never orphan a position on a feed switch.
    maltest::check(feed_switch_orphans_position("alpaca_paper",
                                                "synthetic_regimes", true),
                   "leaving alpaca_paper with an open position is blocked");
    maltest::check(!feed_switch_orphans_position("alpaca_paper",
                                                 "synthetic_regimes", false),
                   "leaving alpaca_paper with no open position is allowed");
    maltest::check(!feed_switch_orphans_position("synthetic_regimes",
                                                 "alpaca_paper", true),
                   "switching INTO alpaca_paper is always allowed (warm gate re-arms)");
    maltest::check(!feed_switch_orphans_position("flat_random_walk",
                                                 "synthetic_regimes", true),
                   "an offline-to-offline switch never orphans a paper position");

    return maltest::report("feed_clock");
}
