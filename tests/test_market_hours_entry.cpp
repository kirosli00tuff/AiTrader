// Market-hours entry-gate tests. Outside US regular trading hours an equity takes
// NO new entry (fast tier and council tier both); exits on an open equity position
// still run so a position is never trapped; crypto is unaffected at any hour. The
// check keys off the SIMULATED bar timestamp under clock_mode simulated. Offline,
// deterministic, temp SQLite DB, no network.
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

#include <sqlite3.h>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "core/util.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}

// Off-hours if us_equity_market_open is false at this ISO-8601 bar timestamp.
bool off_hours(const std::string& ts) {
    return !util::us_equity_market_open(
        static_cast<std::time_t>(util::iso8601_to_epoch(ts)));
}
}  // namespace

int main() {
    // ---------- 1. Pure entry-gate helper ----------
    // The rule lives in one named function reused by the engine and the tests.
    const std::time_t in_hours =   // 2026-01-05 15:00Z = 10:00 ET Mon (open)
        static_cast<std::time_t>(util::iso8601_to_epoch("2026-01-05T15:00:00Z"));
    const std::time_t off_hours_t =  // 2026-01-05 02:00Z = 21:00 ET Sun (closed)
        static_cast<std::time_t>(util::iso8601_to_epoch("2026-01-05T02:00:00Z"));
    maltest::check(util::us_equity_market_open(in_hours) &&
                       !util::us_equity_market_open(off_hours_t),
                   "test fixtures: 15:00Z is in RTH, 02:00Z is outside RTH");

    // Equity outside hours with the gate enabled is blocked (no entry).
    maltest::check(
        util::equity_entry_blocked_by_market_hours(true, "equity", off_hours_t),
        "equity entry outside US regular hours is blocked (no entry)");
    // Equity inside hours is allowed.
    maltest::check(
        !util::equity_entry_blocked_by_market_hours(true, "equity", in_hours),
        "equity entry inside US regular hours is allowed");
    // Crypto is never blocked, at any hour.
    for (const char* ts :
         {"2026-01-05T02:00:00Z", "2026-01-05T15:00:00Z", "2026-01-04T09:00:00Z",
          "2026-01-05T23:30:00Z"}) {
        std::time_t t = static_cast<std::time_t>(util::iso8601_to_epoch(ts));
        maltest::check(
            !util::equity_entry_blocked_by_market_hours(true, "crypto", t),
            std::string("crypto entry is never hours-gated at ") + ts);
    }
    // The flag off leaves equities ungated (no behavior change when disabled).
    maltest::check(
        !util::equity_entry_blocked_by_market_hours(false, "equity", off_hours_t),
        "flag off leaves equity entries ungated");
    // Simulated time is honored: the decision follows the PASSED timestamp, so an
    // offline simulated run gates by simulated bar time, not the wall clock.
    maltest::check(
        util::equity_entry_blocked_by_market_hours(true, "equity", off_hours_t) &&
            !util::equity_entry_blocked_by_market_hours(true, "equity", in_hours),
        "gate decision follows the supplied (simulated) timestamp");

    config::Config cfg = config::load_config("config/default_config.yaml");
    const std::string tf = cfg.strategy.bar_timeframe;

    // ---------- 2. Engine end-to-end: exit outside hours still executes ----------
    // A crafted SPY replay: a decline builds the trend (fast EMA below slow, ADX
    // up), a rise crosses fast above slow and fires a momentum long DURING US
    // hours, a plateau holds it (wide ATR keeps the target far), then a crash bar
    // TIMESTAMPED AFTER THE CLOSE hits the stop. The strategy is pure on OHLCV and
    // ignores timestamps, so the entry lands in-hours and the stop-loss exit lands
    // off-hours. This proves an equity exit on an open position outside hours still
    // executes (the position is never trapped) while the entry itself was allowed.
    {
        const std::string db = "/tmp/mal_test_mh_replay.db";
        rm_db(db);
        std::vector<double> px;
        for (int i = 0; i < 110; ++i) px.push_back(150.0 - i * 0.4);  // decline
        double last = px.back();
        for (int i = 0; i < 28; ++i) { last += 0.9; px.push_back(last); }  // rise
        double plateau = last;
        for (int i = 0; i < 12; ++i) px.push_back(plateau);  // hold (no stop/target)
        px.push_back(plateau - 30.0);                        // crash -> stop hit
        const int n = static_cast<int>(px.size());
        // In-hours slots: base 2026-01-05T14:30Z (RTH open EST), cycle days so all
        // warmup + entry bars fall inside a US session (well before 21:00Z close).
        auto in_ts = [](int idx) {
            long base = 1767623400L;  // 2026-01-05T14:30:00Z
            return util::epoch_to_iso8601(base + (idx / 60) * 86400L +
                                          (idx % 60) * 300L);
        };
        // Crash bar: 2026-01-07T21:30:00Z = 16:30 ET, after the close AND later than
        // every in-hours bar, so the chronological replay keeps it last.
        const std::string crash_ts = util::epoch_to_iso8601(1767821400L);
        {
            storage::Storage s(db);
            s.init_schema("storage/schema.sql");
            for (int i = 0; i < n; ++i) {
                double c = px[i], o = (i ? px[i - 1] : c);
                double hi = std::max(o, c) + 3.0;   // wide range => large ATR =>
                double lo = std::min(o, c) - 3.0;   // target sits far from entry
                std::string ts = (i == n - 1) ? crash_ts : in_ts(i);
                if (i == n - 1) lo = c - 1.0;        // crash low well below the stop
                s.upsert_bar({"alpaca", "SPY", tf, ts, o, hi, lo, c, 5000.0});
            }
        }
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "replay";
        opts.clock_mode = "simulated";
        core::Engine e(cfg, opts);
        e.run(n + 5);

        sqlite3* h = e.storage().handle();
        sqlite3_stmt* st = nullptr;
        int opens_in = 0, opens_off = 0, exits_off = 0, blocked = 0;
        sqlite3_prepare_v2(
            h, "SELECT ts,outcome FROM trades WHERE symbol='SPY' ORDER BY id", -1,
            &st, nullptr);
        while (sqlite3_step(st) == SQLITE_ROW) {
            std::string ts = reinterpret_cast<const char*>(sqlite3_column_text(st, 0));
            std::string out = reinterpret_cast<const char*>(sqlite3_column_text(st, 1));
            bool off = off_hours(ts);
            if (out == "open") { if (off) ++opens_off; else ++opens_in; }
            if (out == "win" || out == "loss") { if (off) ++exits_off; }
        }
        sqlite3_finalize(st);
        sqlite3_prepare_v2(h,
                           "SELECT COUNT(*) FROM events WHERE "
                           "kind='market_hours_entry' AND symbol='SPY'",
                           -1, &st, nullptr);
        if (sqlite3_step(st) == SQLITE_ROW) blocked = sqlite3_column_int(st, 0);
        sqlite3_finalize(st);

        maltest::check(opens_in == 1 && opens_off == 0,
                       "crafted equity entry executed IN US hours (allowed)");
        maltest::check(blocked == 0,
                       "the in-hours equity entry was not hours-blocked");
        maltest::check(exits_off >= 1,
                       "equity exit on the open position executed OUTSIDE hours "
                       "(position never trapped)");
        rm_db(db);
    }

    // ---------- 3. Synthetic end-to-end: no equity entry outside hours ----------
    // A deterministic simulated run spans many days and hours. With the gate on, no
    // equity ENTRY fires outside US regular hours (the reported bug), the gate logs
    // one market_hours_entry per off-hours equity signal, and crypto keeps entering
    // 24/7. Under clock_mode simulated the check keys off the simulated bar time.
    {
        const std::string db = "/tmp/mal_test_mh_synth.db";
        rm_db(db);
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "synthetic_regimes";
        opts.clock_mode = "simulated";
        core::Engine e(cfg, opts);
        e.run(6000);

        sqlite3* h = e.storage().handle();
        sqlite3_stmt* st = nullptr;
        int eq_open = 0, eq_open_off = 0, cr_open_off = 0;
        sqlite3_prepare_v2(
            h, "SELECT ts,category,outcome FROM trades WHERE outcome='open'", -1,
            &st, nullptr);
        while (sqlite3_step(st) == SQLITE_ROW) {
            std::string ts = reinterpret_cast<const char*>(sqlite3_column_text(st, 0));
            std::string cat = reinterpret_cast<const char*>(sqlite3_column_text(st, 1));
            bool off = off_hours(ts);
            if (cat == "equity") { ++eq_open; if (off) ++eq_open_off; }
            if (cat == "crypto" && off) ++cr_open_off;
        }
        sqlite3_finalize(st);

        int mh = 0, mh_offhours = 0, mh_crypto = 0;
        sqlite3_prepare_v2(
            h, "SELECT ts,symbol FROM events WHERE kind='market_hours_entry'", -1,
            &st, nullptr);
        while (sqlite3_step(st) == SQLITE_ROW) {
            std::string ts = reinterpret_cast<const char*>(sqlite3_column_text(st, 0));
            std::string sym = reinterpret_cast<const char*>(sqlite3_column_text(st, 1));
            ++mh;
            if (off_hours(ts)) ++mh_offhours;
            if (sym.find('/') != std::string::npos) ++mh_crypto;  // crypto pairs
        }
        sqlite3_finalize(st);

        maltest::check(eq_open > 0 && eq_open_off == 0,
                       "no equity entry fires outside US regular hours (the fix)");
        maltest::check(cr_open_off > 0,
                       "crypto entries fire outside US hours (unaffected, 24/7)");
        maltest::check(mh > 0 && mh == mh_offhours && mh_crypto == 0,
                       "every market_hours_entry skip is an equity at an off-hours "
                       "timestamp (clean log, no crypto, no spam)");
        rm_db(db);
    }

    return maltest::report("market_hours_entry");
}
