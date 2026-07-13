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

    // --- Source axis (mock/real), Task 1 -----------------------------------
    // Missing file => every layer on-real (full-activation default).
    maltest::check(miss.council_real && miss.dnn_advisory_real && miss.whale_real,
                   "missing controls.json defaults every source to real");

    const std::string src = "/tmp/mal_src_controls.json";
    { std::ofstream o(src);
      o << R"({"layers": {"adaptive": true, "council": true, )"
           R"("dnn_advisory": true, "whale": true}, )"
           R"("council_source": "mock", "whale_source": "real"})"; }
    LayerToggles s = read_layer_toggles(src);
    maltest::check(!s.council_real, "council_source mock => council_real false");
    maltest::check(s.whale_real, "whale_source real => whale_real true");
    maltest::check(s.dnn_advisory_real,
                   "missing dnn_advisory_source defaults to real");
    std::remove(src.c_str());

    // factor_source_real maps each advisory factor to its layer source; the
    // native + rl factors have no mock/real axis and report real.
    maltest::check(!factor_source_real("llm_primary", s),
                   "llm factor source follows council_real (mock)");
    maltest::check(factor_source_real("whale_signal", s),
                   "whale factor source follows whale_real (real)");
    maltest::check(factor_source_real("rule_based", s),
                   "rule_based has no source axis, reports real");
    maltest::check(factor_source_real("rl_advisory", s),
                   "rl_advisory has no source axis, reports real");

    // Three-state label: off / on-mock / on-real.
    maltest::check(std::string(layer_state(false, true)) == "off",
                   "disabled layer state is off");
    maltest::check(std::string(layer_state(true, false)) == "on-mock",
                   "enabled+mock state is on-mock");
    maltest::check(std::string(layer_state(true, true)) == "on-real",
                   "enabled+real state is on-real");
    return maltest::report("layer_toggles");
}
