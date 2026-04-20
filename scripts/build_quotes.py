#!/usr/bin/env python3
"""
Build quotes.json for the stock label generator frontend.
Shells out to `longbridge quote ... --format json` (CLI must be installed and authed).

Usage:
    python3 scripts/build_quotes.py > quotes.json
"""
import json
import subprocess
import sys
from datetime import datetime, timezone

SYMBOLS = [
    # US tech
    "AAPL.US", "MSFT.US", "NVDA.US", "GOOGL.US", "AMZN.US", "META.US",
    "TSLA.US", "NFLX.US", "AMD.US", "AVGO.US", "ORCL.US", "CRM.US",
    "ADBE.US", "PLTR.US", "COIN.US", "UBER.US",
    # US consumer / finance
    "JPM.US", "V.US", "MA.US", "WMT.US", "COST.US", "DIS.US", "KO.US",
    "MCD.US", "SBUX.US", "NKE.US", "UNH.US", "LLY.US", "XOM.US",
    # China ADR
    "BABA.US", "PDD.US", "JD.US", "BIDU.US", "NIO.US", "LI.US",
    "XPEV.US", "TME.US", "BILI.US", "NTES.US",
    # HK blue chips
    "700.HK", "9988.HK", "3690.HK", "1810.HK", "9618.HK", "1299.HK",
    "2318.HK", "1024.HK", "1211.HK", "9866.HK",
    # A shares
    "600519.SH", "300750.SZ",
]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    r = subprocess.run(
        ["longbridge", "quote", *SYMBOLS, "--format", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        sys.stderr.write(f"longbridge CLI failed: {r.stderr}\n")
        sys.exit(1)

    raw = json.loads(r.stdout)
    if not isinstance(raw, list):
        raw = [raw]

    out = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        sym = q.get("symbol", "")
        last = num(q.get("last"))
        prev = num(q.get("prev_close"))
        change_pct = ((last - prev) / prev * 100) if prev else 0.0
        out.append({
            "symbol": sym,
            "ticker": sym.split(".")[0] if sym else "",
            "price": round(last, 4),
            "prev_close": round(prev, 4),
            "changePct": round(change_pct, 4),
            "volume": int(num(q.get("volume"))),
            "turnover": num(q.get("turnover")),
            "name": q.get("name_hk") or q.get("name_cn") or q.get("name_en") or "",
        })

    out.sort(key=lambda x: -x["changePct"])

    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(out),
        "quotes": out,
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
