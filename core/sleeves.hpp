// Market AI Lab — core-satellite sleeve math (pure, header-only).
//
// The portfolio splits into two sleeves: quant_core (the systematic RSI-2 +
// momentum stack) and research_satellite (LLM deep-research positions). This
// header holds the MECHANICAL enforcement of the split as pure functions so it
// is unit-testable without a full Engine:
//   - satellite_has_room / satellite_cap_value: the HARD CAP. The satellite can
//     never exceed its target allocation plus the drift band. A research
//     conviction can never override this, it is checked in code before any order.
//   - decide_rebalance: when a sleeve drifts past target +/- band, trim the
//     OVERWEIGHT sleeve back toward target (executed by the engine through the
//     normal RiskGate-approved exit path, never a bypass).
// None of this touches a Level-1 risk limit. The RiskGate still judges every
// order in both sleeves with all its limits unchanged.
#pragma once

#include <string>

#include "config/config.hpp"

namespace mal::sleeve {

enum class Sleeve { QuantCore, ResearchSatellite };

inline std::string sleeve_to_string(Sleeve s) {
    return s == Sleeve::ResearchSatellite ? "research_satellite" : "quant_core";
}

inline Sleeve sleeve_from_string(const std::string& s) {
    return s == "research_satellite" ? Sleeve::ResearchSatellite
                                     : Sleeve::QuantCore;
}

// Current capital deployed per sleeve (position notional), plus uninvested cash.
struct Allocations {
    double quant_core = 0.0;
    double research_satellite = 0.0;
    double cash = 0.0;
    double invested() const { return quant_core + research_satellite; }
    double total() const { return quant_core + research_satellite + cash; }
};

// Fraction of equity currently in the satellite (0 when equity is 0).
inline double satellite_share(const Allocations& a, double equity) {
    return equity > 0.0 ? a.research_satellite / equity : 0.0;
}

inline double core_share(const Allocations& a, double equity) {
    return equity > 0.0 ? a.quant_core / equity : 0.0;
}

// The absolute currency ceiling for the satellite: (target + band) * equity.
inline double satellite_cap_value(const config::SleeveConfig& cfg, double equity) {
    double cap_pct = cfg.research_satellite_target_pct + cfg.drift_band_pct;
    return cap_pct * (equity > 0.0 ? equity : 0.0);
}

// HARD CAP: may the satellite add `new_notional` without exceeding its cap? A
// research conviction cannot override a false here. Also false when the sleeve is
// disabled, so a disabled satellite never opens a position.
inline bool satellite_has_room(const config::SleeveConfig& cfg,
                               const Allocations& a, double new_notional,
                               double equity) {
    if (!cfg.research_satellite_enabled) return false;
    if (new_notional <= 0.0) return false;
    return a.research_satellite + new_notional <=
           satellite_cap_value(cfg, equity) + 1e-9;
}

enum class RebalanceAction { None, TrimSatellite, TrimCore };

inline std::string rebalance_action_to_string(RebalanceAction r) {
    switch (r) {
        case RebalanceAction::TrimSatellite: return "trim_satellite";
        case RebalanceAction::TrimCore: return "trim_core";
        case RebalanceAction::None: return "none";
    }
    return "none";
}

struct RebalanceDecision {
    RebalanceAction action = RebalanceAction::None;
    double trim_amount = 0.0;            // currency to trim from the overweight sleeve
    double satellite_share_before = 0.0;  // satellite share of equity before
    double satellite_target = 0.0;
    double band = 0.0;
};

// Decide whether a sleeve drifted past its target +/- band and how much to trim
// the OVERWEIGHT sleeve back toward its target. equity is total account equity.
inline RebalanceDecision decide_rebalance(const config::SleeveConfig& cfg,
                                          const Allocations& a, double equity) {
    RebalanceDecision d;
    d.satellite_target = cfg.research_satellite_target_pct;
    d.band = cfg.drift_band_pct;
    d.satellite_share_before = satellite_share(a, equity);
    if (equity <= 0.0) return d;
    double sat_target_value = cfg.research_satellite_target_pct * equity;
    double core_target_value = cfg.quant_core_target_pct * equity;
    // Satellite overweight past the band: trim it back to target (the balloon
    // case, the safety-critical one).
    if (d.satellite_share_before > cfg.research_satellite_target_pct + cfg.drift_band_pct) {
        d.action = RebalanceAction::TrimSatellite;
        d.trim_amount = a.research_satellite - sat_target_value;
        return d;
    }
    // Satellite underweight past the band means the core is overweight: trim the
    // core back to target, returning capital toward the underweight satellite.
    if (d.satellite_share_before < cfg.research_satellite_target_pct - cfg.drift_band_pct &&
        a.quant_core > core_target_value) {
        d.action = RebalanceAction::TrimCore;
        d.trim_amount = a.quant_core - core_target_value;
        return d;
    }
    return d;
}

}  // namespace mal::sleeve
