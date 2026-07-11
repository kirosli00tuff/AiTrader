// Per-layer toggle tests (Task 5). read_layer_toggles defaults all layers ON
// when the file is missing or malformed, and respects explicit toggles.
// factor_enabled drops a layer's factor when off, but NEVER gates rule_based
// (native, safety-adjacent) or rl_advisory, so the RiskGate still sees the
// native conviction and evaluates every order. Safety has no toggle field.
#include <cstdio>
#include <fstream>
#include <string>

#include "core/layer_toggles.hpp"
#include "test_util.hpp"

using namespace mal::core;

int main() {
    LayerToggles miss = read_layer_toggles("/tmp/mal_no_such_controls_XYZ.json");
    maltest::check(miss.adaptive && miss.council && miss.dnn_advisory && miss.whale,
                   "missing controls.json defaults all layers ON");

    const std::string bad = "/tmp/mal_bad_controls.json";
    { std::ofstream o(bad); o << "not json at all {{{"; }
    LayerToggles bt = read_layer_toggles(bad);
    maltest::check(bt.adaptive && bt.council && bt.dnn_advisory && bt.whale,
                   "malformed controls.json defaults all layers ON");
    std::remove(bad.c_str());

    const std::string good = "/tmp/mal_good_controls.json";
    { std::ofstream o(good);
      o << R"({"layers": {"adaptive": true, "council": false, )"
           R"("dnn_advisory": false, "whale": true}})"; }
    LayerToggles t = read_layer_toggles(good);
    maltest::check(t.adaptive && !t.council && !t.dnn_advisory && t.whale,
                   "explicit layer toggles are respected");
    std::remove(good.c_str());

    maltest::check(!factor_enabled("llm_primary", t), "council off drops llm_primary");
    maltest::check(!factor_enabled("llm_secondary", t), "council off drops llm_secondary");
    maltest::check(!factor_enabled("llm_tertiary", t), "council off drops llm_tertiary");
    maltest::check(!factor_enabled("dnn_advisory", t), "dnn off drops dnn_advisory");
    maltest::check(factor_enabled("whale_signal", t), "whale on keeps whale_signal");

    LayerToggles alloff;
    alloff.adaptive = alloff.council = alloff.dnn_advisory = alloff.whale = false;
    maltest::check(factor_enabled("rule_based", alloff),
                   "rule_based never gated by a layer toggle (safety-adjacent)");
    maltest::check(factor_enabled("rl_advisory", alloff),
                   "rl_advisory never gated by a layer toggle (separately gated)");
    return maltest::report("layer_toggles");
}
