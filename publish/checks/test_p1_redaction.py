"""Check that the public relevance CSVs carry no third-party headline text.

Originals sit in reports/. Redacted copies sit in publish/llm-news-drift/reports/.
Both are resolved from the repository root, the parent of publish/.
"""
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = ROOT / "reports"
REDACTED_DIR = ROOT / "publish" / "llm-news-drift" / "reports"

NAMES = [
    "c1_relevance_sample.csv",
    "c1_relevance_grader_input.csv",
    "c1_relevance_grades_opus.csv",
    "c1_relevance_grades_fable.csv",
    "c1_relevance_final.csv",
]
KEPT = {"id", "symbol", "query_date", "sector", "stratum", "grade", "name_source", "source"}
DROPPED_ALWAYS = {"headline", "issuer_name", "reason"}
MIN_LEN_SHORT_FIELDS = 12  # applies to reason and issuer_name only
SOURCE_LABEL_MAX_LEN = 20


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames), rows


@pytest.fixture(params=NAMES)
def pair(request):
    name = request.param
    original = read_csv(ORIGINAL_DIR / name)
    redacted = read_csv(REDACTED_DIR / name)
    redacted_text = (REDACTED_DIR / name).read_text(encoding="utf-8")
    return name, original, redacted, redacted_text


def test_row_counts_and_ids_match(pair):
    _, (_, orig_rows), (_, red_rows), _ = pair
    assert len(red_rows) == len(orig_rows)
    assert [r["id"] for r in red_rows] == [r["id"] for r in orig_rows]


def test_kept_columns_equal_original_columns_in_kept_set(pair):
    _, (orig_cols, orig_rows), (red_cols, red_rows), _ = pair
    expected = [c for c in orig_cols if c in KEPT]
    assert red_cols == expected
    for orig, red in zip(orig_rows, red_rows):
        assert {c: orig[c] for c in expected} == red


def test_dropped_columns_are_absent(pair):
    _, (orig_cols, _), (red_cols, _), _ = pair
    for col in DROPPED_ALWAYS & set(orig_cols):
        assert col not in red_cols
    assert set(red_cols) <= KEPT


def test_no_original_text_appears_in_redacted_file(pair):
    name, (orig_cols, orig_rows), _, redacted_text = pair
    for col in orig_cols:
        if col in KEPT:
            continue
        for row in orig_rows:
            value = row[col]
            if not value:
                continue
            if col in {"reason", "issuer_name"} and len(value) < MIN_LEN_SHORT_FIELDS:
                continue
            assert value not in redacted_text, f"{name}: text from dropped column {col} found"


def test_source_column_holds_short_labels_only(pair):
    _, _, (red_cols, red_rows), _ = pair
    if "source" not in red_cols:
        pytest.skip("no source column in this file")
    labels = {r["source"] for r in red_rows}
    assert all(0 < len(v) <= SOURCE_LABEL_MAX_LEN for v in labels)
    assert len(labels) <= 5


def test_files_use_unix_line_ends_and_utf8(pair):
    name, _, _, _ = pair
    raw = (REDACTED_DIR / name).read_bytes()
    assert b"\r" not in raw
    raw.decode("utf-8")
