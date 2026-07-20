// Market AI Lab — core engine loop / orchestration.
//
// Wires the four-layer decision architecture together for the continuous paper
// loop: gather advisory factors (LLM consensus, rule-based, DNN/RL, whale) →
// combine (signal_engine) → propose order → Layer-1 RiskGate (final authority)
// → mode router (paper) → record outcome → persist to SQLite. Advisory factors
// come from the Python bridge when available, otherwise deterministic mocks so
// the engine always runs offline.
#pragma once

#include <csignal>
#include <future>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "account_manager/account_manager.hpp"
#include "core/adaptive_actions.hpp"
#include "core/adaptive_controls.hpp"
#include "core/discovery_controls.hpp"
#include "core/feed_clock.hpp"
#include "core/layer_toggles.hpp"
#include "core/sleeve_controls.hpp"
#include "core/operator_controls.hpp"
#include "config/config.hpp"
#include "execution/execution.hpp"
#include "learning/adaptive.hpp"
#include "market_data/market_data.hpp"
#include "market_data/synthetic_feed.hpp"
#include "news_ingestion/news_ingestion.hpp"
#include "core/sleeves.hpp"
#include "risk/risk_gate.hpp"
#include "signal_engine/council_gate.hpp"
#include "signal_engine/factor_engine.hpp"
#include "signal_engine/strategy.hpp"
#include "storage/storage.hpp"

namespace mal::core {

struct EngineOptions {
    std::string db_path;
    std::string schema_path;
    std::string bridge_host = "127.0.0.1";
    int bridge_port = 8765;
    bool use_bridge = false;  // try the Python bridge for advisory factors
    uint64_t seed = 42;
    // Continuous (run-forever) mode. Empty data_source means "use config".
    bool continuous = false;
    int interval_seconds = 0;        // 0 -> use cfg.engine.loop_interval_seconds
    std::string data_source;          // "mock" | "alpaca"; empty -> use config
    // Bootstrap-only: run the legacy generic factor loop with simulated PnL
    // (simulate_outcome). OFF by default — the native strategy layer is the
    // default trading path and learns from REAL closed-trade fills (Task 3).
    bool bootstrap_sim = false;
    // Seconds per native bar bucket (default 5 min). <= 0 means one bar per tick
    // (testability lever so the native entry/exit path can be exercised quickly).
    long native_bar_seconds = 300;
    // Offline feed/clock overrides (empty => use cfg.simulation.*):
    //   feed_mode  : flat_random_walk | synthetic_regimes | replay
    //   clock_mode : real | simulated
    // These make the offline loop a real training environment; they NEVER touch
    // live behavior (Alpaca stays paper + market-data only, no live path).
    std::string feed_mode;
    std::string clock_mode;
};

class Engine {
public:
    Engine(config::Config cfg, EngineOptions opts);

    // Run one decision iteration across all instruments. Returns number of
    // executed paper trades this iteration.
    int run_iteration();

    // Run N iterations (the demo paper loop).
    void run(int iterations);

    // Run forever (continuous 24/7 paper loop), sleeping interval seconds
    // between ticks. Returns when *stop_flag becomes non-zero (set by a signal
    // handler) — the current tick completes, state is flushed, then it exits.
    void run_forever(const volatile std::sig_atomic_t* stop_flag);

    storage::Storage& storage() { return *storage_; }

    bool last_poll_was_live() const { return last_poll_live_; }

    // Read-only kill-switch state (used by tests and status surfaces). The switch
    // itself is only ever changed through the latching trip / manual-resume path.
    bool kill_switch_tripped() const { return kill_switch_.tripped(); }
    bool manual_resume_pending() const { return kill_switch_.manual_resume_pending(); }

    // Strict mode (Task 3): on the real paper path (feed_mode alpaca_paper), a
    // layer set on-real must have a reachable real service or this throws with
    // exactly what is missing, so the engine refuses to start rather than
    // silently substituting a mock. A layer set on-mock is an explicit choice
    // and does not throw. Offline feed modes are a no-op (they keep mock). Called
    // at the top of run() and run_forever(); public so it is directly testable.
    void verify_real_layers_reachable();

