// Market AI Lab — thin RPC client to the Python bridge (JSON over HTTP).
//
// Optional: if the Python bridge is not running, callers fall back to internal
// deterministic mocks so the C++ engine always runs offline. The request/
// response bodies are compact JSON. This deliberately uses only POSIX sockets
// to avoid pulling in an HTTP dependency.
#pragma once

#include <optional>
#include <string>

namespace mal::bridge {

// POST `body` to http://host:port/path and return the response body, or
// std::nullopt on any failure (connection refused, timeout, non-200).
std::optional<std::string> http_post_json(const std::string& host, int port,
                                          const std::string& path,
                                          const std::string& body,
                                          int timeout_ms = 1500);

// Extract a numeric field from a flat JSON object (no nesting). Returns default
// if not found. Tiny helper so the engine can read RPC results without a full
// JSON parser.
double json_get_number(const std::string& json, const std::string& key,
                       double def = 0.0);
std::string json_get_string(const std::string& json, const std::string& key,
                            const std::string& def = "");
// Read a boolean field from a flat JSON object. Accepts true/false and 1/0.
bool json_get_bool(const std::string& json, const std::string& key,
                   bool def = false);

}  // namespace mal::bridge
