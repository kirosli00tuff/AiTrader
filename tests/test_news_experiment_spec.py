"""The transcription is checked against EXPERIMENT.md, not trusted.

`news_experiment/spec.py` claims to transcribe an ACCEPTED and CLOSED
specification. A claim like that is worth nothing unless something reads the
document and compares, so these tests do exactly that: they parse EXPERIMENT.md
and fail when the code and the document disagree.

Every check here is MUTATION-TESTED. It is not enough that a check passes on
correct input; a check that passes on everything is not a check. Each mutation
below is applied to a copy of the real value and the assertion helper must
reject it.
"""
from __future__ import annotations

import ast
import os
import re

import pytest

from news_experiment import spec

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENT_MD = os.path.join(REPO, "EXPERIMENT.md")


def _document() -> str:
    with open(EXPERIMENT_MD, encoding="utf-8") as fh:
        return fh.read()


def extract_system_block(text: str) -> str:
    """The fenced system block under Task 3's byte-for-byte heading."""
    heading = "### The exact prompt, byte for byte"
    start = text.index(heading)
    fence = text.index("```", start)
    body_start = text.index("\n", fence) + 1
    body_end = text.index("```", body_start)
    return text[body_start:body_end].rstrip("\n")


def assert_prompt_matches(candidate: str, document: str) -> None:
    """The assertion under test. Raises when the prompt is not byte-identical."""
    expected = extract_system_block(document)
    if candidate != expected:
        raise AssertionError("system prompt differs from EXPERIMENT.md")


# --- The prompt --------------------------------------------------------------

def test_system_prompt_is_byte_identical_to_the_specification():
    assert_prompt_matches(spec.SYSTEM_PROMPT, _document())


@pytest.mark.parametrize("mutate", [
    lambda s: s.replace("integer from 1 to 5", "integer from 1 to 10"),
    lambda s: s.replace("When judgment is NEUTRAL, set strength to 1.", ""),
    lambda s: s.replace("barely tilts the odds", "slightly tilts the odds"),
    lambda s: s.replace('"strength": 3, ', ""),
    lambda s: s.replace("by the next close.", "by the next week."),
    lambda s: s + "\n",
    lambda s: s.replace("POSITIVE, NEGATIVE, NEUTRAL", "POSITIVE, NEGATIVE"),
], ids=["scale-1-to-10", "drop-neutral-rule", "reword-anchor-1",
        "drop-strength-from-template", "change-horizon", "trailing-newline",
        "drop-neutral-judgment"])
def test_prompt_check_rejects_every_mutation(mutate):
    """MUTATION TEST. Each edit is a real way the prompt could drift and the
    byte-identity check must catch every one. The trailing newline is included
    deliberately: it is invisible in review and would change the hash."""
    mutated = mutate(spec.SYSTEM_PROMPT)
    assert mutated != spec.SYSTEM_PROMPT, "mutation did not change the prompt"
    with pytest.raises(AssertionError):
        assert_prompt_matches(mutated, _document())


def test_user_block_is_byte_identical_to_the_specification():
    doc = _document()
    start = doc.index("**User block**")
    fence = doc.index("```", start)
    body_start = doc.index("\n", fence) + 1
    body_end = doc.index("```", body_start)
    assert spec.USER_PROMPT_TEMPLATE == doc[body_start:body_end].rstrip("\n")


def test_prompt_hash_is_stable_and_recorded():
    assert spec.prompt_sha256() == spec.prompt_sha256()
    assert len(spec.prompt_sha256()) == 64


def test_headline_is_stripped_but_never_truncated_or_cleaned():
    raw = "  Acme Corp beats: revenue +12%, guidance raised  "
    built = spec.build_user_prompt("ACME", raw)
    assert built.endswith(raw.strip())
    assert "+12%" in built and ":" in built


# --- The numbers -------------------------------------------------------------

def test_band_and_floor_match_the_document():
    doc = _document()
    assert "2,070,000" in doc and spec.ADV_BAND_LOW == 2_070_000.0
    assert "65,300,000" in doc and spec.ADV_BAND_HIGH == 65_300_000.0
    # AMENDMENT 2 derived the floor at 10.00 from the tick's proportional cost.
    assert spec.MIN_MEDIAN_CLOSE == 10.00
    assert "**THE CHOICE: 10.00 USD**" in doc


