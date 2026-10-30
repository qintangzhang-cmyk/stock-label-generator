#!/usr/bin/env python3
"""
Build quotes.json for the stock label generator frontend.

Uses the Longbridge Python SDK with **API Key** auth (App Key / App Secret /
Access Token from env).

Required env vars (read by Config.from_apikey_env):
    LONGBRIDGE_APP_KEY
    LONGBRIDGE_APP_SECRET
    LONGBRIDGE_ACCESS_TOKEN
Set LONGBRIDGE_PRINT_QUOTE_PACKAGES=false to keep the SDK banner quiet.

The stickers show the latest *completed* session, whenever the job runs:
  * US symbols: after the US close last_done vs prev_close is the session
    that just ended. If the job runs while today's US session is still open
    (e.g. a manual run during New York trading hours), the change is taken
    from the last two completed daily candles instead.
  * Hong Kong / A-share symbols: the stickers are printed in the Hong Kong
    morning and show *yesterday's* moves. If the quote already belongs to
    today's session (pre-market auction, intraday, or after today's close),
    the change is taken from the last two daily candles before today.

The file is written atomically and only when the key symbols are present.

Exit codes: 0 ok · 3 token rejected · 4 key symbols missing · 1 other error.

Usage:
    python3 scripts/build_quotes.py quotes.json
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from longbridge.openapi import AdjustType, Config, Period, QuoteContext, TradeSessions

from market_clock import NY, READY_AT

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
    # Singapore companies listed in the US (watchlist of the /sg/ page)
    "SE.US", "GRAB.US",
    # S&P 500 ETF — the default index for "market mood" stickers on both pages
    "SPY.US",
]

# Without these the main stickers cannot be printed, so never publish a file missing them.
REQUIRED = ["AAPL.US", "MSFT.US", "NVDA.US", "GOOGL.US", "AMZN.US", "META.US", "TSLA.US", "SPY.US"]

MARKET_TZ = {
    "US": ZoneInfo("America/New_York"),
    "HK": ZoneInfo("Asia/Hong_Kong"),
    "SH": ZoneInfo("Asia/Shanghai"),
    "SZ": ZoneInfo("Asia/Shanghai"),
}

EXIT_TOKEN, EXIT_MISSING, EXIT_OTHER = 3, 4, 1


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def market(sym):
    return sym.rsplit(".", 1)[-1]


def local_date(ts, tz):
    """Exchange-local date of an SDK timestamp (naive values are UTC on the runner)."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz).date()


def yesterday_from_candles(ctx, sym, today):
    """(close, prev_close, volume, turnover, trade_date) of the last completed session before `today`."""
    tz = MARKET_TZ[market(sym)]
    candles = ctx.candlesticks(sym, Period.Day, 5, AdjustType.NoAdjust, TradeSessions.Intraday)
    done = [c for c in candles if local_date(c.timestamp, tz) and local_date(c.timestamp, tz) < today]
    if len(done) < 2:
        return None
    last, prev = done[-1], done[-2]
    return num(last.close), num(prev.close), int(num(last.volume)), num(last.turnover), local_date(last.timestamp, tz)


def build(ctx, now):
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
        mkt = market(sym)
        tz = MARKET_TZ.get(mkt, timezone.utc)
        last, prev = num(q.last_done), num(q.prev_close)
        volume, turnover = int(num(q.volume)), num(q.turnover)
        trade_date = local_date(getattr(q, "timestamp", None), tz)
        source = "quote"

        today = now.astimezone(tz).date()
        if mkt in ("HK", "SH", "SZ"):
            use_candles = trade_date is not None and trade_date >= today
        elif mkt == "US":
            session_open = now < datetime.combine(today, READY_AT, tzinfo=NY)
            use_candles = trade_date is not None and trade_date >= today and session_open
        else:
            use_candles = False
        if use_candles:
            try:
                y = yesterday_from_candles(ctx, sym, today)
            except Exception as e:  # noqa: BLE001 — keep the quote rather than drop the symbol
                sys.stderr.write("candlesticks failed for %s (%s); using quote\n" % (sym, e))
                y = None
            if y:
                last, prev, volume, turnover, trade_date = y
                source = "daily"

        change_pct = ((last - prev) / prev * 100) if prev else 0.0
        out.append({
            "symbol": sym,
            "ticker": sym.split(".")[0] if sym else "",
            "price": round(last, 4),
            "prev_close": round(prev, 4),
            "changePct": round(change_pct, 4),
            "volume": volume,
            "turnover": turnover,
            "name": names.get(sym, ""),
            "tradeDate": trade_date.isoformat() if trade_date else "",
            "source": source,
        })

    out.sort(key=lambda x: -x["changePct"])
    us_dates = sorted({x["tradeDate"] for x in out if market(x["symbol"]) == "US" and x["tradeDate"]})
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "usTradeDate": us_dates[-1] if us_dates else "",
        "count": len(out),
        "symbols": SYMBOLS,
        "quotes": out,
    }


def write_atomic(path, doc):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".quotes.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def classify(err):
    text = "%s %s" % (getattr(err, "code", ""), err)
    m = re.search(r"\b(4010\d\d)\b", text)
    return EXIT_TOKEN if m else EXIT_OTHER


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "quotes.json"
    now = datetime.now(timezone.utc)
    try:
        ctx = QuoteContext(Config.from_apikey_env())
        doc = build(ctx, now)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("fetch failed: %s: %s\n" % (type(e).__name__, e))
        sys.exit(classify(e))

    got = {q["symbol"] for q in doc["quotes"] if q["price"]}
    missing = [s for s in REQUIRED if s not in got]
    if missing:
        sys.stderr.write("key symbols missing or zero: %s — not writing %s\n" % (", ".join(missing), path))
        sys.exit(EXIT_MISSING)

    write_atomic(path, doc)
    daily = [q["symbol"] for q in doc["quotes"] if q["source"] == "daily"]
    sys.stderr.write("wrote %d symbols, US session %s%s\n" % (
        doc["count"], doc["usTradeDate"], ("; daily candles used for " + ", ".join(daily)) if daily else ""))


if __name__ == "__main__":
    main()
