// Zero weight and participation, the two exclusion rules that look alike and
// are not (2026-07-27).
//
// WHY THIS EXISTS. Both rules were verified by REPLAY and by reading the code,
// never by test. Replay proves what happened on one recorded record; a test
// proves the rule. The 2026-07-27 deactivation session recorded the gap in
// writing and this closes it.
//
// THE TWO RULES, and the distinction is the whole point:
//
//   ZERO WEIGHT is a deactivation. combine() drops any factor at w <= 0.0
//   BEFORE the numerator and before the denominator, so a zero-weighted factor
//   contributes nothing at all. It does not sit neutral. That matters because
//   composed confidence is the weight-normalised MEAN of participating
//   factors: a factor left in at weight 0 with a low confidence would still
//   have to leave the DENOMINATOR or the mean would be wrong.
//
//   NON-PARTICIPATION is an absence of opinion. A council slot whose service
//   reported it did not run carries structural zeros, not a pessimistic view,
//   so compose_gate_verdict drops it from the confidence/edge denominator. A
//   PARTICIPATING factor reporting genuine low confidence STAYS IN, because
//   excluding it would inflate confidence on a genuinely weak setup. A benched
//   factor and a pessimistic factor look identical in the average and are
//   opposite cases, which is exactly the trap CONTEXT.md records.
//
// Nothing here touches RiskGate, any threshold, or any Level-1 value: these
// assert composition arithmetic only.
#include <cmath>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

#include "signal_engine/factor_engine.hpp"
#include "test_util.hpp"

using namespace mal;
using signal_engine::FactorSignal;
using signal_engine::WeightState;

namespace {

FactorSignal sig(const std::string& f, double bias, double conf, double edge,
                 bool participating = true) {
    FactorSignal s;
    s.factor = f;
    s.bias = bias;
    s.confidence = conf;
    s.edge = edge;
    s.participating = participating;
    return s;
}

WeightState weights(const std::vector<std::pair<std::string, double>>& ws) {
    WeightState w;
    for (const auto& [f, v] : ws) w.set_weight(f, v);
    return w;
}

}  // namespace

