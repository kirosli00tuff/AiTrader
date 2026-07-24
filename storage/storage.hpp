// Market AI Lab — SQLite storage facade (DAO).
//
// Single source of truth shared with the Python services + Dash UI via the same
// DB file. The C++ core is the primary writer. The `events` table is treated as
// append-only. All writes are parameterized (no string interpolation) to keep
// the audit log injection-safe.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

struct sqlite3;

namespace mal::storage {

struct EventRow {
    std::string ts;
    std::string kind;
    std::string venue;
    std::string symbol;
    std::string severity = "info";
    std::string message;
    std::string payload_json;
};

struct TradeRow {
    std::string ts;
    std::string venue, symbol, market, category, side;
    double qty = 0, price = 0, notional = 0, fee = 0;
    std::string mode;
    std::optional<double> pnl;
    std::string outcome;
    double combined_conf = 0, combined_edge = 0;
    // Core-satellite sleeve tag ("quant_core" | "research_satellite").
    std::string sleeve = "quant_core";
    // What DECIDED this trade: "strategy" | "adaptive_react" | "rebalance".
    // Defaults to strategy so every existing call site keeps its meaning; only
    // the two non-strategy paths set it. Read by the real-fill gates, which
    // count strategy fills only.
    std::string origin = "strategy";
    // Provenance of the bar this trade executed against (same five values as
    // BarRow.source). Default unknown, never real. The real-fill gates exclude
    // proven-synthetic fills: a trade against walk prices exercised nothing.
    std::string bar_source = "unknown";
};

// A persisted LLM deep-research thesis attached to a research_satellite position,
// so the operator can read why each long-term hold exists.
struct ResearchThesisRow {
    std::string ts, symbol, direction;   // direction: long | short | flat
    double conviction = 0;               // council conviction [0,1]
    std::string horizon;                 // e.g. "weeks" | "months"
    std::string rationale;               // written thesis (never a key value)
    std::string status = "open";         // open | invalidated | target | closed
    // Long-term strategy fields (discovery.long_term_sleeve_enabled, OFF by
    // default). A long-term hold exits on target or invalidation, never on a
    // short-term signal, so both persist with the position. Zero/empty on a
    // thesis from the original council-mapped path, which carries neither.
    double target = 0;                   // price target
    double invalidation_price = 0;       // level at which the thesis is broken
    std::string invalidation;            // readable invalidation condition
    double entry_price = 0;
};

// A per-sleeve accounting snapshot for the GUI (equity/pnl/positions per sleeve).
struct SleeveSnapshotRow {
    std::string ts, sleeve;
    double allocation = 0, realized_pnl = 0, unrealized_pnl = 0;
    int open_positions = 0, wins = 0, losses = 0;
};

struct SignalRow {
    std::string ts, venue, symbol, factor;
    double bias = 0, confidence = 0, edge = 0;
    std::string payload_json;
};

struct ModelOutputRow {
    std::string ts, model, verdict;
    double confidence = 0, edge = 0, weight = 0;
    std::string extra_json;
};

struct BlockedRow {
    std::string ts, venue, symbol, side;
    double qty = 0;
    std::string reason, layer;
};

struct BalanceRow {
    std::string ts, venue;
    double equity = 0, cash = 0, realized_pnl = 0, unrealized_pnl = 0,
           drawdown_pct = 0;
};

struct WeightChangeRow {
    std::string ts, factor, source;
    double old_weight = 0, new_weight = 0;
    bool locked = false;
};

struct ParamHistoryRow {
    std::string ts, param, old_value, new_value, source, reason;
};

// One historical OHLCV bar. `timestamp` is the bar's open time (ISO-8601 UTC).
struct BarRow {
    std::string venue, symbol, timeframe, timestamp;
    double open = 0, high = 0, low = 0, close = 0, volume = 0;
    // Provenance: real_feed | backfill | synthetic | replay | unknown. The
    // default is unknown, NEVER real: a caller that does not know where its
    // prices came from must not claim they are real (core/provenance.hpp).
    std::string source = "unknown";
};

// RAII SQLite wrapper. Non-copyable.
class Storage {
public:
    explicit Storage(const std::string& db_path);
    ~Storage();
    Storage(const Storage&) = delete;
    Storage& operator=(const Storage&) = delete;

    // Create all tables from schema_sql_path if they do not exist.
    void init_schema(const std::string& schema_sql_path);

    long long append_event(const EventRow& e);
    long long insert_trade(const TradeRow& t);
    long long insert_signal(const SignalRow& s);
    long long insert_model_output(const ModelOutputRow& m);
    long long insert_blocked(const BlockedRow& b);
    long long insert_balance(const BalanceRow& b);
    long long insert_weight_change(const WeightChangeRow& w);
    long long insert_param_history(const ParamHistoryRow& p);

    void upsert_venue_state(const std::string& venue, const std::string& mode,
                            bool live_enabled, bool kill_switch_tripped,
                            int consecutive_losses,
                            const std::string& cooldown_until_ts,
                            const std::string& updated_ts);

    void set_approval_state(bool live_enabled, bool manual_confirmation,
                            const std::string& last_checked_ts,
                            const std::string& readiness_json);

    // Persist a research thesis (research_satellite sleeve) and update its status.
    long long insert_research_thesis(const ResearchThesisRow& t);
    void update_research_thesis_status(const std::string& symbol,
                                       const std::string& status,
                                       const std::string& ts);
    // Persist a per-sleeve accounting snapshot (history for the GUI).
    long long insert_sleeve_snapshot(const SleeveSnapshotRow& s);

    void upsert_position(const std::string& venue, const std::string& symbol,
                         const std::string& market, const std::string& category,
                         const std::string& side, double qty, double avg_price,
                         double notional, const std::string& opened_ts,
                         const std::string& sleeve = "quant_core");

