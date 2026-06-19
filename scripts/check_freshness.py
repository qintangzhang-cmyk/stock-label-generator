#!/usr/bin/env python3
"""Print the age (whole hours) of the live quotes.json on main.

Used by the Data Watchdog workflow. Prints 9999 if the file can't be fetched
or parsed, so the caller treats "unknown" as "stale" and retries/alerts.

Usage:
    python3 scripts/check_freshness.py <owner/repo>
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "qintangzhang-cmyk/stock-label-generator"
    url = "https://raw.githubusercontent.com/%s/main/quotes.json?t=%d" % (repo, int(time.time()))
    try:
        d = json.load(urllib.request.urlopen(url, timeout=30))
        gen = datetime.fromisoformat(d["generatedAt"].replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - gen).total_seconds() // 3600
        print(int(age_h))
    except Exception as e:  # noqa: BLE001 — any failure → treat as stale
        sys.stderr.write("freshness probe failed: %s\n" % e)
        print(9999)


if __name__ == "__main__":
    main()
