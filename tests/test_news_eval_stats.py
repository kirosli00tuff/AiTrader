"""Tests for news_eval/stats.py (STAGE C.1 Task 3). Synthetic toys only.

Bars and draw counts here are literals for the arithmetic under test; the
registered values live in news_eval/constants.py and are pinned elsewhere.
"""
from __future__ import annotations

import itertools
import math
from fractions import Fraction

import numpy as np
import pytest

from news_eval import stats

BAR = 2.50
BAR_S = 2.24
N_DRAWS = 10_000


# ------------------------------------------------------------------ helpers

def _mc_tolerance(prob: float, n: int) -> float:
    """4.5 binomial standard errors around a probability, plus rounding slack."""
    return 4.5 * math.sqrt(max(prob * (1.0 - prob), 1e-12) / n) + 1e-12


def _exact_null(excess, labels, strata, mode, groups=None):
    """Every arrangement the within-stratum null allows, each equally likely.

    Built independently of stats.py: blocks are (stratum, group) with unshared
    rows alone; within each (stratum, block size) class every ordering of the
    blocks' label vectors is enumerated, and classes combine by product.
    """
    bp = 10_000.0 * np.asarray(excess, dtype=float)
    lab = np.asarray(labels)
    blocks: dict = {}
    for i, s in enumerate(strata):
        g = None if groups is None else groups[i]
        key = (s, ("row", i) if g in (None, "") else ("g", g))
        blocks.setdefault(key, []).append(i)
    classes: dict = {}
    for (s, _), rows in blocks.items():
        classes.setdefault((s, len(rows)), []).append(rows)
    per_class = []
    for rows_list in classes.values():
        vectors = [lab[r].copy() for r in rows_list]
        per_class.append([
            [(rows_list[j], vectors[perm[j]]) for j in range(len(rows_list))]
            for perm in itertools.permutations(range(len(rows_list)))])

    def stat(arr):
        if mode == stats.MODE_SUBSET:
            return float(np.mean(arr * bp))
        return float(np.mean(-bp[arr == -1]))

    values = []
    for combo in itertools.product(*per_class):
        new = lab.copy()
        for assignment in combo:
            for rows, vec in assignment:
                new[rows] = vec
        values.append(stat(new))
    return np.array(values), stat(lab)


def _assert_mc_matches_exact(result, t_all, t_obs):
    p_ge = float(np.mean(t_all >= t_obs))
    p_le = float(np.mean(t_all <= t_obs))
    p_exact = min(1.0, 2.0 * min(p_ge, p_le))
    n = result.n_perm
    assert result.t_obs == pytest.approx(t_obs, rel=1e-12, abs=1e-12)
    assert abs(result.count_ge / n - p_ge) <= _mc_tolerance(p_ge, n)
    assert abs(result.count_le / n - p_le) <= _mc_tolerance(p_le, n)
    p_min = min(p_ge, p_le)
    assert abs(result.p - p_exact) <= 2 * _mc_tolerance(p_min, n) + 2.0 / (n + 1)
    if abs(p_ge - p_le) > 0.05:
        assert result.upper_tail == (p_ge < p_le)
    return p_exact


# ----------------------------------------------------------- normal, no scipy

def test_normal_cdf_known_values():
    assert stats.normal_cdf(2.5) == pytest.approx(0.9937903346742238, rel=1e-14)
    assert stats.normal_cdf(0.0) == 0.5
    assert stats.normal_cdf(-1.959963984540054) == pytest.approx(0.025, rel=1e-12)
    assert stats.normal_cdf(-2.5) == pytest.approx(1 - 0.9937903346742238, rel=1e-12)


def test_normal_quantile_known_values_and_round_trip():
    assert stats.normal_quantile(0.975) == pytest.approx(1.959963984540054, abs=1e-12)
    assert stats.normal_quantile(0.5) == pytest.approx(0.0, abs=1e-15)
    assert stats.normal_quantile(0.99) == pytest.approx(2.3263478740408408, abs=1e-12)
    assert stats.normal_quantile(0.9937903346742238) == pytest.approx(2.5, abs=1e-12)
    for p in (1e-10, 0.001, 0.02, 0.3, 0.7, 0.98, 0.999999):
        assert stats.normal_cdf(stats.normal_quantile(p)) == pytest.approx(p, rel=1e-11)
    with pytest.raises(ValueError):
        stats.normal_quantile(1.0)


# -------------------------------------------------------------------- 9.4

def test_signed_bp_hand_values():
    out = stats.signed_bp([0.001, -0.002, 0.003], np.array([True, False, False]))
    assert out.tolist() == pytest.approx([10.0, 20.0, -30.0])
    assert stats.observation_weighted_mean(out) == pytest.approx(0.0, abs=1e-12)