    // Exit state persisted WITH the position (2026-07-23). Written at entry
    // beside upsert_position, and by the rehydration backfill when it recovers
    // exit state from the trade_entry event. Never touches qty/price columns.
    void upsert_position_exit_state(const std::string& venue,
                                    const std::string& symbol,
                                    double stop_price, double target_price,
                                    int time_stop_bars,
                                    const std::string& factor, int bars_held);

    // Persist the per-bar hold counter so the time-stop clock survives a
    // restart (one tiny UPDATE per open position per closed bar).
    void update_position_bars_held(const std::string& venue,
                                   const std::string& symbol, int bars_held);

    // One open-position row read back for rehydration. The exit fields are
    // optional: a row written before the exit-state migration holds NULL
    // there, and NULL must read as "never recorded", never as 0 (a target of
    // 0 would exit a long instantly at price 0 — a guess the reader must not
    // make).
    struct PositionRow {
        long long id = 0;
        std::string venue, symbol, market, category, side, opened_ts, sleeve;
        double qty = 0, avg_price = 0, notional = 0;
        std::optional<double> stop_price, target_price;
        std::optional<int> time_stop_bars, bars_held;
        std::optional<std::string> factor;
    };
    // Every positions row with qty != 0, ordered by id. Tolerant: a DB whose
    // positions table predates the exit-state columns (opened read-only or a
    // failed migration) reads with every exit field absent rather than
    // throwing.
    std::vector<PositionRow> open_position_rows();

    // payload_json of the newest trade_entry event for (venue, symbol), for
    // the rehydration backfill: the only durable record of a pre-migration
    // position's stop and target. nullopt when no such event exists.
    std::optional<std::string> latest_trade_entry_payload(
        const std::string& venue, const std::string& symbol);

    // Historical bars. upsert_bar is idempotent on (venue,symbol,timeframe,
    // timestamp). recent_bars returns up to `limit` most-recent bars for a
    // symbol+timeframe, ordered oldest-first (ascending) for indicator math.
    void upsert_bar(const BarRow& b);
    std::vector<BarRow> recent_bars(const std::string& symbol,
                                    const std::string& timeframe, int limit);
    // All bars for a symbol+timeframe within an inclusive timestamp range,
    // ordered oldest-first (ascending). Empty start/end means unbounded on that
    // side. Used by the historical replay feed mode.
    std::vector<BarRow> bars_in_range(const std::string& symbol,
                                      const std::string& timeframe,
                                      const std::string& start_ts,
                                      const std::string& end_ts);

    // THE TRADEABLE INVARIANT'S DATA QUESTION (2026-07-20): does this symbol
    // have any REAL bar history (source real_feed or backfill), any timeframe?
    // Engine::symbol_is_tradeable is the C++ enforcement point and this is its
    // storage read; the Python mirror is market_data/tradeable.py, and a test
    // pins that the two source sets cannot drift. A DB whose bars table has no
    // source column (pre-provenance) reads any bar as history, matching the
    // Python fallback: an unprovable provenance keeps the old semantics rather
    // than grounding every symbol.
    bool has_real_bars(const std::string& symbol);

    // Active dynamic-watchlist symbols, optionally for one sleeve (quant_core |
    // research_satellite; empty means both). READ-ONLY: the Python discovery
    // package is the writer of the watchlist, the same way it writes `bars`.
    // The engine reads this only when discovery.discovery_enabled is true, so
    // with discovery off (the default) it is never called and the traded
    // universe stays exactly the configured whitelist. Returns empty when the
    // table is absent (a DB predating discovery), so an old DB is never a crash.
    std::vector<std::string> watchlist_symbols(const std::string& sleeve = "");

    // One queued defensive request from the adaptive real-time layer.
    // `action` is a raw string here on purpose: this struct is the untrusted
    // WIRE shape, straight off a row. core/adaptive_actions.hpp is what turns it
    // into a typed DefensiveKind, and it refuses anything not defensive. Keeping
    // the two apart means the parsing rule has exactly one home.
    struct AdaptiveActionRow {
        long long id = 0;
        std::string ts;
        std::string symbol;
        std::string action;
        std::string reason;
        double severity = 0.0;
        long long event_id = 0;
    };

    // Queued adaptive actions with id > after_id, oldest first. READ-ONLY: the
    // Python adaptive package is the writer, exactly as it writes the watchlist.
    // The engine reads this only when adaptive_react_defensive_enabled is true,
    // so with the flag off (the default) it is never called. Returns empty when
    // the table is absent (a DB predating the adaptive layer), so an old DB is
    // never a crash.
    std::vector<AdaptiveActionRow> adaptive_actions_after(long long after_id);

    // The highest adaptive_action id present. The engine calls this ONCE at
    // construction to set its watermark, so actions queued before the engine
    // started are never replayed on a restart. Returns 0 when the table is
    // absent or empty.
    long long max_adaptive_action_id();

    // Persist the current regime + the regime-selected active factor for a symbol
    // (single row per symbol). active_factor is momentum | reversion | blend.
    void upsert_regime(const std::string& symbol, const std::string& regime,
                       double adx, double rvol, const std::string& active_factor,
                       const std::string& updated_ts);

    // Count rows in a table (used by tests/demo verification).
    long long count(const std::string& table);

    // Count CLOSED real fills (trades with a realized win/loss/flat outcome).
    // Used by the RL training gate + startup transparency (fills vs gate).
    long long count_closed_trades();

    sqlite3* handle() { return db_; }

private:
    void exec(const std::string& sql);
    sqlite3* db_ = nullptr;
};

}  // namespace mal::storage
