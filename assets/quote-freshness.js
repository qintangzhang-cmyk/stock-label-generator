// Is the cloud quotes.json from the latest US session?
// Shared by index.html (Hong Kong) and sg/index.html (Singapore).
//
// Mirrors scripts/market_clock.py: the data counts as current when it was
// generated after the most recent weekday 16:15 New York time. New York time
// is resolved by the browser, so the EDT/EST switch needs no change here.
(function (root) {
  const NY = 'America/New_York';
  const nyFmt = new Intl.DateTimeFormat('en-US', {
    timeZone: NY, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });

  function nyParts(d) {
    return Object.fromEntries(nyFmt.formatToParts(d).map(x => [x.type, x.value]));
  }

  // 16:15 New York time on a calendar date (EDT = 20:15 UTC, EST = 21:15 UTC).
  function usCloseOn(y, m, d) {
    for (const h of [20, 21]) {
      const t = new Date(Date.UTC(y, m - 1, d, h, 15));
      const p = nyParts(t);
      if (p.hour === '16' && p.minute === '15') return t;
    }
    return new Date(Date.UTC(y, m - 1, d, 21, 15));
  }

  // Most recent weekday 16:15 New York time at or before `now`.
  function latestUsClose(now) {
    now = now || new Date();
    const p = nyParts(now);
    let day = new Date(Date.UTC(+p.year, +p.month - 1, +p.day));
    for (let i = 0; i < 10; i++) {
      const wd = day.getUTCDay();
      if (wd !== 0 && wd !== 6) {
        const t = usCloseOn(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate());
        if (t <= now) return t;
      }
      day = new Date(day.getTime() - 86400000);
    }
    return null;
  }

  function nyDate(d) {
    const p = nyParts(d);
    return `${p.year}-${p.month}-${p.day}`;
  }

  function isFresh(doc, now) {
    const g = new Date(doc && doc.generatedAt);
    const ready = latestUsClose(now);
    return !isNaN(g) && !!ready && g >= ready;
  }

  // US session the data covers. Older files have no usTradeDate: derive it
  // from when they were generated.
  function usTradeDate(doc) {
    if (doc && doc.usTradeDate) return doc.usTradeDate;
    const g = new Date(doc && doc.generatedAt);
    const ready = isNaN(g) ? null : latestUsClose(g);
    return ready ? nyDate(ready) : '';
  }

  function expectedUsTradeDate(now) {
    const ready = latestUsClose(now);
    return ready ? nyDate(ready) : '';
  }

  // Latest session date among the non-US quotes actually used (HK / A-shares).
  function otherTradeDate(quotes) {
    const ds = (quotes || [])
      .filter(q => q && q.tradeDate && !/\.US$/i.test(q.symbol || ''))
      .map(q => q.tradeDate).sort();
    return ds.length ? ds[ds.length - 1] : '';
  }

  // Requested tickers that came back without a usable price.
  function missingTickers(tickers, data) {
    const got = new Set();
    (data || []).forEach(d => [d.symbol, d.ticker].forEach(x => x && got.add(String(x).toUpperCase())));
    return (tickers || []).filter(t => {
      const u = String(t).toUpperCase();
      return !got.has(u) && !got.has(u.replace(/\.US$/, ''));
    });
  }

  const WD_ZH = '日一二三四五六';
  const WD_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MON_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  // '2026-10-29' → '10月29日（周四）' / 'Thu 29 Oct'
  function formatDate(iso, lang) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return iso || '—';
    const y = +m[1], mo = +m[2], d = +m[3];
    const wd = new Date(Date.UTC(y, mo - 1, d)).getUTCDay();
    return lang === 'en' ? `${WD_EN[wd]} ${d} ${MON_EN[mo - 1]}` : `${mo}月${d}日（周${WD_ZH[wd]}）`;
  }

  // Generation time in UTC+8 (Hong Kong and Singapore share it).
  function formatUpdated(doc, lang) {
    const g = new Date(doc && doc.generatedAt);
    if (isNaN(g)) return '—';
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Hong_Kong', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(g).map(x => [x.type, x.value]));
    return lang === 'en' ? `${p.day} ${MON_EN[+p.month - 1]} ${p.hour}:${p.minute}` : `${p.month}月${p.day}日 ${p.hour}:${p.minute}`;
  }

  root.QuoteFreshness = {
    latestUsClose, isFresh, usTradeDate, expectedUsTradeDate, otherTradeDate,
    missingTickers, formatDate, formatUpdated,
  };
})(window);
