// Defensive actions from the adaptive real-time layer. The engine's half of the
// asymmetry.
//
// The Python side already refuses to QUEUE anything that is not defensive
// (adaptive/actions.py: DefensiveAction's constructor raises). This header
// refuses to READ anything that is not defensive. The two checks are
// independent, in different languages, on opposite sides of a database, and both
// would have to fail before a live event could increase exposure.
//
// The enforcement is the TYPE, not a check a caller has to remember:
//
//   * DefensiveKind has exactly three values. There is no enumerator for open or
//     increase. An aggressive action is not a value this code can hold.
//   * parse_defensive_kind is an ALLOWLIST returning nullopt for everything else,
//     so an unknown action name from a future Python version, a hand-edited row,
//     or a corrupted string is refused by default rather than passed through.
//   * The engine's consumer takes a DefensiveAction. It cannot be handed an
//     instruction to buy, so it needs no branch that declines to buy.
//
// The aggressive path is therefore not "blocked" here. It is absent. Aggressive
// entry goes through the discovery funnel (Stage A, Stage B, the four levels)
// and the RiskGate, exactly as every other entry does. See CONTEXT.md.
#pragma once

#include <optional>
#include <string>

#include "core/util.hpp"

namespace mal::core {

// The complete set of things a live event may ask the engine to do. All three
// reduce or freeze exposure. Adding an aggressive enumerator here would not be a
// tweak, it would be a redesign, and the compiler makes that visible.
enum class DefensiveKind {
    Trim,           // close part of an open position
    Exit,           // close an open position
    FlagForReview,  // mark for a human; changes no position at all
};

inline const char* defensive_kind_to_string(DefensiveKind k) {
    switch (k) {
        case DefensiveKind::Trim: return "trim";
        case DefensiveKind::Exit: return "exit";
        case DefensiveKind::FlagForReview: return "flag_for_review";
    }
    return "unknown";
}

// One queued request, as read from adaptive_action. Only constructible with a
// DefensiveKind, so a value of this type is defensive by definition.
struct DefensiveAction {
    long long id = 0;
    std::string ts;
    std::string symbol;
    std::string reason;
    DefensiveKind kind = DefensiveKind::FlagForReview;  // safest default
    double severity = 0.0;
    long long event_id = 0;
};

// Parse an action name. ALLOWLIST: nullopt for anything not defensive, including
// "open" and "increase", including an empty string, including a name this build
// has never heard of.
inline std::optional<DefensiveKind> parse_defensive_kind(
    const std::string& action) {
    if (action == "trim") return DefensiveKind::Trim;
    if (action == "exit") return DefensiveKind::Exit;
    if (action == "flag_for_review") return DefensiveKind::FlagForReview;
    return std::nullopt;
}

// Whether the engine may act on this action name at all.
inline bool is_defensive_action(const std::string& action) {
    return parse_defensive_kind(action).has_value();
}

// Whether a queued action is too old to act on.
//
// Stale news must not move a position. If the engine was down for an hour, the
// right answer on resume is to drop what queued up, not to replay it into a
// market that has already repriced. An unparseable timestamp reads as STALE:
// when we cannot tell how old an instruction is, we do not follow it.
inline bool action_is_stale(const std::string& ts, long now_epoch,
                            int max_age_seconds) {
    const long when = util::iso8601_to_epoch(ts);
    if (when <= 0) return true;          // unparseable => refuse
    if (now_epoch < when) return false;  // clock skew: future-dated is not stale
    return (now_epoch - when) > static_cast<long>(max_age_seconds);
}

// Whether a defensive action changes a position at all. FlagForReview is
// deliberately inert: it records that a human should look, and does nothing to
// the book. Separating "act" from "notice" keeps the loudest available response
// to an uncertain read a non-destructive one.
inline bool kind_touches_position(DefensiveKind k) {
    return k == DefensiveKind::Trim || k == DefensiveKind::Exit;
}

}  // namespace mal::core
