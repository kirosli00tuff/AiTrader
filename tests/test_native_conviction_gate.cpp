// native_conviction_feeds_gate composition test (Task 3).
// True (default): the native rule_based conviction feeds the gate confidence
// and edge. False: gate confidence/edge come from the advisory factors alone,
// while direction (bias) and agreement stay from the full ensemble. This is
// composition only and never touches the RiskGate.
#include <cmath>
#include <map>
#include <vector>

#include "signal_engine/factor_engine.hpp"
#include "test_util.hpp"

using namespace mal::signal_engine;

int main() {
    WeightState w;
    w.set_from_map({{"rule_based", 0.18}, {"llm_primary", 0.27},
                    {"llm_secondary", 0.18}, {"llm_tertiary", 0.12},
                    {"dnn_advisory", 0.15}, {"whale_signal", 0.10}});
    std::vector<FactorSignal> sig = {
        {"rule_based",    0.8, 0.95, 0.15},  // strong native conviction
        {"llm_primary",   0.3, 0.55, 0.02},
        {"llm_secondary", 0.2, 0.50, 0.02},
        {"llm_tertiary",  0.1, 0.50, 0.02},
        {"dnn_advisory",  0.25, 0.55, 0.03},
        {"whale_signal",  0.1, 0.50, 0.01},
    };

    auto on = compose_gate_verdict(sig, w, /*native_feeds_gate=*/true);
    auto off = compose_gate_verdict(sig, w, /*native_feeds_gate=*/false);

    maltest::check(on.confidence > off.confidence,
                   "flag ON: gate confidence includes native conviction (higher)");
    maltest::check(on.edge >= off.edge,
                   "flag ON: gate edge includes native conviction");
    maltest::check(std::fabs(on.bias - off.bias) < 1e-9,
                   "direction (bias) identical under both flag states");
    maltest::check(on.agreement_count == off.agreement_count,
                   "agreement count identical under both flag states");

    auto base = combine(sig, w);
    maltest::check(std::fabs(base.confidence - on.confidence) < 1e-9,
                   "flag ON equals the plain full-ensemble combine (default)");
    maltest::check(off.confidence > 0.0,
                   "advisory-only confidence stays well-defined when flag OFF");
    return maltest::report("native_conviction_gate");
}
