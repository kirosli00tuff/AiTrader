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
      o << R"({"layer_adaptive_enabled": true, "layer_council_enabled": false, )"
           R"("layer_dnn_advisory_enabled": false, "layer_whale_enabled": true})"; }
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
      o << R"({"layer_adaptive_enabled": true, "layer_council_enabled": true, )"
           R"("layer_dnn_advisory_enabled": true, "layer_whale_enabled": true, )"
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

    // --- The enable key must not collide with the source key ----------------
    // THIS IS THE REGRESSION. The enable axis used to read a BARE layer name
    // ("whale"), and the GUI keys BOTH of its maps by layer name, so
    // controls.json carried "whale" twice: the bool in layers and the source
    // string in layer_sources. json_get_bool is a flat search that takes the
    // FIRST hit, so the bool won only because layers is emitted first.
    //
    // Both orders are written here. Before the fix the second one read whale ON
    // with the file plainly saying off: a string parses as neither true nor
    // false, so json_get_bool returned its DEFAULT of true. The failure is
    // silent and one-directional, the layer STICKS ON, which is the wrong
    // direction for a spender the operator is trying to switch off.
    const std::string ord = "/tmp/mal_order_controls.json";
    for (int sources_first = 0; sources_first < 2; ++sources_first) {
        { std::ofstream o(ord);
          o << "{";
          if (sources_first)
              o << R"("layer_sources": {"whale": "real"}, )"
                   R"("layers": {"whale": false}, )";
          else
              o << R"("layers": {"whale": false}, )"
                   R"("layer_sources": {"whale": "real"}, )";
          o << R"("layer_whale_enabled": false, "whale_source": "real"})"; }
        LayerToggles ot = read_layer_toggles(ord);
        maltest::check(!ot.whale,
                       sources_first
                           ? "whale off resolves with layer_sources emitted FIRST"
                           : "whale off resolves with layers emitted first");
        maltest::check(ot.whale_real,
                       "whale source stays real regardless of block order");
    }
    std::remove(ord.c_str());

    // The enable key and the source key resolve INDEPENDENTLY: off + real is a
    // real state (the layer is off, and it would use the live service if on).
    const std::string ind = "/tmp/mal_indep_controls.json";
    { std::ofstream o(ind);
      o << R"({"layer_whale_enabled": false, "whale_source": "mock", )"
           R"("layer_council_enabled": true, "council_source": "real"})"; }
    LayerToggles it = read_layer_toggles(ind);
    maltest::check(!it.whale && !it.whale_real,
                   "whale resolves off + mock independently");
    maltest::check(it.council && it.council_real,
                   "council resolves on + real independently");
    std::remove(ind.c_str());

    // Three-state label: off / on-mock / on-real.
    maltest::check(std::string(layer_state(false, true)) == "off",
                   "disabled layer state is off");
    maltest::check(std::string(layer_state(true, false)) == "on-mock",
                   "enabled+mock state is on-mock");
    maltest::check(std::string(layer_state(true, true)) == "on-real",
                   "enabled+real state is on-real");
    return maltest::report("layer_toggles");
}
