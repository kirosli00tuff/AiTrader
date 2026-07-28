"""De-duplication and story grouping (EXPERIMENT.md Task 5).

Task 5 handles news-event clustering by DE-DUPLICATION rather than by the
variance estimator, and states two rules:

  * "near-identical headlines for the same ticker within 24 hours collapse to
    the first"
  * "one story naming several tickers produces one observation per ticker with
    a shared `story_group_id` recorded"

WHAT "NEAR-IDENTICAL" IS TAKEN TO MEAN, and why it is not a similarity score.
A fuzzy match needs a threshold and the specification does not give one.
Inventing a cutoff would be choosing a specification value after acceptance,
which this session may not do. Two signals the specification DOES provide are
used instead, and either alone is sufficient:

  1. THE PROVIDER'S OWN ARTICLE ID. Task 8 records `source_article_id`
     explicitly "for de-duplication". The same id twice is the same article by
     the source's own account, which is stronger evidence than any string
     comparison.
  2. THE NORMALISED HEADLINE. Case, punctuation and whitespace carry no
     information about whether two syndicated copies are the same story, so
     they are removed before comparison. What remains is compared exactly.

That pair collapses the syndication case the rule exists for without adding a
knob. If a later measurement shows it leaves real duplicates uncollapsed, the
fix is a pre-registered threshold, not a guess made here.

STORY GROUPS ARE ASSIGNED FROM THE FIRST SIGHTING, never from a calendar
bucket. Bucketing by day would split one story across midnight and give one
event two group ids, the opposite of what the field is for.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import spec

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_headline(text: str) -> str:
    """Lower-cased, punctuation removed, whitespace collapsed.

    Deliberately lossy in exactly three ways, none of which distinguishes two
    copies of one story. The RAW headline is recorded untouched on the row
    (Task 8); this form exists only to compare.
    """
    lowered = str(text or "").lower()
    return _SPACE.sub(" ", _PUNCT.sub(" ", lowered)).strip()


@dataclass
class _Story:
    group_id: str
    first_seen: datetime


@dataclass
class Deduplicator:
    """Collapses repeats within the window and assigns story groups.

    Stateful and order-dependent by design: "collapse to the FIRST" is a
    statement about arrival order, so headlines must be fed in ascending
    publication time. `collect` sorts before feeding and a test pins it.
    """
    window: timedelta = field(
        default_factory=lambda: timedelta(hours=spec.DEDUP_WINDOW_HOURS))
    _by_article: dict[str, datetime] = field(default_factory=dict)
    _by_ticker_text: dict[tuple[str, str], datetime] = field(
        default_factory=dict)
    _stories: dict[str, _Story] = field(default_factory=dict)

    def _story_group(self, normalized: str, published: datetime) -> str:
        prior = self._stories.get(normalized)
        if prior is not None and published - prior.first_seen <= self.window:
            return prior.group_id
        group_id = "sg_" + hashlib.sha256(
            (normalized + "|" + published.strftime("%Y-%m-%dT%H:%M:%SZ")
             ).encode("utf-8")).hexdigest()[:16]
        self._stories[normalized] = _Story(group_id, published)
        return group_id

    def consider(self, *, ticker: str, headline: str, article_id: str,
                 published: datetime) -> tuple[bool, str]:
        """Return (is_duplicate, story_group_id) for one headline.

        The story group is assigned even to a duplicate, so a collapsed row
        still records which story it belonged to. Dropping the group on a
        duplicate would make the 10-percent re-clustering check in Task 5
        under-count exactly the stories it looks for.
        """
        normalized = normalize_headline(headline)
        group_id = self._story_group(normalized, published)

        aid = str(article_id or "").strip()
        if aid:
            seen = self._by_article.get(aid)
            if seen is not None and published - seen <= self.window:
                return True, group_id

        key = (str(ticker).upper(), normalized)
        seen_text = self._by_ticker_text.get(key)
        if seen_text is not None and published - seen_text <= self.window:
            return True, group_id

        if aid:
            self._by_article[aid] = published
        self._by_ticker_text[key] = published
        return False, group_id
