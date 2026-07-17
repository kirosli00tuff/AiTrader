// Runtime sleeve enables read from the GUI control file controls.json.
//
// WHY THIS EXISTS. The engine read cfg_.sleeves.research_satellite_enabled
// directly, which comes from default_config.yaml and ships false, while the GUI
// sleeve toggle writes .control/controls.json. So the toggle was COSMETIC: the
// operator flipped it, the API validated and audited the write, and the engine
// went on reading config and never ran the sleeve. api_server/controls.py said
// so outright ("The engine reads sleeve enable from config at startup ... engine
// consumption is a documented follow-up") and the GUI panel admitted it to the
// operator's face ("the toggle here records intent"). This is that follow-up.
//
// It is the same defect core/discovery_controls.hpp and core/adaptive_controls.hpp
// were written to fix, and this reader has the same shape as those and as
// core/layer_toggles.hpp and core/operator_controls.hpp.
//
// DEFAULT POSTURE IS OFF, matching discovery_controls.hpp and inverted from
// layer_toggles.hpp. A missing or malformed controls.json means all LAYERS on
// there (a broken file must not silently blind the ensemble). Here it means off,
// seeded from config, which ships false. The asymmetry is the point: a broken
// file must never allocate capital to a sleeve nobody turned on.
//
// Allocation only. Nothing here can weaken a Level-1 limit. An enabled sleeve is
// still bounded by the hard cap (target + drift band, checked in
// core/sleeves.hpp satellite_has_room), and the RiskGate still judges every order
// in both sleeves exactly as before.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "config/config.hpp"
#include "core/bridge_client.hpp"  // bridge::json_get_bool

namespace mal::core {

struct SleeveRuntime {
    bool research_satellite = false;

    bool operator==(const SleeveRuntime& o) const {
        return research_satellite == o.research_satellite;
    }
};

// Seed from config, then let controls.json override. Precedence matches every
// other runtime control (discovery, adaptive, layers, feed/clock): the
// operator's control file wins when it carries the key, else config.
//
// quant_core is deliberately NOT read. It is the core sleeve and no engine path
// gates on it, so reading a toggle the engine cannot honor would be the same
// cosmetic-control bug this file exists to fix, one level down.
//
// The JSON reader is flat, and find_value_start matches "research_satellite"
// with its closing quote, so it cannot collide with research_satellite_enabled
// or research_satellite_target_pct.
inline SleeveRuntime read_sleeve_controls(const std::string& path,
                                          const config::SleeveConfig& cfg) {
    SleeveRuntime s;
    s.research_satellite = cfg.research_satellite_enabled;  // config first
    std::ifstream in(path);
    if (!in) return s;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return s;
    s.research_satellite =
        bridge::json_get_bool(body, "research_satellite", s.research_satellite);
    return s;
}

}  // namespace mal::core