def test_signed_bp_refuses_integer_labels():
    with pytest.raises(ValueError):
        stats.signed_bp([0.001, 0.002], np.array([1, -1]))


def test_observation_weighted_mean_is_not_mean_of_cluster_means():
    values = [10.0, 20.0, 30.0]
    clusters = ["a", "a", "b"]
    mean_of_cluster_means = (15.0 + 30.0) / 2
    t = stats.observation_weighted_mean(values)
    assert t == 20.0 and t != mean_of_cluster_means
    boot = stats.cluster_bootstrap_ratio(values, clusters, n_draws=100,
                                         rng=np.random.default_rng(1), bar=BAR)
    assert boot.statistic == 20.0
    assert stats.cr1_mean(values, clusters).statistic == 20.0
    perm = stats.permutation_test([0.001, 0.002, 0.003], [1, 1, 1], clusters,
                                  mode=stats.MODE_SUBSET, n_perm=10,
                                  rng=np.random.default_rng(1))
    assert perm.t_obs == pytest.approx(20.0)


# ---------------------------------------------------------- 9.5 bootstrap

def test_bootstrap_hand_toy_two_unequal_clusters():
    # Draw support: (2,0) -> 15, (1,1) -> 20, (0,2) -> 30 w.p. 1/4, 1/2, 1/4.
    res = stats.cluster_bootstrap_ratio([10.0, 20.0, 30.0], ["a", "a", "b"],
                                        n_draws=N_DRAWS,
                                        rng=np.random.default_rng(7), bar=BAR)
    assert res.ok and res.statistic == 20.0
    assert set(np.unique(res.replicates).tolist()) <= {15.0, 20.0, 30.0}
    freq = [np.mean(res.replicates == v) for v in (15.0, 20.0, 30.0)]
    assert freq == pytest.approx([0.25, 0.5, 0.25], abs=0.02)
    assert res.se == pytest.approx(math.sqrt(29.6875), rel=0.03)
    assert res.se == float(np.std(res.replicates, ddof=1))
    assert res.z == res.statistic / res.se
    assert res.lower == res.statistic - BAR * res.se
    assert res.upper == res.statistic + BAR * res.se
    assert res.lower_above_zero is True
    q = np.quantile(res.replicates, [stats.normal_cdf(-BAR), stats.normal_cdf(BAR)])
    assert (res.percentile_lower, res.percentile_upper) == (q[0], q[1])
    assert res.percentile_label == "descriptive"
    assert res.percentile_coverage == pytest.approx(0.98758, abs=1e-5)
    assert (res.n_clusters, res.n_obs, res.n_undefined) == (2, 3, 0)


def test_bootstrap_lower_bound_not_above_zero_when_interval_spans_zero():
    res = stats.cluster_bootstrap_ratio([5.0, -4.0, 3.0, -3.5], ["a", "b", "c", "d"],
                                        n_draws=2000, rng=np.random.default_rng(3),
                                        bar=BAR)
    assert res.ok and res.lower_above_zero is False and res.lower < 0 < res.upper


def test_bootstrap_one_cluster_is_degenerate_and_draws_nothing():
    rng = np.random.default_rng(5)
    before = rng.bit_generator.state
    res = stats.cluster_bootstrap_ratio([1.0, 2.0, 3.0], ["a", "a", "a"],
                                        n_draws=100, rng=rng, bar=BAR)
    assert res.status == stats.STATUS_DEGENERATE and not res.ok
    assert res.statistic is None and res.se is None and res.z is None
    assert res.lower is None and res.upper is None
    assert rng.bit_generator.state == before
    with pytest.raises(stats.DegenerateRefusal):
        res.require_ok()


def test_bootstrap_zero_se_is_degenerate_exact_and_rounding():
    exact = stats.cluster_bootstrap_ratio([1.0, 3.0, 2.0, 2.0], ["a", "a", "b", "b"],
                                          n_draws=200, rng=np.random.default_rng(2),
                                          bar=BAR)
    assert exact.status == stats.STATUS_DEGENERATE and exact.se is None
    assert exact.reason == "bootstrap SE is zero"
    rounding = stats.cluster_bootstrap_ratio([0.1] * 7, list("aaabbbb"), n_draws=200,
                                             rng=np.random.default_rng(2), bar=BAR)
    assert rounding.status == stats.STATUS_DEGENERATE and rounding.z is None


def _random_toy(seed: int, n_clusters: int = 7):
    rng = np.random.default_rng(seed)
    sizes = rng.integers(1, 7, size=n_clusters)
    clusters = np.repeat([f"2026-09-{i + 10:02d}" for i in range(n_clusters)], sizes)
    y = rng.normal(3.0, 40.0, size=clusters.size)
    return y, clusters


