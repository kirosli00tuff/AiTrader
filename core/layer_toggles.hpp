// Per-layer enable toggles read from the GUI control file controls.json.
//
// The Controls and Ops pages write per-layer enable states for the four
// toggleable layers (adaptive strategy, LLM council, dnn_advisory, whale). The
// engine reads them each loop iteration, the same control-file pattern as the
// kill request. A layer toggled off drops its factor from the ensemble for that
// iteration. This is ADVISORY ONLY: it removes a signal, it never disables,
// weakens, or bypasses the RiskGate, the kill switch, or any Level-1 limit. The
// static-safety layer has no toggle and is never gated here.
//
// Read defensively: a missing or malformed file means all layers ON, the safe
// default.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "core/bridge_client.hpp"  // bridge::json_get_bool

namespace mal::core {

struct LayerToggles {
    bool adaptive = true;
    bool council = true;
    bool dnn_advisory = true;
    bool whale = true;

    bool operator==(const LayerToggles& o) const {
        return adaptive == o.adaptive && council == o.council &&
               dnn_advisory == o.dnn_advisory && whale == o.whale;
    }
};

// Read the four toggleable layer states from controls.json. Missing/malformed
// file => all layers ON. Safety has no toggle and never appears here.
inline LayerToggles read_layer_toggles(const std::string& path) {
    LayerToggles t;  // defaults: all ON
    std::ifstream in(path);
    if (!in) return t;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return t;
    t.adaptive = bridge::json_get_bool(body, "adaptive", true);
    t.council = bridge::json_get_bool(body, "council", true);
    t.dnn_advisory = bridge::json_get_bool(body, "dnn_advisory", true);
    t.whale = bridge::json_get_bool(body, "whale", true);
    return t;
}

// Whether an ensemble factor participates under these toggles. The native
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

}  // namespace mal::core
