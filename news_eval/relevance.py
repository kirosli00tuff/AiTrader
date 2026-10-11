"""The 8.3 relevance sample: the frozen draw and the grading summary (STAGE C.1 Task 9).

EXPERIMENT.md Amendment 8.3 and Amendment 9.13; reports/c1_verdict_mapping.md
D23. Frozen with the harness BEFORE the draw runs; the C.1 lead runs the draw
after the freeze commit.

The draw (9.13, D23): the RELEVANCE loader phase's population (judged
collection rows with query_date <= constants.RELEVANCE_QUERY_DATE_MAX, the six
columns, ordered by id), numpy.random.default_rng(RELEVANCE_SEED),
choice(n, RELEVANCE_N, replace=False), output sorted by id. Only the six
columns are read, through news_eval.data.RelevancePhase.relevance_population;
nothing else of the database is touched.

    python -m news_eval.relevance draw --db <path> --out reports/c1_relevance_sample.csv
    python -m news_eval.relevance summarize --sample <csv> --opus <csv> \
        --fable <csv> --final <csv> --out <json>

`draw` needs an explicit --db (no default, C.1 ruling N4: the live read is
never a casual default) and runs envcheck.assert_numpy_sane() before
anything else. Its --real-db flag is refused outside test mode,
NEWS_EVAL_TEST_MODE=1 (ruling S5).

The grades (8.3) are company-specific, roundup or off-topic. Nothing is
filtered on them (8.3: "Nothing is removed on the basis of these grades").
The summary reports raw agreement, Cohen's kappa, both grade sets and the
final grades, overall and with the 8.2 exclusions removed (9.13).

8.2 on the sample. Rule (a) is exact by symbol (contains "." or is one of
STRK, STRF, STRD, STRC). Rule (b) needs the modal sector and sector_source of
a symbol over a whole formation, and neither sector_source nor the formation
is among the six sampled columns, so rule (b) has no exact form here. Two
APPROXIMATE variants are reported, both labelled so:
  b1: the 2026-07-01 rule (b) members Amendment 8.2 lists.
  b2: b1 plus any sampled row whose sampled sector is 'N/A'.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from news_eval import constants as K
from news_eval import data
from news_eval import envcheck

GRADE_COMPANY = "company-specific"
GRADE_ROUNDUP = "roundup"
GRADE_OFF_TOPIC = "off-topic"
GRADES = (GRADE_COMPANY, GRADE_ROUNDUP, GRADE_OFF_TOPIC)
GRADE_COLUMNS = ("id", "grade", "reason")

DRAW_METHOD = (
    "population: news_eval.data RELEVANCE phase relevance_population("
    f"{K.RELEVANCE_QUERY_DATE_MAX!r}), judged collection rows, six columns, "
    "ordered by id; rng = numpy.random.default_rng(RELEVANCE_SEED); "
    f"idx = rng.choice(n, {K.RELEVANCE_N}, replace=False); "
    "output rows sorted by id (EXPERIMENT.md 9.13; c1_verdict_mapping D23)")

# EXPERIMENT.md line 759 (Amendment 8.2), quoted:
#   "- (b): BCAR, BCX, BIT, BMEZ, BSTZ, BUI, GDV, HQH, PSUS"
# The 2026-07-01 formation's rule (b) members, computed 2026-09-28.
RULE_B_2026_07_01 = ("BCAR", "BCX", "BIT", "BMEZ", "BSTZ", "BUI", "GDV",
                     "HQH", "PSUS")

VARIANT_ALL = "all_rows"
VARIANT_A = "excl_rule_a_exact"
VARIANT_A_B1 = "excl_rule_a_exact_and_rule_b1_approximate"
VARIANT_A_B2 = "excl_rule_a_exact_and_rule_b2_approximate"
VARIANT_NOTES = {
    VARIANT_ALL: "every sampled row",
    VARIANT_A: "8.2 rule (a), exact by symbol",
    VARIANT_A_B1: ("8.2 rule (a) exact, plus rule (b) APPROXIMATED by the "
                   "2026-07-01 members Amendment 8.2 lists"),
    VARIANT_A_B2: ("8.2 rule (a) exact, plus rule (b) APPROXIMATED by the "
                   "2026-07-01 members and any sampled row whose sector is "
                   "'N/A'"),
}


class RelevanceRefusal(Exception):
    """The draw or a grades file refused, with the reason."""


# ------------------------------------------------------------------ hashing

def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def meta_path(out_csv: str | os.PathLike) -> Path:
    """The sidecar next to the sample: <csv>.meta.json."""
    return Path(os.fspath(out_csv) + ".meta.json")


# --------------------------------------------------------------------- draw

def draw_indices(n: int) -> np.ndarray:
    """The 9.13 / D23 draw over a population of n rows ordered by id, sorted."""
    if n < K.RELEVANCE_N:
        raise RelevanceRefusal(
            f"population of {n} rows is below the {K.RELEVANCE_N} the 9.13 "
            "draw needs")
    rng = np.random.default_rng(K.RELEVANCE_SEED)
    idx = rng.choice(n, K.RELEVANCE_N, replace=False)
    return np.sort(idx)


def _population(db_path: str | os.PathLike,
                real_db_path: str | os.PathLike | None) -> tuple[tuple, ...]:
    with data.open_phase(data.Phase.RELEVANCE, db_path,
                         real_db_path=real_db_path) as phase:
        rows = phase.relevance_population(K.RELEVANCE_QUERY_DATE_MAX)
    if rows.columns != K.RELEVANCE_COLUMNS:
        raise RelevanceRefusal(f"unexpected columns {rows.columns}")
    ids = [r[0] for r in rows.data]
    if any(not isinstance(i, int) for i in ids) \
            or any(a >= b for a, b in zip(ids, ids[1:])):
        raise RelevanceRefusal("population is not ordered by a unique "
                               "integer id")
    return rows.data


def draw(db_path: str | os.PathLike, out_csv: str | os.PathLike, *,
         real_db_path: str | os.PathLike | None = None,
         overwrite: bool = False) -> dict:
    """Draw the 200-row sample (9.13, D23) and write it with its sidecar.

    Checks numpy first (envcheck.assert_numpy_sane, ruling N4). Reads only
    through the RELEVANCE loader phase. Writes out_csv (columns
    exactly constants.RELEVANCE_COLUMNS, csv module, header row, UTF-8,
    QUOTE_MINIMAL, "\\n" line ends) and <out_csv>.meta.json. Refuses a
    population under 200 rows and, unless overwrite is set, an existing
    output file. Returns the sidecar dict.
    """
    envcheck.assert_numpy_sane()
    out = Path(out_csv)
    side = meta_path(out)
    if not overwrite and (out.exists() or side.exists()):
        raise RelevanceRefusal(f"{out} or its sidecar exists; refusing to "
                               "overwrite a drawn sample")
    population = _population(db_path, real_db_path)
    idx = draw_indices(len(population))
    sample = sorted((population[int(i)] for i in idx), key=lambda r: r[0])

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(K.RELEVANCE_COLUMNS)
        writer.writerows(sample)

    meta = {
        "schema": "c1_relevance_sample_meta/1",
        "population_count": len(population),
        "population_min_id": population[0][0],
        "population_max_id": population[-1][0],
        "population_max_query_date": max(r[2] for r in population),
        "query_date_max_filter": K.RELEVANCE_QUERY_DATE_MAX,
        "n_drawn": len(sample),
        "seed": K.RELEVANCE_SEED,
        "draw_method": DRAW_METHOD,
        "columns": list(K.RELEVANCE_COLUMNS),
        "csv_path": str(out),
        "csv_sha256": sha256_file(out),
        "numpy_version": np.__version__,
        "utc_time": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    }
    side.write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    return meta


# ------------------------------------------------------------------- grades

def load_sample(path: str | os.PathLike) -> dict[int, dict[str, str]]:
    """The drawn sample: {id: row dict}; refuses a wrong header or duplicate ids."""
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != K.RELEVANCE_COLUMNS:
            raise RelevanceRefusal(f"{path}: header must be "
                                   f"{','.join(K.RELEVANCE_COLUMNS)}")
        out: dict[int, dict[str, str]] = {}
        for line, row in enumerate(reader, start=2):
            rid = _parse_id(row.get("id"), path, line)
            if rid in out:
                raise RelevanceRefusal(f"{path}:{line}: duplicate id {rid}")
            out[rid] = row
    return out


def _parse_id(value: object, path: object, line: int) -> int:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        raise RelevanceRefusal(f"{path}:{line}: missing id")
    try:
        return int(text)
    except ValueError:
        raise RelevanceRefusal(f"{path}:{line}: id {text!r} is not an "
                               "integer") from None


def load_grades(path: str | os.PathLike,
                expected_ids: Iterable[int] | None = None) -> dict[int, str]:
    """A grades CSV: {id: grade}.

    The header must contain id, grade and reason (other columns are allowed
    and ignored). A grade is one of GRADES after stripping surrounding
    whitespace; anything else refuses. A missing or duplicate id refuses.
    With expected_ids, the id set must equal it exactly.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = tuple(reader.fieldnames or ())
        missing = [c for c in GRADE_COLUMNS if c not in header]
        if missing:
            raise RelevanceRefusal(f"{path}: header lacks {missing}")
        grades: dict[int, str] = {}
        for line, row in enumerate(reader, start=2):
            rid = _parse_id(row.get("id"), path, line)
            if rid in grades:
                raise RelevanceRefusal(f"{path}:{line}: duplicate id {rid}")
            grade = (row.get("grade") or "").strip()
            if grade not in GRADES:
                raise RelevanceRefusal(f"{path}:{line}: grade {grade!r} is "
                                       f"not one of {GRADES}")
            grades[rid] = grade
    if expected_ids is not None:
        expected = set(expected_ids)
        absent = sorted(expected - set(grades))
        extra = sorted(set(grades) - expected)
        if absent or extra:
            raise RelevanceRefusal(f"{path}: ids missing {absent[:10]} "
                                   f"({len(absent)}), extra {extra[:10]} "
                                   f"({len(extra)})")
    return grades


