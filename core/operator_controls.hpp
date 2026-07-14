// Remaining operator controls read from the GUI control file controls.json
// (Task 2), the same control-file pattern as the layer/source/feed-clock toggles:
//
//   * council model toggles  -> per-slot enable (llm_primary/secondary/tertiary),
//     so disabling a provider drops it from the council for the iteration. At
//     least one active provider is required or the engine logs a council skip.
//   * council budget          -> runtime council_daily_budget and per-symbol
//     cooldown minutes (validated server-side, re-clamped defensively here).
//   * regime pins             -> per-symbol manual regime override (test-only).
//
// These are ADVISORY / cost controls only. Nothing here disables, weakens, or
// bypasses the RiskGate, the kill switch, or any Level-1 limit. Read defensively:
// a missing or malformed entry keeps the safe current behavior (all providers on,
// config budget, no pin). The keys are flat and distinct so the tiny JSON reader
// cannot confuse them (llm_primary_enabled, rt_council_daily_budget,
// rt_per_symbol_cooldown_minutes, regime_pin:<symbol>).
#pragma once

#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>

#include "core/bridge_client.hpp"

namespace mal::core {

struct OperatorControls {
    // Council provider slot enables (default on). Disabling drops the slot.
    bool llm_primary = true;
    bool llm_secondary = true;
    bool llm_tertiary = true;
    // Runtime council budget overrides. -1 => keep the config default.
    int council_daily_budget = -1;
    int per_symbol_cooldown_minutes = -1;
    // Per-symbol regime pin (symbol -> "trending" | "range_bound" | "neutral").
    // Only present symbols are pinned; absence means auto-detect.
    std::map<std::string, std::string> regime_pins;

    bool operator==(const OperatorControls& o) const {
        return llm_primary == o.llm_primary &&
               llm_secondary == o.llm_secondary &&
               llm_tertiary == o.llm_tertiary &&
               council_daily_budget == o.council_daily_budget &&
               per_symbol_cooldown_minutes == o.per_symbol_cooldown_minutes &&
               regime_pins == o.regime_pins;
    }
    bool operator!=(const OperatorControls& o) const { return !(*this == o); }
};

// At least one council provider must be active for the council to run.
inline bool any_council_provider(const OperatorControls& oc) {
    return oc.llm_primary || oc.llm_secondary || oc.llm_tertiary;
}

// Whether a regime-pin label is one of the three valid regimes.
inline bool is_valid_regime_label(const std::string& r) {
    return r == "trending" || r == "range_bound" || r == "neutral";
}

// Read the remaining operator controls from controls.json. Missing/malformed =>
// safe defaults (all providers on, config budget via the -1 sentinel, no pins).
// The budget values are re-clamped to the same server-side bounds so a
// hand-edited file cannot widen them.
inline OperatorControls read_operator_controls(
    const std::string& path, const std::vector<std::string>& whitelist) {
    OperatorControls oc;
    std::ifstream in(path);
    if (!in) return oc;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return oc;

    oc.llm_primary = bridge::json_get_bool(body, "llm_primary_enabled", true);
    oc.llm_secondary = bridge::json_get_bool(body, "llm_secondary_enabled", true);
    oc.llm_tertiary = bridge::json_get_bool(body, "llm_tertiary_enabled", true);

    // Budget: -1 sentinel means "not set, keep config". Clamp to [1,500] and
    // cooldown to [0,1440] defensively (the server clamps too). The flat keys use
    // an rt_ prefix so they never collide with the nested budget block's keys.
    double b = bridge::json_get_number(body, "rt_council_daily_budget", -1.0);
    if (b >= 0.0) {
        int bi = static_cast<int>(b);
        oc.council_daily_budget = bi < 1 ? 1 : (bi > 500 ? 500 : bi);
    }
    double c =
        bridge::json_get_number(body, "rt_per_symbol_cooldown_minutes", -1.0);
    if (c >= 0.0) {
        int ci = static_cast<int>(c);
        oc.per_symbol_cooldown_minutes = ci > 1440 ? 1440 : ci;
    }

    // Regime pins: one flat key per pinned symbol (regime_pin:<symbol>).
    for (const auto& sym : whitelist) {
        std::string v = bridge::json_get_string(body, "regime_pin:" + sym, "");
        if (is_valid_regime_label(v)) oc.regime_pins[sym] = v;
    }
    return oc;
}

}  // namespace mal::core
