#!/usr/bin/env python3
"""
Build quotes.json for the stock label generator frontend.

Uses the Longbridge Python SDK with **API Key** auth (App Key / App Secret /
Access Token from env). This replaces the old `longbridge` CLI + browser-OAuth
flow, which broke roughly every ~2 weeks (token decrypt/refresh failures).
The API-Key access token is valid 90 days and is auto-refreshed by the
workflow's refresh step.

Required env vars (read by Config.from_apikey_env):
    LONGBRIDGE_APP_KEY
    LONGBRIDGE_APP_SECRET
    LONGBRIDGE_ACCESS_TOKEN
Set LONGBRIDGE_PRINT_QUOTE_PACKAGES=false so the SDK's quote-package banner
does NOT pollute stdout (stdout is redirected into quotes.json).

Usage:
    python3 scripts/build_quotes.py > quotes.json
"""
import json
import sys
from datetime import datetime, timezone

from longbridge.openapi import Config, QuoteContext

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
    ctx = QuoteContext(Config.from_apikey_env())

    quotes = ctx.quote(SYMBOLS)

    # Names are best-effort: a static_info failure must not break the price feed.
    names = {}
    try:
        for s in ctx.static_info(SYMBOLS):
            names[s.symbol] = s.name_cn or s.name_hk or s.name_en or ""
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("static_info failed (names omitted): %s\n" % e)

    out = []
    for q in quotes:
        sym = q.symbol or ""
        last = num(q.last_done)
        prev = num(q.prev_close)
        change_pct = ((last - prev) / prev * 100) if prev else 0.0
        out.append({
            "symbol": sym,
            "ticker": sym.split(".")[0] if sym else "",
            "price": round(last, 4),
            "prev_close": round(prev, 4),
            "changePct": round(change_pct, 4),
            "volume": int(num(q.volume)),
            "turnover": num(q.turnover),
            "name": names.get(sym, ""),
        })

    if not out:
        sys.stderr.write("no quotes returned — aborting so we don't overwrite good data\n")
        sys.exit(1)

    out.sort(key=lambda x: -x["changePct"])

    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(out),
        "quotes": out,
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