def test_bootstrap_matches_bruteforce_expansion_on_same_draws():
    y, clusters = _random_toy(11)
    labels, inverse = stats.cluster_index(clusters)
    res = stats.cluster_bootstrap_ratio(y, clusters, n_draws=3000,
                                        rng=np.random.default_rng(42), bar=BAR)
    brute = []
    for counts in stats.cluster_draw_counts(np.random.default_rng(42),
                                            labels.size, 3000):
        for w in counts:
            assert w.sum() == labels.size
            brute.append(np.repeat(y, w[inverse]).mean())
    np.testing.assert_allclose(res.replicates, brute, rtol=1e-12, atol=1e-12)
    assert res.se == pytest.approx(float(np.std(brute, ddof=1)), rel=1e-10)
    q = np.quantile(brute, [stats.normal_cdf(-BAR), stats.normal_cdf(BAR)])
    assert res.percentile_lower == pytest.approx(q[0], rel=1e-12)
    assert res.percentile_upper == pytest.approx(q[1], rel=1e-12)
    assert res.percentile_lower != pytest.approx(float(np.quantile(brute, 0.025)))


def test_bootstrap_se_matches_independent_cluster_resampling_loop():
    # Statistical agreement: the brute force draws its own cluster ids with
    # replacement (rng.integers), so the draws are not shared. 10,000 each.
    y, clusters = _random_toy(12)
    labels, inverse = stats.cluster_index(clusters)
    res = stats.cluster_bootstrap_ratio(y, clusters, n_draws=N_DRAWS,
                                        rng=np.random.default_rng(8), bar=BAR)
    rng = np.random.default_rng(9)
    members = [y[inverse == c] for c in range(labels.size)]
    brute = []
    for _ in range(N_DRAWS):
        ids = rng.integers(0, labels.size, size=labels.size)
        brute.append(np.concatenate([members[i] for i in ids]).mean())
    assert res.se == pytest.approx(float(np.std(brute, ddof=1)), rel=0.05)


def test_bootstrap_rng_consumption_order_is_one_multinomial_per_draw():
    y, clusters = _random_toy(13)
    c = stats.cluster_index(clusters)[0].size
    rng_a, rng_b = np.random.default_rng(77), np.random.default_rng(77)
    stats.cluster_bootstrap_ratio(y, clusters, n_draws=1234, rng=rng_a, bar=BAR)
    rng_b.multinomial(c, np.full(c, 1.0 / c), size=1234)
    assert rng_a.random() == rng_b.random()


def test_bootstrap_is_chunk_invariant_and_deterministic(monkeypatch):
    y, clusters = _random_toy(14)
    base = stats.cluster_bootstrap_ratio(y, clusters, n_draws=1500,
                                         rng=np.random.default_rng(3), bar=BAR)
    again = stats.cluster_bootstrap_ratio(y, clusters, n_draws=1500,
                                          rng=np.random.default_rng(3), bar=BAR)
    monkeypatch.setattr(stats, "BOOT_CHUNK", 7)
    small = stats.cluster_bootstrap_ratio(y, clusters, n_draws=1500,
                                          rng=np.random.default_rng(3), bar=BAR)
    np.testing.assert_array_equal(base.replicates, again.replicates)
    np.testing.assert_array_equal(base.replicates, small.replicates)


# ------------------------------------------------------------ Spearman, S1

def test_average_ranks_hand():
    assert stats.average_ranks([10, 20, 20, 5]).tolist() == [2.0, 3.5, 3.5, 1.0]


