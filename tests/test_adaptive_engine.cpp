// Adaptive defensive actions, through a REAL engine against a real DB.
//
// tests/test_adaptive_react.cpp covers the pure predicates. This covers the part
// that actually moves money: consume_adaptive_actions -> apply_defensive_action,
// which realizes PnL, writes trades, and mutates positions.
//
// It exists because that path originally had NO coverage at all: the consumer
// was called only from run_forever, and every test and the offline probe use the
// finite run(), so a regression in the trim accounting could not have been
// caught by anything.
//
// Offline synthetic feed, temp SQLite DB, temp control dir. No network.
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <string>
#include <vector>

#include <sqlite3.h>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}

core::EngineOptions synth_opts(const std::string& db) {
    core::EngineOptions o;
    o.db_path = db;
    o.schema_path = "storage/schema.sql";
    o.feed_mode = "synthetic_regimes";
    o.clock_mode = "simulated";
    o.native_bar_seconds = 300;
    return o;
}

void write_controls(const std::string& dir, bool feed, bool defensive) {
    std::ofstream f(dir + "/controls.json");
    f << R"({"adaptive_realtime": {"adaptive_news_feed_enabled": )"
      << (feed ? "true" : "false")
      << R"(, "adaptive_react_defensive_enabled": )"
      << (defensive ? "true" : "false") << "}}";
}

// Queue a row the way the Python poller would. A separate connection on purpose:
// this is exactly the cross-process shape the real system has (Python writes,
// the engine reads).
void queue_action(const std::string& db, const std::string& ts,
                  const std::string& symbol, const std::string& action) {
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) return;
    const std::string sql =
        "INSERT INTO adaptive_action(ts,event_id,symbol,action,reason,severity,"
        "source) VALUES('" + ts + "',1,'" + symbol + "','" + action +
        "','test',0.9,'adaptive_react')";
    sqlite3_exec(h, sql.c_str(), nullptr, nullptr, nullptr);
    sqlite3_close(h);
}

std::vector<std::string> adaptive_events(const std::string& db) {
    std::vector<std::string> out;
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) return out;
    sqlite3_stmt* st = nullptr;
    if (sqlite3_prepare_v2(h,
            "SELECT kind FROM events WHERE kind LIKE 'adaptive%' ORDER BY id",
            -1, &st, nullptr) == SQLITE_OK) {
        while (sqlite3_step(st) == SQLITE_ROW) {
            const unsigned char* s = sqlite3_column_text(st, 0);
            if (s) out.emplace_back(reinterpret_cast<const char*>(s));
        }
    }
    sqlite3_finalize(st);
    sqlite3_close(h);
    return out;
}

int count_of(const std::vector<std::string>& v, const std::string& want) {
    int n = 0;
    for (const auto& s : v) if (s == want) ++n;
    return n;
}

std::string now_iso() {
    std::time_t t = std::time(nullptr);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t));
    return buf;
}
}  // namespace

int main() {
    const std::string dir = "/tmp/mal_adaptive_engine_ctl";
    if (std::system(("mkdir -p " + dir).c_str()) != 0) return 1;
    auto cfg = config::load_config("config/default_config.yaml");
    setenv("MAL_CONTROL_DIR", dir.c_str(), 1);

    // --- Flags OFF: the consumer must not touch anything --------------------
    {
        const std::string db = "/tmp/mal_adaptive_engine_off.db";
        rm_db(db);
        write_controls(dir, false, false);
        {
            core::Engine e(cfg, synth_opts(db));
            e.run(5);
            // Queued while the layer is off. Must be ignored entirely.
            queue_action(db, now_iso(), "SPY", "exit");
            e.run(5);
        }
        maltest::check(adaptive_events(db).empty(),
                       "flags off: a queued action is never even looked at");
        rm_db(db);
    }

    // --- Flags ON: the engine consumes, and the asymmetry holds -------------
    {
        const std::string db = "/tmp/mal_adaptive_engine_on.db";
        rm_db(db);
        write_controls(dir, true, true);
        {
            core::Engine e(cfg, synth_opts(db));
            // Run first so the watermark is established, THEN queue. Actions
            // that predate the engine are deliberately never replayed, so a test
            // that queued first would prove nothing.
            e.run(5);

            const std::string ts = now_iso();
            // flag_for_review needs no open position and is always applied.
            queue_action(db, ts, "SPY", "flag_for_review");
            // THE ASYMMETRY, hand-written straight into the queue: the thing
            // Python's DefensiveAction constructor cannot even build. The engine
            // must refuse it on READ.
            queue_action(db, ts, "SPY", "open");
            queue_action(db, ts, "SPY", "increase");
            // Stale: queued while the engine was "down". Must be refused.
            queue_action(db, "2020-01-01T00:00:00Z", "SPY", "exit");
            e.run(5);
        }

        const auto ev = adaptive_events(db);
        maltest::check(count_of(ev, "adaptive_flag_for_review") == 1,
                       "the GUI toggle reaches the engine: a defensive action is "
                       "consumed from controls.json alone (config says false)");
        // Two aggressive rows plus one stale row: three refusals, zero applied.
        maltest::check(count_of(ev, "adaptive_action_refused") == 3,
                       "both aggressive rows and the stale row are refused");
        maltest::check(count_of(ev, "adaptive_defensive") == 0,
                       "no aggressive row ever produced a position change");
        rm_db(db);
    }

    // --- An action is attempted exactly ONCE --------------------------------
    // The watermark advances before the row is judged, so a refused or no-op
    // action must not be retried on the next iteration. A defensive action that
    // silently retried forever would fire the moment its symbol was next bought,
    // which is the opposite of what the event asked for.
    {
        const std::string db = "/tmp/mal_adaptive_engine_once.db";
        rm_db(db);
        write_controls(dir, true, true);
        {
            core::Engine e(cfg, synth_opts(db));
            e.run(5);
            queue_action(db, now_iso(), "NOSUCHSYM", "exit");
            e.run(20);  // many iterations: the action must be seen once only
        }
        maltest::check(count_of(adaptive_events(db), "adaptive_action_noop") == 1,
                       "an action with no open position is attempted once, not "
                       "retried on every iteration");
        rm_db(db);
    }

    std::remove((dir + "/controls.json").c_str());
    return maltest::report("adaptive_engine");
}
