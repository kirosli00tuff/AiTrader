// Bar provenance (2026-07-18, after the silent walk-substitution outage).
//
// Three properties, each load-bearing:
//   1. The entry gate: on the real path (alpaca_paper) ONLY real_feed and
//      backfill bars may open a position. Synthetic, replay, unknown, empty,
//      and junk are all refused. Offline feed modes are untouched.
//   2. Normalization never invents realness: anything unrecognized collapses
//      to unknown, and unknown is not real.
//   3. The storage round trip: a bar written with a source reads back with it,
//      a bar written empty reads back unknown, and a pre-migration row (no
//      source value) reads back unknown. No path defaults to real.
//
//   4. FILL provenance (2026-07-27): a TRADE row carries the bar set plus
//      `unclassified`. `unknown` on a trade means an unmigrated historical
//      row, so no live write may produce it. Empty, `unknown` and junk all
//      land `unclassified`, and each one emits a CRITICAL
//      fill_provenance_unclassified event naming WHY, which is what keeps a
//      never-set write distinguishable from an unestablishable one.
//
// Mutation checks (verified by hand during development, recorded in RETURN.md):
// flipping allows_entry to return true makes the real-path cases fail, and
// removing the empty->unknown guard in upsert_bar makes the empty-source
// round trip fail. Restoring either fill-provenance fallback fails this suite:
// the ternary makes the two unclassified round trips read `unknown` and emit
// no event, and the struct default turns the never-set write's reason from
// field_never_set into provenance_unavailable. tests/test_fill_provenance.py
// pins the same two removals lexically.
#include <sqlite3.h>

#include <cstdio>
#include <string>

#include "core/provenance.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {

// Read one text cell straight out of the file. The fill-provenance assertions
// have to describe what is ON DISK, not what the writer meant to put there.
std::string cell(const std::string& db, const std::string& sql) {
    sqlite3* h = nullptr;
    if (sqlite3_open(db.c_str(), &h) != SQLITE_OK) { sqlite3_close(h); return ""; }
    sqlite3_stmt* st = nullptr;
    std::string out;
    if (sqlite3_prepare_v2(h, sql.c_str(), -1, &st, nullptr) == SQLITE_OK &&
        sqlite3_step(st) == SQLITE_ROW) {
        const unsigned char* v = sqlite3_column_text(st, 0);
        if (v) out = reinterpret_cast<const char*>(v);
    }
    sqlite3_finalize(st);
    sqlite3_close(h);
    return out;
}

std::string trade_bar_source(const std::string& db, long long id) {
    return cell(db, "SELECT bar_source FROM trades WHERE id=" +
                        std::to_string(id));
}

int count_fill_events(const std::string& db) {
    const std::string n = cell(db,
        "SELECT COUNT(*) FROM events WHERE kind='fill_provenance_unclassified'");
    return n.empty() ? -1 : std::stoi(n);
}

int count_critical_fill_events(const std::string& db) {
    const std::string n = cell(db,
        "SELECT COUNT(*) FROM events WHERE kind='fill_provenance_unclassified'"
        " AND severity='critical'");
    return n.empty() ? -1 : std::stoi(n);
}

// The reason field out of the event payload for one trade id, or "" when the
// write emitted no event at all.
std::string fill_event_reason(const std::string& db, long long id) {
    const std::string payload = cell(db,
        "SELECT payload_json FROM events WHERE "
        "kind='fill_provenance_unclassified' AND payload_json LIKE "
        "'%\"trade_id\":" + std::to_string(id) + ",%'");
    const std::string key = "\"reason\":\"";
    const auto at = payload.find(key);
    if (at == std::string::npos) return "";
    const auto from = at + key.size();
    const auto to = payload.find('"', from);
    return to == std::string::npos ? "" : payload.substr(from, to - from);
}

}  // namespace

