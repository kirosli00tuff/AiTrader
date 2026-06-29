// Market AI Lab — news / catalyst ingestion (C++ core).
//
// The C++ core holds catalyst state; messy live API parsing is delegated to
// Python fetchers (news_ingestion/fetchers.py). For the offline demo this
// produces a deterministic catalyst score per symbol so the DNN/rule factors
// have a news context feature.
#pragma once

#include <string>
#include <vector>

namespace mal::news {

struct CatalystScore {
    std::string symbol;
    double score = 0.0;       // [-1,1] directional catalyst pressure
    double importance = 0.0;  // [0,1]
    std::string headline;
    std::string ts;
};

class CatalystProvider {
public:
    virtual ~CatalystProvider() = default;
    virtual CatalystScore score_for(const std::string& symbol) = 0;
};

// Deterministic mock catalyst provider (offline demo).
class MockCatalystProvider : public CatalystProvider {
public:
    explicit MockCatalystProvider(unsigned seed = 7) : seed_(seed) {}
    CatalystScore score_for(const std::string& symbol) override;

private:
    unsigned seed_;
};

}  // namespace mal::news
