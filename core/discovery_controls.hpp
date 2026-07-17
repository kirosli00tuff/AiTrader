// Runtime discovery settings read from the GUI control file controls.json.
//
// WHY THIS EXISTS. The engine read cfg_.discovery.discovery_enabled directly,
// which made the GUI's discovery toggle COSMETIC on the C++ side: the operator
// flipped it, the API wrote controls.json, discovery/settings.py honored it, and
// the engine went on reading the config default (false). So the engine never
// merged a discovered symbol into the traded universe, no matter what the funnel
// found. This is the identical defect core/adaptive_controls.hpp was written to
// fix for the react layer, and its comment names discovery as the original case.
// Discovery never got the same fix. This is that fix, in the same shape as
// core/layer_toggles.hpp, core/operator_controls.hpp, and adaptive_controls.hpp.
//
// DEFAULT POSTURE IS OFF, matching adaptive_controls.hpp and inverted from
// layer_toggles.hpp. A missing or malformed controls.json means all LAYERS on
// there (a broken file must not silently blind the ensemble). Here it means off,
// seeded from config, which ships false. The asymmetry is the point: a broken
// file must never START a spender. Unreadable means off.
//
// Cadence and cost only. Nothing here can weaken a Level-1 limit: a discovered
// symbol is judged by the same RiskGate, the same warm gate, and the same
// strategy as a configured one, with no special case anywhere.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "config/config.hpp"
#include "core/bridge_client.hpp"  // bridge::json_get_bool

namespace mal::core {

// How often the engine ASKS whether a pass is due. This is not the cadence: the
// cadence lives in discovery/run.py's due(), the single authority the engine,
// the maintenance job, and the CLI all share, so the hourly interval and the
// equities US-hours rule are never written twice in two languages.
//
// An ask is one cheap indexed SQLite read over the bridge, so asking often costs
// nothing and buys two things: a pass that comes due mid-interval starts within
// five minutes instead of waiting out a full hour of phase drift, and an
// operator who just flipped the toggle sees the layer run promptly rather than
// wondering whether it is working, which is exactly the complaint that produced
// this file.
inline constexpr long kDiscoveryTriggerIntervalSeconds = 300;

struct DiscoveryRuntime {
    bool enabled = false;

    bool operator==(const DiscoveryRuntime& o) const {
        return enabled == o.enabled;
    }
};

// Seed from config, then let controls.json override. Precedence matches
// discovery/settings.py exactly (the operator's control file wins when it
// carries the key, else config), so the C++ engine and the Python funnel resolve
// the SAME flag from the SAME file and cannot disagree about whether discovery
// is on. That agreement is the entire point: they disagreed before, and the
// disagreement was invisible.
//
// The JSON reader is flat (it finds a key anywhere in the body), which is how
// read_layer_toggles already reads its nested "layers" object. discovery_enabled
// is unique in controls.json, so it cannot collide with another block's key.
inline DiscoveryRuntime read_discovery_controls(
    const std::string& path, const config::DiscoveryConfig& cfg) {
    DiscoveryRuntime d;
    d.enabled = cfg.discovery_enabled;  // config first: what the engine launched with
    std::ifstream in(path);
    if (!in) return d;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return d;
    d.enabled = bridge::json_get_bool(body, "discovery_enabled", d.enabled);
    return d;
}

}  // namespace mal::core
