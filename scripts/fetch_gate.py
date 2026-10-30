#!/usr/bin/env python3
"""Decide whether this Fetch Quotes run should fetch, and wait for the US close.

GitHub's scheduled runs start hours late (median ~3h in Oct 2026), so the
workflow is scheduled *before* the US close and this gate:

  wait    If the upcoming US close (16:15 New York) is less than
          MAX_WAIT_HOURS away, sleep until then — so data lands right after
          the close no matter how early GitHub starts the job.
  decide  Print "skip" if quotes.json already holds data generated after the
          latest close and contains the key symbols ("one good copy per
          day"), so later or delayed runs cannot overwrite the morning data
          with Hong Kong pre-market or intraday prices. Otherwise "fetch".

Explanations go to stderr.

Usage:
    python3 scripts/fetch_gate.py wait
    python3 scripts/fetch_gate.py decide <quotes.json> [--force]
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_clock import is_fresh, latest_ready, next_ready  # noqa: E402

MAX_WAIT_HOURS = float(os.environ.get("MAX_WAIT_HOURS", "5"))
REQUIRED = ["AAPL.US", "MSFT.US", "NVDA.US", "GOOGL.US", "AMZN.US", "META.US", "TSLA.US", "SPY.US"]


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def has_required(doc):
    got = {q.get("symbol") for q in doc.get("quotes", []) if q.get("price")}
    return all(s in got for s in REQUIRED)


def wait_for_close():
    now = datetime.now(timezone.utc)
    upcoming = next_ready(now)
    wait = (upcoming - now).total_seconds()
    if wait <= MAX_WAIT_HOURS * 3600:
        log("US close is %.0f min away; waiting until %s UTC" % (wait / 60, upcoming.strftime("%Y-%m-%d %H:%M")))
        time.sleep(max(0.0, wait) + 5)
    else:
        log("next US close is %.1f h away; not waiting" % (wait / 3600))


def decide(path, force):
    if force:
        log("force: fetching regardless of existing data")
        return "fetch"
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        log("no readable %s (%s): fetching" % (path, e))
        return "fetch"
    if is_fresh(doc) and has_required(doc):
        log("%s was generated %s, after the latest US close (%s UTC), and is complete: skipping"
            % (path, doc.get("generatedAt"), latest_ready().strftime("%Y-%m-%d %H:%M")))
        return "skip"
    log("%s predates the latest US close or is incomplete: fetching" % path)
    return "fetch"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "wait":
        wait_for_close()
    elif cmd == "decide":
        path = sys.argv[2] if len(sys.argv) > 2 else "quotes.json"
        print(decide(path, "--force" in sys.argv[3:]))
    else:
        sys.exit("usage: fetch_gate.py wait | decide <quotes.json> [--force]")


if __name__ == "__main__":
    main()
