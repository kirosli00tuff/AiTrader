// Market AI Lab — small shared utilities (time + minimal JSON emission).
#pragma once

#include <ctime>
#include <map>
#include <string>

namespace mal::util {

// Current UTC time as ISO-8601 (e.g. 2026-06-29T12:34:56Z).
std::string now_iso8601();

// Format an explicit UTC epoch-second as ISO-8601. Used by the simulated-clock
// feed modes so generated/replayed bars carry an advancing timestamp (drives the
// per-day trade-cap bucket) independent of wall-clock time.
std::string epoch_to_iso8601(long epoch_seconds);

// Parse an ISO-8601 UTC timestamp (YYYY-MM-DDThh:mm:ssZ) to an epoch second.
// Used by replay so council-cooldown spacing keys off the true historical bar
// time. Returns 0 on a malformed string.
long iso8601_to_epoch(const std::string& ts);

// True if the US equity regular trading session (09:30–16:00 America/New_York,
// Mon–Fri) is open at the given UTC time. Used by the continuous engine loop to
// skip equity ticks when the market is closed (crypto + prediction markets are
// 24/7 and are never gated by this). This is a lightweight approximation: it
// applies a fixed US Eastern offset with a standard US DST window and does NOT
// account for market holidays. Defaults to the current time.
bool us_equity_market_open(std::time_t utc_now = std::time(nullptr));

// True if a NEW equity entry must be refused because it is outside US regular
// trading hours. Entry-only: exits bypass this and always run so an open position
// is never trapped. Crypto is never blocked (returns false for any non-equity
// category, at any hour). `enabled` is cfg.engine.equities_market_hours_only.
// `now` is the SIMULATED epoch under clock_mode simulated and wall-clock
// otherwise, so the decision honors the clock mode. Reused by the engine entry
// path and the tests so the rule lives in one place.
bool equity_entry_blocked_by_market_hours(bool enabled,
                                          const std::string& category,
                                          std::time_t now);

// Build a flat JSON object from string->string and string->double maps.
// Values are escaped. Intended for compact structured payloads in the event log
// (not a general-purpose serializer).
std::string to_json(const std::map<std::string, std::string>& str_fields,
                    const std::map<std::string, double>& num_fields = {});

std::string json_escape(const std::string& s);

}  // namespace mal::util
