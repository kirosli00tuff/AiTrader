# CTest unit suite: RiskGate, config validation, weight normalization.
# Tests run from the project root so they can read config/ + storage/ files.

add_executable(test_risk_gate test_risk_gate.cpp)
target_link_libraries(test_risk_gate PRIVATE mal_risk mal_config)
add_test(NAME risk_gate COMMAND test_risk_gate
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

add_executable(test_config test_config.cpp)
target_link_libraries(test_config PRIVATE mal_config)
add_test(NAME config COMMAND test_config WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

add_executable(test_weights test_weights.cpp)
target_link_libraries(test_weights PRIVATE mal_signal_engine mal_learning mal_config)
add_test(NAME weights COMMAND test_weights WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

add_executable(test_strategy test_strategy.cpp)
target_link_libraries(test_strategy PRIVATE mal_signal_engine mal_config)
add_test(NAME strategy COMMAND test_strategy WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Core-satellite sleeves: hard cap holds against over-conviction, drift-band
# rebalancing trims the overweight sleeve, sleeve config validates. Pure header.
add_executable(test_sleeves test_sleeves.cpp)
target_link_libraries(test_sleeves PRIVATE mal_config)
add_test(NAME sleeves COMMAND test_sleeves WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# research_satellite sleeve enable, engine side: the engine must read the sleeve
# toggle from the controls.json the GUI writes, not from the config default, or
# the toggle is cosmetic and the long-term strategy can never get a sleeve.
add_executable(test_sleeve_controls test_sleeve_controls.cpp)
target_link_libraries(test_sleeve_controls PRIVATE mal_config mal_util mal_bridge)
add_test(NAME sleeve_controls COMMAND test_sleeve_controls
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Discovery flag consumption, engine side: the engine must read discovery_enabled
# from the controls.json the GUI writes, not from the config default, or the
# operator's toggle is cosmetic and no discovered symbol is ever traded.
add_executable(test_discovery_engine test_discovery_engine.cpp)
# mal_bridge: discovery_controls.hpp reads controls.json through the shared flat
# JSON reader (bridge::json_get_bool).
target_link_libraries(test_discovery_engine PRIVATE mal_config mal_util mal_bridge)
add_test(NAME discovery_engine COMMAND test_discovery_engine
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Adaptive real-time layer, engine side. The asymmetry: a live event may trim,
# exit, or flag, and has NO representation for opening or increasing a position.
# Also covers action staleness (old news must not move a position) and that all
# three flags ship false in both the struct and the shipped config file.
add_executable(test_adaptive_react test_adaptive_react.cpp)
# mal_bridge: adaptive_controls.hpp reads controls.json through the shared
# flat JSON reader (bridge::json_get_bool / json_get_number).
target_link_libraries(test_adaptive_react PRIVATE mal_config mal_util mal_bridge)
add_test(NAME adaptive_react COMMAND test_adaptive_react
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Adaptive defensive actions through a REAL engine: the GUI toggle in
# controls.json actually reaches the consumer, an aggressive row hand-written
# into the queue is refused on read, a stale action is refused, and an action is
# attempted exactly once. Covers THE MONEY PATH: a trim against a real open
# position, asserting it halves the position, books the closed portion only, and
# realizes pnl as (price - entry) * closed_qty - fee. Mutation-checked: breaking
# either the qty or the pnl scaling fails this suite.
add_executable(test_adaptive_engine test_adaptive_engine.cpp)
target_link_libraries(test_adaptive_engine PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_storage mal_risk mal_config mal_util)
add_test(NAME adaptive_engine COMMAND test_adaptive_engine
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Global-session equity rotation scaffold: config-driven regional sessions, the
# venue-capability gate (only NY/Alpaca reachable today), disabled rotation flag,
# and simulated-time session detection.
add_executable(test_regional_session test_regional_session.cpp)
target_link_libraries(test_regional_session PRIVATE mal_config)
add_test(NAME regional_session COMMAND test_regional_session
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Header-only pure predicate (learning/adapt_gate.hpp) — no library link needed.
add_executable(test_tuner_minsample test_tuner_minsample.cpp)
add_test(NAME tuner_minsample COMMAND test_tuner_minsample
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Feed modes + simulated clock (synthetic-regime feed, replay). Links the full
# engine so it can drive finite synthetic + replay runs against temp SQLite DBs.
add_executable(test_feed_modes test_feed_modes.cpp)
target_link_libraries(test_feed_modes PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_storage mal_config mal_util)
add_test(NAME feed_modes COMMAND test_feed_modes
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# IBKR routing safety: live refused while the gate is closed, and every IBKR
# order passes the RiskGate in the routing path (no bypass). No socket opened.
add_executable(test_ibkr_routing test_ibkr_routing.cpp)
target_link_libraries(test_ibkr_routing PRIVATE mal_execution mal_risk
                      mal_config mal_util)
add_test(NAME ibkr_routing COMMAND test_ibkr_routing
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Operator kill-switch wiring: the engine consumes the GUI/API kill-request
# control file and trips the same latching kill switch; stale/archived files
# never re-trip; manual resume still required. Offline synthetic feed, temp DB.
add_executable(test_kill_switch test_kill_switch.cpp)
target_link_libraries(test_kill_switch PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_storage mal_risk mal_config mal_util)
add_test(NAME kill_switch COMMAND test_kill_switch
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# native_conviction_feeds_gate composition (Task 3): flag ON feeds the native
# rule_based conviction into the gate confidence/edge, OFF takes them from the
# advisory factors alone. Direction and agreement stay unchanged. No RiskGate.
add_executable(test_native_conviction_gate test_native_conviction_gate.cpp)
target_link_libraries(test_native_conviction_gate PRIVATE mal_signal_engine)
add_test(NAME native_conviction_gate COMMAND test_native_conviction_gate
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Fast-tier native confidence: the council-skipped fast tier must NOT let the
# un-consulted neutral LLM mocks drag a genuine native conviction below the
# RiskGate floor, while a genuinely weak advisory read still blocks (no forced
# trades) and the council tier stays the full-ensemble blend.
add_executable(test_fast_tier_confidence test_fast_tier_confidence.cpp)
target_link_libraries(test_fast_tier_confidence PRIVATE mal_signal_engine)
add_test(NAME fast_tier_confidence COMMAND test_fast_tier_confidence
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Per-layer toggles (controls.json): read defaults all ON on a missing/malformed
# file, explicit toggles are respected, a layer off drops its factor, and
# rule_based (safety-adjacent) is never gated so the RiskGate is unaffected.
add_executable(test_layer_toggles test_layer_toggles.cpp)
target_link_libraries(test_layer_toggles PRIVATE mal_core mal_util)
add_test(NAME layer_toggles COMMAND test_layer_toggles
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Strict mode (Task 3): on feed_mode alpaca_paper a layer set on-real with no
# reachable real service makes the engine refuse to start; on-mock is an
# explicit choice and starts; offline feed modes are a no-op. No network.
add_executable(test_strict_mode test_strict_mode.cpp)
target_link_libraries(test_strict_mode PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_storage mal_risk mal_config mal_util)
add_test(NAME strict_mode COMMAND test_strict_mode
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Feed/clock runtime toggle (Task 3): read_feed_clock resolves each mode and
# keeps the launch fallback on a missing/invalid value; feed_switch_orphans_
# position enforces the open-position safety rule. Pure, header-only.
add_executable(test_feed_clock test_feed_clock.cpp)
target_link_libraries(test_feed_clock PRIVATE mal_bridge)
add_test(NAME feed_clock COMMAND test_feed_clock
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Warm-start (Task 1/2): the engine seeds indicators from the backfilled bars
# table; warm_states() reports WARM above the longest lookback and COLD below;
# the warm gate the entry path consults is the same pure predicate. Temp DB.
add_executable(test_warm_start test_warm_start.cpp)
target_link_libraries(test_warm_start PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_storage mal_risk mal_config mal_util)
add_test(NAME warm_start COMMAND test_warm_start
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Tuner floor (Task 1): the tuner never drives rule_based below the floor,
# compose_gate_verdict guarantees rule_based its min share, and a long synthetic
# run keeps generating native entries past 100 closed trades (no plateau).
add_executable(test_tuner_floor test_tuner_floor.cpp)
target_link_libraries(test_tuner_floor PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_learning mal_storage mal_risk
                      mal_config mal_util)
add_test(NAME tuner_floor COMMAND test_tuner_floor
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Market-hours entry gate: outside US regular hours an equity takes no entry (fast
# tier and council tier both), exits on an open equity position still run, and
# crypto is unaffected 24/7. Pure helper plus deterministic engine runs (a crafted
# replay for the off-hours exit, a synthetic run for the no-off-hours-entry rule).
add_executable(test_market_hours_entry test_market_hours_entry.cpp)
target_link_libraries(test_market_hours_entry PRIVATE mal_core mal_market_data
                      mal_signal_engine mal_learning mal_storage mal_risk
                      mal_config mal_util ${MAL_SQLITE_LIB})
add_test(NAME market_hours_entry COMMAND test_market_hours_entry
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Operator controls reader (Task 2): flat-key model toggles, clamped runtime
# budget, regime pins, and the at-least-one-provider rule. Pure, header-only.
add_executable(test_operator_controls test_operator_controls.cpp)
target_link_libraries(test_operator_controls PRIVATE mal_bridge)
add_test(NAME operator_controls COMMAND test_operator_controls
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Time modes (Task 3 + 4): iso8601_to_epoch round-trip for replay cooldown
# spacing, and us_equity_market_open honoring the explicit time for the
# simulated-clock market-hours skip.
add_executable(test_time_modes test_time_modes.cpp)
target_link_libraries(test_time_modes PRIVATE mal_util)
add_test(NAME time_modes COMMAND test_time_modes
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Bar provenance (2026-07-18): the entry gate refuses synthetic/unknown bars on
# the real path, normalization never invents realness, and the storage round
# trip persists sources with no default to real.
add_executable(test_provenance test_provenance.cpp)
target_link_libraries(test_provenance PRIVATE mal_storage mal_util
                      ${MAL_SQLITE_LIB})
add_test(NAME provenance COMMAND test_provenance
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# The real path never fabricates (2026-07-20): AlpacaFeed with the bridge down
# yields NO ticks instead of a synthetic walk. Mutation killer for the
# fabrication removal. Loopback only, nothing binds, no network.
add_executable(test_feed_no_fabrication test_feed_no_fabrication.cpp)
target_link_libraries(test_feed_no_fabrication PRIVATE mal_market_data
                      mal_bridge mal_util)
add_test(NAME feed_no_fabrication COMMAND test_feed_no_fabrication
         WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
