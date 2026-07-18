// Bar provenance: where a bar's prices actually came from.
//
// Exists because of the 2026-07-17 outage: the bridge lost live Alpaca data at
// 11:50Z, the feed fell back to the deterministic walk, and the engine wrote
// 916 synthetic bars into the real bars table and traded twice against them
// while every health signal stayed green. Nothing recorded that the prices
// were not real, so nothing could refuse them or alarm on them.
//
// The rule set here is deliberately small and pure so it is exhaustively
// testable without an Engine:
//   * Five values. real_feed | backfill | synthetic | replay | unknown.
//   * Anything unrecognized, including empty, normalizes to unknown. A bar
//     whose source cannot be established is unknown, NEVER real.
//   * On the real path (feed_mode alpaca_paper) only real_feed and backfill
//     bars may open a position. Exits are not gated here: a position is never
//     trapped, the exit simply logs what it executed against.
//   * Offline feed modes (flat_random_walk, synthetic_regimes, replay) are
//     synthetic BY DESIGN, so the entry gate does not apply to them.
//
// This is a data-validity gate, not a risk control. The RiskGate still judges
// every order that passes it. Nothing here touches RiskGate logic, the
// live-trading gate, or any Level-1 value.
#pragma once

#include <string>

namespace mal::provenance {

inline constexpr const char* kRealFeed = "real_feed";
inline constexpr const char* kBackfill = "backfill";
inline constexpr const char* kSynthetic = "synthetic";
inline constexpr const char* kReplay = "replay";
inline constexpr const char* kUnknown = "unknown";

// Collapse any string to one of the five values. Empty or junk means the
// source could not be established, which is unknown, never real.
inline std::string normalize(const std::string& s) {
    if (s == kRealFeed || s == kBackfill || s == kSynthetic || s == kReplay ||
        s == kUnknown)
        return s;
    return kUnknown;
}

// True when the provenance is real market data (live venue feed or a real
// historical backfill).
inline bool is_real(const std::string& source) {
    const std::string n = normalize(source);
    return n == kRealFeed || n == kBackfill;
}

// The entry gate. On the real path only real bars may open a position. On the
// offline feed modes every bar is synthetic or replayed by design, so the gate
// passes them through unchanged.
inline bool allows_entry(const std::string& feed_mode,
                         const std::string& source) {
    if (feed_mode != "alpaca_paper") return true;
    return is_real(source);
}

}  // namespace mal::provenance
