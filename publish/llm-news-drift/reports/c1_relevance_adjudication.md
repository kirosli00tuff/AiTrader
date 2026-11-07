# Stage C.1 relevance grade adjudication (headline-free summary)

This file summarizes the original adjudication of 2026-10-11. The original stays in the AiTrader repository. It quotes third-party headlines, so it is not published here. The rubric is Amendment 8.3 and the grader input rule is Amendment 9.13 of EXPERIMENT.md.

## What was adjudicated

- A sample of 200 rows, drawn by the frozen relevance code. The columns are in `c1_relevance_sample.csv`.
- Two graders each labeled every row. Each grader was blind to the other. Each saw only the symbol, the issuer name and the headline. The issuer names came from the universe table for all 140 symbols. Their provenance is the `name_source` column in `c1_relevance_grader_input.csv`.
- The lead reconciled the two label sets and wrote the final grade for each row, in `c1_relevance_final.csv`.
- Nothing is filtered on these grades (Amendment 8.3).

## Counts per outcome

| Label set | company-specific | roundup | off-topic |
|---|---|---|---|
| Grader 1 (Opus) | 134 | 38 | 28 |
| Grader 2 (Fable) | 131 | 7 | 62 |
| Final | 131 (65.5%) | 7 (3.5%) | 62 (31.0%) |

- The graders agreed on 164 of 200 rows. Raw agreement is 0.820. Cohen's kappa is 0.648.
- Agreed rows keep the shared grade. The `source` column reads `agreed` for these 164 rows.
- The graders disagreed on 36 rows. The `source` column reads `lead` for these. The lead ruled on each one.
- Disagreement pattern: 32 rows where Grader 1 said roundup and Grader 2 said off-topic, 3 rows where Grader 1 said company-specific and Grader 2 said off-topic, and 1 row where Grader 1 said off-topic and Grader 2 said roundup.

## Rubric

- company-specific: the headline is about the symbol's issuer.
- roundup: the issuer is one of several named.
- off-topic: neither of the above.

## The rule used

A headline that does not name the issuer, and does not refer to it unambiguously in another way, is off-topic. It is not a roundup, because the issuer is not named. The grader cannot see the article body, so the body is not graded. This covers stock lists, mover lists, market wraps, analyst roundups that name other firms, sector pieces, fund letters and generic templates.

The rule follows the rubric wording ("named", "the headline is about"). It was not chosen to follow either grader. It matches Grader 2 on all 36 disagreements.

The alternative reading counts an unnamed multi-stock list as a roundup when the issuer plausibly sits in the article. Under it, the 32 roundup-versus-off-topic rows would flip. The final rates would then be 131 company-specific (65.5%), 39 roundup (19.5%) and 30 off-topic (15.0%). The original reports this so a reader can apply it. No row moves between company-specific and the other two classes under either reading.

## Individual rulings outside the rule

Four rows needed a separate ruling. Their ids and symbols are SOC (id 11888), MGEE (id 15442), INDB (id 19800) and STRK (id 22436). The first three are off-topic. STRK is roundup. In each case the lead read the headline text alone, as the graders did. The reasoning is in the original file.

## Final rates by subset

The frozen summary reports the final rates on the full sample (200 rows) and on three subsets. The subsets remove rows under rule (a) of Amendment 8.2 and two approximations of rule (b). Rule (b) has no exact form on the six sampled columns, so Stage C.2 recomputes it exactly. The company-specific share is 68.5% after rule (a) alone (181 rows) and 68.9% after rule (a) plus either rule (b) approximation (180 rows).

## Files in this directory

- `c1_relevance_sample.csv`: id, symbol, query_date, sector, stratum.
- `c1_relevance_grader_input.csv`: id, symbol, name_source.
- `c1_relevance_grades_opus.csv` and `c1_relevance_grades_fable.csv`: id, grade.
- `c1_relevance_final.csv`: id, grade, source.

Headline text, issuer names and grader reasons are dropped from all five. Row order and row counts match the originals. The check is `checks/test_p1_redaction.py`.
