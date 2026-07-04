# =============================================================================
# Market AI Lab — C++20 core build.
# Configures and builds all C++ library targets, the engine binary, and the
# CTest unit suite (RiskGate, config validation, weight normalization).
# Links system SQLite3 (libsqlite3-dev); falls back to a bundled amalgamation
# if a system SQLite is not found.
# =============================================================================
cmake_minimum_required(VERSION 3.16)
project(market_ai_lab LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(-Wall -Wextra)

# --- SQLite3: prefer system lib, else bundled amalgamation (third_party) ---
find_package(SQLite3 QUIET)
if(SQLite3_FOUND)
  message(STATUS "Using system SQLite3: ${SQLite3_VERSION}")
  set(MAL_SQLITE_LIB SQLite::SQLite3)
elseif(EXISTS "${CMAKE_SOURCE_DIR}/third_party/sqlite3/sqlite3.c")
  message(STATUS "Using bundled SQLite3 amalgamation")
  add_library(sqlite3_bundled STATIC third_party/sqlite3/sqlite3.c)
  target_include_directories(sqlite3_bundled PUBLIC third_party/sqlite3)
  set(MAL_SQLITE_LIB sqlite3_bundled)
else()
  message(FATAL_ERROR
    "SQLite3 not found. Install libsqlite3-dev or place the amalgamation in "
    "third_party/sqlite3/{sqlite3.c,sqlite3.h}.")
endif()

# All modules include headers via repo-root-relative paths ("config/config.hpp").
include_directories(${CMAKE_SOURCE_DIR})

# --- Core utility (shared) ---
add_library(mal_util STATIC core/util.cpp)

# --- Bridge client (RPC to Python bridge; POSIX sockets, no deps) ---
# Standalone so market_data / execution can call the bridge without depending on
# the whole core engine.
add_library(mal_bridge STATIC core/bridge_client.cpp)

# --- Config (typed config + YAML subset parser + validation) ---
add_library(mal_config STATIC config/config.cpp config/yaml.cpp)

# --- Storage (SQLite DAO) ---
add_library(mal_storage STATIC storage/storage.cpp)
target_link_libraries(mal_storage PUBLIC ${MAL_SQLITE_LIB})

# --- Risk (Layer 1) ---
add_library(mal_risk STATIC risk/risk_gate.cpp)
target_link_libraries(mal_risk PUBLIC mal_config)

# --- Signal engine (factor combination + weights + native strategy layer) ---
add_library(mal_signal_engine STATIC
  signal_engine/factor_engine.cpp signal_engine/strategy.cpp
  signal_engine/council_gate.cpp)
target_link_libraries(mal_signal_engine PUBLIC mal_config)

# --- Learning (Layer 2) ---
add_library(mal_learning STATIC learning/adaptive.cpp)
target_link_libraries(mal_learning PUBLIC mal_config mal_signal_engine)

# --- Market data / news / execution / account_manager ---
add_library(mal_market_data STATIC market_data/market_data.cpp)
target_link_libraries(mal_market_data PUBLIC mal_util mal_bridge)

add_library(mal_news STATIC news_ingestion/news_ingestion.cpp)
target_link_libraries(mal_news PUBLIC mal_util)

add_library(mal_execution STATIC execution/execution.cpp)
target_link_libraries(mal_execution PUBLIC mal_config mal_risk mal_util mal_bridge)

add_library(mal_account STATIC account_manager/account_manager.cpp)
target_link_libraries(mal_account PUBLIC mal_config)

# --- Core engine ---
add_library(mal_core STATIC core/engine.cpp)
target_link_libraries(mal_core PUBLIC
  mal_config mal_storage mal_risk mal_signal_engine mal_learning
  mal_market_data mal_news mal_execution mal_account mal_util mal_bridge)

# --- Engine binary ---
add_executable(mal_engine core/main.cpp)
target_link_libraries(mal_engine PRIVATE mal_core)

# --- Tests (CTest) ---
enable_testing()
add_subdirectory(tests)