def _paired(a: Mapping[int, str], b: Mapping[int, str]
            ) -> tuple[list[str], list[str]]:
    if set(a) != set(b):
        raise RelevanceRefusal("the two grade sets cover different ids")
    if not a:
        raise RelevanceRefusal("no graded rows")
    ids = sorted(a)
    return [a[i] for i in ids], [b[i] for i in ids]


def raw_agreement(a: Mapping[int, str], b: Mapping[int, str]) -> float:
    """Share of ids given the same grade by both sets."""
    xa, xb = _paired(a, b)
    return sum(x == y for x, y in zip(xa, xb)) / len(xa)


def confusion(a: Mapping[int, str], b: Mapping[int, str]
              ) -> list[list[int]]:
    """3x3 counts, rows = a's grade, columns = b's grade, in GRADES order."""
    xa, xb = _paired(a, b)
    pos = {g: i for i, g in enumerate(GRADES)}
    m = [[0] * len(GRADES) for _ in GRADES]
    for x, y in zip(xa, xb):
        m[pos[x]][pos[y]] += 1
    return m


def cohens_kappa(a: Mapping[int, str], b: Mapping[int, str]) -> float | None:
    """Cohen's kappa over the three classes: (p_o - p_e) / (1 - p_e), with
    p_e = sum_k p_a(k) p_b(k). None when p_e = 1 (both sets one class)."""
    m = confusion(a, b)
    n = sum(map(sum, m))
    p_o = sum(m[i][i] for i in range(len(GRADES))) / n
    rows = [sum(r) / n for r in m]
    cols = [sum(m[i][j] for i in range(len(GRADES))) / n
            for j in range(len(GRADES))]
    p_e = sum(r * c for r, c in zip(rows, cols))
    if p_e >= 1.0:
        return None
    return (p_o - p_e) / (1.0 - p_e)


