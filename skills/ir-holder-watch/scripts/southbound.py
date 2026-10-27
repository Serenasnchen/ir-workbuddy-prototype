"""Fetch Southbound (Stock Connect) shareholding of one HK stock from HKEXnews, day by day, with a local cache.

Usage:
  python southbound.py 700 --dates 2026-10-20,2026-10-21,2026-10-23 [--out southbound.json]
  python southbound.py 700 --from 2026-10-01 --to 2026-10-23

Source: https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk (public). The page is an ASP.NET form; this
script posts one date at a time, politely (1.5 s apart) with a generic User-Agent, and caches results in
southbound_<code>.json so re-runs make no requests. Holiday dates return the previous trading day's page date.
Output values are 结构化数据; day-to-day changes are 计算. No trading advice, no causal claims.
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

URL = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk"
UA = "Mozilla/5.0 (compatible; research-bot; contact@example.com)"


def http(url, fields=None):
    data = urllib.parse.urlencode(fields).encode() if fields else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode("utf-8", "ignore")
    time.sleep(1.5)
    return body


def field(h, n):
    m = re.search(r'name="%s"[^>]*value="([^"]*)"' % n, h)
    return m.group(1) if m else ""


def base(h):
    return {"__EVENTTARGET": "btnSearch", "__EVENTARGUMENT": "", "__VIEWSTATE": field(h, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": field(h, "__VIEWSTATEGENERATOR"), "today": field(h, "today"),
            "sortBy": "stockcode", "sortDirection": "asc", "originalShareholdingDate": field(h, "originalShareholdingDate"),
            "alertMsg": "", "btnSearch": "Search"}


def parse(page, code):
    t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", page))
    d = re.search(r"Shareholding Date: (\d{4}/\d{2}/\d{2})", t)
    m = re.search(r"Stock Code: \| \| %d \|.*?Shareholding in CCASS: \| \| ([\d,]+) \|.*?Issued Shares/Units: \| \| ([\d.]+)%%" % code, t)
    return {"page_date": d.group(1).replace("/", "-") if d else None,
            "shares": int(m.group(1).replace(",", "")) if m else None,
            "pct": float(m.group(2)) if m else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", type=int, help="stock code, e.g. 700")
    ap.add_argument("--dates")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--out", default="southbound.json")
    a = ap.parse_args()
    if a.dates:
        days = a.dates.split(",")
    else:
        s, e = date.fromisoformat(a.start), date.fromisoformat(a.end)
        days = [(s + timedelta(i)).isoformat() for i in range((e - s).days + 1) if (s + timedelta(i)).weekday() < 5]
    cache_p = Path(f"southbound_{a.code:05d}.json")
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    todo = [d for d in days if d not in cache or cache[d].get("shares") is None]
    if todo:
        h = http(URL)
        b = base(h)
        for d in todo:
            r = parse(http(URL, dict(b, txtShareholdingDate=d.replace("-", "/"))), a.code)
            if r["shares"] is None:  # view state may have expired; refresh once
                b = base(http(URL))
                r = parse(http(URL, dict(b, txtShareholdingDate=d.replace("-", "/"))), a.code)
            cache[d] = r
            cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    rows, prev = [], None
    for d in days:
        r = dict(cache.get(d, {}), date=d, label="结构化数据")
        if r.get("page_date") and r["page_date"] != d:
            r["note"] = "非交易日，页面返回前一交易日数据"
        if prev and r.get("shares") is not None and prev.get("shares") is not None and r.get("page_date") != prev.get("page_date"):
            r["d_shares"] = r["shares"] - prev["shares"]
            r["d_pp"] = round(r["pct"] - prev["pct"], 2)
        rows.append(r)
        if r.get("shares") is not None:
            prev = r
    Path(a.out).write_text(json.dumps({"code": a.code, "source": URL, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['date']}  {r.get('shares') or '—':>15}  {r.get('pct') or '—'}%  {('Δ ' + format(r['d_shares'], ',')) if 'd_shares' in r else ''} {r.get('note', '')}")


if __name__ == "__main__":
    main()
