#include "storage/storage.hpp"

#include <sqlite3.h>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace mal::storage {

namespace {

// Small RAII wrapper around a prepared statement with positional binding.
class Stmt {
public:
    Stmt(sqlite3* db, const std::string& sql) : db_(db) {
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &st_, nullptr) != SQLITE_OK)
            throw std::runtime_error(std::string("prepare failed: ") +
                                     sqlite3_errmsg(db));
    }
    ~Stmt() { if (st_) sqlite3_finalize(st_); }

    Stmt& bind(int i, const std::string& v) {
        sqlite3_bind_text(st_, i, v.c_str(), -1, SQLITE_TRANSIENT);
        return *this;
    }
    Stmt& bind(int i, double v) { sqlite3_bind_double(st_, i, v); return *this; }
    Stmt& bind(int i, int v) { sqlite3_bind_int(st_, i, v); return *this; }
    Stmt& bind_null(int i) { sqlite3_bind_null(st_, i); return *this; }

    void step_done() {
        if (sqlite3_step(st_) != SQLITE_DONE)
            throw std::runtime_error(std::string("step failed: ") +
                                     sqlite3_errmsg(db_));
    }
    sqlite3_stmt* raw() { return st_; }

private:
    sqlite3* db_;
    sqlite3_stmt* st_ = nullptr;
};

}  // namespace

Storage::Storage(const std::string& db_path) {
    if (sqlite3_open(db_path.c_str(), &db_) != SQLITE_OK) {
        std::string msg = db_ ? sqlite3_errmsg(db_) : "unknown";
        if (db_) sqlite3_close(db_);
        throw std::runtime_error("Cannot open DB " + db_path + ": " + msg);
    }
    sqlite3_busy_timeout(db_, 5000);
}

Storage::~Storage() {
    if (db_) sqlite3_close(db_);
}

void Storage::exec(const std::string& sql) {
    char* err = nullptr;
    if (sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &err) != SQLITE_OK) {
        std::string msg = err ? err : "unknown";
        sqlite3_free(err);
        throw std::runtime_error("exec failed: " + msg);
    }
}

