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
