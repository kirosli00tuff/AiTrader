// Market AI Lab — Layer 2: Adaptive Strategy.
//
// Tunes model weights / thresholds / sizing within bounded, safe ranges. Every
// change is logged (param history) and rollback-able. CRITICAL INVARIANT: the
// adaptive layer is *structurally incapable* of weakening any Layer-1 hard
// limit — `validate_not_weakening_limits` rejects any proposed risk change that
// would make a limit more permissive, and locked weights are never touched.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "config/config.hpp"
#include "signal_engine/factor_engine.hpp"

namespace mal::learning {

// A single recorded parameter change (for audit + rollback).
struct ParamChange {
    std::string ts;
    std::string param;
    std::string old_value;
    std::string new_value;
    std::string source;  // adaptive | manual | rollback
    std::string reason;
};

// Compare a proposed risk config against the immutable hard limits. Returns a
// list of violations (empty => the proposal does not weaken any hard limit).
// "Weaken" = make a loss/exposure limit larger, or a quality gate smaller.
std::vector<std::string> validate_not_weakening_limits(
    const config::RiskConfig& hard, const config::RiskConfig& proposed);

// Champion/challenger record for DNN model bookkeeping.
struct ModelRecord {
    std::string model_id;
    std::string role;  // champion | challenger | retired
    double metric = 0.0;  // e.g. expectancy / sharpe proxy
    std::string ts;
};

// Adaptive tuner owns parameter history + rollback + bounded weight tuning.
class AdaptiveTuner {
public:
    AdaptiveTuner(config::RiskConfig hard_limits, config::AdaptiveConfig cfg)
        : hard_(std::move(hard_limits)), cfg_(std::move(cfg)) {}

    // Propose adaptive weight nudges toward better-performing factors. Returns
    // the proposed normalized-ish weight map (caller applies via WeightState,
    // which itself skips locked factors). Bounded so no single factor exceeds
    // `max_single_weight`.
    std::map<std::string, double> propose_weight_update(
        const signal_engine::WeightState& current,
        const std::map<std::string, double>& factor_performance,
        double learning_rate = 0.05, double max_single_weight = 0.6) const;

    // Apply a weight update through the WeightState (respects locks) and record
    // each change. Returns the list of changed factors.
    std::vector<std::string> apply_and_record(
        signal_engine::WeightState& weights,
        const std::map<std::string, double>& proposed,
        const std::string& source, const std::string& ts);

    // Propose a threshold change, but ONLY if it does not weaken hard limits.
    // Returns std::nullopt (and records nothing) if the change is rejected.
    std::optional<config::RiskConfig> propose_threshold_update(
        const config::RiskConfig& current,
        const config::RiskConfig& proposed, const std::string& ts);

    // Roll back the most recent recorded change of a given param. Returns the
    // restored old value if a change existed.
    std::optional<std::string> rollback_last(const std::string& param,
                                             const std::string& ts);

    const std::vector<ParamChange>& history() const { return history_; }

    bool adaptive_enabled() const { return cfg_.adaptive_learning_enabled; }

private:
    config::RiskConfig hard_;
    config::AdaptiveConfig cfg_;
    std::vector<ParamChange> history_;
};

}  // namespace mal::learning
