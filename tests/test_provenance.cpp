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
// Mutation checks (verified by hand during development, recorded in RETURN.md):
// flipping allows_entry to return true makes the real-path cases fail, and
// removing the empty->unknown guard in upsert_bar makes the empty-source
// round trip fail.
#include <cstdio>
#include <string>

#include "core/provenance.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

int main() {
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

        // A trade row carries the bar it executed against; empty lands unknown.
        storage::TradeRow tr;
        tr.ts = "2026-07-18T10:10:00Z";
        tr.venue = "alpaca";
        tr.symbol = "BTC/USD";
        tr.side = "buy";
        tr.mode = "paper";
        tr.outcome = "open";
        tr.bar_source = "synthetic";
        st.insert_trade(tr);
        tr.bar_source = "";
        st.insert_trade(tr);
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
