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

// One currently-open position, or {"", 0}. The trim/exit branch only runs
// against a real open position, so the test has to find one rather than assume.
struct OpenPos {
    std::string symbol;
    double qty = 0.0;
    double avg_price = 0.0;
};

OpenPos first_open(const std::string& db) {
    OpenPos p;
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) return p;
    sqlite3_stmt* st = nullptr;
    if (sqlite3_prepare_v2(h,
            "SELECT symbol, qty, avg_price FROM positions WHERE qty > 0 "
            "ORDER BY symbol LIMIT 1", -1, &st, nullptr) == SQLITE_OK &&
        sqlite3_step(st) == SQLITE_ROW) {
        const unsigned char* s = sqlite3_column_text(st, 0);
        if (s) p.symbol = reinterpret_cast<const char*>(s);
        p.qty = sqlite3_column_double(st, 1);
        p.avg_price = sqlite3_column_double(st, 2);
    }
    sqlite3_finalize(st);
    sqlite3_close(h);
    return p;
}

double qty_of(const std::string& db, const std::string& symbol) {
    double q = -1.0;
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) return q;
    sqlite3_stmt* st = nullptr;
    if (sqlite3_prepare_v2(h, "SELECT qty FROM positions WHERE symbol = ?", -1,
                           &st, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(st, 1, symbol.c_str(), -1, SQLITE_TRANSIENT);
        if (sqlite3_step(st) == SQLITE_ROW) q = sqlite3_column_double(st, 0);
    }
    sqlite3_finalize(st);
    sqlite3_close(h);
    return q;
}

// The most recent trade row for a symbol. A trim must book the CLOSED PORTION
// only, so the test needs qty, price, fee, AND pnl to check the identity rather
// than just the size.
struct TradeRow {
    double qty = -1.0, price = 0.0, fee = 0.0, pnl = 0.0;
    std::string side;
};

TradeRow last_trade(const std::string& db, const std::string& symbol) {
    TradeRow t;
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) return t;
    sqlite3_stmt* st = nullptr;
    if (sqlite3_prepare_v2(h,
            "SELECT qty, price, fee, pnl, side FROM trades WHERE symbol = ? "
            "ORDER BY id DESC LIMIT 1", -1, &st, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(st, 1, symbol.c_str(), -1, SQLITE_TRANSIENT);
        if (sqlite3_step(st) == SQLITE_ROW) {
            t.qty = sqlite3_column_double(st, 0);
            t.price = sqlite3_column_double(st, 1);
            t.fee = sqlite3_column_double(st, 2);
            t.pnl = sqlite3_column_double(st, 3);
            const unsigned char* s = sqlite3_column_text(st, 4);
            if (s) t.side = reinterpret_cast<const char*>(s);
        }
    }
    sqlite3_finalize(st);
    sqlite3_close(h);
    return t;
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

    // --- THE MONEY PATH: a trim against a REAL open position ----------------
    // This is the branch that actually moves money, and it had no coverage at
    // all until now: every other case here returns before touching a position
    // (flag_for_review exits early, aggressive and stale rows are refused, an
    // unknown symbol is a no-op). So the frac/qty/pnl/remaining_qty arithmetic
    // had never once executed in a test. It is the most dangerous code in the
    // layer and it was the least exercised.
    {
        const std::string db = "/tmp/mal_adaptive_engine_trim.db";
        rm_db(db);
        write_controls(dir, true, true);
        OpenPos pos;
        {
            core::Engine e(cfg, synth_opts(db));
            // Run until the synthetic feed actually opens a native position.
            // consume_adaptive_actions runs at the TOP of each iteration, before
            // the bar steps, so queueing after this loop and running one more
            // iteration applies the trim before any bar could close the position
            // out from under it. Deterministic, not a race.
            for (int i = 0; i < 400 && pos.symbol.empty(); ++i) {
                e.run(5);
                pos = first_open(db);
            }
            maltest::check(!pos.symbol.empty(),
                           "the synthetic feed opened a position to trim");
            if (pos.symbol.empty()) return maltest::report("adaptive_engine");

            queue_action(db, now_iso(), pos.symbol, "trim");
            e.run(1);

            const double after = qty_of(db, pos.symbol);
            // defensive_trim_fraction defaults to 0.50.
            maltest::check_near(after, pos.qty * 0.5, 1e-9,
                                "a trim HALVES the open position");
            maltest::check(after > 0.0,
                           "a trim leaves the position OPEN, it is not an exit");
            const TradeRow tr = last_trade(db, pos.symbol);
            maltest::check_near(tr.qty, pos.qty * 0.5, 1e-9,
                                "the trade books the CLOSED PORTION, not the "
                                "whole position");
            maltest::check(tr.side == "sell",
                           "trimming a long books a sell");
            // THE PNL IDENTITY. realized_pnl works off the WHOLE position, so a
            // trim must scale it by frac; booking the full position's pnl on a
            // half close is the mistake this asserts against, and asserting qty
            // alone would not catch it.
            const double expected = (tr.price - pos.avg_price) * tr.qty - tr.fee;
            maltest::check_near(tr.pnl, expected, 1e-6,
                                "pnl is realized on the CLOSED PORTION only "
                                "(price - entry) * closed_qty - fee");
            maltest::check(count_of(adaptive_events(db), "adaptive_defensive") == 1,
                           "the trim is logged as an adaptive_defensive action");

            // ...and a follow-up exit closes the remainder, so a trimmed
            // position is left in a coherent state rather than a stuck one.
            queue_action(db, now_iso(), pos.symbol, "exit");
            e.run(1);
            maltest::check_near(qty_of(db, pos.symbol), 0.0, 1e-9,
                               "an exit after a trim closes the remainder");
        }
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
