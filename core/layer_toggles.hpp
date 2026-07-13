// Per-layer enable + source toggles read from the GUI control file controls.json.
//
// Two independent axes per toggleable advisory layer (LLM council, dnn_advisory,
// whale):
//   * enable axis (off/on): off drops the layer's factor from the ensemble.
//   * source axis (mock/real): applies only when the layer is on. real uses the
//     live service (via the Python bridge); mock uses the deterministic C++
//     stand-in. So each layer has three states: off, on-mock, on-real.
//
// The adaptive layer has an enable axis only (there is no mock-vs-real service to
// switch, so a source axis is not meaningful there).
//
// This is ADVISORY ONLY. It removes or mocks a signal, it never disables,
// weakens, or bypasses the RiskGate, the kill switch, or any Level-1 limit. The
// static-safety layer has neither axis: it is always on and always real.
//
// Read defensively: a missing or malformed file means all layers ON and, on the
// real paper path, source real, the safe full-activation default.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "core/bridge_client.hpp"  // bridge::json_get_bool / json_get_string

namespace mal::core {

struct LayerToggles {
    // Enable axis (off/on). Off removes the factor from the ensemble.
    bool adaptive = true;
    bool council = true;
    bool dnn_advisory = true;
    bool whale = true;
    // Source axis (mock=false / real=true). Applies only when the layer is on.
    // Defaults to real so a missing/malformed file means on-real on the paper
    // path. Adaptive has no source axis.
    bool council_real = true;
    bool dnn_advisory_real = true;
    bool whale_real = true;

    bool operator==(const LayerToggles& o) const {
        return adaptive == o.adaptive && council == o.council &&
               dnn_advisory == o.dnn_advisory && whale == o.whale &&
               council_real == o.council_real &&
               dnn_advisory_real == o.dnn_advisory_real &&
               whale_real == o.whale_real;
    }
};

// A source string resolves to real unless it is exactly "mock". Missing key =>
// default real (the safe full-activation default on the paper path).
inline bool source_is_real(const std::string& body, const std::string& key) {
    return bridge::json_get_string(body, key, "real") != "mock";
}

// Read the layer enable + source states from controls.json. Missing/malformed
// file => all layers ON and source real. Safety has neither axis and never
// appears here. The source keys are distinct from the enable keys
// (council_source vs council) so the flat JSON reader cannot confuse them.
inline LayerToggles read_layer_toggles(const std::string& path) {
    LayerToggles t;  // defaults: all ON, source real
    std::ifstream in(path);
    if (!in) return t;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return t;
    t.adaptive = bridge::json_get_bool(body, "adaptive", true);
    t.council = bridge::json_get_bool(body, "council", true);
    t.dnn_advisory = bridge::json_get_bool(body, "dnn_advisory", true);
    t.whale = bridge::json_get_bool(body, "whale", true);
    t.council_real = source_is_real(body, "council_source");
    t.dnn_advisory_real = source_is_real(body, "dnn_advisory_source");
    t.whale_real = source_is_real(body, "whale_source");
    return t;
}

// Whether an ensemble factor participates under the ENABLE axis. The native
// rule_based factor and the (separately gated) rl_advisory factor are never
// gated here: a layer toggle removes an advisory input, never the native signal
// or safety. The RiskGate still evaluates every order regardless.
inline bool factor_enabled(const std::string& factor, const LayerToggles& t) {
    if (factor == "llm_primary" || factor == "llm_secondary" ||
        factor == "llm_tertiary")
        return t.council;
    if (factor == "dnn_advisory") return t.dnn_advisory;
    if (factor == "whale_signal") return t.whale;
    return true;  // rule_based, rl_advisory, and anything else: always on
}

// Whether an enabled advisory factor should use its REAL source (the bridge) vs
// the deterministic mock. Only meaningful for the three bridge-backed advisory
// layers. rule_based and rl_advisory have no mock-vs-real axis (rule_based is
// always native C++; rl_advisory is gated separately), so they report real.
inline bool factor_source_real(const std::string& factor, const LayerToggles& t) {
    if (factor == "llm_primary" || factor == "llm_secondary" ||
        factor == "llm_tertiary")
        return t.council_real;
    if (factor == "dnn_advisory") return t.dnn_advisory_real;
    if (factor == "whale_signal") return t.whale_real;
    return true;
}

// Three-state label for a toggleable layer: off / on-mock / on-real.
inline const char* layer_state(bool enabled, bool real) {
    if (!enabled) return "off";
    return real ? "on-real" : "on-mock";
}

}  // namespace mal::core
