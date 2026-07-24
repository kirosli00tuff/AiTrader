// EXIT STATE MUST SURVIVE A RESTART (2026-07-23).
//
// The stranded-position defect: open_positions_ lived only in memory,
// populated only at entry, so a restart left every open position invisible —
// not evaluated, not exited, silent. This guard proves the fix both ways:
//
//   1. RESTART MANAGES. An engine constructed against a DB holding an open
//      position with recorded exit state (durable columns for one position,
//      only a trade_entry event for the other, the backfill path) fires the
//      stop on the first closed bar that breaches it.
//   2. UNMANAGEABLE IS LOUD. A position whose venue no longer exists, and one
//      whose exit state is unrecoverable, each raise the critical
//      position_unmanageable condition, are NOT silently managed (no exit
//      fires) and are NOT silently dropped (the row survives untouched).
//
// Mutation-tested with file-copy rollback: reverting the rehydration call
// fails scenario 1; reverting the loud condition fails scenario 2.
#include <sqlite3.h>

#include <cstdio>
#include <string>

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

long long count_events(storage::Storage& s, const std::string& kind,
                       const std::string& severity = "") {
    std::string sql = "SELECT COUNT(*) FROM events WHERE kind='" + kind + "'";
    if (!severity.empty()) sql += " AND severity='" + severity + "'";
    sqlite3_stmt* st = nullptr;
    long long n = 0;
    if (sqlite3_prepare_v2(s.handle(), sql.c_str(), -1, &st, nullptr) ==
        SQLITE_OK) {
        if (sqlite3_step(st) == SQLITE_ROW) n = sqlite3_column_int64(st, 0);
    }
    if (st) sqlite3_finalize(st);
    return n;
}

double position_stop(storage::Storage& s, const std::string& symbol) {
    sqlite3_stmt* st = nullptr;
    double v = -1.0;
    const std::string sql =
        "SELECT COALESCE(stop_price, -1.0) FROM positions WHERE symbol='" +
        symbol + "'";
    if (sqlite3_prepare_v2(s.handle(), sql.c_str(), -1, &st, nullptr) ==
        SQLITE_OK) {
        if (sqlite3_step(st) == SQLITE_ROW) v = sqlite3_column_double(st, 0);
    }
    if (st) sqlite3_finalize(st);
    return v;
}

// Seed `n` replay bars whose lows breach a stop at 95 (long entry 100).
void seed_breaching_bars(storage::Storage& s, const std::string& sym,
                         const std::string& tf, int n) {
    for (int i = 0; i < n; ++i) {
        std::string ts = util::epoch_to_iso8601(1767571200L + i * 300L);
        double px = 90.0 - i * 0.1;
        s.upsert_bar({"alpaca", sym, tf, ts, px, px + 1.0, px - 1.0, px - 0.5,
                      100.0, "backfill"});
    }
}

}  // namespace

int main() {
    config::Config cfg = config::load_config("config/default_config.yaml");
    const std::string& tf = cfg.strategy.bar_timeframe;

    // ---- Scenario 1: a restart manages the position, both recovery paths ----
    const std::string db1 = "/tmp/mal_test_rehydrate.db";
    rm_db(db1);
    {
        storage::Storage s(db1);
        s.init_schema("storage/schema.sql");
        // BTC/USD: exit state in the DURABLE COLUMNS (the post-migration path).
        s.upsert_position("alpaca", "BTC/USD", "BTC/USD", "crypto", "buy", 1.0,
                          100.0, 100.0, "2026-01-01T00:00:00Z");
        s.upsert_position_exit_state("alpaca", "BTC/USD", 95.0, 200.0, 24,
                                     "momentum", 0);
        // ETH/USD: NO durable columns, only the trade_entry event (the
        // backfill path a pre-migration position depends on).
        s.upsert_position("alpaca", "ETH/USD", "ETH/USD", "crypto", "buy", 1.0,
                          100.0, 100.0, "2026-01-01T00:00:00Z");
        s.append_event({"2026-01-01T00:00:00Z", "trade_entry", "alpaca",
                        "ETH/USD", "info", "Native momentum buy ETH/USD",
                        "{\"factor\":\"momentum\",\"stop\":95.0,"
                        "\"target\":200.0,\"strength\":0.7}"});
        seed_breaching_bars(s, "BTC/USD", tf, 5);
        seed_breaching_bars(s, "ETH/USD", tf, 5);
    }
    {
        core::EngineOptions opts;
        opts.db_path = db1;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "replay";
        opts.clock_mode = "simulated";
        core::Engine engine(cfg, opts);
        maltest::check(engine.unmanageable_positions().empty(),
                       "recoverable positions raise no loud condition");
        engine.run(0);  // replay runs every stored bar, then stops

        storage::Storage s(db1);
        maltest::check(s.open_position_rows().empty(),
                       "both rehydrated positions exited (qty 0 in the table)");
        maltest::check(s.count("trades") == 2,
                       "each breached stop booked exactly one exit trade");
        maltest::check(count_events(s, "position_rehydrated") == 2,
                       "rehydration journalled per position");
        maltest::check(count_events(s, "trade_exit") == 2,
                       "the stop fired on the first closed bar after restart");
        maltest::check(position_stop(s, "ETH/USD") == 95.0,
                       "event-recovered exit state was made durable");
    }

    // ---- Scenario 2: unmanageable is LOUD, never silent -------------------
    const std::string db2 = "/tmp/mal_test_rehydrate_loud.db";
    rm_db(db2);
    {
        storage::Storage s(db2);
        s.init_schema("storage/schema.sql");
        // Venue gone: predates the Polymarket removal.
        s.upsert_position("polymarket", "PRES-X", "PRES-X", "politics", "sell",
                          5.0, 0.5, 2.5, "2026-01-01T00:00:00Z");
        // Exit state unrecoverable: no durable columns, no trade_entry event.
        s.upsert_position("alpaca", "BTC/USD", "BTC/USD", "crypto", "buy", 1.0,
                          100.0, 100.0, "2026-01-01T00:00:00Z");
    }
    {
        core::EngineOptions opts;
        opts.db_path = db2;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "flat_random_walk";
        core::Engine engine(cfg, opts);

        const auto& um = engine.unmanageable_positions();
        maltest::check(um.size() == 2,
                       "both unmanageable positions are reported");
        bool venue_named = false, unrecoverable_named = false;
        for (const auto& p : um) {
            if (p.symbol == "PRES-X" &&
                p.reason.find("polymarket") != std::string::npos)
                venue_named = true;
            if (p.symbol == "BTC/USD" &&
                p.reason.find("unrecoverable") != std::string::npos)
                unrecoverable_named = true;
        }
        maltest::check(venue_named,
                       "a dead venue is named as the reason");
        maltest::check(unrecoverable_named,
                       "unrecoverable exit state is named, never invented");

        storage::Storage s(db2);
        maltest::check(count_events(s, "position_unmanageable", "critical") == 2,
                       "the loud condition is a CRITICAL event per position");
        maltest::check(s.count("trades") == 0,
                       "an unmanageable position is never silently managed");
        maltest::check(s.open_position_rows().size() == 2,
                       "an unmanageable position is never silently dropped");
    }

    return maltest::report("position_rehydration");
}