    // Per-symbol indicator warm-state (Task 1), computed from the in-memory bar
    // history seeded from the backfilled bars table on construction. main.cpp
    // prints one line per symbol at startup so the operator can confirm the
    // backfill warmed the indicators. Read-only.
    struct SymbolWarm {
        std::string symbol;
        strategy::WarmState state;
    };
    std::vector<SymbolWarm> warm_states() const;

private:
    std::vector<signal_engine::FactorSignal> gather_factors(
        const market_data::MarketState& ms, const news::CatalystScore& cat,
        bool council_allowed = true,
        const strategy::StrategySignal* native = nullptr);
    signal_engine::FactorSignal mock_factor(const std::string& name,
                                            const market_data::MarketState& ms,
                                            const news::CatalystScore& cat);
    void maybe_adapt(int iteration);
    void snapshot_balances();
    double simulate_outcome(const signal_engine::CombinedVerdict& v,
                            double notional);
    // Feed one market-data tick into the 5-min bar aggregator. On a bar close
    // for a whitelisted symbol: persist the bar, update in-memory history, and
    // recompute + persist the symbol's regime. Advisory only — never trades.
    void update_bars(const market_data::MarketState& ms, long epoch_seconds);
    // Shared closed-bar path: persist the bar, update in-memory history + regime,
    // and (unless bootstrap-sim) run the native strategy on it. Reached from the
    // tick aggregator (flat_random_walk) AND directly from the bar-driven feed
    // modes (synthetic_regimes / replay), so all three exercise the same logic.
    // bar_source is REQUIRED at every call site (no default), so the compiler
    // refuses a new caller that forgets to say where its prices came from. The
    // tick path derives it per bar from tick provenance, synthetic_regimes
    // passes "synthetic", replay passes "replay". See core/provenance.hpp.
    void on_closed_bar(const market_data::MarketState& ms,
                       const strategy::Bar& closed, long epoch,
                       const std::string& bar_source);
    // Set up the bar-driven feed modes (synthetic_regimes / replay). Builds the
    // per-symbol synthetic generators or loads the replay queue from the bars
    // table; throws with a clear message if replay has no bars for the range.
    void init_bar_mode(const std::vector<market_data::Instrument>& instruments);
    // Advance one step of the bar-driven feed. Returns the number of bars
    // ingested this step (0 => replay exhausted; synthetic never returns 0).
    int step_bar_mode();
    bool is_whitelisted(const std::string& symbol) const;
    // Native trading on a CLOSED bar for a whitelisted symbol: manage the open
    // position's native exit first, else consider a new strategy entry (council
    // gate -> factors/verdict -> RiskGate -> open). Never runs on ticks.
    void handle_bar_close(const market_data::MarketState& ms,
                          const strategy::Bar& bar, long now_epoch);
    // Rebuild aggregate portfolio/exposure state from currently open native
    // positions so the RiskGate sees true open risk when judging a new entry.
    void sync_portfolio_state();
    // Operator halt: consume the GUI/API kill-request control file (if present)
    // at the top of each loop iteration and trip the SAME latching kill switch
    // used for a loss-triggered halt, then archive the processed request so a
    // stale file cannot re-trip on a later run. Reads a control file only; it
    // never touches the RiskGate.
    void consume_operator_kill_request();
    // Consume the per-layer enable toggles from controls.json each iteration.
    // A toggle off drops that layer's factor from the ensemble. Safety has no
    // toggle and is never gated here. Advisory only, never a safety bypass.
    void consume_layer_toggles();
    // Consume discovery_enabled from controls.json each iteration and drive the
    // funnel, the same control-file pattern as the kill request and the layer
    // toggles. Disabled means no pass, exactly as before. Enabled means: ask the
    // bridge whether a pass is due (discovery/run.py owns the cadence), and if
    // so start one OFF the loop thread. Never blocks: a pass runs for tens of
    // seconds once council calls fire, and the kill switch is checked at the top
    // of every iteration, so the loop must never wait on one.
    //
    // The funnel itself is Python (Finnhub, the Haiku gate, the council all live
    // there), so this drives it over the bridge rather than reimplementing it.
    // The engine stays the sole writer of the events table, which is why the
    // pass start, the stage counts, the cadence skips, and the prerequisite
    // blocks are all logged from here rather than Python-side.
    void consume_discovery();
    // Consume the research_satellite sleeve enable from controls.json each
    // iteration, the same control-file pattern as the layer toggles. It
    // REFRESHES cfg_.sleeves.research_satellite_enabled in place, because that
    // is the single field both consumers already read (the maintenance gate in
    // on_closed_bar, and sleeves::satellite_has_room), so one write makes the
    // toggle real everywhere with no second source of truth.
    //
    // Allocation only. An enabled sleeve is still bounded by the hard cap and
    // the RiskGate still judges every order in both sleeves.
    void consume_sleeves();
    // Reap any finished pass, log its outcome (stage counts / skip / block), and
    // onboard whatever it surfaced. Called every iteration from consume_discovery.
    void collect_discovery_passes();
    // Start one pass for one asset class on its own thread. Captures by value
    // only and touches no engine state, so the loop thread stays the only writer.
    void launch_discovery_pass(const std::string& asset_class,
                               const std::string& ts);
    // Merge the watchlist into the traded universe, ADD-ONLY, and warm what is
    // new: extend the whitelist and the polled feed, then seed indicator history
    // from the bars the pass backfilled. Add-only is the safety property: a
    // symbol is never withdrawn mid-run, so a pass can never move a symbol out
    // from under an open position. A restart still picks up the current list.
    void onboard_discovered_symbols(const std::string& ts);
    // Log a discovery skip/block once per state change instead of once per
    // trigger. The operator needs to SEE that discovery is idle or blocked and
    // why, without the reason repeating every five minutes forever.
    void log_discovery_state_once(const std::string& kind,
                                  const std::string& asset_class,
                                  const std::string& reason,
                                  const std::string& severity,
                                  const std::string& ts);
    // Consume the runtime feed-mode + clock-mode toggle from controls.json each
    // loop iteration (Task 3). A clock switch applies immediately. A feed switch
    // rebuilds the feed source, but a switch AWAY from alpaca_paper with an open
    // position is BLOCKED so it never orphans a position. Every applied switch
    // logs old/new to the event log. Called only from the continuous loop.
    void consume_feed_clock();
    // Apply a validated feed switch: rebuild the tick feed (alpaca/mock) or the
    // bar-driven generators (synthetic/replay). Entering alpaca_paper re-arms the
    // warm-start gate through the per-symbol bar history that persists across the
    // switch. Does not throw; a runtime switch never crashes the running loop.
    void apply_feed_switch(const std::string& new_feed, const std::string& ts);
    // Whether any native paper position is currently open (open-position safety
    // rule for a feed switch).
    bool has_open_positions() const { return !open_positions_.empty(); }
    // Warm-state transition tracking on the real path: log a warm_state event
    // when a symbol crosses cold<->warm. Called from on_closed_bar.
    void track_warm_state(const std::string& symbol, const std::string& venue,
                          const std::string& key, const std::string& ts);
    // Whether the symbol at `key` is warm enough to evaluate a native entry.
    bool symbol_is_warm(const std::string& key) const;
    // Consume queued DEFENSIVE actions from the adaptive real-time layer, at the
    // top of each loop iteration. Gated on
    // adaptive_realtime.adaptive_react_defensive_enabled, which is FALSE by
    // default: with the flag off this reads nothing and does nothing.
    //
    // This function is the whole of the engine's exposure to live news, and note
    // what it cannot do. It consumes core::DefensiveAction values, a type with no
    // representation for opening or increasing a position, so there is no
    // instruction it could receive that would make the engine more aggressive. It
    // reaches only the exit accounting, never handle_bar_close's ENTRY branch. A
    // symbol the adaptive layer wants BOUGHT lands on the watchlist as
    // `referred` and must clear the discovery funnel and the RiskGate like
    // anything else.
    //
    // Three independent refusals apply to every row: the flag, the defensive
    // allowlist (core/adaptive_actions.hpp), and the action's age.
    void consume_adaptive_actions(const std::string& ts, long now_epoch);
    // Re-read the adaptive runtime settings from controls.json. Called once
    // per loop iteration, exactly like the layer toggles: the poller is a
    // separate process, so a cached value would keep the engine consuming
    // actions after the operator turned the react half off.
    AdaptiveRuntime adaptive_runtime() const;
    // Apply one defensive action through the SAME native exit accounting the
    // engine already uses. Never a bypass, and never a new order path. Returns
    // false (with a logged reason) when there is nothing to act on. Exits
    // deliberately do not consult the RiskGate: the gate's job is to refuse
    // risk-INCREASING orders, and a gate that could refuse an exit would trap a
    // position. The exit path in handle_bar_close has always worked this way.
    bool apply_defensive_action(const core::DefensiveAction& a,
                                const AdaptiveRuntime& rt,
                                const std::string& ts);
    // Trip the latching kill switch if today's realized loss has breached the
    // Level-1 daily limit. Called from EVERY path that realizes PnL, so a
    // defensive exit cannot cross the limit unnoticed until some later native
    // exit happens to look. Reads the limit, never changes it.
    void check_daily_loss_breach(const std::string& ts);

