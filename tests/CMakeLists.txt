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