def class_rates(grades: Mapping[int, str],
                ids: Iterable[int] | None = None) -> dict:
    """Counts and rates of each class over `ids` (default: every graded id)."""
    keep = sorted(grades) if ids is None else sorted(ids)
    n = len(keep)
    counts = {g: 0 for g in GRADES}
    for i in keep:
        counts[grades[i]] += 1
    return {"n": n, "counts": counts,
            "rates": {g: (counts[g] / n if n else None) for g in GRADES}}


# ------------------------------------------------------- 8.2 on the sample

def rule_a(symbol: str) -> bool:
    """8.2 (a), exact: a symbol containing "." or one of STRK, STRF, STRD, STRC."""
    return K.SENS_RULE_A_CHAR in symbol or symbol in K.SENS_RULE_A_SYMBOLS


def rule_b1(symbol: str) -> bool:
    """8.2 (b) APPROXIMATED: the 2026-07-01 members Amendment 8.2 lists."""
    return symbol in RULE_B_2026_07_01


def rule_b2(symbol: str, sector: str | None) -> bool:
    """8.2 (b) APPROXIMATED: b1, or the sampled row's own sector is 'N/A'."""
    return rule_b1(symbol) or sector == K.SENS_RULE_B_SECTOR


def variant_ids(sample: Mapping[int, Mapping[str, str]]) -> dict[str, list[int]]:
    """The ids KEPT under each reporting variant, sorted."""
    keep: dict[str, list[int]] = {v: [] for v in VARIANT_NOTES}
    for rid in sorted(sample):
        sym = sample[rid]["symbol"]
        sector = sample[rid].get("sector")
        keep[VARIANT_ALL].append(rid)
        if rule_a(sym):
            continue
        keep[VARIANT_A].append(rid)
        if not rule_b1(sym):
            keep[VARIANT_A_B1].append(rid)
        if not rule_b2(sym, sector):
            keep[VARIANT_A_B2].append(rid)
    return keep