    // Consume the remaining controls.json overrides each iteration (Task 2):
    // council model toggles, runtime budget, and per-symbol regime pins. Logs
    // each change with old and new. Advisory/cost only, never a safety bypass.
    void consume_operator_controls();
    // Apply an operator regime pin for `symbol` if present, else return the
    // detected regime unchanged. The pin overrides the detector for that symbol.
    strategy::Regime pinned_or(const std::string& symbol,
                               strategy::Regime detected) const;

    // --- Core-satellite sleeves (Q) --------------------------------------
    // Sum the currently-open position notionals per sleeve (quant_core vs
    // research_satellite). Uninvested equity is cash. Used for the hard cap and
    // rebalancing. Pure read of open_positions_.
    sleeve::Allocations current_allocations() const;
    // Persist a per-sleeve accounting snapshot (allocation, realized/unrealized
    // pnl, open positions, wins/losses) to sleeve_history for the GUI.
    void snapshot_sleeves(const std::string& ts);
    // Rebalance the sleeves when one drifts past target +/- band. Trims the
    // OVERWEIGHT sleeve back toward target through the normal native exit path
    // (never a bypass), logs before/after allocations. Runs on the drift trigger
    // and on the scheduled cadence. A no-op when the satellite sleeve is off.
    void maybe_rebalance(const std::string& ts, long now_epoch);
    // Run a scheduled deep-research pass for the research_satellite sleeve: query
    // the bridge for a structured thesis per candidate, and open a satellite
    // position (through the RiskGate, under the HARD CAP) when the conviction
    // clears the threshold and the sleeve has room. Guarded by
    // research_satellite_enabled AND the bridge being available AND the combined
    // spend ceiling / research budget. A no-op otherwise. Never touches quant_core.
    void maybe_run_research_pass(const market_data::MarketState& ms,
                                 const std::string& ts, long now_epoch);
    // Whether combined council + research spend has reached the monthly ceiling
    // (pauses new council AND research calls in both sleeves). 0.0 = disabled.
    bool combined_spend_ceiling_reached() const;

