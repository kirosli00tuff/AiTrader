#include "storage/storage.hpp"

#include <sqlite3.h>

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
           "notional,fee,mode,pnl,outcome,combined_conf,combined_edge)"
           " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
    s.bind(1, t.ts).bind(2, t.venue).bind(3, t.symbol).bind(4, t.market)
        .bind(5, t.category).bind(6, t.side).bind(7, t.qty).bind(8, t.price)
        .bind(9, t.notional).bind(10, t.fee).bind(11, t.mode);
    if (t.pnl) s.bind(12, *t.pnl); else s.bind_null(12);
    s.bind(13, t.outcome).bind(14, t.combined_conf).bind(15, t.combined_edge);
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
                              const std::string& opened_ts) {
    Stmt s(db_,
           "INSERT INTO positions(venue,symbol,market,category,side,qty,"
           "avg_price,notional,opened_ts) VALUES(?,?,?,?,?,?,?,?,?)"
           " ON CONFLICT(venue,symbol) DO UPDATE SET qty=excluded.qty,"
           " avg_price=excluded.avg_price, notional=excluded.notional,"
           " side=excluded.side");
    s.bind(1, venue).bind(2, symbol).bind(3, market).bind(4, category)
        .bind(5, side).bind(6, qty).bind(7, avg_price).bind(8, notional)
        .bind(9, opened_ts);
    s.step_done();
}

long long Storage::count(const std::string& table) {
    // Table name is caller-controlled internal constant, not user input.
    Stmt s(db_, "SELECT COUNT(*) FROM " + table);
    if (sqlite3_step(s.raw()) != SQLITE_ROW) return 0;
    return sqlite3_column_int64(s.raw(), 0);
}

}  // namespace mal::storage
