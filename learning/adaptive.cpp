#include "learning/adaptive.hpp"

#include <algorithm>
#include <cmath>
#include <sstream>

namespace mal::learning {

namespace {
std::string d2s(double v) {
    std::ostringstream os;
    os << v;
    return os.str();
}
}  // namespace

std::vector<std::string> validate_not_weakening_limits(
    const config::RiskConfig& hard, const config::RiskConfig& proposed) {
    std::vector<std::string> bad;
    // A LARGER loss/exposure ceiling = weaker safety => reject.
    auto no_larger = [&](const char* name, double h, double p) {
        if (p > h + 1e-12)
            bad.push_back(std::string(name) + " would be weakened (" + d2s(h) +
                          " -> " + d2s(p) + ")");
    };
    // A SMALLER quality gate / count = weaker safety => reject.
    auto no_smaller = [&](const char* name, double h, double p) {
        if (p < h - 1e-12)
            bad.push_back(std::string(name) + " would be weakened (" + d2s(h) +
                          " -> " + d2s(p) + ")");
    };

    no_larger("max_daily_loss_total_pct", hard.max_daily_loss_total_pct,
              proposed.max_daily_loss_total_pct);
    no_larger("max_daily_loss_per_venue_pct", hard.max_daily_loss_per_venue_pct,
              proposed.max_daily_loss_per_venue_pct);
    no_larger("max_trade_risk_pct_of_equity", hard.max_trade_risk_pct_of_equity,
              proposed.max_trade_risk_pct_of_equity);
    no_larger("max_total_open_risk_pct", hard.max_total_open_risk_pct,
              proposed.max_total_open_risk_pct);
    no_larger("max_exposure_per_symbol_pct", hard.max_exposure_per_symbol_pct,
              proposed.max_exposure_per_symbol_pct);
    no_larger("max_exposure_per_market_pct", hard.max_exposure_per_market_pct,
              proposed.max_exposure_per_market_pct);
    no_larger("max_exposure_per_category_pct",
              hard.max_exposure_per_category_pct,
              proposed.max_exposure_per_category_pct);
    no_larger("max_open_positions_total", hard.max_open_positions_total,
              proposed.max_open_positions_total);
    no_larger("max_open_positions_per_venue", hard.max_open_positions_per_venue,
              proposed.max_open_positions_per_venue);
    no_larger("max_consecutive_losses", hard.max_consecutive_losses,
              proposed.max_consecutive_losses);

    no_smaller("min_confidence_default", hard.min_confidence_default,
               proposed.min_confidence_default);
    no_smaller("min_edge_default", hard.min_edge_default,
               proposed.min_edge_default);
    no_smaller("required_model_agreement_count",
               hard.required_model_agreement_count,
               proposed.required_model_agreement_count);

    // Safety toggles must never be turned off by adaptive logic.
    if (hard.kill_switch_enabled && !proposed.kill_switch_enabled)
        bad.push_back("kill_switch_enabled must not be disabled");
    if (hard.hard_stop_live_if_loss_breach &&
        !proposed.hard_stop_live_if_loss_breach)
        bad.push_back("hard_stop_live_if_loss_breach must not be disabled");
    return bad;
}

std::map<std::string, double> AdaptiveTuner::propose_weight_update(
    const signal_engine::WeightState& current,
    const std::map<std::string, double>& factor_performance,
    double learning_rate, double max_single_weight) const {
    std::map<std::string, double> proposed;
    // Nudge each (unlocked, enabled) factor's weight toward its performance.
    // Performance is expected in roughly [-1,1]; positive => increase weight.
    for (const auto& [factor, entry] : current.entries()) {
        if (entry.locked || !entry.enabled) {
            proposed[factor] = entry.weight;  // unchanged (skipped on apply)
            continue;
        }
        double perf = 0.0;
        auto it = factor_performance.find(factor);
        if (it != factor_performance.end()) perf = it->second;
        double w = entry.weight * (1.0 + learning_rate * perf);
        w = std::clamp(w, 0.0, max_single_weight);
        // Floor the native rule_based weight so the tuner cannot starve native
        // entry generation over a long run. The floor is a lower bound on an
        // advisory weight, still under the max_single_weight cap, and it never
        // touches a risk limit. The tuner may still lower rule_based toward the
        // floor and raise it up to the cap.
        if (factor == "rule_based") {
            double floor = std::min(cfg_.rule_based_weight_floor, max_single_weight);
            w = std::max(w, floor);
        }
        proposed[factor] = w;
    }
    return proposed;
}

std::vector<std::string> AdaptiveTuner::apply_and_record(
    signal_engine::WeightState& weights,
    const std::map<std::string, double>& proposed, const std::string& source,
    const std::string& ts) {
    std::vector<std::string> changed;
    for (const auto& [factor, new_w] : proposed) {
        auto cur = weights.get(factor);
        if (!cur) continue;
        if (cur->locked || !cur->enabled) continue;
        if (std::abs(cur->weight - new_w) <= 1e-12) continue;
        history_.push_back({ts, "weight." + factor, d2s(cur->weight),
                            d2s(new_w), source, "adaptive weight nudge"});
        weights.set_weight(factor, new_w);
        changed.push_back(factor);
    }
    return changed;
}

std::optional<config::RiskConfig> AdaptiveTuner::propose_threshold_update(
    const config::RiskConfig& current, const config::RiskConfig& proposed,
    const std::string& ts) {
    // SAFETY: reject anything that would weaken a hard limit relative to the
    // immutable baseline captured at construction.
    auto violations = validate_not_weakening_limits(hard_, proposed);
    if (!violations.empty()) {
        history_.push_back({ts, "threshold_update", "(rejected)",
                            violations.front(), "adaptive",
                            "rejected: would weaken hard limit"});
        return std::nullopt;
    }
    // Record the (tightening) change for min_confidence as a representative.
    if (std::abs(current.min_confidence_default -
                 proposed.min_confidence_default) > 1e-12) {
        history_.push_back({ts, "min_confidence_default",
                            d2s(current.min_confidence_default),
                            d2s(proposed.min_confidence_default), "adaptive",
                            "tightened confidence gate"});
    }
    return proposed;
}

std::optional<std::string> AdaptiveTuner::rollback_last(const std::string& param,
                                                        const std::string& ts) {
    for (auto it = history_.rbegin(); it != history_.rend(); ++it) {
        if (it->param == param && it->source != "rollback") {
            std::string restored = it->old_value;
            history_.push_back({ts, param, it->new_value, restored, "rollback",
                                "rollback to previous value"});
            return restored;
        }
    }
    return std::nullopt;
}

}  // namespace mal::learning