int main() {
    // --- 1. A ZERO-WEIGHT FACTOR CONTRIBUTES NOTHING ---------------------
    // Two factors at equal weight, then the second dropped to 0. If the zero
    // factor stayed in the denominator the mean would fall toward its
    // confidence; dropped from both, the mean is the survivor's own.
    {
        const std::vector<FactorSignal> s = {
            sig("rule_based", 0.8, 0.90, 0.05),
            sig("dnn_advisory", 0.8, 0.10, 0.01),
        };
        const auto both = signal_engine::combine(
            s, weights({{"rule_based", 0.5}, {"dnn_advisory", 0.5}}));
        const auto zeroed = signal_engine::combine(
            s, weights({{"rule_based", 0.5}, {"dnn_advisory", 0.0}}));
        maltest::check_near(both.confidence, 0.5, 1e-9,
                            "both at equal weight: confidence is the MEAN of "
                            "0.90 and 0.10");
        maltest::check_near(zeroed.confidence, 0.90, 1e-9,
                            "at weight 0 the factor leaves the DENOMINATOR too: "
                            "confidence is the survivor's 0.90, not a mean "
                            "dragged toward 0.10");
        maltest::check(zeroed.confidence > both.confidence,
                       "zeroing a low-confidence factor RAISES the composed "
                       "mean, which is why a deactivation is never neutral");
    }

    // --- 2. ZERO WEIGHT IS EXACT, NOT AN APPROXIMATION -------------------
    // A zero-weighted factor at maximum opposite conviction must not move the
    // verdict at all. Any residue leaking into the numerator flips this.
    {
        const std::vector<FactorSignal> s = {
            sig("rule_based", 1.0, 0.80, 0.04),
            sig("whale_signal", -1.0, 0.99, 0.09),
        };
        const auto alone = signal_engine::combine(
            {sig("rule_based", 1.0, 0.80, 0.04)}, weights({{"rule_based", 1.0}}));
        const auto zeroed = signal_engine::combine(
            s, weights({{"rule_based", 1.0}, {"whale_signal", 0.0}}));
        maltest::check_near(zeroed.bias, alone.bias, 1e-12,
                            "a zero-weighted factor cannot move bias, even at "
                            "maximum opposite conviction");
        maltest::check_near(zeroed.confidence, alone.confidence, 1e-12,
                            "nor confidence");
        maltest::check_near(zeroed.edge, alone.edge, 1e-12, "nor edge");
    }

    // --- 3. A FACTOR ABSENT FROM THE WEIGHT MAP IS ALSO EXCLUDED ---------
    // A different code path from w <= 0: an unknown factor never appears in
    // normalized() at all. The legacy dnn_rl factor was exactly this shape.
    {
        const std::vector<FactorSignal> s = {
            sig("rule_based", 0.5, 0.80, 0.04),
            sig("dnn_rl", -0.9, 0.20, 0.01),   // no weight entry exists
        };
        const auto v = signal_engine::combine(s, weights({{"rule_based", 1.0}}));
        maltest::check_near(v.confidence, 0.80, 1e-9,
                            "a factor with no weight entry is not in the "
                            "denominator");
    }

    // --- 4. A NON-PARTICIPATING COUNCIL SLOT LEAVES THE DENOMINATOR ------
    // The council ran, so the slots are eligible, but one service reported it
    // did NOT participate. Its structural zeros must not drag the mean.
    {
        const auto w = weights({{"rule_based", 0.4},
                                {"llm_primary", 0.3},
                                {"llm_secondary", 0.3}});
        const std::vector<FactorSignal> all_in = {
            sig("rule_based", 0.7, 0.80, 0.04),
            sig("llm_primary", 0.6, 0.70, 0.03),
            sig("llm_secondary", 0.6, 0.70, 0.03),
        };
        std::vector<FactorSignal> one_out = all_in;
        one_out[2] = sig("llm_secondary", 0.0, 0.0, 0.0, /*participating=*/false);

        const auto v_all = signal_engine::compose_gate_verdict(
            all_in, w, /*native_conviction_feeds_gate=*/true, 0.05, 0.0,
            /*council_ran=*/true);
        const auto v_out = signal_engine::compose_gate_verdict(
            one_out, w, true, 0.05, 0.0, true);

        maltest::check_near(v_out.confidence, (0.4 * 0.80 + 0.3 * 0.70) / 0.7,
                            1e-9,
                            "a non-participating slot leaves the DENOMINATOR: "
                            "confidence is the mean of the factors that "
                            "actually answered");
        maltest::check(v_out.confidence > 0.70,
                       "and it does NOT read as a zero-confidence vote");
        maltest::check(std::abs(v_out.confidence - v_all.confidence) < 0.06,
                       "dropping a silent slot barely moves the mean, because "
                       "it is an absence rather than an opinion");
    }

    // --- 5. THE CASE THAT MUST NOT BE 'FIXED': GENUINE LOW CONFIDENCE ----
    // A PARTICIPATING factor reporting real low confidence stays in the
    // denominator. Excluding it would inflate confidence on a weak setup, the
    // opposite error from case 4.
    {
        const auto w = weights({{"rule_based", 0.5}, {"llm_primary", 0.5}});
        const std::vector<FactorSignal> pessimistic = {
            sig("rule_based", 0.7, 0.90, 0.05),
            sig("llm_primary", 0.1, 0.10, 0.00, /*participating=*/true),
        };
        std::vector<FactorSignal> benched = pessimistic;
        benched[1] = sig("llm_primary", 0.0, 0.0, 0.0, /*participating=*/false);

        const auto v_pess = signal_engine::compose_gate_verdict(
            pessimistic, w, true, 0.0, 0.0, true);
        const auto v_bench = signal_engine::compose_gate_verdict(
            benched, w, true, 0.0, 0.0, true);
        maltest::check_near(v_pess.confidence, 0.5, 1e-9,
                            "a participating pessimist STAYS in: 0.90 and 0.10 "
                            "average to 0.50");
        maltest::check_near(v_bench.confidence, 0.90, 1e-9,
                            "a benched slot leaves: the survivor's 0.90 stands");
        maltest::check(v_bench.confidence > v_pess.confidence,
                       "THE TRAP: the two look identical in the raw numbers and "
                       "compose to opposite answers, so the flag separates "
                       "them, never the confidence value");
    }

    return maltest::report("zero_weight_participation");
}