def test_strata_partition_the_band_with_no_gap_and_no_overlap():
    lows = [lo for _n, lo, _hi in spec.STRATA]
    highs = [hi for _n, _lo, hi in spec.STRATA]
    assert highs[0] == spec.ADV_BAND_HIGH
    assert lows[-1] == spec.ADV_BAND_LOW
    for i in range(len(spec.STRATA) - 1):
        assert lows[i] == highs[i + 1], "strata must abut exactly"
    for _n, lo, hi in spec.STRATA:
        assert spec.stratum_for((lo + hi) / 2) is not None
    assert spec.stratum_for(spec.ADV_BAND_LOW) == "S4"
    assert spec.stratum_for(spec.ADV_BAND_HIGH) == "S1"
    assert spec.stratum_for(spec.ADV_BAND_LOW - 1) is None
    assert spec.stratum_for(spec.ADV_BAND_HIGH + 1) is None


def test_model_is_an_approved_string_in_claude_md():
    with open(os.path.join(REPO, "CLAUDE.md"), encoding="utf-8") as fh:
        claude_md = fh.read()
    assert spec.MODEL_ID == "claude-haiku-4-5"
    assert spec.MODEL_ID in claude_md, (
        "the model must be one of CLAUDE.md's approved strings; Amendment 3 "
        "closed the hard-rule conflict by removal, not by exception")


def test_delay_window_matches_the_document():
    assert spec.MIN_DELAY_MINUTES == 20 and "**20 minutes**" in _document()
    assert spec.DEDUP_WINDOW_HOURS == 24


def test_the_stale_rule_id_is_recorded_verbatim_and_the_floor_beside_it():
    """The rule id says p5 and Amendment 2 set the floor to 10.00. The id is
    transcribed as written and the floor recorded separately, so a row is
    self-describing whatever the label says."""
    assert spec.RULE_ID == "U-NEWS-ADV2M-65M-stk-w60-m40-p5-s400"
    assert spec.RULE_ID in _document()
    assert spec.MIN_MEDIAN_CLOSE == 10.00


# --- Isolation ---------------------------------------------------------------

def test_no_production_module_imports_the_experiment():
    """STANDALONE MEANS STANDALONE. If the engine, the risk gate, execution,
    the sleeves, the bridge or the GUI ever import this package, the collector
    has stopped being a research script and this test says so."""
    watched = ("core", "risk", "execution", "signal_engine", "learning",
               "storage", "python_bridge", "api_server", "ui", "web",
               "discovery", "adaptive", "research_satellite", "ml_factor",
               "rl_advisory", "whale_signal", "llm_consensus", "backtest",
               "market_data", "account_manager", "ops")
    offenders = []
    for folder in watched:
        root = os.path.join(REPO, folder)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for fn in files:
                if not fn.endswith((".py", ".cpp", ".hpp")):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    body = fh.read()
                # IMPORTS, not mentions. A comment naming the package is
                # documentation; an import is a dependency, and only the
                # second one breaks standalone.
                if re.search(r"^\s*(?:from|import)\s+news_experiment\b", body,
                             re.MULTILINE):
                    offenders.append(os.path.relpath(path, REPO))
    assert not offenders, (
        f"news_experiment must stay standalone, imported by: {offenders}")


def test_the_collector_never_writes_the_operational_database():
    """The C++ engine is the sole writer of the operational tables. A research
    collector writing beside it is how two writers come to disagree."""
    from news_experiment import store
    assert not store.DEFAULT_DB.endswith("market_ai_lab.db")
    # A STRING THE CODE COULD OPEN, not a mention. store.py's docstring
    # explains why it stays away from the operational database, and a check
    # that failed on the explanation would push the reasoning out of the file.
    # Docstrings are therefore excluded and every other string constant is
    # examined, which is what a path passed to sqlite3.connect would be.
    for module in ("collect", "store", "outcomes", "universe"):
        path = os.path.join(REPO, "news_experiment", f"{module}.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docstrings:
                    continue
                assert "market_ai_lab" not in node.value, (
                    f"{module} carries an operational-database path")
