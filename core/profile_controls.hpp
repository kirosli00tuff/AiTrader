// Runtime lever for the strategy profile (2026-07-23).
//
// strategy.profile selected the whole active_quant overlay, yet its only
// lever was editing config/default_config.yaml, so the operator's runtime
// choice lived as an edit to the SHIPPED default and was eventually swept
// into a commit (440fda8). This is exactly the pattern CONTEXT.md names: a
// runtime flag needs a runtime lever, or the operator edits the shipped
// default.
//
// The lever is the flat controls.json key "strategy_profile" (valid values
// "swing" and "active_quant"), read ONCE at startup by core/main.cpp and
// applied as config::load_config's profile override. It is deliberately NOT
// re-read per iteration: the profile decides the whitelist, the indicator
// stack, and the warm thresholds, so a mid-run switch would re-derive the
// world under a running loop. A change takes effect on the next engine
// start, and the startup banner prints the resolved profile WITH ITS SOURCE
// so the operator sees which authority decided.
//
// FALLBACK DIRECTION (decided, see CONTEXT.md): unreadable or absent means
// NO OVERRIDE, config decides. An unreadable file cannot switch a RUNNING
// strategy (startup-only resolution); the only exposure is across a restart,
// which the loud source-labelled banner and the stop/start attribution make
// visible. An invalid value is refused, never guessed.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "core/bridge_client.hpp"

namespace mal::core {

inline bool profile_value_valid(const std::string& p) {
    return p == "swing" || p == "active_quant";
}

// The profile override from controls.json, or "" when the file is missing,
// unreadable, the key absent, or the value invalid ("" = config decides).
inline std::string resolve_profile_override(const std::string& controls_path) {
    std::ifstream in(controls_path);
    if (!in) return "";
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    const std::string p =
        bridge::json_get_string(body, "strategy_profile", "");
    return profile_value_valid(p) ? p : "";
}

}  // namespace mal::core
