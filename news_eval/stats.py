"""Statistics core of the Stage C harness (EXPERIMENT.md Amendment 9, 6; Task 5).

Pure functions over numpy arrays: no database, no file I/O, no registered bar,
count or seed. Every bar, draw count, floor and seed is a parameter the caller
passes from news_eval.constants. The one imported number is BP_PER_UNIT, the
9.4 unit conversion.

Paragraph map
    9.4   signed_bp, observation_weighted_mean
    9.5   cluster_bootstrap_ratio, weighted_draw_bootstrap, cluster_draw_counts
    9.10  spearman_bootstrap (S1), top_bottom_bootstrap (S2), cr1_mean (sector)
    9.8   gate_quantities
    Amendment 6 with 9.3 and 9.9
          permutation_test, permuted_label_chunks, minority_share_and_mixed
    Task 5 (S1)  average_ranks, spearman, weighted_spearman
    9.11  child_rngs, child_rng
    normal_cdf, normal_quantile (no scipy)

No function here averages per-cluster means. Every statistic is
observation-weighted (9.4): a sum over observations divided by their count.

Random-number consumption (fixed; results are deterministic given the stream)
    Bootstrap (9.5, also S1 and S2). Clusters are indexed 0..C-1 in the sorted
    order of np.unique over the cluster labels. Draws come in consecutive
    chunks of m = min(BOOT_CHUNK, remaining) draws, each chunk ONE call
    rng.multinomial(C, np.full(C, 1.0 / C), size=m); row r is draw r's
    vector of cluster counts, summing to C. Nothing else touches rng. numpy
    fills the draws sequentially, so the replicates do not depend on
    BOOT_CHUNK (pinned by a test). A refusal decided before drawing
    (C < 2, an undefined observed statistic, an empty S2 pool) draws nothing.
    Permutation (Amendment 6). Blocks are listed in canonical order: stratum
    label (np.unique sorted order), then block size ascending, then the
    block's first row index ascending. In the plain null every row is its own
    block. Per chunk of m permutations, ONE call rng.random((m, n_blocks));
    entry [r, j] is block j's key in permutation r. Within each
    (stratum, block size) class, a stable argsort of that class's keys gives
    the permutation: the class's j-th block receives the label vector of its
    perm[j]-th block. Chunk size is min(PERM_CHUNK, MAX_CHUNK_ELEMENTS //
    n_obs) and does not change any result (pinned by a test). A degenerate
    input draws nothing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping, Sequence

import numpy as np

from news_eval.constants import BP_PER_UNIT

# Draws per multinomial call in the bootstrap. Memory only; results are
# chunk-invariant.
BOOT_CHUNK = 500
# Permutations per uniform-key call. Memory only; results are chunk-invariant.
PERM_CHUNK = 500
# Cap on the elements of any per-chunk (rows x observations) float64 array,
# 1e6 elements = 8 MB, so peak memory stays far below 200 MB at any n.
MAX_CHUNK_ELEMENTS = 1_000_000
# A standard error at or below ZERO_SE_RTOL x the data scale is float64
# rounding noise around an exact zero (rounding is near 1e-16 relative) and is
# treated as the 9.5 "SE of zero". A numerical floor, not a registered bar.
ZERO_SE_RTOL = 1e-12

STATUS_OK = "ok"
STATUS_DEGENERATE = "degenerate"
STATUS_ABSTAIN_EMPTY_POOL = "abstain_empty_pool"
PERCENTILE_LABEL = "descriptive"

MODE_SUBSET = "subset"
MODE_NEGATIVE_ONLY = "negative_only"
POSITIVE_LABEL = 1
NEGATIVE_LABEL = -1


class DegenerateRefusal(Exception):
    """Raised by require_ok() on a result whose status is not "ok" (9.5)."""


class _Status:
    status: str
    reason: str

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def require_ok(self):
        """Return self when status is "ok", else raise DegenerateRefusal."""
        if self.status != STATUS_OK:
            raise DegenerateRefusal(f"{self.status}: {self.reason}")
        return self


# ---------------------------------------------------------------- validation

def _as_float(name: str, values) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} holds a non-finite value")
    return arr


def _as_same_length(name: str, values, n: int) -> np.ndarray:
    arr = np.asarray(values)
    if arr.ndim != 1 or arr.size != n:
        raise ValueError(f"{name} must be one-dimensional with length {n}")
    return arr


def _as_labels(labels, n: int | None = None) -> np.ndarray:
    arr = np.asarray(labels)
    if arr.ndim != 1 or (n is not None and arr.size != n):
        raise ValueError("labels must be one-dimensional and match excess")
    if arr.dtype == bool or not np.all(np.isin(arr, (POSITIVE_LABEL, NEGATIVE_LABEL))):
        raise ValueError("labels must hold only +1 (POSITIVE) and -1 (NEGATIVE)")
    return arr.astype(np.int8)


def _check_bar(bar: float) -> float:
    bar = float(bar)
    if not (math.isfinite(bar) and bar > 0):
        raise ValueError("bar must be a positive finite number")
    return bar


def _check_count(name: str, value: int, minimum: int) -> int:
    if int(value) != value or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _chunk_rows(n_cols: int, cap: int) -> int:
    return max(1, min(cap, MAX_CHUNK_ELEMENTS // max(1, n_cols)))


def _exact_mean_rows(matrix: np.ndarray, denom: int) -> np.ndarray:
    """Per-row math.fsum / denom. fsum is the correctly rounded exact sum, so it
    does not depend on element order, and arrangements whose sums tie in exact
    arithmetic tie here too (Amendment 6 counts ties in both tails)."""
    return np.array([math.fsum(row) for row in matrix.tolist()],
                    dtype=np.float64) / denom


# ------------------------------------------------------------ normal (no scipy)

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)
# Acklam's rational approximation, refined below by two Halley steps.
_QA = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
       1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_QB = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
       6.680131188771972e+01, -1.328068155288572e+01)
_QC = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
       -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_QD = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
       3.754408661907416e+00)
_Q_LOW = 0.02425


def normal_cdf(x: float) -> float:
    """Standard normal CDF Phi(x) = erfc(-x / sqrt 2) / 2 (math only, no scipy).

    Used for the 9.5 descriptive percentile levels Phi(-bar) and Phi(+bar).
    """
    return 0.5 * math.erfc(-float(x) / _SQRT2)


def _tail_guess(q: float) -> float:
    c, d = _QC, _QD
    num = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    return num / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def normal_quantile(p: float) -> float:
    """Inverse standard normal CDF for 0 < p < 1 (Acklam plus two Halley steps).

    Supports the 9.5 percentile coverage and the Task 5 z arithmetic; no
    scipy is available.
    """
    p = float(p)
    if not 0.0 < p < 1.0:
        raise ValueError("p must lie strictly between 0 and 1")
    if p < _Q_LOW:
        x = _tail_guess(math.sqrt(-2.0 * math.log(p)))
    elif p <= 1.0 - _Q_LOW:
        q = p - 0.5
        r = q * q
        a, b = _QA, _QB
        num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        x = num / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        x = -_tail_guess(math.sqrt(-2.0 * math.log(1.0 - p)))
    for _ in range(2):
        e = normal_cdf(x) - p
        u = e * _SQRT2PI * math.exp(x * x / 2.0)
        x = x - u / (1.0 + x * u / 2.0)
    return x


# ---------------------------------------------------------------- 9.4 and 9.11

def signed_bp(excess, is_positive) -> np.ndarray:
    """9.4: signed_bp = +10,000 x excess for POSITIVE, -10,000 x excess for NEGATIVE.

    is_positive must be a boolean array (True = POSITIVE, False = NEGATIVE).
    Integer +1/-1 labels are refused, because both are truthy.
    """
    ex = _as_float("excess", excess)
    pos = np.asarray(is_positive)
    if pos.dtype != bool or pos.shape != ex.shape:
        raise ValueError("is_positive must be a boolean array matching excess")
    bp = BP_PER_UNIT * ex
    return np.where(pos, bp, -bp)


def observation_weighted_mean(values) -> float:
    """9.4: T = (sum over the test's observations) / n, observation-weighted.

    Computed with math.fsum, so it is exact up to one final rounding and does
    not depend on row order. Never a mean of cluster means.
    """
    arr = _as_float("values", values)
    if arr.size == 0:
        raise ValueError("no observations")
    return math.fsum(arr.tolist()) / arr.size


def child_rng(seed: int, index: int) -> np.random.Generator:
    """9.11: the index-th child of SeedSequence(seed).spawn, as a PCG64 Generator.

    Equal to child_rngs(seed, n)[index] for every n > index (spawn_key (index,)).
    """
    return np.random.default_rng(
        np.random.SeedSequence(int(seed), spawn_key=(int(index),)))


def child_rngs(seed: int, n_children: int) -> list[np.random.Generator]:
    """9.11: Generators from numpy.random.SeedSequence(seed).spawn(n_children).

    The caller picks child i by the (test, reading) index in
    news_eval.constants.STREAM_ORDER. Child i is the same for any n_children.
    """
    children = np.random.SeedSequence(int(seed)).spawn(
        _check_count("n_children", n_children, 1))
    return [np.random.default_rng(child) for child in children]


# --------------------------------------------------------------- 9.5 bootstrap

@dataclass(frozen=True, eq=False)
class BootstrapResult(_Status):
    """One 9.5 cluster-bootstrap reading. Numbers are None unless status is "ok"."""
    status: str
    reason: str
    statistic: float | None
    se: float | None
    z: float | None
    bar: float
    lower: float | None
    upper: float | None
    lower_above_zero: bool | None
    percentile_lower: float | None
    percentile_upper: float | None
    percentile_coverage: float
    percentile_label: str
    n_obs: int
    n_clusters: int
    n_draws: int
    n_defined: int
    n_undefined: int
    replicates: np.ndarray | None  # all draws, NaN where undefined; None if not drawn


def cluster_index(clusters) -> tuple[np.ndarray, np.ndarray]:
    """Cluster labels in np.unique sorted order and each row's cluster index (9.5)."""
    arr = np.asarray(clusters)
    if arr.ndim != 1:
        raise ValueError("clusters must be one-dimensional")
    labels, inverse = np.unique(arr, return_inverse=True)
    return labels, inverse.reshape(-1)


def cluster_draw_counts(rng: np.random.Generator, n_clusters: int,
                        n_draws: int) -> Iterator[np.ndarray]:
    """9.5 draws: per draw, C clusters sampled with replacement, equal probability.

    Yields int64 arrays of shape (m, C): row r holds how many times each
    cluster was drawn in that replicate (a multinomial(C, 1/C) vector). One
    rng.multinomial call per chunk of m = min(BOOT_CHUNK, remaining) draws.
    """
    c = _check_count("n_clusters", n_clusters, 1)
    remaining = _check_count("n_draws", n_draws, 1)
    pvals = np.full(c, 1.0 / c)
    while remaining > 0:
        m = min(BOOT_CHUNK, remaining)
        yield rng.multinomial(c, pvals, size=m).astype(np.int64)
        remaining -= m


def _boot_refusal(status: str, reason: str, *, bar: float, n_obs: int,
                  n_clusters: int, n_draws: int, replicates=None,
                  n_defined: int = 0, n_undefined: int = 0) -> BootstrapResult:
    return BootstrapResult(
        status=status, reason=reason, statistic=None, se=None, z=None, bar=bar,
        lower=None, upper=None, lower_above_zero=None, percentile_lower=None,
        percentile_upper=None,
        percentile_coverage=normal_cdf(bar) - normal_cdf(-bar),
        percentile_label=PERCENTILE_LABEL, n_obs=n_obs, n_clusters=n_clusters,
        n_draws=n_draws, n_defined=n_defined, n_undefined=n_undefined,
        replicates=replicates)


def weighted_draw_bootstrap(observed: float,
                            replicate_fn: Callable[[np.ndarray], np.ndarray],
                            n_clusters: int, *, n_obs: int, n_draws: int,
                            rng: np.random.Generator, bar: float,
                            zero_scale: float) -> BootstrapResult:
    """9.5 cluster bootstrap for any statistic, by multinomial cluster counts.

    Each of n_draws draws samples C clusters with replacement from the C
    clusters present (cluster_draw_counts). replicate_fn maps a (m, C) count
    array to m replicate values, recomputing the statistic over every
    observation of the drawn clusters with multiplicity; NaN marks an
    undefined replicate. SE is the ddof-1 standard deviation of the defined
    replicates, z = observed / SE, the interval is observed +/- bar x SE
    (bar 2.50 for primaries and E-tests, 2.24 for S1 and S2), and the
    percentile interval at quantiles Phi(-bar), Phi(+bar) (numpy linear
    method) is labelled descriptive and decides nothing. Fewer than 2
    clusters, fewer than 2 defined replicates, or an SE of zero (at or below
    ZERO_SE_RTOL x zero_scale) is the named refusal "degenerate".
    """
    bar = _check_bar(bar)
    n_draws = _check_count("n_draws", n_draws, 2)
    n_clusters = int(n_clusters)
    common = dict(bar=bar, n_obs=int(n_obs), n_clusters=n_clusters, n_draws=n_draws)
    if n_clusters < 2:
        return _boot_refusal(STATUS_DEGENERATE, "fewer than 2 clusters", **common)
    reps = np.empty(n_draws, dtype=np.float64)
    pos = 0
    for counts in cluster_draw_counts(rng, n_clusters, n_draws):
        vals = np.asarray(replicate_fn(counts), dtype=np.float64)
        if vals.shape != (counts.shape[0],):
            raise ValueError("replicate_fn must return one value per draw")
        reps[pos:pos + vals.size] = vals
        pos += vals.size
    defined = reps[np.isfinite(reps)]
    n_def = int(defined.size)
    counts_kw = dict(replicates=reps, n_defined=n_def, n_undefined=n_draws - n_def)
    if n_def < 2:
        return _boot_refusal(STATUS_DEGENERATE, "fewer than 2 defined replicates",
                             **common, **counts_kw)
    se = float(np.std(defined, ddof=1))
    if np.ptp(defined) == 0 or se <= ZERO_SE_RTOL * float(zero_scale):
        return _boot_refusal(STATUS_DEGENERATE, "bootstrap SE is zero",
                             **common, **counts_kw)
    observed = float(observed)
    lower, upper = observed - bar * se, observed + bar * se
    q_lo, q_hi = np.quantile(defined, [normal_cdf(-bar), normal_cdf(bar)])
    return BootstrapResult(
        status=STATUS_OK, reason="", statistic=observed, se=se, z=observed / se,
        lower=lower, upper=upper, lower_above_zero=bool(lower > 0),
        percentile_lower=float(q_lo), percentile_upper=float(q_hi),
        percentile_coverage=normal_cdf(bar) - normal_cdf(-bar),
        percentile_label=PERCENTILE_LABEL, **common, **counts_kw)


def cluster_bootstrap_ratio(values, clusters, *, n_draws: int,
                            rng: np.random.Generator, bar: float) -> BootstrapResult:
    """9.4 T with its 9.5 cluster bootstrap (P1 to P4 on signed_bp, E1 to E4 on net_bp).

    T = sum(values) / n. Rows collapse to per-cluster sums S_c and counts n_c;
    a draw with cluster counts w gives T* = sum(w S) / sum(w n), the ratio over
    every observation in the drawn clusters with multiplicity. Pass story
    group ids (unshared rows as their own id) as clusters for the 9.10
    story-group re-run.
    """
    y = _as_float("values", values)
    _, inverse = cluster_index(_as_same_length("clusters", clusters, y.size))
    c = int(inverse.max()) + 1 if y.size else 0
    if y.size == 0:
        return _boot_refusal(STATUS_DEGENERATE, "no observations", bar=_check_bar(bar),
                             n_obs=0, n_clusters=0, n_draws=int(n_draws))
    s_c = np.bincount(inverse, weights=y, minlength=c)
    n_c = np.bincount(inverse, minlength=c).astype(np.float64)

    def replicate(counts: np.ndarray) -> np.ndarray:
        w = counts.astype(np.float64)
        return (w @ s_c) / (w @ n_c)

    return weighted_draw_bootstrap(
        observation_weighted_mean(y), replicate, c, n_obs=y.size,
        n_draws=n_draws, rng=rng, bar=bar, zero_scale=float(np.max(np.abs(y))))


# ------------------------------------------------- Task 5 S1: Spearman ranks

def average_ranks(values) -> np.ndarray:
    """1-based ranks with ties at their average rank (Task 5 S1, 9.10)."""
    a = _as_float("values", values)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    s = a[order]
    new_group = np.ones(n, dtype=bool)
    new_group[1:] = s[1:] != s[:-1]
    starts = np.flatnonzero(new_group)
    ends = np.append(starts[1:], n)
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.repeat((starts + ends + 1) / 2.0, ends - starts)
    return ranks


def spearman(x, y) -> float | None:
    """S1 statistic (Task 5, 9.10): Spearman correlation, ties at average ranks.

    The Pearson correlation of the average ranks. None when either variable
    has zero rank variance (all values tied) or fewer than 2 rows.
    """
    xa, ya = _as_float("x", x), _as_float("y", y)
    if xa.size != ya.size:
        raise ValueError("x and y must have the same length")
    if xa.size < 2:
        return None
    dx = average_ranks(xa)
    dy = average_ranks(ya)
    dx -= dx.mean()
    dy -= dy.mean()
    vx, vy = float(dx @ dx), float(dy @ dy)
    if vx == 0.0 or vy == 0.0:
        return None
    return float(dx @ dy) / math.sqrt(vx * vy)


def _group_ranks(group_weights: np.ndarray) -> np.ndarray:
    """Average rank of each value group given per-group weights (rows = draws).

    A group of weight G after L lower-ranked observations occupies ranks
    L+1..L+G, average L + (G+1)/2 = cumsum - (G-1)/2. Exact for integer weights.
    """
    return np.cumsum(group_weights, axis=1) - (group_weights - 1.0) / 2.0


def _weighted_pearson_rows(w: np.ndarray, rx: np.ndarray, ry: np.ndarray) -> np.ndarray:
    wt = w.sum(axis=1)
    dx = rx - ((w * rx).sum(axis=1) / wt)[:, None]
    dy = ry - ((w * ry).sum(axis=1) / wt)[:, None]
    wdx = w * dx
    cov = (wdx * dy).sum(axis=1)
    vxy = (wdx * dx).sum(axis=1) * (w * dy * dy).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return cov / np.sqrt(vxy)


def _value_groups(values: np.ndarray) -> tuple[np.ndarray, int]:
    uniq, inv = np.unique(values, return_inverse=True)
    return inv.reshape(-1), int(uniq.size)


def weighted_spearman(x, y, weights) -> float | None:
    """Spearman with integer observation weights (Task 5 S1 under 9.5 multiplicity).

    Equals spearman(np.repeat(x, w), np.repeat(y, w)): weighted average ranks
    reproduce the ranks of the expanded sample exactly. None when either
    variable has fewer than 2 distinct values carrying positive weight.
    """
    xa, ya = _as_float("x", x), _as_float("y", y)
    w = np.asarray(weights)
    if xa.size != ya.size or w.shape != xa.shape:
        raise ValueError("x, y and weights must have the same length")
    if np.any(w < 0) or not np.all(np.equal(np.mod(w, 1), 0)):
        raise ValueError("weights must be non-negative integers")
    wf = w.astype(np.float64)
    gx, kx = _value_groups(xa)
    gy, ky = _value_groups(ya)
    gwx = np.bincount(gx, weights=wf, minlength=kx)[None, :]
    gwy = np.bincount(gy, weights=wf, minlength=ky)[None, :]
    if (gwx > 0).sum() < 2 or (gwy > 0).sum() < 2:
        return None
    rx = _group_ranks(gwx)[:, gx]
    ry = _group_ranks(gwy)[:, gy]
    return float(_weighted_pearson_rows(wf[None, :], rx, ry)[0])


def spearman_bootstrap(strength, values, clusters, *, n_draws: int,
                       rng: np.random.Generator, bar: float) -> BootstrapResult:
    """9.10 S1: Spearman(strength, signed_bp), bootstrapped per 9.5.

    Pass the scored rows with strength_parse_ok = 1. Each draw recomputes the
    Spearman of the drawn sample with multiplicity: every observation carries
    its cluster's drawn count as an integer weight, and weighted average ranks
    equal the expanded sample's ranks. A draw whose sample has zero rank
    variance in either variable is undefined and leaves the SE (n_undefined is
    reported). Zero rank variance in the observed data is "degenerate".
    """
    x = _as_float("strength", strength)
    y = _as_float("values", values)
    if x.size != y.size:
        raise ValueError("strength and values must have the same length")
    _, inverse = cluster_index(_as_same_length("clusters", clusters, y.size))
    c = int(inverse.max()) + 1 if y.size else 0
    bar = _check_bar(bar)
    common = dict(bar=bar, n_obs=int(y.size), n_clusters=c, n_draws=int(n_draws))
    if c < 2:
        return _boot_refusal(STATUS_DEGENERATE, "fewer than 2 clusters", **common)
    observed = spearman(x, y)
    if observed is None:
        return _boot_refusal(STATUS_DEGENERATE,
                             "zero rank variance in the observed data", **common)
    gx, kx = _value_groups(x)
    gy, ky = _value_groups(y)
    ax = np.zeros((c, kx))
    np.add.at(ax, (inverse, gx), 1.0)
    ay = np.zeros((c, ky))
    np.add.at(ay, (inverse, gy), 1.0)
    step = _chunk_rows(max(y.size, ky), BOOT_CHUNK)

    def replicate(counts: np.ndarray) -> np.ndarray:
        out = np.empty(counts.shape[0], dtype=np.float64)
        for start in range(0, counts.shape[0], step):
            w = counts[start:start + step].astype(np.float64)
            gwx, gwy = w @ ax, w @ ay
            vals = _weighted_pearson_rows(w[:, inverse], _group_ranks(gwx)[:, gx],
                                          _group_ranks(gwy)[:, gy])
            undefined = ((gwx > 0).sum(axis=1) < 2) | ((gwy > 0).sum(axis=1) < 2)
            vals[undefined] = np.nan
            out[start:start + w.shape[0]] = vals
        return out

    return weighted_draw_bootstrap(observed, replicate, c, n_obs=y.size,
                                   n_draws=n_draws, rng=rng, bar=bar, zero_scale=1.0)


def top_bottom_bootstrap(strength, values, clusters, *, top_strengths: Sequence[int],
                         bottom_strengths: Sequence[int], n_draws: int,
                         rng: np.random.Generator, bar: float) -> BootstrapResult:
    """9.10 S2: mean signed_bp over top strengths minus over bottom, per 9.5.

    Both means are observation-weighted (9.4). Pass the S1/S2 population
    (scored, strength_parse_ok = 1): clusters are those holding any passed
    row, so strength-3 rows hold their clusters in the draw while entering
    neither pool. A draw with an empty pool is undefined. An empty pool in
    the observed data is "abstain_empty_pool" (9.10).
    """
    x = _as_float("strength", strength)
    y = _as_float("values", values)
    if x.size != y.size:
        raise ValueError("strength and values must have the same length")
    if set(top_strengths) & set(bottom_strengths):
        raise ValueError("top and bottom strength sets overlap")
    _, inverse = cluster_index(_as_same_length("clusters", clusters, y.size))
    c = int(inverse.max()) + 1 if y.size else 0
    bar = _check_bar(bar)
    common = dict(bar=bar, n_obs=int(y.size), n_clusters=c, n_draws=int(n_draws))
    top = np.isin(x, list(top_strengths))
    bot = np.isin(x, list(bottom_strengths))
    if not top.any() or not bot.any():
        return _boot_refusal(STATUS_ABSTAIN_EMPTY_POOL,
                             "empty strength pool in the observed data", **common)
    if c < 2:
        return _boot_refusal(STATUS_DEGENERATE, "fewer than 2 clusters", **common)
    observed = observation_weighted_mean(y[top]) - observation_weighted_mean(y[bot])
    ts = np.bincount(inverse, weights=np.where(top, y, 0.0), minlength=c)
    tn = np.bincount(inverse, weights=top.astype(np.float64), minlength=c)
    bs = np.bincount(inverse, weights=np.where(bot, y, 0.0), minlength=c)
    bn = np.bincount(inverse, weights=bot.astype(np.float64), minlength=c)

    def replicate(counts: np.ndarray) -> np.ndarray:
        w = counts.astype(np.float64)
        tw, bw = w @ tn, w @ bn
        with np.errstate(invalid="ignore", divide="ignore"):
            vals = (w @ ts) / tw - (w @ bs) / bw
        vals[(tw == 0) | (bw == 0)] = np.nan
        return vals

    return weighted_draw_bootstrap(observed, replicate, c, n_obs=y.size,
                                   n_draws=n_draws, rng=rng, bar=bar,
                                   zero_scale=float(np.max(np.abs(y))))


# ------------------------------------------------------------- 9.10 CR1 sector

@dataclass(frozen=True)
class CR1Result(_Status):
    """9.10 sector robustness: T with a CR1 cluster-robust SE. Descriptive, no bar."""
    status: str
    reason: str
    statistic: float | None
    se: float | None
    z: float | None
    n_obs: int
    n_clusters: int


def cr1_mean(values, clusters) -> CR1Result:
    """9.10 sector figure: CR1 cluster-robust SE of the observation-weighted mean.

    Residuals e_i = y_i - T; V = (G/(G-1)) x sum_g (sum_{i in g} e_i)^2 / N^2.
    The intercept-only model has K = 1, so the (N-1)/(N-K) factor is 1.
    SE = sqrt(V), z = T / SE. Fewer than 2 clusters or an SE of zero is
    "degenerate".
    """
    y = _as_float("values", values)
    _, inverse = cluster_index(_as_same_length("clusters", clusters, y.size))
    n = int(y.size)
    g = int(inverse.max()) + 1 if n else 0
    if g < 2:
        return CR1Result(STATUS_DEGENERATE, "fewer than 2 clusters", None, None,
                         None, n, g)
    t = observation_weighted_mean(y)
    e_g = np.bincount(inverse, weights=y - t, minlength=g)
    se = math.sqrt((g / (g - 1)) * float(np.sum(e_g ** 2)) / (n * n))
    if se <= ZERO_SE_RTOL * float(np.max(np.abs(y))):
        return CR1Result(STATUS_DEGENERATE, "CR1 SE is zero", None, None, None, n, g)
    return CR1Result(STATUS_OK, "", t, se, t / se, n, g)


# ------------------------------------------------------------------ 9.8 gate

@dataclass(frozen=True)
class GateResult(_Status):
    """9.8 gate quantities. Derived numbers are None unless status is "ok"."""
    status: str
    reason: str
    sigma: float | None
    msb: float | None
    msw: float | None
    n0: float | None
    rho_raw: float | None
    rho: float | None
    k_eff: float | None
    required: float | None
    n_rows: int                    # N, gate rows G
    n_clusters_gate: int           # C_G, clusters among the gate rows
    n_clusters_directional: int    # C_dir, clusters with m_c >= 1
    n_directional: int             # M, directional scorable rows
    passed: bool
    failing: tuple[str, ...]


def _directional_counts(directional_counts, gate_labels: np.ndarray) -> np.ndarray:
    if isinstance(directional_counts, Mapping):
        known = set(gate_labels.tolist())
        for key in directional_counts:
            if key not in known:
                raise ValueError(f"directional cluster {key!r} has no gate rows")
        counts = np.array(list(directional_counts.values()))
    else:
        counts = np.asarray(directional_counts)
    if counts.ndim != 1 or np.any(counts < 0) or not np.all(np.mod(counts, 1) == 0):
        raise ValueError("directional counts must be non-negative integers")
    return counts.astype(np.int64)


def gate_quantities(excess, clusters, directional_counts, *, power_constant: float,
                    effect_bp: float, min_clusters: int,
                    min_directional: int) -> GateResult:
    """9.8 (Amendment 8.4) gate: sigma, ANOVA rho, k_eff, Required and the pass.

    excess and clusters are the gate rows G (NEUTRAL included, no judgment
    read). y = 10,000 x excess. sigma = std(y, ddof 1), no trimming. With N
    rows in C_G clusters: n0 = (N - sum n_c^2 / N) / (C_G - 1),
    MSB = sum n_c (mean_c - grand)^2 / (C_G - 1),
    MSW = sum (y - mean_c)^2 / (N - C_G),
    rho = (MSB - MSW) / (MSB + (n0 - 1) MSW) floored at 0. n0 needs no floor:
    it is positive whenever C_G >= 2 (the prompt's "n0 floored at 0" is read
    as the rho floor of 9.8). directional_counts maps cluster -> m_c (or is a
    sequence of m_c); k_eff = sum m_c^2 / M. Required = power_constant x
    (sigma / effect_bp)^2 x (1 + (k_eff - 1) rho), with the caller passing
    11.156 and 30. Pass: C_dir >= min_clusters, M >= min_directional and
    M >= Required. "degenerate" when C_G < 2, N - C_G < 1, every y is equal
    (the exact case of a zero rho denominator), the computed denominator is
    not positive, or M = 0 (k_eff undefined).
    """
    y = BP_PER_UNIT * _as_float("excess", excess)
    labels, inverse = cluster_index(_as_same_length("clusters", clusters, y.size))
    m_c = _directional_counts(directional_counts, labels)
    n, c_g = int(y.size), int(labels.size)
    big_m, c_dir = int(m_c.sum()), int(np.sum(m_c >= 1))
    counts = dict(n_rows=n, n_clusters_gate=c_g, n_clusters_directional=c_dir,
                  n_directional=big_m)

    def refuse(reason: str) -> GateResult:
        return GateResult(STATUS_DEGENERATE, reason, None, None, None, None, None,
                          None, None, None, **counts, passed=False,
                          failing=(STATUS_DEGENERATE,))

    if c_g < 2:
        return refuse("fewer than 2 gate clusters")
    if n - c_g < 1:
        return refuse("N - C_G < 1: no within-cluster degrees of freedom")
    if np.ptp(y) == 0:
        return refuse("every gate value is equal: the rho denominator is 0")
    if big_m == 0:
        return refuse("no directional rows: k_eff is undefined")
    n_c = np.bincount(inverse, minlength=c_g).astype(np.float64)
    mean_c = np.bincount(inverse, weights=y, minlength=c_g) / n_c
    grand = observation_weighted_mean(y)
    msb = float(np.sum(n_c * (mean_c - grand) ** 2)) / (c_g - 1)
    msw = float(np.sum((y - mean_c[inverse]) ** 2)) / (n - c_g)
    n0 = (n - float(np.sum(n_c ** 2)) / n) / (c_g - 1)
    denom = msb + (n0 - 1.0) * msw
    if not denom > 0:
        return refuse("the rho denominator is not positive")
    rho_raw = (msb - msw) / denom
    rho = max(0.0, rho_raw)
    sigma = float(np.std(y, ddof=1))
    k_eff = float(np.sum(m_c.astype(np.float64) ** 2)) / big_m
    required = float(power_constant) * (sigma / float(effect_bp)) ** 2 * (
        1.0 + (k_eff - 1.0) * rho)
    failing = []
    if c_dir < min_clusters:
        failing.append(f"C_dir {c_dir} < {min_clusters}")
    if big_m < min_directional:
        failing.append(f"M {big_m} < {min_directional}")
    if big_m < required:
        failing.append(f"M {big_m} < Required {required:.3f}")
    return GateResult(STATUS_OK, "", sigma, msb, msw, n0, rho_raw, rho, k_eff,
                      required, **counts, passed=not failing, failing=tuple(failing))


# ------------------------------------------------ Amendment 6 permutation null

@dataclass(frozen=True)
class PermutationResult(_Status):
    """One Amendment 6 permutation null (9.3, 9.9). p and counts None unless "ok"."""
    status: str
    reason: str
    mode: str
    blocked: bool
    t_obs: float | None
    p: float | None
    count_ge: int | None
    count_le: int | None
    upper_tail: bool | None
    n_perm: int
    n_obs: int
    n_negative: int
    n_strata: int
    n_blocks: int


@dataclass(frozen=True, eq=False)
class _BlockClass:
    offset: int          # first column of this class in the per-chunk key array
    rows: np.ndarray     # (b, k) row indices, blocks by first row, rows ascending
    labels: np.ndarray   # (b, k) observed labels, int8


def _is_unshared(group) -> bool:
    if group is None:
        return True
    if isinstance(group, float) and math.isnan(group):
        return True
    return isinstance(group, str) and group == ""


def _block_layout(labels: np.ndarray, strata: np.ndarray,
                  story_groups) -> tuple[list[_BlockClass], int, int]:
    _, srank = np.unique(strata, return_inverse=True)
    srank = srank.reshape(-1)
    blocks: dict[tuple, list[int]] = {}
    for i in range(labels.size):
        group = None if story_groups is None else story_groups[i]
        key = ("row", i) if _is_unshared(group) else ("group", group)
        blocks.setdefault((int(srank[i]), key), []).append(i)
    classes: dict[tuple[int, int], list[list[int]]] = {}
    for (stratum, _), rows in blocks.items():
        classes.setdefault((stratum, len(rows)), []).append(rows)
    layout, offset = [], 0
    for key in sorted(classes):
        members = sorted(classes[key], key=lambda rows: rows[0])
        rows = np.array(members, dtype=np.intp)
        layout.append(_BlockClass(offset, rows, labels[rows]))
        offset += rows.shape[0]
    return layout, offset, int(srank.max()) + 1 if labels.size else 0


def permuted_label_chunks(labels, strata, *, n_perm: int, rng: np.random.Generator,
                          story_groups=None) -> Iterator[np.ndarray]:
    """Amendment 6 within-day label shuffles, as int8 arrays of shape (m, n).

    Labels move only within their stratum (scoring_session, 9.9), so each
    stratum's POSITIVE and NEGATIVE counts are held exactly. Unblocked, each
    stratum's labels are shuffled uniformly without replacement. Blocked
    (story_groups given; 9.10 trigger): blocks are (stratum, story_group_id)
    groups, every unshared row (None or "") its own block; within each
    stratum, blocks of equal size form a class and the classes' label vectors
    (rows in ascending input order inside each block) are permuted across
    blocks. Lead's choice, recorded: Amendment 6 says "permuting story groups
    as blocks within day, one judgment moving with its whole group" without
    fixing unequal block sizes; the size-class permutation is the reading
    that keeps each day's counts fixed. Consumption: module docstring.
    """
    lab = _as_labels(labels)
    st = _as_same_length("strata", strata, lab.size)
    if story_groups is not None:
        story_groups = list(_as_same_length("story_groups", story_groups, lab.size))
    total = _check_count("n_perm", n_perm, 1)
    layout, n_blocks, _ = _block_layout(lab, st, story_groups)
    rows_per_chunk = _chunk_rows(lab.size, PERM_CHUNK)
    done = 0
    while done < total:
        m = min(rows_per_chunk, total - done)
        keys = rng.random((m, n_blocks))
        out = np.empty((m, lab.size), dtype=np.int8)
        for cls in layout:
            b = cls.rows.shape[0]
            flat = cls.rows.reshape(-1)
            if b == 1:
                out[:, flat] = cls.labels.reshape(-1)
                continue
            perm = np.argsort(keys[:, cls.offset:cls.offset + b], axis=1, kind="stable")
            out[:, flat] = cls.labels[perm].reshape(m, -1)
        yield out
        done += m


def _perm_statistic(label_rows: np.ndarray, bp: np.ndarray, mode: str,
                    denom: int) -> np.ndarray:
    if mode == MODE_SUBSET:
        vals = label_rows * bp
    else:
        vals = np.where(label_rows == NEGATIVE_LABEL, -bp, 0.0)
    return _exact_mean_rows(vals, denom)


def permutation_test(excess, labels, strata, *, mode: str, n_perm: int,
                     rng: np.random.Generator, story_groups=None) -> PermutationResult:
    """Amendment 6 within-day judgment-permutation null with 9.3 and 9.9.

    Strata are scoring_session clusters (9.9). labels: +1 POSITIVE, -1 NEGATIVE.
    mode "subset" (P1 pooled, P3 thin-end, P4 second half): pass the test's
    own observations; T = mean of label x 10,000 x excess over them.
    mode "negative_only" (P2): pass ALL of the day's scored observations; on
    each permutation the NEGATIVE subset is re-formed from the permuted labels
    and T = mean over it of -10,000 x excess. Its size per stratum is fixed,
    so the denominator is fixed. Sums are exact (math.fsum), so arrangements
    that tie in exact arithmetic tie here and count in both tails.
    p = min(1, 2 x min(1 + count(T_perm >= T_obs), 1 + count(T_perm <= T_obs))
    / (n_perm + 1)). upper_tail (9.3) is count(T_perm >= T_obs) strictly
    below count(T_perm <= T_obs). story_groups switches on the block version
    (permuted_label_chunks). The informativeness diagnostic is the caller's
    (minority_share_and_mixed). No observations, or no NEGATIVE row in
    negative_only mode, is "degenerate" and draws nothing.
    """
    if mode not in (MODE_SUBSET, MODE_NEGATIVE_ONLY):
        raise ValueError(f"mode must be {MODE_SUBSET!r} or {MODE_NEGATIVE_ONLY!r}")
    ex = _as_float("excess", excess)
    lab = _as_labels(labels, ex.size)
    st = _as_same_length("strata", strata, ex.size)
    n_perm = _check_count("n_perm", n_perm, 1)
    blocked = story_groups is not None
    n_neg = int(np.sum(lab == NEGATIVE_LABEL))
    layout_groups = None if not blocked else list(
        _as_same_length("story_groups", story_groups, ex.size))
    _, n_blocks, n_strata = _block_layout(lab, st, layout_groups)
    denom = ex.size if mode == MODE_SUBSET else n_neg
    if denom == 0:
        reason = "no observations" if ex.size == 0 else "no NEGATIVE observation"
        return PermutationResult(STATUS_DEGENERATE, reason, mode, blocked, None, None,
                                 None, None, None, n_perm, int(ex.size), n_neg,
                                 n_strata, n_blocks)
    bp = BP_PER_UNIT * ex
    t_obs = float(_perm_statistic(lab[None, :], bp, mode, denom)[0])
    count_ge = count_le = 0
    for chunk in permuted_label_chunks(lab, st, n_perm=n_perm, rng=rng,
                                       story_groups=layout_groups):
        t_perm = _perm_statistic(chunk, bp, mode, denom)
        count_ge += int(np.sum(t_perm >= t_obs))
        count_le += int(np.sum(t_perm <= t_obs))
    p = min(1.0, 2.0 * min(1 + count_ge, 1 + count_le) / (n_perm + 1))
    return PermutationResult(STATUS_OK, "", mode, blocked, t_obs, p, count_ge,
                             count_le, count_ge < count_le, n_perm, int(ex.size),
                             n_neg, n_strata, n_blocks)


@dataclass(frozen=True)
class BalanceResult:
    """Amendment 6 directional-balance diagnostic inputs (reported before the null)."""
    n_positive: int
    n_negative: int
    minority_share: float | None   # None when there is no directional row
    n_mixed_strata: int
    n_strata: int


def minority_share_and_mixed(labels, strata) -> BalanceResult:
    """Amendment 6 skew diagnostic: pooled minority share min(P, N) / (P + N) and
    the number of strata (scoring_session, 9.9) holding at least one +1 and one
    -1. The UNINFORMATIVE call against the registered thresholds is the
    caller's.
    """
    lab = _as_labels(labels)
    st = _as_same_length("strata", strata, lab.size)
    n_pos = int(np.sum(lab == POSITIVE_LABEL))
    n_neg = int(lab.size - n_pos)
    if lab.size == 0:
        return BalanceResult(0, 0, None, 0, 0)
    _, inverse = cluster_index(st)
    k = int(inverse.max()) + 1
    pos_by = np.bincount(inverse, weights=(lab == POSITIVE_LABEL).astype(np.float64),
                         minlength=k)
    neg_by = np.bincount(inverse, weights=(lab == NEGATIVE_LABEL).astype(np.float64),
                         minlength=k)
    mixed = int(np.sum((pos_by > 0) & (neg_by > 0)))
    return BalanceResult(n_pos, n_neg, min(n_pos, n_neg) / lab.size, mixed, k)