    config::Config cfg_;
    EngineOptions opts_;
    std::unique_ptr<storage::Storage> storage_;
    std::unique_ptr<market_data::Feed> feed_;
    std::unique_ptr<news::MockCatalystProvider> news_;
    std::unique_ptr<risk::RiskGate> gate_;
    std::unique_ptr<account::AccountManager> accounts_;
    signal_engine::WeightState weights_;
    learning::AdaptiveTuner tuner_;
    execution::ModeRouter router_;
    risk::KillSwitch kill_switch_;

    // Aggregate portfolio/risk state, updated as trades happen.
    risk::PortfolioState pstate_;
    double equity_;
    double peak_equity_;
    uint64_t rng_;
    int trade_count_ = 0;
    std::map<std::string, double> factor_perf_;  // running perf per factor

    // Native strategy inputs: 5-min bar aggregation + bounded per-symbol history
    // ("venue|symbol" -> bars, oldest-first) seeded from storage on startup.
    strategy::BarAggregator bar_agg_;
    std::map<std::string, std::vector<strategy::Bar>> bar_history_;

    // --- Bar provenance (2026-07-18, after the silent walk-substitution
    // outage; see core/provenance.hpp for the rules) -----------------------
    // Per-key contamination of the bar currently being aggregated on the tick
    // path. One synthetic tick makes the whole bar synthetic. One tick of
    // unestablished source makes it unknown. Only all-real ticks make it real.
    struct BarProv {
        bool synthetic = false;
        bool unknown = false;
    };
    std::map<std::string, BarProv> bar_prov_;
    // Record one tick's provenance into the building bar.
    void note_tick_provenance(const std::string& key, const std::string& src);
    // Resolve and reset the building bar's provenance at bar close.
    std::string finish_bar_provenance(const std::string& key);
    // Provenance of the bar currently being handled by on_closed_bar and
    // everything it calls (entry gate, exit logging, trade rows, research
    // path). Set once per closed bar. "unknown" outside a bar close.
    std::string current_bar_source_ = "unknown";
    // Substitution detector state (real path only): true while any whitelisted
    // symbol's ticks are non-real. Logged as a critical event on the way in and
    // an info event on recovery, once per transition.
    bool feed_substituted_ = false;
    void check_feed_substitution(
        const std::vector<market_data::MarketState>& states,
        const std::string& ts);
    // Entry-gate dedup: symbol -> the non-real source last logged, so the
    // provenance_block event fires once per transition, not once per bar.
    std::map<std::string, std::string> provenance_block_state_;

