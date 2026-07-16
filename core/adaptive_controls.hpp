// Runtime adaptive-layer settings read from the GUI control file controls.json.
//
// WHY THIS EXISTS. The engine used to read cfg_.adaptive_realtime.* directly,
// which made the GUI's react toggle COSMETIC: the operator flipped it, the API
// wrote controls.json, the Python poller honored it and queued defensive
// actions, and the engine went on reading the config default (false) and never
// consumed them. Actions piled up unapplied forever. This is the same defect the
// discovery build hit ("the flags were CONFIG-only, so a GUI toggle would have
// been cosmetic"), so this reader follows the same fix and the same shape as
// core/layer_toggles.hpp and core/operator_controls.hpp.
//
// DEFAULT POSTURE IS INVERTED FROM layer_toggles.hpp, deliberately. A missing or
// malformed controls.json means all LAYERS on there (the safe full-activation
// default: a broken file must not silently blind the ensemble). Here it means
// everything OFF, seeded from config, which ships false. The asymmetry is the
// point: a broken file must never be able to START a spender or hand a live
// event power over a position. Unreadable means off.
//
// Cost and staleness only. Nothing here can weaken a Level-1 limit, and there is
// deliberately no aggressive-entry field to read, because no such path exists.
#pragma once

#include <fstream>
#include <iterator>
#include <string>

#include "config/config.hpp"
#include "core/bridge_client.hpp"  // bridge::json_get_bool / json_get_number

namespace mal::core {

struct AdaptiveRuntime {
    bool news_feed_enabled = false;
    bool watchlist_shaping_enabled = false;
    bool react_defensive_enabled = false;
    int action_max_age_seconds = 300;
    double defensive_trim_fraction = 0.50;

    bool operator==(const AdaptiveRuntime& o) const {
        return news_feed_enabled == o.news_feed_enabled &&
               watchlist_shaping_enabled == o.watchlist_shaping_enabled &&
               react_defensive_enabled == o.react_defensive_enabled &&
               action_max_age_seconds == o.action_max_age_seconds &&
               defensive_trim_fraction == o.defensive_trim_fraction;
    }
};

// Seed from config, then let controls.json override. Precedence matches
// discovery/settings.py and adaptive/settings.py exactly: the operator's control
// file wins when it carries a key, else config, and config ships every flag
// false. So a missing file, an empty file, a malformed file, and a fresh
// checkout all mean the same thing: off.
//
// The JSON reader is flat (it finds a key anywhere in the body), which is how
// read_layer_toggles already reads its nested "layers" object. The adaptive keys
// are long and unique, so they cannot collide with another block's.
inline AdaptiveRuntime read_adaptive_controls(
    const std::string& path, const config::AdaptiveRealtimeConfig& cfg) {
    AdaptiveRuntime a;
    // Config first. These are the values the engine launched with.
    a.news_feed_enabled = cfg.adaptive_news_feed_enabled;
    a.watchlist_shaping_enabled = cfg.adaptive_watchlist_shaping_enabled;
    a.react_defensive_enabled = cfg.adaptive_react_defensive_enabled;
    a.action_max_age_seconds = cfg.action_max_age_seconds;
    a.defensive_trim_fraction = cfg.defensive_trim_fraction;

    std::ifstream in(path);
    if (!in) return a;
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    if (body.empty()) return a;

    a.news_feed_enabled =
        bridge::json_get_bool(body, "adaptive_news_feed_enabled",
                              a.news_feed_enabled);
    a.watchlist_shaping_enabled =
        bridge::json_get_bool(body, "adaptive_watchlist_shaping_enabled",
                              a.watchlist_shaping_enabled);
    a.react_defensive_enabled =
        bridge::json_get_bool(body, "adaptive_react_defensive_enabled",
                              a.react_defensive_enabled);
    a.action_max_age_seconds = static_cast<int>(bridge::json_get_number(
        body, "action_max_age_seconds",
        static_cast<double>(a.action_max_age_seconds)));
    a.defensive_trim_fraction = bridge::json_get_number(
        body, "defensive_trim_fraction", a.defensive_trim_fraction);

    // Re-validate every value read from the file. The API clamps on write, but a
    // hand-edited control file must not be able to widen a bound the config
    // validator would refuse. Both of these are safety-relevant:
    //   * a non-positive max age means "never expires", the exact thing the
    //     field exists to prevent (an hours-old headline moving a position after
    //     a restart);
    //   * a trim fraction outside (0,1] is either a silent no-op that still logs
    //     as applied, or an over-close.
    // An out-of-range value falls back to the CONFIG value, never to a guess.
    if (a.action_max_age_seconds <= 0)
        a.action_max_age_seconds = cfg.action_max_age_seconds;
    if (a.defensive_trim_fraction <= 0.0 || a.defensive_trim_fraction > 1.0)
        a.defensive_trim_fraction = cfg.defensive_trim_fraction;

    // The feed is the MASTER. Shaping and defensive actions are both downstream
    // of a poll, so with the feed off they cannot do anything anyway. Forcing
    // them off here mirrors the API (_adaptive_downstream_off) and the config
    // validator, so a hand-edited file cannot leave the engine consuming actions
    // from a feed that is not running.
    if (!a.news_feed_enabled) {
        a.watchlist_shaping_enabled = false;
        a.react_defensive_enabled = false;
    }
    return a;
}

}  // namespace mal::core
