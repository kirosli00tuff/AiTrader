// The transport reports the outcome it MEASURED, never a generic cause.
//
// Before 2026-07-25 `http_post_json` collapsed four unrelated outcomes into one
// std::nullopt, and the discovery collector named all four "bridge
// unreachable". It was false for three of them and, as the diagnostic proved,
// for the one that actually fired 44 times: a funnel that legitimately ran past
// a 60 s per-receive timeout while the bridge was healthy and answered 30 s
// later.
//
// These tests bind a loopback listener on an ephemeral port and make it behave
// badly on purpose. No production port, no database, nothing beyond 127.0.0.1.
#include "core/bridge_client.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <functional>
#include <set>
#include <string>
#include <thread>

#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

namespace {

// A one-shot loopback server. `behave` receives the accepted fd and decides what
// (if anything) to answer, which is how each outcome is provoked deliberately.
class OneShotServer {
public:
    explicit OneShotServer(std::function<void(int)> behave)
        : behave_(std::move(behave)) {
        fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
        int yes = 1;
        ::setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);  // loopback only
        addr.sin_port = 0;                              // ephemeral
        ::bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
        socklen_t len = sizeof(addr);
        ::getsockname(fd_, reinterpret_cast<sockaddr*>(&addr), &len);
        port_ = ntohs(addr.sin_port);
        ::listen(fd_, 1);
        thread_ = std::thread([this] {
            int c = ::accept(fd_, nullptr, nullptr);
            if (c >= 0) {
                behave_(c);
                ::close(c);
            }
        });
    }
    ~OneShotServer() {
        ::shutdown(fd_, SHUT_RDWR);
        ::close(fd_);
        if (thread_.joinable()) thread_.join();
    }
    int port() const { return port_; }

private:
    int fd_ = -1;
    int port_ = 0;
    std::function<void(int)> behave_;
    std::thread thread_;
};

void drain_request(int c) {
    char buf[2048];
    ::recv(c, buf, sizeof(buf), 0);
}

void send_all(int c, const std::string& s) {
    ::send(c, s.data(), s.size(), MSG_NOSIGNAL);
}

// Find a port nothing is listening on, so connect() is genuinely refused.
int closed_port() {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = 0;
    ::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    socklen_t len = sizeof(addr);
    ::getsockname(fd, reinterpret_cast<sockaddr*>(&addr), &len);
    int p = ntohs(addr.sin_port);
    ::close(fd);  // nobody is listening on p now
    return p;
}

}  // namespace

