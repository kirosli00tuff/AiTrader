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
