"""Horizon and the actionable moment (EXPERIMENT.md Task 4).

THE CONVENTION, both cases:

  headline arrives DURING the regular session
      scored from that session's CLOSE to the next session's CLOSE
  headline arrives OUTSIDE the regular session
      scored from the next session's OPEN to that same session's CLOSE

Either way the hold is roughly one session.

THE MINIMUM DELAY is 20 minutes between the publication timestamp and the
FIRST ACTIONABLE MOMENT. Task 4 names one instance of it: a headline published
within 20 minutes of a close "cannot be acted on at that close and rolls to the
next session, scored open-to-close there". The rule as stated is general, about
the first actionable moment rather than about closes specifically, so it is
applied to an OPEN anchor too. A headline landing eight minutes before the
opening bell is exactly as unactionable at that bell as one landing eight
minutes before the closing bell, and treating only the close case would make
the delay depend on which side of the session the news arrived.

EVERY DATE COMES FROM THE EXCHANGE CALENDAR, never from a weekday rule, and
every close comes from the calendar's own `close` column, so a half day is
honoured rather than assumed to be 16:00.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import spec

_MARKET = ZoneInfo(spec.MARKET_TZ)


class UnknownSession(KeyError):
    """A session the calendar does not carry.

    RAISED RATHER THAN DEFAULTED. `open_utc` and `close_utc` used to fall back
    to 09:30 and 16:00 for any date handed to them, so a session beyond the
    loaded calendar produced a complete, plausible, entirely invented trading
    day. Measured on the stale calendar: close_utc('2026-08-15'), a Saturday
    past coverage, returned 20:00Z as though it were a normal session. That is
    the shape of all six fabrications recorded in this project, a plausible
    value manufactured from absent input, and a default is what made it
    possible.
    """


def parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp. Raises on anything else rather than
    guessing a timezone, because a guessed offset silently moves a headline
    across the session boundary the whole convention turns on."""
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    out = datetime.fromisoformat(text)
    if out.tzinfo is None:
        raise ValueError(f"timestamp carries no timezone: {ts!r}")
    return out.astimezone(timezone.utc)


def to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Calendar:
    """The exchange calendar as the horizon rules need it."""
    sessions: tuple[str, ...]
    opens: dict[str, str]
    closes: dict[str, str]

    @classmethod
    def from_rows(cls, rows: list[tuple[str, str, str]]) -> "Calendar":
        rows = sorted(rows, key=lambda r: r[0])
        return cls(sessions=tuple(r[0] for r in rows),
                   opens={r[0]: r[1] for r in rows},
                   closes={r[0]: r[2] for r in rows})

    def index_of(self, session: str) -> int:
        return self.sessions.index(session)

    def next_session(self, session: str) -> str | None:
        i = self.index_of(session)
        return self.sessions[i + 1] if i + 1 < len(self.sessions) else None

    def session_ahead(self, session: str, n: int) -> str | None:
        i = self.index_of(session) + n
        return self.sessions[i] if 0 <= i < len(self.sessions) else None

    def _at(self, session: str, hhmm: str) -> datetime:
        h, m = hhmm.split(":")
        naive = datetime.strptime(session, "%Y-%m-%d").replace(
            hour=int(h), minute=int(m))
        return naive.replace(tzinfo=_MARKET).astimezone(timezone.utc)

    def open_utc(self, session: str) -> datetime:
        if session not in self.opens:
            raise UnknownSession(session)
        return self._at(session, self.opens[session])

    def close_utc(self, session: str) -> datetime:
        """The calendar's OWN close, so a half day is honoured. A session the
        calendar does not carry raises rather than assuming 16:00: on
        2026-11-27 the real close is 13:00, and a default would put the
        actionable moment three hours after the bell."""
        if session not in self.closes:
            raise UnknownSession(session)
        return self._at(session, self.closes[session])

    def session_on_or_after(self, day: str) -> str | None:
        for s in self.sessions:
            if s >= day:
                return s
        return None


@dataclass(frozen=True)
class AnchorResolution:
    """Where a headline becomes actionable and what window scores it."""
    anchor_kind: str          # spec.ANCHOR_*
    anchor_session: str       # the session the anchor belongs to
    anchor_ts: str            # ISO-8601 UTC
    scoring_session: str      # the session whose close ends the scored window
    delay_rolled: bool        # the 20-minute delay pushed it to a later session
    reason: str               # "" when resolvable, else an exclusion reason


def resolve_anchor(published: datetime, cal: Calendar) -> AnchorResolution:
    """The first actionable moment for one headline, and the session it scores.

    Returns a resolution carrying an exclusion reason instead of raising when
    the calendar runs out, because a headline published after the last known
    session is not an error. It is an observation that cannot be scored YET and
    must still be recorded.
    """
    delay = timedelta(minutes=spec.MIN_DELAY_MINUTES)
    day = published.astimezone(_MARKET).strftime("%Y-%m-%d")

    in_session = (day in cal.closes
                  and cal.open_utc(day) <= published < cal.close_utc(day))

    if in_session:
        close = cal.close_utc(day)
        if published + delay <= close:
            nxt = cal.next_session(day)
            if nxt is None:
                return AnchorResolution(
                    spec.ANCHOR_SAME_SESSION_CLOSE, day, to_iso_z(close), "",
                    False, spec.EXCLUSION_CALENDAR_EXHAUSTED)
            return AnchorResolution(spec.ANCHOR_SAME_SESSION_CLOSE, day,
                                    to_iso_z(close), nxt, False, "")
        # Inside the 20 minutes before the close. Roll to the next session and
        # score it open-to-close there.
        rolled_to = cal.next_session(day)
        if rolled_to is None:
            return AnchorResolution(spec.ANCHOR_NEXT_SESSION_OPEN, "", "", "",
                                    True, spec.EXCLUSION_CALENDAR_EXHAUSTED)
        return AnchorResolution(spec.ANCHOR_NEXT_SESSION_OPEN, rolled_to,
                                to_iso_z(cal.open_utc(rolled_to)), rolled_to,
                                True, "")

    # Outside the regular session. Take the first session whose OPEN is both
    # after the publication and at least the delay away from it.
    candidate = cal.session_on_or_after(day)
    rolled = False
    while candidate is not None:
        opening = cal.open_utc(candidate)
        if opening > published:
            if published + delay <= opening:
                return AnchorResolution(spec.ANCHOR_NEXT_SESSION_OPEN,
                                        candidate, to_iso_z(opening),
                                        candidate, rolled, "")
            rolled = True
        candidate = cal.next_session(candidate)
    return AnchorResolution(spec.ANCHOR_NEXT_SESSION_OPEN, "", "", "", rolled,
                            spec.EXCLUSION_CALENDAR_EXHAUSTED)