    // --- THE TRADEABLE INVARIANT (2026-07-20) ------------------------------
    // On the real path (feed_mode alpaca_paper) a symbol with NO real bar
    // history (source real_feed or backfill, any timeframe) is NOT TRADEABLE:
    // it is not evaluated for entry, no bar is ever fabricated for it, and it
    // never contributes to a stack-level alarm. Its only condition is
    // symbol_unavailable: contained, per-symbol, prune-worthy, never
    // remediation. This is the ONE C++ enforcement point; every consumer
    // (entry evaluation, the substitution alarm, availability reporting,
    // discovery onboarding) calls this predicate rather than re-checking.
    // Offline feed modes are synthetic by design and always tradeable.
    // The Python mirror is market_data/tradeable.py (same source set, pinned
    // by tests/test_tradeable_invariant.py against drift).
    bool symbol_is_tradeable(const std::string& symbol);
    // Cache over storage_->has_real_bars: seeded lazily per symbol, flipped
    // true by the first live real tick, refreshed after a discovery onboard
    // (a backfill may have just landed).
    std::map<std::string, bool> has_real_bars_;
    // symbol_unavailable / symbol_available events fire once per transition,
    // not once per poll. symbol -> currently-logged-unavailable.
    std::map<std::string, bool> symbol_unavailable_logged_;
    // Per poll on the real path: flip the cache on real ticks and log the
    // once-per-transition availability events for whitelisted symbols.
    void note_symbol_availability(
        const std::vector<market_data::MarketState>& states,
        const std::string& ts);

    // An open native position plus the advisory context captured at ENTRY, so
    // realized PnL can be attributed back to the factors when it closes.
    struct ActivePosition {
        strategy::OpenPosition pos;
        std::vector<signal_engine::FactorSignal> entry_signals;
        double entry_bias = 0.0;
        // Core-satellite sleeve this position belongs to. Native strategy entries
        // are always quant_core; research_satellite positions come from the
        // deep-research path.
        std::string sleeve = "quant_core";
    };
    std::map<std::string, ActivePosition> open_positions_;  // key "venue|symbol"
    signal_engine::CouncilGateState council_state_;
    // Core-satellite scheduling + combined spend tracking (Q). research/rebalance
    // run on cadence, not per tick. calls_month feeds the combined spend ceiling.
    std::string research_day_;          // UTC day bucket for the research budget
    int research_calls_today_ = 0;      // deep-research council calls today
    long research_calls_month_ = 0;     // deep-research calls this month (combined ceiling)
    std::string research_month_;        // UTC month bucket (YYYY-MM)
    long last_rebalance_epoch_ = 0;     // last scheduled rebalance (epoch seconds)
    long last_research_epoch_ = 0;      // last scheduled research pass (epoch seconds)
    int trades_today_ = 0;              // native entries today (max_trades_per_day)
    std::string trades_today_day_;      // UTC day bucket for the counter above
    long closed_trade_count_ = 0;       // closed native trades (min-sample gate)

    // Highest adaptive_action id this engine has already seen. Seeded at
    // construction with the CURRENT max, so actions queued while the engine was
    // down are never replayed on a restart: an old headline must not move a
    // position in a market that has since repriced. Only ever moves forward.
    long long adaptive_action_watermark_ = 0;