void Storage::init_schema(const std::string& schema_sql_path) {
    std::ifstream f(schema_sql_path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot read schema: " + schema_sql_path);
    std::ostringstream ss;
    ss << f.rdbuf();
    exec(ss.str());
    // Additive migrations for DBs created before a column existed. CREATE TABLE
    // IF NOT EXISTS never alters an existing table, so add new columns tolerantly
    // (a duplicate-column error on a fresh DB is expected and ignored). Never a
    // destructive change.
    char* err = nullptr;
    sqlite3_exec(db_, "ALTER TABLE regime_state ADD COLUMN active_factor TEXT",
                 nullptr, nullptr, &err);
    if (err) sqlite3_free(err);
    // Sleeve tag on trades/positions (default quant_core so existing rows read as
    // the systematic core). Tolerant: a duplicate-column error on a fresh DB is
    // expected and ignored.
    const char* migrations[] = {
        "ALTER TABLE trades ADD COLUMN sleeve TEXT DEFAULT 'quant_core'",
        // Trade provenance for the real-fill gates. Existing rows backfill to
        // 'strategy', which is right for any DB predating the adaptive layer.
        // A pre-existing rebalance trim in an old DB also backfills to
        // 'strategy' and stays miscounted: the information to tell them apart
        // was never recorded, so it cannot be recovered retroactively.
        "ALTER TABLE trades ADD COLUMN origin TEXT DEFAULT 'strategy'",
        "ALTER TABLE positions ADD COLUMN sleeve TEXT DEFAULT 'quant_core'",
        // Long-term thesis fields (discovery.long_term_sleeve_enabled, OFF by
        // default). NULL on a thesis from the original council-mapped path.
        "ALTER TABLE research_thesis ADD COLUMN target REAL",
        "ALTER TABLE research_thesis ADD COLUMN invalidation_price REAL",
        "ALTER TABLE research_thesis ADD COLUMN invalidation TEXT",
        "ALTER TABLE research_thesis ADD COLUMN entry_price REAL",
        // Bar provenance (2026-07-18, after the silent walk-substitution
        // outage). Existing rows mark 'unknown', NEVER a guess at real: the
        // information about where their prices came from was not recorded.
        // The one identified contaminated window is marked 'synthetic' by
        // scripts/quarantine_synthetic_bars_20260717.py, from diagnostic
        // evidence, not from here.
        "ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
        // Provenance of the bar each trade executed against. Same posture.
        "ALTER TABLE trades ADD COLUMN bar_source TEXT DEFAULT 'unknown'",
        // Exit state on the position (2026-07-23), so a restart can rehydrate
        // open positions instead of stranding them. NULL on existing rows:
        // "never recorded" is distinct from any value and is never guessed at.
        "ALTER TABLE positions ADD COLUMN stop_price REAL",
        "ALTER TABLE positions ADD COLUMN target_price REAL",
        "ALTER TABLE positions ADD COLUMN time_stop_bars INTEGER",
        "ALTER TABLE positions ADD COLUMN factor TEXT",
        "ALTER TABLE positions ADD COLUMN bars_held INTEGER",
    };
    for (const char* m : migrations) {
        char* e = nullptr;
        sqlite3_exec(db_, m, nullptr, nullptr, &e);
        if (e) sqlite3_free(e);
    }
}

long long Storage::append_event(const EventRow& e) {
    Stmt s(db_,
           "INSERT INTO events(ts,kind,venue,symbol,severity,message,payload_json)"
           " VALUES(?,?,?,?,?,?,?)");
    s.bind(1, e.ts).bind(2, e.kind).bind(3, e.venue).bind(4, e.symbol)
        .bind(5, e.severity).bind(6, e.message).bind(7, e.payload_json);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_trade(const TradeRow& t) {
    Stmt s(db_,
           "INSERT INTO trades(ts,venue,symbol,market,category,side,qty,price,"
           "notional,fee,mode,pnl,outcome,combined_conf,combined_edge,sleeve,"
           "origin,bar_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
    s.bind(1, t.ts).bind(2, t.venue).bind(3, t.symbol).bind(4, t.market)
        .bind(5, t.category).bind(6, t.side).bind(7, t.qty).bind(8, t.price)
        .bind(9, t.notional).bind(10, t.fee).bind(11, t.mode);
    if (t.pnl) s.bind(12, *t.pnl); else s.bind_null(12);
    s.bind(13, t.outcome).bind(14, t.combined_conf).bind(15, t.combined_edge)
        .bind(16, t.sleeve).bind(17, t.origin)
        .bind(18, t.bar_source.empty() ? "unknown" : t.bar_source);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_signal(const SignalRow& sig) {
    Stmt s(db_,
           "INSERT INTO signals(ts,venue,symbol,factor,bias,confidence,edge,"
           "payload_json) VALUES(?,?,?,?,?,?,?,?)");
    s.bind(1, sig.ts).bind(2, sig.venue).bind(3, sig.symbol).bind(4, sig.factor)
        .bind(5, sig.bias).bind(6, sig.confidence).bind(7, sig.edge)
        .bind(8, sig.payload_json);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_model_output(const ModelOutputRow& m) {
    Stmt s(db_,
           "INSERT INTO model_outputs(ts,model,verdict,confidence,edge,weight,"
           "extra_json) VALUES(?,?,?,?,?,?,?)");
    s.bind(1, m.ts).bind(2, m.model).bind(3, m.verdict).bind(4, m.confidence)
        .bind(5, m.edge).bind(6, m.weight).bind(7, m.extra_json);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_blocked(const BlockedRow& b) {
    Stmt s(db_,
           "INSERT INTO blocked_trades(ts,venue,symbol,side,qty,reason,layer)"
           " VALUES(?,?,?,?,?,?,?)");
    s.bind(1, b.ts).bind(2, b.venue).bind(3, b.symbol).bind(4, b.side)
        .bind(5, b.qty).bind(6, b.reason).bind(7, b.layer);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_balance(const BalanceRow& b) {
    Stmt s(db_,
           "INSERT INTO account_balances(ts,venue,equity,cash,realized_pnl,"
           "unrealized_pnl,drawdown_pct) VALUES(?,?,?,?,?,?,?)");
    s.bind(1, b.ts).bind(2, b.venue).bind(3, b.equity).bind(4, b.cash)
        .bind(5, b.realized_pnl).bind(6, b.unrealized_pnl).bind(7, b.drawdown_pct);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_weight_change(const WeightChangeRow& w) {
    Stmt s(db_,
           "INSERT INTO weight_changes(ts,factor,old_weight,new_weight,source,"
           "locked) VALUES(?,?,?,?,?,?)");
    s.bind(1, w.ts).bind(2, w.factor).bind(3, w.old_weight).bind(4, w.new_weight)
        .bind(5, w.source).bind(6, w.locked ? 1 : 0);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

long long Storage::insert_param_history(const ParamHistoryRow& p) {
    Stmt s(db_,
           "INSERT INTO param_history(ts,param,old_value,new_value,source,reason)"
           " VALUES(?,?,?,?,?,?)");
    s.bind(1, p.ts).bind(2, p.param).bind(3, p.old_value).bind(4, p.new_value)
        .bind(5, p.source).bind(6, p.reason);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

void Storage::upsert_venue_state(const std::string& venue,
                                 const std::string& mode, bool live_enabled,
                                 bool kill_switch_tripped,
                                 int consecutive_losses,
                                 const std::string& cooldown_until_ts,
                                 const std::string& updated_ts) {
    Stmt s(db_,
           "INSERT INTO venue_state(venue,mode,live_enabled,kill_switch_tripped,"
           "consecutive_losses,cooldown_until_ts,updated_ts)"
           " VALUES(?,?,?,?,?,?,?)"
           " ON CONFLICT(venue) DO UPDATE SET mode=excluded.mode,"
           " live_enabled=excluded.live_enabled,"
           " kill_switch_tripped=excluded.kill_switch_tripped,"
           " consecutive_losses=excluded.consecutive_losses,"
           " cooldown_until_ts=excluded.cooldown_until_ts,"
           " updated_ts=excluded.updated_ts");
    s.bind(1, venue).bind(2, mode).bind(3, live_enabled ? 1 : 0)
        .bind(4, kill_switch_tripped ? 1 : 0).bind(5, consecutive_losses)
        .bind(6, cooldown_until_ts).bind(7, updated_ts);
    s.step_done();
}

void Storage::set_approval_state(bool live_enabled, bool manual_confirmation,
                                 const std::string& last_checked_ts,
                                 const std::string& readiness_json) {
    Stmt s(db_,
           "INSERT INTO approval_state(id,live_enabled,manual_confirmation,"
           "last_checked_ts,readiness_json) VALUES(1,?,?,?,?)"
           " ON CONFLICT(id) DO UPDATE SET live_enabled=excluded.live_enabled,"
           " manual_confirmation=excluded.manual_confirmation,"
           " last_checked_ts=excluded.last_checked_ts,"
           " readiness_json=excluded.readiness_json");
    s.bind(1, live_enabled ? 1 : 0).bind(2, manual_confirmation ? 1 : 0)
        .bind(3, last_checked_ts).bind(4, readiness_json);
    s.step_done();
}

void Storage::upsert_position(const std::string& venue, const std::string& symbol,
                              const std::string& market,
                              const std::string& category,
                              const std::string& side, double qty,
                              double avg_price, double notional,
                              const std::string& opened_ts,
                              const std::string& sleeve) {
    Stmt s(db_,
           "INSERT INTO positions(venue,symbol,market,category,side,qty,"
           "avg_price,notional,opened_ts,sleeve) VALUES(?,?,?,?,?,?,?,?,?,?)"
           " ON CONFLICT(venue,symbol) DO UPDATE SET qty=excluded.qty,"
           " avg_price=excluded.avg_price, notional=excluded.notional,"
           " side=excluded.side, sleeve=excluded.sleeve");
    s.bind(1, venue).bind(2, symbol).bind(3, market).bind(4, category)
        .bind(5, side).bind(6, qty).bind(7, avg_price).bind(8, notional)
        .bind(9, opened_ts).bind(10, sleeve);
    s.step_done();
}

void Storage::upsert_position_exit_state(const std::string& venue,
                                         const std::string& symbol,
                                         double stop_price, double target_price,
                                         int time_stop_bars,
                                         const std::string& factor,
                                         int bars_held) {
    Stmt s(db_,
           "UPDATE positions SET stop_price=?, target_price=?,"
           " time_stop_bars=?, factor=?, bars_held=?"
           " WHERE venue=? AND symbol=?");
    s.bind(1, stop_price).bind(2, target_price).bind(3, time_stop_bars)
        .bind(4, factor).bind(5, bars_held).bind(6, venue).bind(7, symbol);
    s.step_done();
}

void Storage::update_position_bars_held(const std::string& venue,
                                        const std::string& symbol,
                                        int bars_held) {
    Stmt s(db_,
           "UPDATE positions SET bars_held=? WHERE venue=? AND symbol=?");
    s.bind(1, bars_held).bind(2, venue).bind(3, symbol);
    s.step_done();
}

std::vector<Storage::PositionRow> Storage::open_position_rows() {
    std::vector<PositionRow> rows;
    auto read = [&](const std::string& sql, bool with_exit_state) {
        Stmt s(db_, sql);
        auto col_text = [&](int i) -> std::string {
            const unsigned char* t = sqlite3_column_text(s.raw(), i);
            return t ? reinterpret_cast<const char*>(t) : "";
        };
        while (sqlite3_step(s.raw()) == SQLITE_ROW) {
            PositionRow p;
            p.id = sqlite3_column_int64(s.raw(), 0);
            p.venue = col_text(1);
            p.symbol = col_text(2);
            p.market = col_text(3);
            p.category = col_text(4);
            p.side = col_text(5);
            p.qty = sqlite3_column_double(s.raw(), 6);
            p.avg_price = sqlite3_column_double(s.raw(), 7);
            p.notional = sqlite3_column_double(s.raw(), 8);
            p.opened_ts = col_text(9);
            p.sleeve = col_text(10);
            if (p.sleeve.empty()) p.sleeve = "quant_core";
            if (with_exit_state) {
                // NULL reads as absent, never as 0: "never recorded" must
                // stay distinguishable from a recorded value.
                if (sqlite3_column_type(s.raw(), 11) != SQLITE_NULL)
                    p.stop_price = sqlite3_column_double(s.raw(), 11);
                if (sqlite3_column_type(s.raw(), 12) != SQLITE_NULL)
                    p.target_price = sqlite3_column_double(s.raw(), 12);
                if (sqlite3_column_type(s.raw(), 13) != SQLITE_NULL)
                    p.time_stop_bars = sqlite3_column_int(s.raw(), 13);
                if (sqlite3_column_type(s.raw(), 14) != SQLITE_NULL)
                    p.factor = col_text(14);
                if (sqlite3_column_type(s.raw(), 15) != SQLITE_NULL)
                    p.bars_held = sqlite3_column_int(s.raw(), 15);
            }
            rows.push_back(std::move(p));
        }
    };
    try {
        read("SELECT id,venue,symbol,market,category,side,qty,avg_price,"
             "notional,opened_ts,COALESCE(sleeve,'quant_core'),stop_price,"
             "target_price,time_stop_bars,factor,bars_held"
             " FROM positions WHERE qty != 0 ORDER BY id",
             /*with_exit_state=*/true);
    } catch (const std::exception&) {
        // Pre-migration table (no exit-state columns): read what exists. The
        // exit fields stay absent, which the caller treats as unrecovered,
        // never as zeros.
        try {
            read("SELECT id,venue,symbol,market,category,side,qty,avg_price,"
                 "notional,opened_ts,COALESCE(sleeve,'quant_core')"
                 " FROM positions WHERE qty != 0 ORDER BY id",
                 /*with_exit_state=*/false);
        } catch (const std::exception&) {
            return {};  // no positions table at all: nothing to rehydrate
        }
    }
    return rows;
}

std::optional<std::string> Storage::latest_trade_entry_payload(
    const std::string& venue, const std::string& symbol) {
    try {
        Stmt s(db_,
               "SELECT payload_json FROM events WHERE kind='trade_entry'"
               " AND venue=? AND symbol=? ORDER BY id DESC LIMIT 1");
        s.bind(1, venue).bind(2, symbol);
        if (sqlite3_step(s.raw()) != SQLITE_ROW) return std::nullopt;
        const unsigned char* t = sqlite3_column_text(s.raw(), 0);
        if (!t) return std::nullopt;
        return std::string(reinterpret_cast<const char*>(t));
    } catch (const std::exception&) {
        return std::nullopt;  // no events table: nothing to recover from
    }
}

long long Storage::insert_research_thesis(const ResearchThesisRow& t) {
    Stmt s(db_,
           "INSERT INTO research_thesis(ts,symbol,direction,conviction,horizon,"
           "rationale,status,target,invalidation_price,invalidation,entry_price)"
           " VALUES(?,?,?,?,?,?,?,?,?,?,?)");
    s.bind(1, t.ts).bind(2, t.symbol).bind(3, t.direction).bind(4, t.conviction)
        .bind(5, t.horizon).bind(6, t.rationale).bind(7, t.status)
        .bind(8, t.target).bind(9, t.invalidation_price)
        .bind(10, t.invalidation).bind(11, t.entry_price);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

void Storage::update_research_thesis_status(const std::string& symbol,
                                            const std::string& status,
                                            const std::string& ts) {
    // Update the most recent open thesis for the symbol.
    Stmt s(db_,
           "UPDATE research_thesis SET status=?, ts=? WHERE id=("
           "SELECT id FROM research_thesis WHERE symbol=? AND status='open'"
           " ORDER BY id DESC LIMIT 1)");
    s.bind(1, status).bind(2, ts).bind(3, symbol);
    s.step_done();
}

long long Storage::insert_sleeve_snapshot(const SleeveSnapshotRow& r) {
    Stmt s(db_,
           "INSERT INTO sleeve_history(ts,sleeve,allocation,realized_pnl,"
           "unrealized_pnl,open_positions,wins,losses)"
           " VALUES(?,?,?,?,?,?,?,?)");
    s.bind(1, r.ts).bind(2, r.sleeve).bind(3, r.allocation).bind(4, r.realized_pnl)
        .bind(5, r.unrealized_pnl).bind(6, r.open_positions).bind(7, r.wins)
        .bind(8, r.losses);
    s.step_done();
    return sqlite3_last_insert_rowid(db_);
}

void Storage::upsert_bar(const BarRow& b) {
    // source is written on every path. An empty string still lands as
    // 'unknown' (BarRow defaults it), so no write can default to real.
    Stmt s(db_,
           "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
           "close,volume,source) VALUES(?,?,?,?,?,?,?,?,?,?)"
           " ON CONFLICT(venue,symbol,timeframe,timestamp) DO UPDATE SET"
           " open=excluded.open, high=excluded.high, low=excluded.low,"
           " close=excluded.close, volume=excluded.volume,"
           " source=excluded.source");
    s.bind(1, b.venue).bind(2, b.symbol).bind(3, b.timeframe).bind(4, b.timestamp)
        .bind(5, b.open).bind(6, b.high).bind(7, b.low).bind(8, b.close)
        .bind(9, b.volume).bind(10, b.source.empty() ? "unknown" : b.source);
    s.step_done();
}

std::vector<BarRow> Storage::recent_bars(const std::string& symbol,
                                         const std::string& timeframe,
                                         int limit) {
    Stmt s(db_,
           "SELECT venue,symbol,timeframe,timestamp,open,high,low,close,volume,"
           "COALESCE(source,'unknown')"
           " FROM bars WHERE symbol=? AND timeframe=?"
           " ORDER BY timestamp DESC LIMIT ?");
    s.bind(1, symbol).bind(2, timeframe).bind(3, limit);
    auto col_text = [&](int i) -> std::string {
        const unsigned char* t = sqlite3_column_text(s.raw(), i);
        return t ? reinterpret_cast<const char*>(t) : "";
    };
    std::vector<BarRow> rows;
    while (sqlite3_step(s.raw()) == SQLITE_ROW) {
        BarRow b;
        b.venue = col_text(0);
        b.symbol = col_text(1);
        b.timeframe = col_text(2);
        b.timestamp = col_text(3);
        b.open = sqlite3_column_double(s.raw(), 4);
        b.high = sqlite3_column_double(s.raw(), 5);
        b.low = sqlite3_column_double(s.raw(), 6);
        b.close = sqlite3_column_double(s.raw(), 7);
        b.volume = sqlite3_column_double(s.raw(), 8);
        b.source = col_text(9);
        rows.push_back(std::move(b));
    }
    std::reverse(rows.begin(), rows.end());  // oldest-first for indicator math
    return rows;
}

bool Storage::has_real_bars(const std::string& symbol) {
    // One indexed probe, LIMIT 1: called per symbol per run (the engine caches
    // the answer and flips it on the first live real tick).
    try {
        Stmt s(db_,
               "SELECT 1 FROM bars WHERE symbol=?"
               " AND source IN ('real_feed','backfill') LIMIT 1");
        s.bind(1, symbol);
        return sqlite3_step(s.raw()) == SQLITE_ROW;
    } catch (const std::exception&) {
        // Pre-provenance DB (no source column): fall back to any-bar history.
        try {
            Stmt s(db_, "SELECT 1 FROM bars WHERE symbol=? LIMIT 1");
            s.bind(1, symbol);
            return sqlite3_step(s.raw()) == SQLITE_ROW;
        } catch (const std::exception&) {
            return false;  // no bars table at all: no history
        }
    }
}

std::vector<BarRow> Storage::bars_in_range(const std::string& symbol,
                                           const std::string& timeframe,
                                           const std::string& start_ts,
                                           const std::string& end_ts) {
    // ISO-8601 timestamps sort lexicographically, so string bounds work as time
    // bounds. Each bound is optional (empty => unbounded on that side).
    std::string sql =
        "SELECT venue,symbol,timeframe,timestamp,open,high,low,close,volume,"
        "COALESCE(source,'unknown')"
        " FROM bars WHERE symbol=? AND timeframe=?";
    if (!start_ts.empty()) sql += " AND timestamp>=?";
    if (!end_ts.empty()) sql += " AND timestamp<=?";
    sql += " ORDER BY timestamp ASC";
    Stmt s(db_, sql.c_str());
    int idx = 1;
    s.bind(idx++, symbol);
    s.bind(idx++, timeframe);
    if (!start_ts.empty()) s.bind(idx++, start_ts);
    if (!end_ts.empty()) s.bind(idx++, end_ts);
    auto col_text = [&](int i) -> std::string {
        const unsigned char* t = sqlite3_column_text(s.raw(), i);
        return t ? reinterpret_cast<const char*>(t) : "";
    };
    std::vector<BarRow> rows;
    while (sqlite3_step(s.raw()) == SQLITE_ROW) {
        BarRow b;
        b.venue = col_text(0);
        b.symbol = col_text(1);
        b.timeframe = col_text(2);
        b.timestamp = col_text(3);
        b.open = sqlite3_column_double(s.raw(), 4);
        b.high = sqlite3_column_double(s.raw(), 5);
        b.low = sqlite3_column_double(s.raw(), 6);
        b.close = sqlite3_column_double(s.raw(), 7);
        b.volume = sqlite3_column_double(s.raw(), 8);
        b.source = col_text(9);
        rows.push_back(std::move(b));
    }
    return rows;
}

std::vector<BarRow> Storage::real_bars_in_range(const std::string& symbol,
                                                const std::string& timeframe,
                                                const std::string& start_ts,
                                                const std::string& end_ts) {
    // The backtest feed: exclude what the live path would never trade on.
    // A first attempt filters the quarantined-volume rows too; a DB whose
    // bars table predates volume_source falls back to the provenance filter
    // alone (those DBs predate the fabrication, so nothing is masked).
    auto run = [&](bool with_vs) {
        std::string sql =
            "SELECT venue,symbol,timeframe,timestamp,open,high,low,close,"
            "volume,COALESCE(source,'unknown') FROM bars WHERE symbol=? AND "
            "timeframe=? AND COALESCE(source,'unknown') IN "
            "('real_feed','backfill')";
        if (with_vs)
            sql += " AND COALESCE(volume_source,'') != 'fabricated_zeroed'";
        if (!start_ts.empty()) sql += " AND timestamp>=?";
        if (!end_ts.empty()) sql += " AND timestamp<=?";
        sql += " ORDER BY timestamp ASC";
        Stmt s(db_, sql);
        int idx = 1;
        s.bind(idx++, symbol);
        s.bind(idx++, timeframe);
        if (!start_ts.empty()) s.bind(idx++, start_ts);
        if (!end_ts.empty()) s.bind(idx++, end_ts);
        auto col_text = [&](int i) -> std::string {
            const unsigned char* t = sqlite3_column_text(s.raw(), i);
            return t ? reinterpret_cast<const char*>(t) : "";
        };
        std::vector<BarRow> rows;
        while (sqlite3_step(s.raw()) == SQLITE_ROW) {
            BarRow b;
            b.venue = col_text(0);
            b.symbol = col_text(1);
            b.timeframe = col_text(2);
            b.timestamp = col_text(3);
            b.open = sqlite3_column_double(s.raw(), 4);
            b.high = sqlite3_column_double(s.raw(), 5);
            b.low = sqlite3_column_double(s.raw(), 6);
            b.close = sqlite3_column_double(s.raw(), 7);
            b.volume = sqlite3_column_double(s.raw(), 8);
            b.source = col_text(9);
            rows.push_back(std::move(b));
        }
        return rows;
    };
    try {
        return run(true);
    } catch (const std::exception&) {
        try {
            return run(false);
        } catch (const std::exception&) {
            return {};
        }
    }
}

std::vector<std::string> Storage::watchlist_symbols(const std::string& sleeve) {
    // Tolerant read: a DB created before discovery has no watchlist table, and a
    // missing table must degrade to "no watchlist", never to a throw. Discovery
    // is an advisory layer and can never take the trading loop down.
    std::vector<std::string> out;
    const std::string sql =
        sleeve.empty()
            ? "SELECT symbol FROM watchlist WHERE status='active' ORDER BY symbol"
            : "SELECT symbol FROM watchlist WHERE status='active' AND "
              "sleeve_target=? ORDER BY symbol";
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        if (raw) sqlite3_finalize(raw);
        return out;
    }
    if (!sleeve.empty())
        sqlite3_bind_text(raw, 1, sleeve.c_str(), -1, SQLITE_TRANSIENT);
    while (sqlite3_step(raw) == SQLITE_ROW) {
        const unsigned char* s = sqlite3_column_text(raw, 0);
        if (s) out.emplace_back(reinterpret_cast<const char*>(s));
    }
    sqlite3_finalize(raw);
    return out;
}

std::vector<Storage::AdaptiveActionRow> Storage::adaptive_actions_after(
    long long after_id) {
    // Tolerant read, same posture as watchlist_symbols: a DB created before the
    // adaptive layer has no adaptive_action table, and a missing table must
    // degrade to "no actions", never to a throw. This layer is advisory and can
    // never take the trading loop down.
    //
    // Oldest first, so a burst of actions applies in the order the events
    // actually happened.
    std::vector<AdaptiveActionRow> out;
    const std::string sql =
        "SELECT id, ts, symbol, action, reason, severity, event_id "
        "FROM adaptive_action WHERE id > ? ORDER BY id ASC";
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        if (raw) sqlite3_finalize(raw);
        return out;
    }
    sqlite3_bind_int64(raw, 1, after_id);
    while (sqlite3_step(raw) == SQLITE_ROW) {
        AdaptiveActionRow r;
        r.id = sqlite3_column_int64(raw, 0);
        auto text = [&](int col) -> std::string {
            const unsigned char* s = sqlite3_column_text(raw, col);
            return s ? reinterpret_cast<const char*>(s) : "";
        };
        r.ts = text(1);
        r.symbol = text(2);
        r.action = text(3);
        r.reason = text(4);
        r.severity = sqlite3_column_double(raw, 5);
        r.event_id = sqlite3_column_int64(raw, 6);
        out.push_back(std::move(r));
    }
    sqlite3_finalize(raw);
    return out;
}

long long Storage::max_adaptive_action_id() {
    // The restart watermark. Reading the CURRENT max at construction is what
    // makes "an action queued while the engine was down is never replayed" true:
    // the engine starts life already past everything that exists, so only
    // actions queued after it came up are ever seen. A missing table gives 0,
    // which means "start from the beginning of an empty table", not "replay
    // history".
    long long out = 0;
    sqlite3_stmt* raw = nullptr;
    const char* sql = "SELECT COALESCE(MAX(id), 0) FROM adaptive_action";
    if (sqlite3_prepare_v2(db_, sql, -1, &raw, nullptr) != SQLITE_OK) {
        if (raw) sqlite3_finalize(raw);
        return 0;
    }
    if (sqlite3_step(raw) == SQLITE_ROW) out = sqlite3_column_int64(raw, 0);
    sqlite3_finalize(raw);
    return out;
}

long long Storage::insert_entry_decision(const EntryDecisionRow& r) noexcept {
    // RECORDING ONLY: this runs on the closed-bar decision path, so it must
    // never throw into it. A failed write is logged once and swallowed.
    static bool warned = false;
    try {
        Stmt s(db_,
               "INSERT INTO entry_decision(ts,venue,symbol,bar_source,regime,"
               "factor,outcome,first_reject,tier,confidence,edge,trade_id,"
               "source,state_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
        s.bind(1, r.ts).bind(2, r.venue).bind(3, r.symbol)
            .bind(4, r.bar_source).bind(5, r.regime).bind(6, r.factor)
            .bind(7, r.outcome).bind(8, r.first_reject).bind(9, r.tier);
        if (r.has_composition) s.bind(10, r.confidence).bind(11, r.edge);
        else { s.bind_null(10); s.bind_null(11); }
        if (r.trade_id > 0)
            sqlite3_bind_int64(s.raw(), 12, r.trade_id);
        else
            s.bind_null(12);
        s.bind(13, r.source).bind(14, r.state_json);
        s.step_done();
        return sqlite3_last_insert_rowid(db_);
    } catch (const std::exception& e) {
        if (!warned) {
            warned = true;
            std::fprintf(stderr,
                         "entry_decision write failed (recording only, "
                         "decisions unaffected): %s\n", e.what());
        }
        return -1;
    }
}

void Storage::prune_entry_decisions(const std::string& before_ts) noexcept {
    try {
        Stmt s(db_, "DELETE FROM entry_decision WHERE ts < ?");
        s.bind(1, before_ts);
        s.step_done();
    } catch (const std::exception&) {
        // Missing table or locked DB: retention is best-effort, never fatal.
    }
}

void Storage::upsert_regime(const std::string& symbol, const std::string& regime,
                            double adx, double rvol,
                            const std::string& active_factor,
                            const std::string& updated_ts) {
    Stmt s(db_,
           "INSERT INTO regime_state(symbol,regime,adx,rvol,active_factor,updated_ts)"
           " VALUES(?,?,?,?,?,?)"
           " ON CONFLICT(symbol) DO UPDATE SET regime=excluded.regime,"
           " adx=excluded.adx, rvol=excluded.rvol,"
           " active_factor=excluded.active_factor,"
           " updated_ts=excluded.updated_ts");
    s.bind(1, symbol).bind(2, regime).bind(3, adx).bind(4, rvol)
        .bind(5, active_factor).bind(6, updated_ts);
    s.step_done();
}

long long Storage::count(const std::string& table) {
    // Table name is caller-controlled internal constant, not user input.
    Stmt s(db_, "SELECT COUNT(*) FROM " + table);
    if (sqlite3_step(s.raw()) != SQLITE_ROW) return 0;
    return sqlite3_column_int64(s.raw(), 0);
}

long long Storage::count_closed_trades() {
    Stmt s(db_,
           "SELECT COUNT(*) FROM trades WHERE outcome IN ('win','loss','flat')"
           " AND pnl IS NOT NULL");
    if (sqlite3_step(s.raw()) != SQLITE_ROW) return 0;
    return sqlite3_column_int64(s.raw(), 0);
}

}  // namespace mal::storage