def _rates_by_variant(grades: Mapping[int, str],
                      keep: Mapping[str, Sequence[int]]) -> dict:
    return {v: class_rates(grades, ids) for v, ids in keep.items()}


def summarize(sample_csv: str | os.PathLike, opus_csv: str | os.PathLike,
              fable_csv: str | os.PathLike, final_csv: str | os.PathLike
              ) -> dict:
    """Agreement, kappa, and rates of the three grade sets (9.13). Every grade
    set must cover exactly the sample's ids."""
    sample = load_sample(sample_csv)
    ids = set(sample)
    opus = load_grades(opus_csv, ids)
    fable = load_grades(fable_csv, ids)
    final = load_grades(final_csv, ids)
    keep = variant_ids(sample)
    return {
        "schema": "c1_relevance_summary/1",
        "n_sample": len(sample),
        "grades_order": list(GRADES),
        "inputs": {name: {"path": str(p), "sha256": sha256_file(p)}
                   for name, p in (("sample", sample_csv), ("opus", opus_csv),
                                   ("fable", fable_csv), ("final", final_csv))},
        "agreement_opus_fable": {
            "raw_agreement": raw_agreement(opus, fable),
            "n_agree": sum(opus[i] == fable[i] for i in ids),
            "n_disagree": sum(opus[i] != fable[i] for i in ids),
            "cohens_kappa": cohens_kappa(opus, fable),
            "confusion_rows_opus_cols_fable": confusion(opus, fable),
        },
        "variants": {v: {"note": VARIANT_NOTES[v], "n": len(keep[v]),
                         "approximate": v in (VARIANT_A_B1, VARIANT_A_B2)}
                     for v in VARIANT_NOTES},
        "rates": {
            "opus": _rates_by_variant(opus, keep),
            "fable": _rates_by_variant(fable, keep),
            "final": _rates_by_variant(final, keep),
        },
        "note": "Nothing is filtered on these grades (Amendment 8.3).",
    }


# ---------------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m news_eval.relevance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="draw the 9.13 sample")
    d.add_argument("--out", required=True)
    d.add_argument("--db", required=True,
                   help="the database to draw from; required, no default "
                   "(C.1 ruling N4)")
    d.add_argument("--real-db", default=None,
                   help="test mode only; adds a live database path")
    d.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("summarize", help="agreement, kappa and rates")
    for flag in ("--sample", "--opus", "--fable", "--final", "--out"):
        s.add_argument(flag, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "draw":
        refusal = data.override_refusal({"--real-db": args.real_db})
        if refusal:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return 2
    try:
        if args.cmd == "draw":
            meta = draw(args.db, args.out, real_db_path=args.real_db,
                        overwrite=args.overwrite)
            print(f"drew {meta['n_drawn']} of {meta['population_count']} "
                  f"rows -> {args.out} sha256 {meta['csv_sha256']}")
            return 0
        out = summarize(args.sample, args.opus, args.fable, args.final)
        Path(args.out).write_text(json.dumps(out, sort_keys=True, indent=2)
                                  + "\n", encoding="utf-8")
        agr = out["agreement_opus_fable"]
        print(f"agreement {agr['raw_agreement']:.4f} kappa "
              f"{agr['cohens_kappa']} -> {args.out}")
        return 0
    except (RelevanceRefusal, data.LoaderRefusal, FileNotFoundError,
            envcheck.EnvironmentRefused) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main())