int main() {
    // 1. A refused connect is the ONLY outcome that means unreachable, and it
    //    is the only one whose description may say the word.
    {
        auto r = bridge::http_post("127.0.0.1", closed_port(), "/x", "{}", 1000);
        check(!r.ok(), "a refused connect is not ok");
        check(r.outcome == bridge::HttpOutcome::kConnectFailed,
              "a refused connect reports kConnectFailed");
        check(r.label() == "connect_failed", "label is connect_failed");
        check(r.describe().find("unreachable") != std::string::npos,
              "only a failed connect describes itself as unreachable");
    }

    // 2. A SLOW but healthy server is a timeout, NOT unreachable. This is the
    //    2026-07-25 defect in one assertion: the funnel was fine and the
    //    deadline was wrong, and the old code called that "bridge unreachable".
    {
        OneShotServer srv([](int c) {
            drain_request(c);
            std::this_thread::sleep_for(std::chrono::milliseconds(1500));
            send_all(c, "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}");
        });
        auto r = bridge::http_post("127.0.0.1", srv.port(), "/slow", "{}", 300);
        check(!r.ok(), "a call that outran its deadline is not ok");
        check(r.outcome == bridge::HttpOutcome::kTimedOut,
              "a slow answer reports kTimedOut, never kConnectFailed");
        check(r.label() == "timed_out", "label is timed_out");
        check(r.describe().find("unreachable") == std::string::npos,
              "a timeout NEVER describes the bridge as unreachable");
        check(r.describe().find("deadline") != std::string::npos,
              "a timeout names the deadline it missed");
        check(r.elapsed_ms >= 250, "a timeout reports how long it waited");
    }

    // 3. THE DEADLINE IS THE ONLY THING THAT DECIDES. The same slow shape,
    //    given enough budget, answers normally. A 90-second funnel must not be
    //    a transport failure.
    {
        OneShotServer srv([](int c) {
            drain_request(c);
            std::this_thread::sleep_for(std::chrono::milliseconds(600));
            send_all(c, "HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\n"
                        "{\"status\":\"ok\"}");
        });
        auto r = bridge::http_post("127.0.0.1", srv.port(), "/slow", "{}", 5000);
        check(r.ok(), "a slow but complete answer inside the deadline is ok");
        check(bridge::json_get_string(r.body, "status", "") == "ok",
              "the slow answer's body is returned intact");
        check(r.elapsed_ms >= 500, "the wait is measured, not assumed");
    }

    // 4. A non-200 is an http_error carrying the status, not "unreachable".
    {
        OneShotServer srv([](int c) {
            drain_request(c);
            send_all(c, "HTTP/1.1 500 Internal Server Error\r\n"
                        "Content-Length: 11\r\n\r\n{\"error\":1}");
        });
        auto r = bridge::http_post("127.0.0.1", srv.port(), "/boom", "{}", 2000);
        check(!r.ok(), "a 500 is not ok");
        check(r.outcome == bridge::HttpOutcome::kHttpError,
              "a complete non-200 reports kHttpError");
        check(r.status == 500, "the status code is carried, not discarded");
        check(r.describe().find("500") != std::string::npos,
              "the description names the status the server actually sent");
        check(r.describe().find("unreachable") == std::string::npos,
              "an answering server is never described as unreachable");
    }

    // 5. A peer that closes mid-response is incomplete, and is again its own
    //    outcome rather than a fourth thing called "unreachable".
    {
        OneShotServer srv([](int c) {
            drain_request(c);
            send_all(c, "HTTP/1.1 200 OK\r\nContent-Len");  // truncated headers
        });
        auto r = bridge::http_post("127.0.0.1", srv.port(), "/cut", "{}", 2000);
        check(!r.ok(), "a truncated response is not ok");
        check(r.outcome == bridge::HttpOutcome::kIncomplete,
              "a peer that closed early reports kIncomplete");
        check(r.describe().find("unreachable") == std::string::npos,
              "an incomplete response is not unreachable either");
    }

    // 6. THE FOUR OUTCOMES ARE DISTINGUISHABLE. This is the mutation guard: a
    //    revert to a single std::nullopt collapses these labels to one value
    //    and this assertion fails.
    {
        std::set<std::string> labels;
        {
            auto r = bridge::http_post("127.0.0.1", closed_port(), "/x", "{}", 500);
            labels.insert(r.label());
        }
        {
            OneShotServer srv([](int c) {
                drain_request(c);
                std::this_thread::sleep_for(std::chrono::milliseconds(900));
            });
            auto r = bridge::http_post("127.0.0.1", srv.port(), "/x", "{}", 200);
            labels.insert(r.label());
        }
        {
            OneShotServer srv([](int c) {
                drain_request(c);
                send_all(c, "HTTP/1.1 503 Busy\r\nContent-Length: 2\r\n\r\n{}");
            });
            auto r = bridge::http_post("127.0.0.1", srv.port(), "/x", "{}", 2000);
            labels.insert(r.label());
        }
        {
            OneShotServer srv([](int c) { drain_request(c); });  // close, no data
            auto r = bridge::http_post("127.0.0.1", srv.port(), "/x", "{}", 2000);
            labels.insert(r.label());
        }
        check(labels.size() == 4,
              "four distinct failure modes report four distinct labels");
        check(labels.count("connect_failed") && labels.count("timed_out") &&
                  labels.count("http_error") &&
                  labels.count("incomplete_response"),
              "each label is the one the transport measured");
    }

    // 7. The compatibility shim still returns just a body, so untouched callers
    //    keep working.
    {
        OneShotServer srv([](int c) {
            drain_request(c);
            send_all(c, "HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\n"
                        "{\"status\":\"ok\"}");
        });
        auto body = bridge::http_post_json("127.0.0.1", srv.port(), "/x", "{}",
                                           2000);
        check(body.has_value(), "the shim returns a body on success");
        check(bridge::json_get_string(*body, "status", "") == "ok",
              "the shim's body is the response body");
    }

    return report("bridge_transport");
}
