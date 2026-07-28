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

// FILL PROVENANCE (2026-07-27). The provenance recorded on a TRADE row, which
// is the bar set above plus one value a bar can never carry.
//
// WHY A SIXTH VALUE EXISTS HERE AND NOWHERE ELSE. `unknown` on a trade row
// means AN UNMIGRATED HISTORICAL ROW. The column arrived by
// `ALTER TABLE trades ADD COLUMN bar_source TEXT DEFAULT 'unknown'`
// (storage.cpp), so all 247 pre-existing rows carry it and nothing recorded
// where their prices came from. Meanwhile two silent fallbacks (a struct field
// default and an empty-string ternary) made a LIVE write with no established
// provenance produce that same literal, byte for byte. Four conditions
// collapsed onto one string and the data could separate none of them.
//
// `unclassified` splits the live case out. A live write whose bar provenance
// cannot be established records `unclassified`, so an unclassified live row is
// distinguishable from an unmigrated historical one and `unknown` keeps one
// meaning. No live write can produce `unknown` any more: classify maps it, and
// empty, and junk, to `unclassified`.
//
// IT SUCCEEDS, IT DOES NOT REFUSE, and the direction is deliberate.
// insert_trade records a fill that ALREADY HAPPENED at the venue. Refusing
// would destroy the only record that it occurred and hide the position from
// reconciliation and rehydration, which is worse than a badly labelled row.
// That is the opposite of the bar path, where a refused bar can be refetched.
//
// AND THE MARKER NEVER TRAVELS ALONE. A silent marker is how three fabrication
// defects survived, so Storage::insert_trade emits a CRITICAL
// `fill_provenance_unclassified` event on every one, carrying the trade id,
// symbol, origin and reason, and the GUI surfaces it.
//
// The real-fill gates are unaffected: they count `real_feed` and `backfill`
// only, so `unclassified` is excluded by the same rule that already excludes
// `unknown`. A gate whose job is to say "not yet" counts nothing it cannot
// prove.
//
// THIS IS A LABEL, NOT A GATE. Nothing here refuses an order, sizes one, or
// touches RiskGate, the live-trading gate, or any Level-1 value.
namespace fill {

inline constexpr const char* kUnclassified = "unclassified";

// WHY a fill was recorded unclassified. These are the two conditions the old
// code made byte-identical: a caller that never stated provenance, and a
// caller whose provenance genuinely could not be established. Both record the
// same marker, because the value set gains exactly one member by design, and
// this field is what separates them in the audit record. It is load-bearing
// rather than decorative: restoring the struct default at storage.hpp turns a
// field_never_set write into a provenance_unavailable one, which is how the
// guard test catches a restored fallback that the row value alone would hide.
inline constexpr const char* kReasonFieldUnset = "field_never_set";
inline constexpr const char* kReasonUnavailable = "provenance_unavailable";

// THE classifier for a trade write. Anything that cannot stand as an
// established live provenance becomes `unclassified`: empty (nobody stated
// it), `unknown` (the historical marker, never a live claim), and junk.
// Everything else keeps the bar meaning it was given.
inline std::string classify(const std::string& s) {
    if (s.empty()) return kUnclassified;
    if (s == kUnclassified) return kUnclassified;
    const std::string n = provenance::normalize(s);
    if (n == kUnknown) return kUnclassified;
    return n;
}

// Which of the two conditions produced an unclassified write.
inline std::string reason_for(const std::string& s) {
    return s.empty() ? kReasonFieldUnset : kReasonUnavailable;
}

// True when a fill's provenance could not be established. Never real.
inline bool is_unclassified(const std::string& s) {
    return classify(s) == kUnclassified;
}

}  // namespace fill

// VOLUME PROVENANCE (2026-07-25). Where a bar's VOLUME came from, which is a
// separate question from where its prices came from.
//
// The two axes genuinely differ on the live path: a real_feed bar takes its
// prices from the venue's latest TRADE and its volume from the venue's latest
// completed MINUTE BAR (market_data::consume_latest_bar). The 2026-07-23
// quarantine proved the axes have to be recorded separately, marking 3,443
// live volumes fabricated_zeroed while their prices stayed real and tradeable.
//
// The column existed from that quarantine onward and nothing populated it: of
// 97,127 bars, 3,443 carried the quarantine mark and 93,684 carried NULL, so
// a real venue volume and an unestablished one were indistinguishable. Every
// write path now states its volume provenance explicitly, and NULL keeps its
// only honest meaning: written before the label existed, provenance unknown,
// never to be read as venue-reported.
namespace volume {

inline constexpr const char* kVenueBar = "venue_bar";            // live minute bars
inline constexpr const char* kVenueBackfill = "venue_backfill";  // historical bars
inline constexpr const char* kSynthetic = "synthetic";           // generated
inline constexpr const char* kReplay = "replay";                 // replayed history
inline constexpr const char* kUnknown = "unknown";               // not established
// Written by scripts/quarantine_fabricated_volume_20260723.py, never by a
// live write path. Listed so the set is closed and the label is not reinvented.
inline constexpr const char* kFabricatedZeroed = "fabricated_zeroed";

inline std::string normalize(const std::string& s) {
    if (s == kVenueBar || s == kVenueBackfill || s == kSynthetic ||
        s == kReplay || s == kUnknown || s == kFabricatedZeroed)
        return s;
    return kUnknown;
}

// True when the volume is the venue's own reported number. Must match
// market_data.tradeable.VENUE_VOLUME_SOURCES on the Python side.
inline bool is_venue(const std::string& volume_source) {
    const std::string n = normalize(volume_source);
    return n == kVenueBar || n == kVenueBackfill;
}

// THE derivation: a bar's volume provenance follows from its price
// provenance, because the same poll that produced the prices produced the
// volume. One function so the mapping is stated once and is testable without
// an Engine. A real_feed bar's volume is the venue's minute-bar aggregate, a
// backfill bar's is the venue's historical bar, and everything else carries
// the provenance of whatever generated it.
inline std::string for_bar_source(const std::string& bar_source) {
    const std::string n = provenance::normalize(bar_source);
    if (n == provenance::kRealFeed) return kVenueBar;
    if (n == provenance::kBackfill) return kVenueBackfill;
    if (n == provenance::kSynthetic) return kSynthetic;
    if (n == provenance::kReplay) return kReplay;
    return kUnknown;
}

}  // namespace volume

}  // namespace mal::provenance
