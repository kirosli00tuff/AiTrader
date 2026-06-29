// Minimal dependency-free test helper (no gtest needed for CI portability).
#pragma once
#include <cmath>
#include <cstdio>
#include <string>

namespace maltest {
inline int g_failures = 0;

inline void check(bool cond, const std::string& msg) {
    if (!cond) {
        std::printf("  [FAIL] %s\n", msg.c_str());
        ++g_failures;
    } else {
        std::printf("  [ok]   %s\n", msg.c_str());
    }
}

inline void check_near(double a, double b, double eps, const std::string& msg) {
    check(std::fabs(a - b) <= eps, msg + " (got " + std::to_string(a) +
                                       ", want " + std::to_string(b) + ")");
}

inline int report(const char* suite) {
    if (g_failures == 0) {
        std::printf("[PASS] %s\n", suite);
        return 0;
    }
    std::printf("[FAILED] %s: %d failure(s)\n", suite, g_failures);
    return 1;
}
}  // namespace maltest
