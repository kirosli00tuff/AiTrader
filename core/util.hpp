// Market AI Lab — small shared utilities (time + minimal JSON emission).
#pragma once

#include <map>
#include <string>

namespace mal::util {

// Current UTC time as ISO-8601 (e.g. 2026-06-29T12:34:56Z).
std::string now_iso8601();

// Build a flat JSON object from string->string and string->double maps.
// Values are escaped. Intended for compact structured payloads in the event log
// (not a general-purpose serializer).
std::string to_json(const std::map<std::string, std::string>& str_fields,
                    const std::map<std::string, double>& num_fields = {});

std::string json_escape(const std::string& s);

}  // namespace mal::util