int main() {
    long long id_syn = 0, id_gap = 0, id_unset = 0;
    // --- 1. The entry gate, exhaustively -------------------------------
    maltest::check(provenance::allows_entry("alpaca_paper", "real_feed"),
                   "real path: real_feed bar may open");
    maltest::check(provenance::allows_entry("alpaca_paper", "backfill"),
                   "real path: backfill bar may open");
    maltest::check(!provenance::allows_entry("alpaca_paper", "synthetic"),
                   "real path: synthetic bar refused");
    maltest::check(!provenance::allows_entry("alpaca_paper", "replay"),
                   "real path: replay bar refused");
    maltest::check(!provenance::allows_entry("alpaca_paper", "unknown"),
                   "real path: unknown bar refused");
    maltest::check(!provenance::allows_entry("alpaca_paper", ""),
                   "real path: empty source refused, never read as real");
    maltest::check(!provenance::allows_entry("alpaca_paper", "REAL_FEED"),
                   "real path: junk casing refused, normalization is exact");
    // Offline feed modes trade synthetic bars by design: the gate stands aside.
    for (const char* mode :
         {"flat_random_walk", "synthetic_regimes", "replay"}) {
        maltest::check(provenance::allows_entry(mode, "synthetic"),
                       std::string(mode) + ": synthetic allowed offline");
        maltest::check(provenance::allows_entry(mode, "unknown"),
                       std::string(mode) + ": unknown allowed offline");
    }

    // --- 2. Normalization ----------------------------------------------
    maltest::check(provenance::normalize("") == "unknown",
                   "empty normalizes to unknown");
    maltest::check(provenance::normalize("walk") == "unknown",
                   "junk normalizes to unknown");
    maltest::check(provenance::normalize("real_feed") == "real_feed",
                   "known value passes through");
    maltest::check(!provenance::is_real(""), "empty is not real");
    maltest::check(!provenance::is_real("unknown"), "unknown is not real");
    maltest::check(provenance::is_real("backfill"), "backfill is real");

    // --- 3. Storage round trip -----------------------------------------
    const std::string db_path = "/tmp/mal_test_provenance.db";
    std::remove(db_path.c_str());
    {
        storage::Storage st(db_path);
        st.init_schema("storage/schema.sql");

        storage::BarRow real{"alpaca", "BTC/USD", "5min",
                             "2026-07-18T10:00:00Z", 1, 2, 0.5, 1.5, 10};
        real.source = "real_feed";
        st.upsert_bar(real);

        storage::BarRow synth{"alpaca", "BTC/USD", "5min",
                              "2026-07-18T10:05:00Z", 1, 2, 0.5, 1.5, 10};
        synth.source = "synthetic";
        st.upsert_bar(synth);

        // Empty source must land as unknown, never as real and never empty.
        storage::BarRow blank{"alpaca", "BTC/USD", "5min",
                              "2026-07-18T10:10:00Z", 1, 2, 0.5, 1.5, 10};
        blank.source = "";
        st.upsert_bar(blank);

        auto rows = st.recent_bars("BTC/USD", "5min", 10);
        maltest::check(rows.size() == 3, "three bars round-trip");
        maltest::check(rows[0].source == "real_feed",
                       "real_feed source persists");
        maltest::check(rows[1].source == "synthetic",
                       "synthetic source persists");
        maltest::check(rows[2].source == "unknown",
                       "empty source lands as unknown");

        // --- 4. VOLUME provenance, the second axis (2026-07-25) ---------
        // The column was added by the 2026-07-23 quarantine and populated by
        // nothing, so a real venue volume and an unestablished one were
        // indistinguishable. These pin the mapping and the write.
        namespace vol = provenance::volume;
        maltest::check(vol::for_bar_source("real_feed") == "venue_bar",
                       "a live bar's volume is the venue's minute bars");
        maltest::check(vol::for_bar_source("backfill") == "venue_backfill",
                       "a backfill bar's volume is the venue's history");
        maltest::check(vol::for_bar_source("synthetic") == "synthetic",
                       "a generated bar's volume is generated");
        maltest::check(vol::for_bar_source("replay") == "replay",
                       "a replayed bar's volume is replayed");
        maltest::check(vol::for_bar_source("") == "unknown",
                       "an unestablished source gives unestablished volume");
        maltest::check(vol::is_venue("venue_bar") &&
                       vol::is_venue("venue_backfill"),
                       "both venue labels read as venue-reported");
        maltest::check(!vol::is_venue("") && !vol::is_venue("unknown") &&
                       !vol::is_venue("fabricated_zeroed") &&
                       !vol::is_venue("synthetic"),
                       "nothing else reads as venue-reported");
        maltest::check(vol::normalize("nonsense") == "unknown",
                       "junk volume provenance normalizes to unknown");

        // Every write states its volume provenance, and an empty one lands as
        // unknown rather than claiming the venue reported it.
        storage::BarRow vb{"alpaca", "ETH/USD", "5min",
                           "2026-07-18T10:00:00Z", 1, 2, 0.5, 1.5, 10};
        vb.source = "real_feed";
        vb.volume_source = vol::for_bar_source(vb.source);
        st.upsert_bar(vb);

        storage::BarRow vblank{"alpaca", "ETH/USD", "5min",
                               "2026-07-18T10:05:00Z", 1, 2, 0.5, 1.5, 10};
        vblank.source = "real_feed";
        vblank.volume_source = "";
        st.upsert_bar(vblank);

        auto eth = st.recent_bars("ETH/USD", "5min", 10);
        maltest::check(eth.size() == 2, "two volume-provenance bars round-trip");
        maltest::check(eth[0].volume_source == "venue_bar",
                       "a stated volume provenance persists");
        maltest::check(eth[1].volume_source == "unknown",
                       "an empty volume provenance lands unknown, never venue");

        // --- 5. FILL provenance (2026-07-27) ----------------------------
        // A trade row carries the bar it executed against. `unknown` on a
        // trade means an UNMIGRATED HISTORICAL ROW, so no live write may
        // produce it: two silent fallbacks used to, and both are gone.
        namespace fp = provenance::fill;
        maltest::check(fp::classify("real_feed") == "real_feed",
                       "an established fill provenance passes through");
        maltest::check(fp::classify("backfill") == "backfill",
                       "backfill passes through");
        maltest::check(fp::classify("synthetic") == "synthetic",
                       "an offline fill keeps its synthetic label");
        maltest::check(fp::classify("replay") == "replay",
                       "a replayed fill keeps its replay label");
        maltest::check(fp::classify("") == "unclassified",
                       "a fill nobody stated provenance for is unclassified");
        maltest::check(fp::classify("unknown") == "unclassified",
                       "a LIVE write can never claim the historical marker");
        maltest::check(fp::classify("walk") == "unclassified",
                       "junk fill provenance is unclassified, never unknown");
        maltest::check(fp::classify("unclassified") == "unclassified",
                       "an explicit unclassified stays itself");
        // The two conditions the old code made byte-identical. The marker is
        // one value by design, so the REASON is what separates them, and it is
        // also what catches a restored struct default.
        maltest::check(fp::reason_for("") == "field_never_set",
                       "an unset field is recorded as the omission it is");
        maltest::check(fp::reason_for("unknown") == "provenance_unavailable",
                       "a stated but unestablishable provenance carries its "
                       "own reason, distinct from an omission");
        maltest::check(fp::is_unclassified("") && fp::is_unclassified("unknown"),
                       "neither empty nor unknown is an established fill");
        maltest::check(!fp::is_unclassified("real_feed") &&
                       !fp::is_unclassified("synthetic"),
                       "an established fill provenance is not unclassified");
        // The BAR rule is UNCHANGED: unclassified is a fill value only, a bar
        // carrying it still normalizes to unknown and still cannot enter.
        maltest::check(provenance::normalize("unclassified") == "unknown",
                       "unclassified is not a BAR provenance");
        maltest::check(!provenance::allows_entry("alpaca_paper", "unclassified"),
                       "unclassified never opens a position on the real path");
        maltest::check(!provenance::is_real("unclassified"),
                       "unclassified is never real, so no gate counts it");

        storage::TradeRow tr;
        tr.ts = "2026-07-18T10:10:00Z";
        tr.venue = "alpaca";
        tr.symbol = "BTC/USD";
        tr.side = "buy";
        tr.mode = "paper";
        tr.outcome = "open";
        tr.bar_source = "synthetic";
        id_syn = st.insert_trade(tr);
        tr.symbol = "ETH/USD";
        tr.bar_source = "unknown";      // provenance genuinely unavailable
        id_gap = st.insert_trade(tr);
        // A caller that NEVER TOUCHES the field. A fresh row on purpose:
        // assigning "" here would bypass the struct default and this case
        // exists to prove the default is gone.
        storage::TradeRow untouched;
        untouched.ts = "2026-07-18T10:15:00Z";
        untouched.venue = "alpaca";
        untouched.symbol = "SOL/USD";
        untouched.side = "buy";
        untouched.mode = "paper";
        untouched.outcome = "open";
        id_unset = st.insert_trade(untouched);
    }
    {
        // Read the rows back through a plain connection, so the assertions
        // describe what is ON DISK rather than what the writer intended.
        maltest::check(trade_bar_source(db_path, id_syn) == "synthetic",
                       "a stated fill provenance round-trips unchanged");
        maltest::check(trade_bar_source(db_path, id_gap) == "unclassified",
                       "an unavailable provenance lands unclassified, NOT the "
                       "historical unknown marker");
        maltest::check(trade_bar_source(db_path, id_unset) == "unclassified",
                       "a never-set provenance lands unclassified, NOT the "
                       "historical unknown marker");
        // THE MARKER NEVER TRAVELS ALONE.
        maltest::check(count_fill_events(db_path) == 2,
                       "exactly the two unclassified writes emitted a "
                       "fill_provenance_unclassified event");
        maltest::check(count_critical_fill_events(db_path) == 2,
                       "and both carry severity critical");
        maltest::check(fill_event_reason(db_path, id_gap) ==
                           "provenance_unavailable",
                       "the unavailable write names its reason");
        maltest::check(fill_event_reason(db_path, id_unset) == "field_never_set",
                       "the never-set write names ITS reason, so the two stay "
                       "distinguishable in the audit record even though the "
                       "marker is a single value");
        maltest::check(fill_event_reason(db_path, id_syn).empty(),
                       "a provenance-confirmed fill emits no such event");
    }
    {
        // Reopen: init_schema is idempotent and the migration tolerant.
        storage::Storage st(db_path);
        st.init_schema("storage/schema.sql");
        auto rows = st.recent_bars("BTC/USD", "5min", 10);
        maltest::check(rows.size() == 3 && rows[0].source == "real_feed",
                       "sources survive reopen + re-migration");
    }
    std::remove(db_path.c_str());

    return maltest::report("test_provenance");
}
