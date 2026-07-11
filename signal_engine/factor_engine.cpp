#include "signal_engine/factor_engine.hpp"

#include <cmath>

namespace mal::signal_engine {

std::string bias_to_verdict(double bias) {
    if (bias <= -0.6) return "strong_sell";
    if (bias <= -0.2) return "sell";
    if (bias < 0.2) return "hold";
    if (bias < 0.6) return "buy";
    return "strong_buy";
}

void WeightState::set_from_map(const std::map<std::string, double>& weights) {
    entries_.clear();
    for (const auto& [k, v] : weights) {
        WeightEntry e;
        e.weight = v;
        entries_[k] = e;
    }
}

void WeightState::set_weight(const std::string& factor, double w) {
    entries_[factor].weight = w;
}
void WeightState::set_enabled(const std::string& factor, bool enabled) {
    entries_[factor].enabled = enabled;
}
void WeightState::set_locked(const std::string& factor, bool locked) {
    entries_[factor].locked = locked;
}

std::optional<WeightEntry> WeightState::get(const std::string& factor) const {
    auto it = entries_.find(factor);
    if (it == entries_.end()) return std::nullopt;
    return it->second;
}

double WeightState::enabled_sum() const {
    double s = 0.0;
    for (const auto& [_, e] : entries_)
        if (e.enabled) s += e.weight;
    return s;
}

std::map<std::string, double> WeightState::normalized() const {
    std::map<std::string, double> out;
    double sum = enabled_sum();
    if (sum <= 0.0) return out;
    for (const auto& [k, e] : entries_)
        out[k] = e.enabled ? e.weight / sum : 0.0;
    return out;
}

std::vector<std::string> WeightState::apply_adaptive(
    const std::map<std::string, double>& proposed) {
    std::vector<std::string> changed;
    for (const auto& [k, v] : proposed) {
        auto it = entries_.find(k);
        if (it == entries_.end()) continue;
        // SAFETY: locked weights are immune to adaptive change; disabled too.
        if (it->second.locked || !it->second.enabled) continue;
        if (std::abs(it->second.weight - v) > 1e-12) {
            it->second.weight = v;
            changed.push_back(k);
        }
    }
    return changed;
}

CombinedVerdict combine(const std::vector<FactorSignal>& signals,
                        const WeightState& weights, double min_factor_conf) {
    CombinedVerdict cv;
    auto norm = weights.normalized();
    if (norm.empty()) return cv;

    double wbias = 0.0, wconf = 0.0, wedge = 0.0, used_weight = 0.0;
    for (const auto& s : signals) {
        auto it = norm.find(s.factor);
        if (it == norm.end()) continue;
        double w = it->second;
        if (w <= 0.0) continue;
        wbias += w * s.bias;
        wconf += w * s.confidence;
        wedge += w * s.edge;
        used_weight += w;
        cv.contributions[s.factor] = w;
    }
    if (used_weight > 0.0) {
        // Re-normalize across factors that actually produced a signal.
        cv.bias = wbias / used_weight;
        cv.confidence = wconf / used_weight;
        cv.edge = wedge / used_weight;
    }
    cv.verdict = bias_to_verdict(cv.bias);

    // Agreement: count factors (with real confidence) on the net side.
    int net_sign = (cv.bias > 0) - (cv.bias < 0);
    for (const auto& s : signals) {
        if (norm.find(s.factor) == norm.end()) continue;
        if (s.confidence < min_factor_conf) continue;
        int sign = (s.bias > 0) - (s.bias < 0);
        if (net_sign != 0 && sign == net_sign) cv.agreement_count++;
    }
    return cv;
}

CombinedVerdict compose_gate_verdict(const std::vector<FactorSignal>& signals,
                                     const WeightState& weights,
                                     bool native_conviction_feeds_gate,
                                     double min_factor_conf) {
    CombinedVerdict full = combine(signals, weights, min_factor_conf);
    if (native_conviction_feeds_gate) return full;
    // Flag OFF: the native setup still drives direction (bias) and sizing, but
    // the gate confidence and edge come from the ADVISORY factors alone. We
    // recompute confidence/edge over the ensemble minus `rule_based` and swap
    // only those two fields. Bias, verdict, and agreement are unchanged. This
    // never touches the RiskGate or its thresholds.
    std::vector<FactorSignal> advisory;
    advisory.reserve(signals.size());
    for (const auto& s : signals)
        if (s.factor != "rule_based") advisory.push_back(s);
    CombinedVerdict adv = combine(advisory, weights, min_factor_conf);
    full.confidence = adv.confidence;
    full.edge = adv.edge;
    return full;
}

}  // namespace mal::signal_engine
