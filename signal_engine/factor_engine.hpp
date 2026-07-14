// Market AI Lab — factor-combination engine + model-weight state.
//
// Combines all advisory factors (LLM consensus, rule-based, DNN/RL, whale) into
// a single weighted verdict. Weights are normalizable, lockable (against the
// adaptive layer), and individually enable/disable-able. This is the core
// decision math that feeds the proposed action into Layer 1 (RiskGate).
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace mal::signal_engine {

// One advisory factor's structured output.
struct FactorSignal {
    std::string factor;       // llm_primary | rule_based | dnn_advisory | whale_signal ...
    double bias = 0.0;        // signed directional bias [-1,1]
    double confidence = 0.0;  // [0,1]
    double edge = 0.0;        // expected edge (return net of fees)
};

// Per-factor weight control state.
struct WeightEntry {
    double weight = 0.0;
    bool enabled = true;
    bool locked = false;  // locked => adaptive layer may not change it
};

// Aggregated decision after weighting.
struct CombinedVerdict {
    double bias = 0.0;        // weighted signed bias [-1,1]
    double confidence = 0.0;  // weighted confidence [0,1]
    double edge = 0.0;        // weighted edge
    std::string verdict;      // strong_sell..strong_buy
    int agreement_count = 0;  // # factors agreeing with the net direction
    std::map<std::string, double> contributions;  // factor -> normalized weight*used
};

std::string bias_to_verdict(double bias);

class WeightState {
public:
    WeightState() = default;

    // Initialize from a name->weight map (e.g. config model_weights).
    void set_from_map(const std::map<std::string, double>& weights);

    void set_weight(const std::string& factor, double w);
    void set_enabled(const std::string& factor, bool enabled);
    void set_locked(const std::string& factor, bool locked);

    std::optional<WeightEntry> get(const std::string& factor) const;
    const std::map<std::string, WeightEntry>& entries() const { return entries_; }

    // Sum of weights of enabled factors.
    double enabled_sum() const;

    // Return normalized weights over enabled factors (sum to 1). Disabled
    // factors get 0. If no enabled factor has positive weight, returns empty.
    std::map<std::string, double> normalized() const;

    // Adaptive update: only applies to UNLOCKED, enabled factors. Returns the
    // factors actually changed (locked ones are skipped — Layer-2 cannot
    // override a manual lock). Pure w.r.t. locked entries.
    std::vector<std::string> apply_adaptive(
        const std::map<std::string, double>& proposed);

private:
    std::map<std::string, WeightEntry> entries_;
};

// Combine factor signals using normalized weights. `min_factor_conf` filters
// out near-zero-confidence factors from the agreement count. `rule_based_min_share`
// (default 0 = off) guarantees the rule_based factor at least that share of the
// normalized weight over the signal-producing factors, so a saturated advisory
// set cannot dilute the native conviction below it. It never changes direction,
// only how much the native confidence/edge feed the weighted average.
CombinedVerdict combine(const std::vector<FactorSignal>& signals,
                        const WeightState& weights,
                        double min_factor_conf = 0.05,
                        double rule_based_min_share = 0.0);

// Compose the confidence/edge the RiskGate sees, honoring
// native_conviction_feeds_gate. When true (default) this returns the full
// ensemble verdict (native rule_based conviction feeds the gate). When false,
// bias/verdict/agreement stay from the full ensemble but confidence/edge come
// from the advisory factors alone (rule_based excluded), so a genuine technical
// setup drives direction and sizing without also inflating the gate
// confidence/edge. This never touches the RiskGate or its thresholds.
CombinedVerdict compose_gate_verdict(const std::vector<FactorSignal>& signals,
                                     const WeightState& weights,
                                     bool native_conviction_feeds_gate,
                                     double min_factor_conf = 0.05,
                                     double rule_based_min_share = 0.0);

}  // namespace mal::signal_engine
