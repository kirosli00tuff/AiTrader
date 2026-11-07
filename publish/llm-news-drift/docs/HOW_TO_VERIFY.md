# How to verify

This page lists what you can check from this repository alone, and what you cannot.

Every command below ran on 2026-11-07, on Linux, in fresh clones of the build that became this
repository. The output shown is what it printed. `<clone>` stands for the folder of the clone.

You need git and [uv](https://docs.astral.sh/uv/). uv downloads Python 3.12.13 and the pinned packages.
No key or account is needed. The test suite takes about 5 minutes.

## 1. Get the repository

```
git clone <this repository's URL> llm-news-drift
cd llm-news-drift
```

## 2. See the dated amendments

```
git log --follow --date=short --format='%h %ad %s' EXPERIMENT.md
```

This lists the 17 commits that changed EXPERIMENT.md, newest first. The oldest is `f99fe72` on
2026-07-27, which proposes the pre-registration. The newest is `c915772` on 2026-10-28, Amendment 10.
docs/TIMELINE.md dates every amendment and names its commit.

Git dates are written by whoever makes the commit, so they are not proof on their own. The same commits
are in AiTrader, the working repository, under the ids in the AiTrader column of docs/TIMELINE.md.
docs/DECISIONS.md (V7) keeps AiTrader public as the dated audit trail until the readout. Commit messages
here quote AiTrader ids, and TIMELINE.md maps them to the ids here.

## 3. Build the harness environment

```
uv venv --python 3.12.13
uv pip install -r news_eval/requirements-eval.lock
export PYTHONPYCACHEPREFIX="$(mktemp -d)"
.venv/bin/python -c 'import sys, sqlite3, numpy; print(sys.version.split()[0], numpy.__version__, sqlite3.sqlite_version)'
```

The last command printed:

```
3.12.13 2.5.3 3.53.1
```

The harness is pinned to Python 3.12.13, numpy 2.5.3 and SQLite 3.53.1. The manifest records all three,
and the freeze check fails under any other version, with a `pins:` line that names it. Ask uv for 3.12.13
exactly, because the check compares the full version. The SQLite version is the one Python's sqlite3
module reports, so it depends on the Python build. The lock file
says why the harness does not use the repository's newer stack: numpy 1.26.4 on Python 3.14.4 silently
corrupted arithmetic on large arrays (news_eval/requirements-eval.lock, line 2).

Set PYTHONPYCACHEPREFIX before the first Python command and keep it set, as C.3 did. The freeze check
fails on any .pyc file under news_eval/, and Python writes one there whenever it imports the harness,
unless bytecode goes somewhere else. PYTHONDONTWRITEBYTECODE is not enough for the test suite. One run
with it instead left 15 .pyc files in news_eval/__pycache__, because some tests start their own Python
processes, and the tests that check the freeze then failed. Two tests in tests/test_news_eval_gate.py
also write bytecode under ~/.cache/news_eval_pyc, outside the clone.

To confirm that no bytecode is in the harness folder:

```
find news_eval -name '*.pyc' | wc -l
```

It printed `0`.

## 4. Check the harness freeze

```
.venv/bin/python -m news_eval.freeze check
```

It printed:

```
manifest <clone>/reports/c3_harness_freeze.json sha256 19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8
FROZEN: match
```

With no options it checks reports/c3_harness_freeze.json, the C.3 manifest, against the clone it runs
in. `--manifest` names another manifest and `--root` another tree.

The manifest is a JSON file. Its `files` and `inputs` sections are lists of `{path, sha256, bytes}`.
`files` has 34 entries: every file under news_eval/, every tests/test_news_eval_*.py and
reports/c1_verdict_mapping.md. `inputs` has 11: EXPERIMENT.md and the collector and cost files the
harness rests on. `pins` holds the versions, the seeds and the harness constants. The check recomputes
every entry. It fails on a missing or changed file, a harness file or test that the manifest does not
list, any .pyc under news_eval/, another Python, numpy or SQLite version, or a changed constant. The top
of news_eval/freeze.py says so.

The `external` section lists 5 PropExperiment files, with path and sha256 only. The harness read them
for patterns, and their paths are absolute paths on the machine that built it. They are informational
and never fail the check. On a machine without them, the check prints one line like this for each,
before `FROZEN: match`:

```
note (record only): external: <path>: None != <sha256>
```

A copy of the manifest with its external paths pointed nowhere printed exactly those five lines, then
`FROZEN: match`.

The manifest's hash ties it to the rest of the record:

```
sha256sum EXPERIMENT.md reports/c3_harness_freeze.json
.venv/bin/python -c 'import json; d = json.load(open("reports/c2_UNLOCK.json")); print(d["stage"], d["utc_time"], d["experiment_sha256"], d["manifest_sha256"])'
```

They printed:

```
964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe  EXPERIMENT.md
19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8  reports/c3_harness_freeze.json
C.2 2026-11-06T07:13:44Z 964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe 19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8
```

So the unlock file binds this EXPERIMENT.md and this manifest.

## 5. The C.1 manifest

reports/c1_harness_freeze.json records the first freeze, committed on 2026-10-11 in `847d381`. The
current code rejects it, because C.3 changed the manifest schema to `c3_harness_freeze/1` when it
re-froze the harness:

```
.venv/bin/python -m news_eval.freeze check --manifest reports/c1_harness_freeze.json
```

It printed:

```
MISMATCH manifest reports/c1_harness_freeze.json schema is not 'c3_harness_freeze/1'
NOT FROZEN: 1 difference(s)
```

To check it, run the code that wrote it. `09a900d` is the last commit before C.3 changed the harness
(AiTrader `86adee9`). `3fa575e` is Amendment 9 (AiTrader `c426318`).

```
git checkout --quiet 09a900d
.venv/bin/python -m news_eval.freeze check --manifest reports/c1_harness_freeze.json
git show 3fa575e:EXPERIMENT.md | sha256sum
git checkout --quiet main
```

The check printed:

```
manifest reports/c1_harness_freeze.json sha256 77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9
MISMATCH inputs: EXPERIMENT.md: bytes 186222 != 182742
MISMATCH inputs: EXPERIMENT.md: sha256 964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe != 641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386
NOT FROZEN: 2 difference(s)
```

and `git show` printed:

```
641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386  -
```

Read it this way. The C.1 manifest pins EXPERIMENT.md as it stood after Amendment 9, which is the file at
`3fa575e`. Amendment 10 came on 2026-10-28 in `c915772`, after the C.1 freeze, and changed the file. The
check lists only those two differences, so every other entry still matched at the commit before C.3:
every harness file and test, the other 10 inputs, the versions and the constants. C.3 ran the same check
at its start. The planner's ruling on it is in reports/C.3_RETURN.md.

## 6. Run the synthetic test suite

The tests use synthetic rows and a synthetic fixture. They need no database and no key.

Run them in a sparse clone that leaves out reports/c2/ and reports/c2_UNLOCK.json. Both are tracked here,
as the record of the C.2 gate runs. Three test files have guards, written before C.2, that assert those
paths do not exist:

| Test file | Guard |
|---|---|
| tests/test_news_eval_known_answers.py | line 119 |
| tests/test_news_eval_run_c2.py | line 95 |
| tests/test_news_eval_mutations.py | line 49 |

In a full clone, 157 tests in those files pass their body and then error at teardown. Each one is the same assertion, `assert [True, False, True] == [False, False, False]`. The list
reads: reports/c2_UNLOCK.json exists, reports/c2_RUN_ONCE.json does not, reports/c2/ exists. C.3 decided
its suite in a clean clone for this reason (reports/c3_evidence/run_suite_clean.sh). The guards are part
of the frozen harness, so changing them means a new manifest and a new unlock (reports/C.3_RETURN.md).

```
git clone --no-checkout <this repository's URL> llm-news-drift-sparse
cd llm-news-drift-sparse
git sparse-checkout set --no-cone '/*' '!/reports/c2/' '!/reports/c2_UNLOCK.json'
git checkout main
uv venv --python 3.12.13
uv pip install -r news_eval/requirements-eval.lock
export PYTHONPYCACHEPREFIX="$(mktemp -d)"
.venv/bin/python -m news_eval.freeze check
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_*.py
```

The freeze check printed `FROZEN: match`, and pytest ended with:

```
1002 passed in 307.34s (0:05:07)
```

`tests/test_*.py` collects the 19 test files here, 1,002 tests. To see the teardown errors, run the same
pytest line in the full clone from step 1.

### Counts, refreshed at the final build

Measured on the build that holds the root README.md and config/default_config.yaml, with the commands above.

| Clone | Tests | Passed | Failed | Errors | Skipped | Time |
|---|---|---|---|---|---|---|
| Sparse, without reports/c2/ and reports/c2_UNLOCK.json | 1,002 | 1,002 | 0 | 0 | 0 | 5:07 |
| Full | 1,002 | 1,002 | 0 | 157 | 0 | 4:36 |

The 157 errors in the full clone are 70 in test_news_eval_known_answers.py, 70 in
test_news_eval_run_c2.py and 17 in test_news_eval_mutations.py.

No test fails in either clone. Two groups of tests failed in earlier builds, and both pass now:

- 5 in tests/test_news_eval_data.py, `test_unlock_existence_alone_is_not_enough`. The test reads the README.md
  at the root of the repository as a file that exists and is not a valid unlock file. The root README.md
  exists in this build, and the 5 pass.
- 8 in tests/test_news_experiment_collector.py. They read config/default_config.yaml through backtest/fees.py
  line 95. This repository includes that file, and the 8 pass.

## 7. What you cannot verify here

**The headline database.** It is third-party news and is never published (LICENSE_NOTE.md). Every gate
figure and every judgment rests on it, so you cannot recompute them from this repository. You can read
the record of each snapshot. reports/c2/snap_20261028/snapshot.json and
reports/c2/snap_20261106/snapshot.json give its sha256, its size in bytes, and its row counts by state
and by query date. reports/c2/gate_log.jsonl records the manifest hash that each gate run used.

**The collection log after 2026-10-01.** COLLECTION_LOG.md here is the copy committed on 2026-10-02 in
`d58ecde` (AiTrader `ee891f3`). Its last run is the one at 2026-10-03T05:00:42Z, for target session
2026-10-01. The collector kept appending after that, but those entries were not committed before this
repository was built. The two permanent gaps before that date, 2026-08-28 and 2026-09-15, are in the log
itself. Two later events are recorded in other committed files:

- Session 2026-10-22, lost to an empty experiment credit balance: docs/DECISIONS.md, V3, line 110,
  committed in `5681f74` on 2026-10-28. reports/c2/snap_20261106/snapshot.json, committed in `fc56589`
  on 2026-11-06, counts 357 `model_failed`, 26 `excluded_pre_call`, 237 `no_news` and no `judged` rows
  for query date 2026-10-22.
- Session 2026-10-30, a permanent gap: docs/DECISIONS.md, V5, line 162, committed in `3a22e99` on
  2026-11-04. The same snapshot has no entry for 2026-10-30.

These commands show it:

```
git log -1 --date=short --format="%h %ad %s" -- COLLECTION_LOG.md
git log --date=short --format='%h %ad' -S'session 10-22 was lost' -- docs/DECISIONS.md
git log --date=short --format='%h %ad' -S'session 2026-10-30 is a new permanent gap' -- docs/DECISIONS.md
.venv/bin/python -c 'import json; q = json.load(open("reports/c2/snap_20261106/snapshot.json"))["collection_rows_by_query_date_state"]; print(q.get("2026-10-22"), q.get("2026-10-30"))'
```

The last one printed:

```
{'excluded_pre_call': 26, 'model_failed': 357, 'no_news': 237} None
```

**The PropExperiment files in the manifest.** They are not in this repository. They never affect the
check.

**Prompts before 2026-09-23.** They were not archived. AiTrader's RETURN.md holds summaries of those
sessions, and that file is not here (docs/TIMELINE.md). The archive in docs/prompts/ starts at STAGE_C.1.md
(2026-10-10), because B.1 to B.3 ran in the planning chat with no CLI prompt.
