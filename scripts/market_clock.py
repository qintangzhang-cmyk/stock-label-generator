#!/usr/bin/env python3
"""When should quotes.json have been refreshed?

The stickers need the latest *closed* US session. US regular trading ends at
16:00 New York time; we treat 16:15 New York time on a weekday as "ready"
(15 minutes of margin for the closing auction to settle). Using New York time
via zoneinfo means the EDT/EST switch (e.g. 2026-11-01) needs no code change:
ready is 20:15 UTC in summer and 21:15 UTC in winter.

US market holidays are not modelled: on a holiday the run still happens after
16:15 and simply records the previous session again, which is harmless.
"""
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
READY_AT = time(16, 15)


def _ready_on(day):
    return datetime.combine(day, READY_AT, tzinfo=NY)


def latest_ready(now=None):
    """Most recent weekday 16:15 New York time at or before `now` (aware, UTC)."""
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(NY).date()
    while True:
        if day.weekday() < 5 and _ready_on(day) <= now:
            return _ready_on(day).astimezone(timezone.utc)
        day -= timedelta(days=1)


def next_ready(now=None):
    """Next weekday 16:15 New York time strictly after `now` (aware, UTC)."""
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(NY).date()
    while True:
        if day.weekday() < 5 and _ready_on(day) > now:
            return _ready_on(day).astimezone(timezone.utc)
        day += timedelta(days=1)


def parse_generated_at(doc):
    return datetime.fromisoformat(doc["generatedAt"].replace("Z", "+00:00"))


def is_fresh(doc, now=None):
    """True when quotes.json was generated after the latest US close."""
    try:
        return parse_generated_at(doc) >= latest_ready(now)
    except (KeyError, TypeError, ValueError):
        return False