    // Continuous-mode state.
    bool continuous_ = false;          // gate equity by market hours when true
    bool alpaca_feed_ = false;         // feed is AlpacaFeed (tracks live status)
    bool last_poll_live_ = false;      // last poll contained real Alpaca data

    // Operator kill-request control file (written by the API backend). Resolved
    // once in the constructor; the processed request is archived to the second
    // path so a stale file never re-trips the kill switch on restart.
    std::string kill_request_path_;
    std::string kill_request_archive_path_;

    // Per-layer enable toggles (controls.json, written by the GUI). Read each
    // iteration like the kill request. Missing or malformed means all ON.
    // Advisory only: a toggle off drops a factor from the ensemble, never safety.
    std::string controls_path_;
    LayerToggles layer_toggles_;
    LayerToggles prev_layer_toggles_;
    // Remaining operator controls (model toggles, budget, regime pins), read from
    // controls.json each iteration like the layer toggles. Advisory/cost only.
    OperatorControls operator_controls_;
    OperatorControls prev_operator_controls_;
    // Discovery, read from controls.json each iteration like the layer toggles.
    // Off by default and off when the file is unreadable: this one starts a
    // spender, so an unreadable file must never turn it on.
    DiscoveryRuntime discovery_;
    DiscoveryRuntime prev_discovery_;
    // research_satellite sleeve enable, read from controls.json each iteration
    // like the layer toggles. Off by default and off when the file is
    // unreadable: a broken file must not allocate capital to a sleeve nobody
    // turned on.
    SleeveRuntime sleeves_;
    SleeveRuntime prev_sleeves_;
    // Epoch seconds of the last time the engine ASKED whether a pass was due.
    // 0 means never asked, which is also how an off->on toggle asks immediately
    // instead of making the operator wait out a trigger interval.
    long last_discovery_trigger_ = 0;
    // In-flight passes, asset_class -> pending response body. Bounded at one per
    // asset class: a class already running is never started again, so a slow pass
    // can never pile up threads or double-spend the discovery budget.
    std::map<std::string, std::future<std::optional<std::string>>>
        discovery_inflight_;
    // Last logged skip/block state per asset class, so a steady reason is logged
    // once on entry rather than every trigger.
    std::map<std::string, std::string> discovery_last_state_;
    // Symbols this run onboarded from the watchlist, so onboarding is idempotent
    // across iterations and re-logs nothing.
    std::vector<std::string> discovery_symbols_;

    // --- Offline feed / clock state (Tasks 2-4) ---------------------------
    // feed_mode_: flat_random_walk (tick path) | synthetic_regimes | replay.
    // simulated_clock_: bar time advances internally (sim_epoch_) instead of
    // against wall-clock, so finite/synthetic runs actually close bars.
    std::string feed_mode_ = "flat_random_walk";
    bool simulated_clock_ = false;
    long sim_epoch_ = 0;               // advancing simulated UTC epoch (seconds)
    long bar_step_seconds_ = 300;      // sim-clock advance per bar step
    // Full instrument universe, kept so a runtime feed switch can rebuild the
    // tick feed or the bar-driven generators without reconstructing the engine.
    std::vector<market_data::Instrument> all_instruments_;
    // Launch feed/clock (resolved in the constructor), the fallback when
    // controls.json has no or an invalid feed_mode/clock_mode, so a missing file
    // never forces an offline run onto the live feed.
    FeedClock launch_feed_clock_;
    // Last feed a blocked switch was logged for, so a persistent unsafe request
    // logs once (not every iteration).
    std::string blocked_feed_request_;
    // Per-symbol warm flag on the real path (key "venue|symbol"): absent = not
    // yet evaluated, so the first computed state logs a transition. Tracked only
    // when feed_mode_ is alpaca_paper.
    std::map<std::string, bool> symbol_warm_;
    // synthetic_regimes: one deterministic generator per whitelisted instrument.
    std::vector<market_data::Instrument> bar_instruments_;
    std::vector<market_data::SyntheticRegimeGenerator> synth_gens_;
    // replay: chronologically-ordered stored bars replayed through on_closed_bar.
    struct BarTick {
        market_data::MarketState ms;
        strategy::Bar bar;
        long epoch = 0;
    };
    std::vector<BarTick> replay_queue_;
    size_t replay_pos_ = 0;
};

}  // namespace mal::core
