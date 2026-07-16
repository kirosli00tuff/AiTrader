// Adaptive real-time layer, engine side. The asymmetry, asserted.
//
// The claim this file exists to defend: a live event can make the engine more
// cautious, and cannot make it more aggressive. The Python side has its own
// tests for its half (tests/test_adaptive_actions.py). This is the second,
// independent half, in a different language, reading from the other side of the
// database. Both would have to be wrong for the guarantee to fail.
#include <string>

#include "config/config.hpp"
#include "core/adaptive_actions.hpp"
#include "core/util.hpp"
#include "test_util.hpp"

using namespace mal::core;

int main() {
    // --- The allowlist: only defensive names parse -------------------------
    maltest::check(parse_defensive_kind("trim").has_value(), "trim parses");
    maltest::check(parse_defensive_kind("exit").has_value(), "exit parses");
    maltest::check(parse_defensive_kind("flag_for_review").has_value(),
                   "flag_for_review parses");

    // THE CENTRAL ASSERTION. These are the two action names that would increase
    // exposure, and the engine has no value to represent either one.
    maltest::check(!parse_defensive_kind("open").has_value(),
                   "'open' does NOT parse: no aggressive action reaches the engine");
    maltest::check(!parse_defensive_kind("increase").has_value(),
                   "'increase' does NOT parse: no aggressive action reaches the engine");
    maltest::check(!is_defensive_action("open"), "'open' is not defensive");
    maltest::check(!is_defensive_action("increase"), "'increase' is not defensive");

    // Allowlist, not denylist: an unknown name is refused by DEFAULT. A future
    // Python version inventing an action, or a corrupted row, gets silence.
    maltest::check(!is_defensive_action("buy"), "unknown action 'buy' refused");
    maltest::check(!is_defensive_action("moon"), "unknown action 'moon' refused");
    maltest::check(!is_defensive_action(""), "empty action refused");
    maltest::check(!is_defensive_action("EXIT"),
                   "case variant refused (the writer emits lowercase; a "
                   "near-miss must not be guessed at)");
    maltest::check(!is_defensive_action("exit; DROP TABLE positions"),
                   "an action name is never interpreted, only matched");

    // --- Flag for review is inert -----------------------------------------
    maltest::check(kind_touches_position(DefensiveKind::Trim),
                   "trim touches the position");
    maltest::check(kind_touches_position(DefensiveKind::Exit),
                   "exit touches the position");
    maltest::check(!kind_touches_position(DefensiveKind::FlagForReview),
                   "flag_for_review changes NO position: notice is not action");

    // A DefensiveAction's default kind is the harmless one, so a value that
    // somehow skipped assignment flags rather than trades.
    DefensiveAction defaulted;
    maltest::check(!kind_touches_position(defaulted.kind),
                   "a default-constructed action touches no position");

    // --- Staleness: old news must not move a position ----------------------
    const long now = mal::util::iso8601_to_epoch("2026-07-16T12:00:00Z");
    maltest::check(now > 0, "test fixture timestamp parses");

    maltest::check(!action_is_stale("2026-07-16T11:58:00Z", now, 300),
                   "a 2-minute-old action is fresh (max age 300s)");
    maltest::check(action_is_stale("2026-07-16T11:50:00Z", now, 300),
                   "a 10-minute-old action is STALE (max age 300s)");
    maltest::check(action_is_stale("2026-07-16T04:00:00Z", now, 300),
                   "an action queued while the engine was down is stale on resume");

    // Unparseable => stale. If we cannot tell how old an instruction is, we do
    // not follow it. This is the safe direction: the failure mode of a bad
    // timestamp is inaction.
    maltest::check(action_is_stale("", now, 300), "empty ts is stale");
    maltest::check(action_is_stale("not-a-timestamp", now, 300),
                   "unparseable ts is stale");

    // Clock skew: a future-dated action is not stale. A queue writer a second
    // ahead of the engine must not have every action silently dropped.
    maltest::check(!action_is_stale("2026-07-16T12:00:30Z", now, 300),
                   "a future-dated action is not stale (clock skew tolerated)");

    // Boundary: exactly at max age is still allowed; one second past is not.
    maltest::check(!action_is_stale("2026-07-16T11:55:00Z", now, 300),
                   "exactly max_age is not yet stale");
    maltest::check(action_is_stale("2026-07-16T11:54:59Z", now, 300),
                   "one second past max_age is stale");

    // --- Config: ships disabled -------------------------------------------
    mal::config::Config cfg;
    maltest::check(!cfg.adaptive_realtime.adaptive_news_feed_enabled,
                   "adaptive_news_feed_enabled defaults FALSE");
    maltest::check(!cfg.adaptive_realtime.adaptive_watchlist_shaping_enabled,
                   "adaptive_watchlist_shaping_enabled defaults FALSE");
    maltest::check(!cfg.adaptive_realtime.adaptive_react_defensive_enabled,
                   "adaptive_react_defensive_enabled defaults FALSE");
    // The shipped config file must agree with the struct defaults. A block that
    // silently enabled the layer would be the worst possible regression.
    auto loaded = mal::config::load_config("config/default_config.yaml");
    maltest::check(!loaded.adaptive_realtime.adaptive_news_feed_enabled,
                   "shipped config: news feed OFF");
    maltest::check(!loaded.adaptive_realtime.adaptive_watchlist_shaping_enabled,
                   "shipped config: watchlist shaping OFF");
    maltest::check(!loaded.adaptive_realtime.adaptive_react_defensive_enabled,
                   "shipped config: defensive react OFF");
    maltest::check(loaded.adaptive_realtime.action_max_age_seconds == 300,
                   "shipped config: action_max_age_seconds parses as 300");
    maltest::check(loaded.adaptive_realtime.adaptive_daily_llm_budget == 20,
                   "shipped config: adaptive budget parses as 20");

    // Parity with adaptive/settings.py::_DEFAULTS. Two sources of truth for the
    // same numbers only stay in step if something checks.
    maltest::check(cfg.adaptive_realtime.poll_interval_seconds == 60,
                   "default parity: poll_interval_seconds 60");
    maltest::check(cfg.adaptive_realtime.max_symbols_per_poll == 30,
                   "default parity: max_symbols_per_poll 30");
    maltest::check(cfg.adaptive_realtime.max_interpretations_per_poll == 3,
                   "default parity: max_interpretations_per_poll 3");
    maltest::check(cfg.adaptive_realtime.action_min_severity == 0.60,
                   "default parity: action_min_severity 0.60");
    maltest::check(cfg.adaptive_realtime.defensive_trim_fraction == 0.50,
                   "default parity: defensive_trim_fraction 0.50");

    // --- Validation --------------------------------------------------------
    maltest::check(mal::config::validate_config(cfg).empty(),
                   "the shipped adaptive defaults validate clean");

    // A trim that closes nothing would be a silent no-op that still logged as
    // applied. A trim that closes more than the position is not a trim.
    {
        auto bad = cfg;
        bad.adaptive_realtime.defensive_trim_fraction = 0.0;
        maltest::check(!mal::config::validate_config(bad).empty(),
                       "a 0.0 trim fraction is refused (a trim must trim)");
        bad.adaptive_realtime.defensive_trim_fraction = 1.5;
        maltest::check(!mal::config::validate_config(bad).empty(),
                       "a >1 trim fraction is refused (that is an over-close)");
    }
    // An unbounded action age means an hours-old headline can move a position
    // after a restart. That is the exact thing the field prevents.
    {
        auto bad = cfg;
        bad.adaptive_realtime.action_max_age_seconds = 0;
        maltest::check(!mal::config::validate_config(bad).empty(),
                       "action_max_age_seconds 0 is refused (never-expires)");
    }
    // A half-configured opt-in must fail LOUDLY at load, not quietly do nothing.
    {
        auto bad = cfg;
        bad.adaptive_realtime.adaptive_react_defensive_enabled = true;
        maltest::check(!mal::config::validate_config(bad).empty(),
                       "defensive react without the news feed is refused");
        auto bad2 = cfg;
        bad2.adaptive_realtime.adaptive_watchlist_shaping_enabled = true;
        maltest::check(!mal::config::validate_config(bad2).empty(),
                       "watchlist shaping without the news feed is refused");
        // ...and the fully-on combination is a VALID config. The layer is off by
        // default, not impossible to turn on.
        auto ok = cfg;
        ok.adaptive_realtime.adaptive_news_feed_enabled = true;
        ok.adaptive_realtime.adaptive_watchlist_shaping_enabled = true;
        ok.adaptive_realtime.adaptive_react_defensive_enabled = true;
        maltest::check(mal::config::validate_config(ok).empty(),
                       "all three flags on is a valid configuration");
    }

    // --- The learning tuner is a DIFFERENT layer ---------------------------
    // Both are called "adaptive". Turning the news layer on must not touch the
    // tuner, and the two config blocks must not bleed into each other.
    {
        auto probe = cfg;
        probe.adaptive_realtime.adaptive_news_feed_enabled = true;
        maltest::check(probe.adaptive.rule_based_weight_floor ==
                           cfg.adaptive.rule_based_weight_floor,
                       "enabling the news layer does not touch the tuner's floor");
    }

    return maltest::report("adaptive_react");
}
