// Entry-decision recording is RECORDING ONLY (2026-07-23).
//
// Guard 1: the entry decision is IDENTICAL with recording enabled and
// disabled, over the deterministic offline synthetic feed, in BOTH profiles
// (the shipped file's profile and the other one). Any divergence is a defect
// in the recording change.
// Guard 2: a rejected candidate PERSISTS a row (a rejection used to write
// nothing at all, which is why filter attribution was impossible), with a
// named first_reject and the full condition state, and an entered candidate's
// row joins its trade.
#include <sqlite3.h>

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {

void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}

long long q1(storage::Storage& s, const std::string& sql) {
    sqlite3_stmt* st = nullptr;
    long long v = -1;
    if (sqlite3_prepare_v2(s.handle(), sql.c_str(), -1, &st, nullptr) ==
        SQLITE_OK) {
        if (sqlite3_step(st) == SQLITE_ROW) v = sqlite3_column_int64(st, 0);
    }
    if (st) sqlite3_finalize(st);
    return v;
}

std::string qs(storage::Storage& s, const std::string& sql) {
    sqlite3_stmt* st = nullptr;
    std::string v;
    if (sqlite3_prepare_v2(s.handle(), sql.c_str(), -1, &st, nullptr) ==
        SQLITE_OK) {
        if (sqlite3_step(st) == SQLITE_ROW) {
            const unsigned char* t = sqlite3_column_text(st, 0);
            if (t) v = reinterpret_cast<const char*>(t);
        }
    }
    if (st) sqlite3_finalize(st);
    return v;
}

// A digest of everything behavioral: every trade row in order, plus the
// blocked and event counts. Identical digests = identical decisions.
std::string behavior_digest(const std::string& db) {
    storage::Storage s(db);
    std::string d = qs(s,
        "SELECT COALESCE(GROUP_CONCAT(ts||'|'||symbol||'|'||side||'|'||"
        "ROUND(price,8)||'|'||ROUND(qty,10)||'|'||outcome, ';'),'') FROM "
        "(SELECT * FROM trades ORDER BY id)");
    d += "#B" + std::to_string(q1(s, "SELECT COUNT(*) FROM blocked_trades"));
    d += "#E" + std::to_string(q1(s, "SELECT COUNT(*) FROM events"));
    return d;
}

void run_engine(const config::Config& cfg, const std::string& db, bool record) {
    rm_db(db);
    core::EngineOptions opts;
    opts.db_path = db;
    opts.schema_path = "storage/schema.sql";
    opts.feed_mode = "synthetic_regimes";
    opts.clock_mode = "simulated";
    opts.record_entry_decisions = record;
    core::Engine engine(cfg, opts);
    engine.run(5000);
}

void check_profile(const config::Config& cfg, const std::string& label,
                   bool expect_entry) {
    const std::string on_db = "/tmp/mal_test_edr_on_" + label + ".db";
    const std::string off_db = "/tmp/mal_test_edr_off_" + label + ".db";
    run_engine(cfg, on_db, /*record=*/true);
    run_engine(cfg, off_db, /*record=*/false);

    maltest::check(behavior_digest(on_db) == behavior_digest(off_db),
                   label + ": decisions identical with recording on and off "
                   "(every trade row, block, and event)");

    storage::Storage on(on_db);
    storage::Storage off(off_db);
    maltest::check(q1(off, "SELECT COUNT(*) FROM entry_decision") == 0,
                   label + ": recording off persists nothing");
    maltest::check(
        q1(on, "SELECT COUNT(*) FROM entry_decision WHERE outcome='rejected'"
               " AND first_reject != '' AND state_json != ''") > 0,
        label + ": a rejected candidate persists a row with a named "
        "first_reject and the full condition state");
    if (expect_entry) {
        maltest::check(
            q1(on, "SELECT COUNT(*) FROM entry_decision e JOIN trades t ON "
                   "t.id = e.trade_id WHERE e.outcome='entered'") > 0,
            label + ": an entered candidate's row joins its trade");
    }
}

}  // namespace

int main() {
    // Profile as shipped in the tree.
    config::Config shipped = config::load_config("config/default_config.yaml");

    // The OTHER profile, via a temp config with the profile line swapped, so
    // both strategy stacks are covered whichever one the tree ships.
    std::ifstream in("config/default_config.yaml");
    std::stringstream ss;
    ss << in.rdbuf();
    std::string text = ss.str();
    const std::string aq = "  profile: active_quant";
    const std::string sw = "  profile: swing";
    std::string other_text = text;
    if (auto p = other_text.find(aq); p != std::string::npos)
        other_text.replace(p, aq.size(), sw);
    else if (auto q = other_text.find(sw); q != std::string::npos)
        other_text.replace(q, sw.size(), aq);
    const std::string other_path = "/tmp/mal_test_edr_other_config.yaml";
    {
        std::ofstream out(other_path);
        out << other_text;
    }
    config::Config other = config::load_config(other_path);

    check_profile(shipped, "shipped_profile", /*expect_entry=*/true);
    check_profile(other, "other_profile", /*expect_entry=*/true);

    return maltest::report("entry_decision_recording");
}
