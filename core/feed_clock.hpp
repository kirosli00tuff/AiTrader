// Runtime feed-mode + clock-mode toggle read from the GUI control file
// controls.json (Task 3), the same control-file pattern as the layer toggles.
//
//   feed_mode  : alpaca_paper | synthetic_regimes | replay | flat_random_walk
//   clock_mode : real | simulated
//
// The engine reads these each loop iteration so the operator can switch the loop
// between real Alpaca data and a synthetic feed, and between real and simulated
// time, without editing config and restarting.
//
// SAFETY: a feed switch never orphans an open position. Switching AWAY from
// alpaca_paper while a paper position is open is blocked (the position keeps
// being managed by its native exits on the current feed) rather than stranded on
// a feed that is about to be replaced. A switch INTO alpaca_paper re-triggers the
// warm-start gate, so evaluation waits until indicators warm on real bars.
//
// Read defensively: a missing or malformed file, or an invalid value, falls back
// to the caller's launch feed/clock, which on the live path is alpaca_paper +
// real. This never affects live trading (Alpaca is paper + market-data only).
#pragma once

#include <array>
#include <fstream>
#include <iterator>
#include <string>

#include "core/bridge_client.hpp"  // bridge::json_get_string

namespace mal::core {

inline constexpr std::array<const char*, 4> kFeedModes = {
    "alpaca_paper", "synthetic_regimes", "replay", "flat_random_walk"};
inline constexpr std::array<const char*, 2> kClockModes = {"real", "simulated"};

struct FeedClock {
    std::string feed_mode = "alpaca_paper";
    std::string clock_mode = "real";

    bool operator==(const FeedClock& o) const {
        return feed_mode == o.feed_mode && clock_mode == o.clock_mode;
    }
    bool operator!=(const FeedClock& o) const { return !(*this == o); }
};

inline bool is_valid_feed_mode(const std::string& m) {
    for (const char* v : kFeedModes)
        if (m == v) return true;
    return false;
}

inline bool is_valid_clock_mode(const std::string& m) {
    for (const char* v : kClockModes)
        if (m == v) return true;
    return false;
}

// Read feed_mode / clock_mode from controls.json. A missing file, missing key,
// or invalid value keeps the passed fallback (the engine's LAUNCH feed/clock),
// so a missing file never forces an offline run onto the live feed and, on the
// live path, a missing/invalid value stays alpaca_paper + real.
inline FeedClock read_feed_clock(const std::string& path,
                                 const FeedClock& fallback) {
    FeedClock fc = fallback;
    std::ifstream in(path);
    if (!in) return fc;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return fc;
    std::string f = bridge::json_get_string(body, "feed_mode", fallback.feed_mode);
    std::string c =
        bridge::json_get_string(body, "clock_mode", fallback.clock_mode);
    if (is_valid_feed_mode(f)) fc.feed_mode = f;
    if (is_valid_clock_mode(c)) fc.clock_mode = c;
    return fc;
}

// A feed switch AWAY from alpaca_paper while a paper position is open would
// strand that position on a feed about to be replaced, so it is blocked. Any
// other switch (including INTO alpaca_paper, or between offline modes, or with no
// open position) is allowed. This is the open-position safety rule.
inline bool feed_switch_orphans_position(const std::string& current,
                                         const std::string& requested,
                                         bool has_open_positions) {
    return current == "alpaca_paper" && requested != "alpaca_paper" &&
           has_open_positions;
}

}  // namespace mal::core
