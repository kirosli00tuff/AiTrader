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

    // Active dynamic-watchlist symbols, optionally for one sleeve (quant_core |
    // research_satellite; empty means both). READ-ONLY: the Python discovery
    // package is the writer of the watchlist, the same way it writes `bars`.
    // The engine reads this only when discovery.discovery_enabled is true, so
    // with discovery off (the default) it is never called and the traded
    // universe stays exactly the configured whitelist. Returns empty when the
    // table is absent (a DB predating discovery), so an old DB is never a crash.
    std::vector<std::string> watchlist_symbols(const std::string& sleeve = "");

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
