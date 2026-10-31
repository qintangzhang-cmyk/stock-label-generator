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

The stickers show the latest *completed* session, whenever the job runs.
The live quote is used when it is "settled" — it describes that session and
has traded — because its prev_close is adjusted on ex-dividend days (a raw
close-to-close would print the dividend gap as a drop). Otherwise the change
comes from daily candles:
  * Hong Kong / A-shares show *yesterday's* moves (stickers are printed in the
    HK morning). Settled = volume > 0 and the quote is from before today. This
    is the case at the scheduled run (~05:15 HKT). From ~08:50 HKT Longbridge
    has rolled prev_close while last_done has not moved (0% on no volume;
    seen 2026-08-27, 09-23, 10-02, 10-07, 10-23), then come the pre-opening
    auction and the session itself: all of these use candles.
  * US: settled unless the quote has rolled over (no volume, last == prev,
    e.g. pre-market or a holiday) or today's session is still open.
Candle changes use forward-adjusted closes (so an ex-date is handled like the
quote does) and the unadjusted last close as the price. If candles are
needed but cannot be fetched, nothing is published (exit 5): a file with a
rolled/intraday number, or with symbols silently missing, would otherwise be
kept for the whole day by the "one good copy per day" gate.

A last check refuses to publish when half or more of the US, or of the
HK/A-share, symbols show exactly 0% on zero volume: the "one good copy per
day" gate would otherwise lock such a file in for the whole day.

The file is written atomically and only when the key symbols are present.

Exit codes: 0 ok · 3 token rejected · 4 key symbols missing ·
5 data not confirmed (rolled over / candles unavailable) · 1 other error.

Usage:
    python3 scripts/build_quotes.py quotes.json
"""
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
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

EXIT_TOKEN, EXIT_MISSING, EXIT_SUSPECT, EXIT_OTHER = 3, 4, 5, 1
CANDLE_PAUSE = 0.15  # seconds between candlestick calls, to stay under the API rate limit


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


def _completed(ctx, sym, adjust, before, tz):
    time.sleep(CANDLE_PAUSE)
    candles = ctx.candlesticks(sym, Period.Day, 5, adjust, TradeSessions.Intraday)
    return [c for c in candles if local_date(c.timestamp, tz) and local_date(c.timestamp, tz) < before]


def last_session_from_candles(ctx, sym, before):
    """(price, prev_close, volume, turnover, trade_date) of the last session before `before`.

    The change comes from forward-adjusted closes, so an ex-dividend day reads
    like the exchange's adjusted prev_close; the price is the actual close.
    """
    tz = MARKET_TZ[market(sym)]
    raw = _completed(ctx, sym, AdjustType.NoAdjust, before, tz)
    if len(raw) < 2:
        return None
    last = raw[-1]
    price, prev = num(last.close), num(raw[-2].close)
    try:
        adj = _completed(ctx, sym, AdjustType.ForwardAdjust, before, tz)
    except Exception as e:  # noqa: BLE001 — the raw prev close is still a usable fallback
        sys.stderr.write("forward-adjusted candles failed for %s (%s); using raw closes\n" % (sym, e))
        adj = []
    if len(adj) >= 2 and local_date(adj[-1].timestamp, tz) == local_date(last.timestamp, tz) and num(adj[-2].close):
        prev = price / (num(adj[-1].close) / num(adj[-2].close))
    return price, prev, int(num(last.volume)), num(last.turnover), local_date(last.timestamp, tz)


def build(ctx, now):
    quotes = ctx.quote(SYMBOLS)

    # Names are best-effort: a static_info failure must not break the price feed.
    names = {}
    try:
        for s in ctx.static_info(SYMBOLS):
            names[s.symbol] = s.name_cn or s.name_hk or s.name_en or ""
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("static_info failed (names omitted): %s\n" % e)

    out, unconfirmed = [], []
    for q in quotes:
        sym = q.symbol or ""
        mkt = market(sym)
        tz = MARKET_TZ.get(mkt, timezone.utc)
        last, prev = num(q.last_done), num(q.prev_close)
        volume, turnover = int(num(q.volume)), num(q.turnover)
        trade_date = local_date(getattr(q, "timestamp", None), tz)
        source = "quote"

        today = now.astimezone(tz).date()
        rolled = volume == 0 and last == prev
        if mkt in ("HK", "SH", "SZ"):
            settled = volume > 0 and trade_date is not None and trade_date < today
            before = today
        elif mkt == "US":
            session_open = now < datetime.combine(today, READY_AT, tzinfo=NY)
            settled = not rolled and not (trade_date is not None and trade_date >= today and session_open)
            # a rolled quote after today's close still means "use up to today"
            before = today if session_open else today + timedelta(days=1)
        else:
            settled, before = True, today
        if not settled:
            y = None
            for attempt in (1, 2):
                try:
                    y = last_session_from_candles(ctx, sym, before)
                    break
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write("candlesticks failed for %s (attempt %d): %s\n" % (sym, attempt, e))
            if not y:
                unconfirmed.append(sym)
                continue
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

    if unconfirmed:
        raise SuspectData("quote is not a settled session and candles are unavailable for %s"
                          % ", ".join(unconfirmed))
    out.sort(key=lambda x: -x["changePct"])
    for label, group in (("US", ("US",)), ("HK/A-share", ("HK", "SH", "SZ"))):
        rows = [x for x in out if market(x["symbol"]) in group]
        flat = [x["symbol"] for x in rows if x["changePct"] == 0 and x["volume"] == 0]
        if rows and len(flat) * 2 >= len(rows):
            raise SuspectData("%s: %d of %d symbols show 0%% on zero volume (%s...)"
                              % (label, len(flat), len(rows), ", ".join(flat[:5])))
    us_dates = sorted({x["tradeDate"] for x in out if market(x["symbol"]) == "US" and x["tradeDate"]})
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "usTradeDate": us_dates[-1] if us_dates else "",
        "count": len(out),
        "symbols": SYMBOLS,
        "quotes": out,
    }


class SuspectData(Exception):
    pass


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
    except SuspectData as e:
        sys.stderr.write("data looks rolled over, not writing %s: %s\n" % (path, e))
        sys.exit(EXIT_SUSPECT)
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