def test_spearman_with_ties_hand_value():
    # ranks x = [1, 2.5, 2.5, 4], y = [1, 3, 2, 4]: cov 4.5, vx 4.5, vy 5.
    assert stats.spearman([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(
        3 / math.sqrt(10), rel=1e-14)
    assert stats.spearman([1, 2, 3], [5, 6, 9]) == pytest.approx(1.0)
    assert stats.spearman([1, 2, 3], [9, 6, 5]) == pytest.approx(-1.0)
    assert stats.spearman([2, 2, 2], [1, 2, 3]) is None


def test_weighted_spearman_equals_repeat_expansion():
    rng = np.random.default_rng(21)
    for _ in range(200):
        n = int(rng.integers(3, 30))
        x = rng.integers(1, 6, size=n).astype(float)
        y = np.round(rng.normal(0, 3, size=n))  # rounding forces ties
        w = rng.integers(0, 4, size=n)
        expanded = stats.spearman(np.repeat(x, w), np.repeat(y, w))
        weighted = stats.weighted_spearman(x, y, w)
        if expanded is None:
            assert weighted is None
        else:
            assert weighted == pytest.approx(expanded, rel=1e-12, abs=1e-12)


def test_spearman_bootstrap_replicates_equal_per_draw_weighted_spearman():
    rng = np.random.default_rng(31)
    clusters = np.repeat(np.arange(6), [3, 1, 4, 2, 5, 3])
    x = rng.integers(1, 6, size=clusters.size).astype(float)
    y = np.round(rng.normal(0, 20, size=clusters.size), 1)
    labels, inverse = stats.cluster_index(clusters)
    res = stats.spearman_bootstrap(x, y, clusters, n_draws=800,
                                   rng=np.random.default_rng(5), bar=BAR_S)
    assert res.ok and res.statistic == stats.spearman(x, y)
    expected = []
    for counts in stats.cluster_draw_counts(np.random.default_rng(5), labels.size, 800):
        for w in counts:
            v = stats.weighted_spearman(x, y, w[inverse])
            expected.append(np.nan if v is None else v)
    np.testing.assert_allclose(res.replicates, expected, rtol=1e-12, atol=1e-12)
    assert res.bar == BAR_S
    assert res.lower == res.statistic - BAR_S * res.se
    assert res.upper == res.statistic + BAR_S * res.se
    assert res.percentile_coverage == pytest.approx(
        stats.normal_cdf(BAR_S) - stats.normal_cdf(-BAR_S))


def test_spearman_bootstrap_counts_undefined_replicates():
    # Each cluster carries one strength, so a draw of a single cluster has zero
    # rank variance in strength and is undefined (probability 3/27).
    x = np.array([1, 1, 5, 5, 3, 3], dtype=float)
    y = np.array([-4.0, 2.0, 9.0, 1.0, 0.5, -1.5])
    clusters = ["a", "a", "b", "b", "c", "c"]
    res = stats.spearman_bootstrap(x, y, clusters, n_draws=3000,
                                   rng=np.random.default_rng(6), bar=BAR_S)
    single = sum(int(np.sum((counts > 0).sum(axis=1) == 1)) for counts in
                 stats.cluster_draw_counts(np.random.default_rng(6), 3, 3000))
    assert res.ok and res.n_undefined == single > 0
    assert res.n_defined + res.n_undefined == 3000
    assert int(np.isnan(res.replicates).sum()) == single
    defined = res.replicates[~np.isnan(res.replicates)]
    assert res.se == float(np.std(defined, ddof=1))


def test_spearman_bootstrap_observed_zero_variance_is_degenerate():
    rng = np.random.default_rng(1)
    before = rng.bit_generator.state
    res = stats.spearman_bootstrap([3, 3, 3, 3], [1.0, 2.0, 3.0, 4.0], list("aabb"),
                                   n_draws=100, rng=rng, bar=BAR_S)
    assert res.status == stats.STATUS_DEGENERATE and res.statistic is None
    assert rng.bit_generator.state == before


# --------------------------------------------------------------------- S2

def test_top_bottom_hand_value_and_bruteforce_draws():
    strength = np.array([5, 4, 1, 2, 3, 4, 1, 5], dtype=float)
    y = np.array([10.0, 20.0, -10.0, 0.0, 99.0, 30.0, -6.0, 2.0])
    clusters = np.array(["a", "a", "b", "b", "c", "c", "d", "d"])
    res = stats.top_bottom_bootstrap(strength, y, clusters, top_strengths=(4, 5),
                                     bottom_strengths=(1, 2), n_draws=500,
                                     rng=np.random.default_rng(4), bar=BAR_S)
    assert res.statistic == pytest.approx((10 + 20 + 30 + 2) / 4 - (-10 + 0 - 6) / 3)
    labels, inverse = stats.cluster_index(clusters)
    top, bot = np.isin(strength, (4, 5)), np.isin(strength, (1, 2))
    expected = []
    for counts in stats.cluster_draw_counts(np.random.default_rng(4), labels.size, 500):
        for w in counts:
            wo = w[inverse]
            yt, yb = np.repeat(y[top], wo[top]), np.repeat(y[bot], wo[bot])
            expected.append(np.nan if yt.size == 0 or yb.size == 0
                            else yt.mean() - yb.mean())
    np.testing.assert_allclose(res.replicates, expected, rtol=1e-12, atol=1e-12)
    assert res.n_undefined == int(np.isnan(expected).sum()) > 0


def test_top_bottom_empty_pool_abstains_without_drawing():
    rng = np.random.default_rng(2)
    before = rng.bit_generator.state
    res = stats.top_bottom_bootstrap([4, 5, 3, 3], [1.0, 2.0, 3.0, 4.0], list("abab"),
                                     top_strengths=(4, 5), bottom_strengths=(1, 2),
                                     n_draws=100, rng=rng, bar=BAR_S)
    assert res.status == stats.STATUS_ABSTAIN_EMPTY_POOL and res.statistic is None
    assert rng.bit_generator.state == before
    with pytest.raises(ValueError):
        stats.top_bottom_bootstrap([4, 1], [1.0, 2.0], ["a", "b"], top_strengths=(4,),
                                   bottom_strengths=(4, 1), n_draws=10,
                                   rng=np.random.default_rng(0), bar=BAR_S)


# ------------------------------------------------------------- 9.8 gate

def _icc_reference(y_bp, clusters):
    ys = [Fraction(float(v)) for v in y_bp]
    groups: dict = {}
    for v, c in zip(ys, clusters):
        groups.setdefault(c, []).append(v)
    n, k = len(ys), len(groups)
    grand = sum(ys) / n
    means = {c: sum(v) / len(v) for c, v in groups.items()}
    msb = sum(len(v) * (means[c] - grand) ** 2 for c, v in groups.items()) / (k - 1)
    msw = sum((x - means[c]) ** 2 for c, v in groups.items() for x in v) / (n - k)
    n0 = (n - Fraction(sum(len(v) ** 2 for v in groups.values()), n)) / (k - 1)
    rho = (msb - msw) / (msb + (n0 - 1) * msw)
    var = sum((x - grand) ** 2 for x in ys) / (n - 1)
    return float(msb), float(msw), float(n0), float(rho), math.sqrt(float(var))


GATE_EXCESS = [0.0010, 0.0020, 0.0030, 0.0040, 0.0060, 0.0100, -0.0050, 0.0012]
GATE_CLUSTERS = ["a", "a", "a", "b", "b", "c", "d", "d"]


def test_gate_icc_matches_exact_fraction_reference():
    y_bp = stats.BP_PER_UNIT * np.array(GATE_EXCESS)
    msb, msw, n0, rho, sigma = _icc_reference(y_bp, GATE_CLUSTERS)
    res = stats.gate_quantities(GATE_EXCESS, GATE_CLUSTERS, {"a": 2, "b": 1, "c": 1},
                                power_constant=11.156, effect_bp=30.0,
                                min_clusters=60, min_directional=1000)
    assert res.ok
    assert res.msb == pytest.approx(msb, rel=1e-12)
    assert res.msw == pytest.approx(msw, rel=1e-12)
    assert res.n0 == pytest.approx(n0, rel=1e-12)
    assert res.rho_raw == pytest.approx(rho, rel=1e-12)
    assert res.rho == max(0.0, res.rho_raw)
    assert res.sigma == pytest.approx(sigma, rel=1e-12)
    assert (res.n_rows, res.n_clusters_gate) == (8, 4)
    assert (res.n_clusters_directional, res.n_directional) == (3, 4)
    assert res.k_eff == pytest.approx((4 + 1 + 1) / 4)
    expected = 11.156 * (res.sigma / 30.0) ** 2 * (1 + (res.k_eff - 1) * res.rho)
    assert res.required == pytest.approx(expected, rel=1e-14)
    assert res.passed is False
    assert any(f.startswith("C_dir 3 < 60") for f in res.failing)
    assert any(f.startswith("M 4 < 1000") for f in res.failing)


def test_gate_passes_when_every_condition_holds():
    small = [e / 100.0 for e in GATE_EXCESS]  # rho is scale-free, Required shrinks
    res = stats.gate_quantities(small, GATE_CLUSTERS, [2, 1, 1, 0],
                                power_constant=11.156, effect_bp=30.0,
                                min_clusters=3, min_directional=4)
    assert res.ok and res.required < 4 and res.passed and res.failing == ()
    assert res.n_clusters_directional == 3


def test_gate_fails_on_required_alone():
    res = stats.gate_quantities(GATE_EXCESS, GATE_CLUSTERS, [2, 1, 1, 0],
                                power_constant=11.156, effect_bp=30.0,
                                min_clusters=3, min_directional=4)
    assert res.ok and res.required > 4 and res.passed is False
    assert len(res.failing) == 1 and res.failing[0].startswith("M 4 < Required")


def test_gate_rho_floored_at_zero_on_negative_raw_icc():
    # Cluster means equal (5 bp), so MSB is about 0 and the raw ICC is negative.
    excess = np.array([0, 10, 1, 9, 4, 6]) / 10_000.0
    res = stats.gate_quantities(excess, list("aabbcc"), {"a": 1, "b": 1},
                                power_constant=11.156, effect_bp=30.0,
                                min_clusters=60, min_directional=1000)
    assert res.ok and res.rho_raw < 0 and res.rho == 0.0
    assert res.required == pytest.approx(11.156 * (res.sigma / 30.0) ** 2)


@pytest.mark.parametrize("excess,clusters,counts,reason", [
    ([0.001, 0.002], ["a", "a"], {"a": 1}, "fewer than 2 gate clusters"),
    ([0.001, 0.002], ["a", "b"], {"a": 1}, "N - C_G < 1"),
    ([0.001] * 4, list("aabb"), {"a": 1}, "every gate value is equal"),
    ([0.001, 0.002, 0.004], list("aab"), {}, "no directional rows"),
])
def test_gate_degenerate_refusals(excess, clusters, counts, reason):
    res = stats.gate_quantities(excess, clusters, counts, power_constant=11.156,
                                effect_bp=30.0, min_clusters=60, min_directional=1000)
    assert res.status == stats.STATUS_DEGENERATE and res.reason.startswith(reason)
    assert res.rho is None and res.required is None and res.passed is False


def test_gate_rejects_directional_cluster_without_gate_rows():
    with pytest.raises(ValueError):
        stats.gate_quantities([0.001, 0.002, 0.003], list("aab"), {"zz": 1},
                              power_constant=11.156, effect_bp=30.0,
                              min_clusters=60, min_directional=1000)


# --------------------------------------------------------------- 9.10 CR1

def test_cr1_hand_computation():
    # T = 3; residuals [-2, -1, 0, 3]; cluster sums -3, 3; V = 2 x 18 / 16.
    res = stats.cr1_mean([1.0, 2.0, 3.0, 6.0], ["a", "a", "b", "b"])
    assert res.ok and res.statistic == 3.0
    assert res.se == pytest.approx(1.5, rel=1e-14)
    assert res.z == pytest.approx(2.0, rel=1e-14)


def test_cr1_degenerate_cases():
    assert stats.cr1_mean([1.0, 2.0], ["a", "a"]).status == stats.STATUS_DEGENERATE
    zero = stats.cr1_mean([0.3] * 6, list("aabbcc"))
    assert zero.status == stats.STATUS_DEGENERATE and zero.se is None


# ------------------------------------------------ Amendment 6 permutation null

SUB_EXCESS = [0.004, 0.0015, -0.002, -0.0035, 0.003, -0.001, 0.0025, -0.004, 0.0005]
SUB_STRATA = ["s1"] * 4 + ["s2"] * 5


def test_permutation_subset_mode_matches_exact_enumeration():
    labels = [1, -1, 1, -1, 1, -1, 1, -1, 1]  # 2 of 4 and 3 of 5 positive
    t_all, t_obs = _exact_null(SUB_EXCESS, labels, SUB_STRATA, stats.MODE_SUBSET)
    assert t_all.size == math.factorial(4) * math.factorial(5)
    res = stats.permutation_test(SUB_EXCESS, labels, SUB_STRATA,
                                 mode=stats.MODE_SUBSET, n_perm=N_DRAWS,
                                 rng=np.random.default_rng(101))
    assert res.ok and not res.blocked
    _assert_mc_matches_exact(res, t_all, t_obs)


def test_permutation_subset_mode_strong_signal_upper_tail():
    labels = [1, 1, -1, -1, 1, -1, 1, -1, 1]  # labels track the excess sign
    t_all, t_obs = _exact_null(SUB_EXCESS, labels, SUB_STRATA, stats.MODE_SUBSET)
    res = stats.permutation_test(SUB_EXCESS, labels, SUB_STRATA,
                                 mode=stats.MODE_SUBSET, n_perm=N_DRAWS,
                                 rng=np.random.default_rng(102))
    p_exact = _assert_mc_matches_exact(res, t_all, t_obs)
    assert p_exact < 0.05 and res.upper_tail is True
    assert res.p == min(1.0, 2.0 * (1 + res.count_ge) / (N_DRAWS + 1))


def test_permutation_negative_only_matches_exact_enumeration():
    labels = [-1, 1, -1, 1, -1, -1, 1, -1, 1]  # 2 of 4 and 3 of 5 NEGATIVE
    t_all, t_obs = _exact_null(SUB_EXCESS, labels, SUB_STRATA, stats.MODE_NEGATIVE_ONLY)
    res = stats.permutation_test(SUB_EXCESS, labels, SUB_STRATA,
                                 mode=stats.MODE_NEGATIVE_ONLY, n_perm=N_DRAWS,
                                 rng=np.random.default_rng(103))
    assert res.ok and res.n_negative == 5
    _assert_mc_matches_exact(res, t_all, t_obs)


def test_permutation_block_version_one_group_matches_exact_enumeration():
    excess = [0.003, 0.002, -0.001, 0.004, -0.003, 0.001, -0.002, 0.0035, -0.0005]
    labels = [1, 1, -1, 1, -1, 1, -1, 1, -1]
    strata = ["s1"] * 5 + ["s2"] * 4
    groups = ["g1", "g1", "", "", None, "", "", "", ""]
    t_all, t_obs = _exact_null(excess, labels, strata, stats.MODE_SUBSET, groups)
    assert t_all.size == math.factorial(3) * math.factorial(4)
    res = stats.permutation_test(excess, labels, strata, mode=stats.MODE_SUBSET,
                                 n_perm=N_DRAWS, rng=np.random.default_rng(104),
                                 story_groups=groups)
    assert res.ok and res.blocked and res.n_blocks == 8
    _assert_mc_matches_exact(res, t_all, t_obs)


def test_permutation_block_version_two_groups_swap_whole_blocks():
    excess = [0.003, -0.002, 0.001, 0.004, -0.003, 0.002, -0.002, 0.0035, -0.0005, 0.001]
    labels = [1, -1, 1, 1, -1, -1, 1, -1, 1, -1]
    strata = ["s1"] * 6 + ["s2"] * 4
    groups = ["g1", "g1", "g2", "g2", "", "", "", "", "", ""]
    for mode, seed in ((stats.MODE_SUBSET, 105), (stats.MODE_NEGATIVE_ONLY, 106)):
        t_all, t_obs = _exact_null(excess, labels, strata, mode, groups)
        assert t_all.size == 2 * 2 * math.factorial(4)
        res = stats.permutation_test(excess, labels, strata, mode=mode,
                                     n_perm=N_DRAWS, rng=np.random.default_rng(seed),
                                     story_groups=groups)
        _assert_mc_matches_exact(res, t_all, t_obs)
    seen = set()
    for chunk in stats.permuted_label_chunks(labels, strata, n_perm=500,
                                             rng=np.random.default_rng(9),
                                             story_groups=groups):
        for row in chunk:
            pair = (tuple(row[0:2]), tuple(row[2:4]))
            assert pair in {((1, -1), (1, 1)), ((1, 1), (1, -1))}
            seen.add(pair)
            assert sorted(row[4:6]) == [-1, -1]
            assert sorted(row[6:]) == sorted(labels[6:])
    assert len(seen) == 2


def test_permutation_block_split_across_strata_is_per_stratum():
    labels = [1, -1, 1, -1]
    res = stats.permutation_test([0.001, 0.002, 0.003, 0.004], labels,
                                 ["s1", "s1", "s2", "s2"], mode=stats.MODE_SUBSET,
                                 n_perm=50, rng=np.random.default_rng(1),
                                 story_groups=["g", "", "g", ""])
    assert res.n_blocks == 4 and res.n_strata == 2


def test_permuted_labels_hold_each_stratum_count_exactly():
    rng = np.random.default_rng(55)
    strata = rng.choice(["d1", "d2", "d3", "d4"], size=40)
    labels = rng.choice([1, -1], size=40)
    for chunk in stats.permuted_label_chunks(labels, strata, n_perm=2000,
                                             rng=np.random.default_rng(56)):
        for s in ("d1", "d2", "d3", "d4"):
            mask = strata == s
            assert np.all((chunk[:, mask] == 1).sum(axis=1) == (labels[mask] == 1).sum())
    shuffled = next(stats.permuted_label_chunks(labels, strata, n_perm=50,
                                                rng=np.random.default_rng(57)))
    assert np.any(shuffled != labels)


def test_shuffling_across_strata_gives_a_different_p_than_within():
    # Each stratum is unanimous with constant excess: the within-day null is
    # degenerate (every draw equals T_obs), while a pooled shuffle is not.
    excess = [0.01] * 5 + [-0.01] * 5
    labels = [1] * 5 + [-1] * 5
    within = stats.permutation_test(excess, labels, ["d1"] * 5 + ["d2"] * 5,
                                    mode=stats.MODE_SUBSET, n_perm=N_DRAWS,
                                    rng=np.random.default_rng(61))
    across = stats.permutation_test(excess, labels, ["all"] * 10,
                                    mode=stats.MODE_SUBSET, n_perm=N_DRAWS,
                                    rng=np.random.default_rng(61))
    assert within.p == 1.0 and within.count_ge == within.count_le == N_DRAWS
    assert within.upper_tail is False  # equal counts are not the upper tail (9.3)
    assert across.p < 0.05 and across.upper_tail is True
    # Exact pooled tail: 1 arrangement in C(10, 5) = 252 reaches T_obs.
    assert across.count_ge / N_DRAWS == pytest.approx(1 / 252, abs=_mc_tolerance(1 / 252, N_DRAWS))


def test_permutation_counts_exact_ties_in_both_tails():
    # NEGATIVE at row 0 or row 2 gives the same exact sum (equal excess). A
    # plain float sum breaks that tie; the exact sums must not.
    excess = [0.001257, -0.001321, 0.001257, 0.001049]
    labels = [1, 1, -1, 1]
    bp = 10_000.0 * np.array(excess)
    assert np.sum(np.array(labels) * bp) != np.sum(np.array([-1, 1, 1, 1]) * bp)
    res = stats.permutation_test(excess, labels, ["d"] * 4, mode=stats.MODE_SUBSET,
                                 n_perm=4000, rng=np.random.default_rng(71))
    ties = sum(int(np.sum((chunk[:, 0] == -1) | (chunk[:, 2] == -1)))
               for chunk in stats.permuted_label_chunks(labels, ["d"] * 4, n_perm=4000,
                                                        rng=np.random.default_rng(71)))
    assert res.count_ge + res.count_le == 4000 + ties


def test_permutation_rng_consumption_and_chunk_invariance(monkeypatch):
    rng_a, rng_b = np.random.default_rng(81), np.random.default_rng(81)
    labels = [1, -1, 1, -1, 1, -1, 1, -1, 1]
    base = stats.permutation_test(SUB_EXCESS, labels, SUB_STRATA,
                                  mode=stats.MODE_SUBSET, n_perm=1500, rng=rng_a)
    rng_b.random((1500, 9))
    assert rng_a.random() == rng_b.random()
    monkeypatch.setattr(stats, "PERM_CHUNK", 3)
    small = stats.permutation_test(SUB_EXCESS, labels, SUB_STRATA,
                                   mode=stats.MODE_SUBSET, n_perm=1500,
                                   rng=np.random.default_rng(81))
    assert (base.count_ge, base.count_le, base.p) == (small.count_ge, small.count_le,
                                                      small.p)


def test_permutation_degenerate_and_invalid_inputs():
    rng = np.random.default_rng(3)
    before = rng.bit_generator.state
    res = stats.permutation_test([0.001, 0.002], [1, 1], ["d", "d"],
                                 mode=stats.MODE_NEGATIVE_ONLY, n_perm=100, rng=rng)
    assert res.status == stats.STATUS_DEGENERATE and res.p is None
    assert rng.bit_generator.state == before
    empty = stats.permutation_test([], [], [], mode=stats.MODE_SUBSET, n_perm=10, rng=rng)
    assert empty.status == stats.STATUS_DEGENERATE
    with pytest.raises(ValueError):
        stats.permutation_test([0.001], [0], ["d"], mode=stats.MODE_SUBSET, n_perm=10,
                               rng=rng)
    with pytest.raises(ValueError):
        stats.permutation_test([0.001], [True], ["d"], mode=stats.MODE_SUBSET,
                               n_perm=10, rng=rng)
    with pytest.raises(ValueError):
        stats.permutation_test([0.001], [1], ["d"], mode="pooled", n_perm=10, rng=rng)


def test_minority_share_and_mixed_hand():
    res = stats.minority_share_and_mixed([1, 1, 1, -1, 1, 1, -1, -1],
                                         list("aaaabbcc"))
    assert (res.n_positive, res.n_negative) == (5, 3)
    assert res.minority_share == pytest.approx(3 / 8)
    assert (res.n_mixed_strata, res.n_strata) == (1, 3)
    assert stats.minority_share_and_mixed([], []).minority_share is None


# --------------------------------------------------------------- 9.11 seeds

def test_child_streams_follow_seedsequence_spawn():
    seed = 20261010
    ref = [np.random.default_rng(c).random(4)
           for c in np.random.SeedSequence(seed).spawn(4)]
    got = [g.random(4) for g in stats.child_rngs(seed, 4)]
    for a, b in zip(ref, got):
        np.testing.assert_array_equal(a, b)
    wide = stats.child_rngs(seed, 28)[3].random(4)
    np.testing.assert_array_equal(wide, ref[3])
    np.testing.assert_array_equal(stats.child_rng(seed, 2).random(4), ref[2])
    assert not np.array_equal(ref[0], ref[1])


def test_p1_statistic_is_identical_in_bootstrap_and_permutation():
    rng = np.random.default_rng(5)
    excess = rng.normal(0, 0.02, size=30)
    labels = rng.choice([1, -1], size=30)
    strata = rng.choice(list("abcd"), size=30)
    y = stats.signed_bp(excess, labels == 1)
    boot = stats.cluster_bootstrap_ratio(y, strata, n_draws=50,
                                         rng=np.random.default_rng(1), bar=BAR)
    perm = stats.permutation_test(excess, labels, strata, mode=stats.MODE_SUBSET,
                                  n_perm=50, rng=np.random.default_rng(2))
    assert boot.statistic == perm.t_obs == stats.observation_weighted_mean(y)
