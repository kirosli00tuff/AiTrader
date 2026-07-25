// Market AI Lab — thin RPC client to the Python bridge (JSON over HTTP).
//
// Optional: if the Python bridge is not running, callers fall back to internal
// deterministic mocks so the C++ engine always runs offline. The request/
// response bodies are compact JSON. This deliberately uses only POSIX sockets
// to avoid pulling in an HTTP dependency.
//
// A CALLER MUST BE ABLE TO REPORT THE OUTCOME IT MEASURED (2026-07-25). The
// old helper returned std::optional<std::string> and collapsed four unrelated
// outcomes into one std::nullopt: a failed connect, a failed send, a receive
// that never completed its headers, and a complete response with a non-200
// status. The discovery collector then named all four "bridge unreachable",
// which was false for three of them and, as it turned out, for the one that
// actually fired 44 times. Every diagnosis that started from that event
// started from a wrong statement. `http_post` reports what happened.
#pragma once

#include <optional>
#include <string>

namespace mal::bridge {

// What the transport actually observed. Never inferred, only measured.
enum class HttpOutcome {
    kOk,             // a complete 2xx response with a body
    kConnectFailed,  // resolve/socket/connect failed: nothing was ever sent
    kSendFailed,     // the request could not be written to the socket
    kTimedOut,       // the deadline expired before a complete response arrived
    kIncomplete,     // the peer closed before the response headers completed
    kHttpError,      // a complete response carrying a non-200 status
};

struct HttpResult {
    HttpOutcome outcome = HttpOutcome::kConnectFailed;
    std::string body;      // response body, populated only on kOk
    int status = 0;        // HTTP status line code, on kOk and kHttpError
    long elapsed_ms = 0;   // measured wall clock for the whole attempt
    long deadline_ms = 0;  // the budget the attempt was given
    std::string detail;    // errno name or a short measured note

    bool ok() const { return outcome == HttpOutcome::kOk; }

    // Stable machine-readable label: ok, connect_failed, send_failed,
    // timed_out, incomplete_response, http_error. Safe in a payload field.
    std::string label() const;

    // One operator-facing phrase naming the MEASURED outcome and the numbers
    // behind it. Never says "unreachable" unless connect actually failed.
    std::string describe() const;
};

// POST `body` to http://host:port/path.
//
// `timeout_ms` is a TOTAL deadline for the attempt, not a per-receive timeout.
// The old code set SO_RCVTIMEO once and left it, so a server that dribbled
// bytes could run forever while a server that thought quietly for 61 s read as
// a transport failure. The remaining budget is recomputed before every receive.
HttpResult http_post(const std::string& host, int port, const std::string& path,
                     const std::string& body, int timeout_ms = 1500);

// Backwards-compatible shim for call sites that only need the body and have
// nothing to report. Prefer http_post anywhere the outcome is user-visible.
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
