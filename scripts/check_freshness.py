#!/usr/bin/env python3
"""Is the quotes.json the stores actually load up to date?

Used by the Data Watchdog workflow. Reads the copy served by GitHub Pages (the
same URL the label pages fetch, cache-busted), not the one on main, so a
failed Pages deploy also counts as stale.

"Fresh" means generated after the latest US close (see market_clock.py) and
containing the key symbols — the same rule fetch_gate.py uses — so the answer
is right on weekends and across the EDT/EST switch, unlike a fixed hour limit.

Prints one line explaining the verdict. Exit 0 fresh, 1 stale or unreadable.

Usage:
    python3 scripts/check_freshness.py [<pages base url>]
    python3 scripts/check_freshness.py --file <quotes.json>   # judge a local copy
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_gate import has_required  # noqa: E402
from market_clock import is_fresh, latest_ready, parse_generated_at  # noqa: E402

DEFAULT_BASE = "https://qintangzhang-cmyk.github.io/stock-label-generator/"


def main():
    now = datetime.now(timezone.utc)
    expected = latest_ready(now).strftime("%Y-%m-%d %H:%M UTC")
    if sys.argv[1:2] == ["--file"]:
        url = sys.argv[2]
    else:
        base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
        url = "%squotes.json?t=%d" % (base.rstrip("/") + "/", int(time.time()))
    try:
        if sys.argv[1:2] == ["--file"]:
            with open(url) as f:
                doc = json.load(f)
        else:
            req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            doc = json.load(urllib.request.urlopen(req, timeout=30))
        gen = parse_generated_at(doc)
    except Exception as e:  # noqa: BLE001 — unreadable counts as stale
        print("could not read %s: %s" % (url, e))
        sys.exit(1)

    age_h = (now - gen).total_seconds() / 3600
    if not is_fresh(doc, now):
        print("stale: generated %s (%.1f h ago), before the latest US close %s" % (doc["generatedAt"], age_h, expected))
        sys.exit(1)
    try:
        complete = has_required(doc)
    except Exception:  # noqa: BLE001
        complete = False
    if not complete:
        print("incomplete: generated %s but key symbols are missing" % doc["generatedAt"])
        sys.exit(1)
    print("fresh: generated %s (%.1f h ago), US session %s" % (doc["generatedAt"], age_h, doc.get("usTradeDate", "?")))


if __name__ == "__main__":
    main()
