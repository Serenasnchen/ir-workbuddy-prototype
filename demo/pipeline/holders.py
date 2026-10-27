# -*- coding: utf-8 -*-
"""M3 股东·资金·回购（输出 demo/data/m3_holders.json）

运行（在 ROOT 下）：
    python -I demo/pipeline/holders.py            # 默认：优先读 demo/data/raw/m3/ 缓存，缺什么才联网补什么
    python -I demo/pipeline/holders.py --offline  # 完全不联网，只用缓存与 data/src 本地文件
    python -I demo/pipeline/holders.py --refresh  # 重新抓取易变数据（最近 10 个交易日南向、DI 列表、公告检索）

数据：
  - 港交所披露易 港股通（南向）持股 mutualmarket.aspx?t=hk（按日 POST，ASP.NET 表单）
  - 港交所 CCASS 持股查询 searchsdw.aspx（按参与者）
  - 港交所 沪深港通每日统计（十大成交活跃股买入/卖出额，静态 JS）
  - 港交所 权益披露（DI）主要股东通知列表与表格详情
  - 港交所披露易 翌日披露报表 PDF（data/src/market_raw/nddr/，逐份解析对账）
  - 腾讯 2025 年报 / 2026 中报、业绩 PPT、业绩会第三方文字稿（本地 data/src）
  - Yahoo Finance 日线（非官方行情接口，原型用）
隐私：所有 GET 走 common.http_get；POST 走本文件 net_post（沿用 common.USER_AGENT 通用 UA 与同样限速）。
      代码、日志、产物中不写入任何个人姓名/邮箱/本机绝对路径。
只用标准库；PDF 文本用 pdftotext（poppler，子进程，相对路径）；自检抽查另用 PyMuPDF 独立提取。
自检结果写入 meta.self_check；说明见 demo/pipeline/m3_holders_NOTES.md。
"""
import argparse
import datetime as dt
import html
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, "demo/pipeline")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ROOT, DATA_SRC, DATA_PARSED, RESEARCH, OUT, AS_OF, USER_AGENT, LABELS,  # noqa: E402
                    http_get, sha256_file, input_record, write_module, load_json, assert_no_email)

MR = DATA_SRC / "market_raw"
RAW = OUT / "raw" / "m3"
MODULE = "m3_holders"
SB_URL = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk"
CCASS_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"
DS_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{}e.js"
DI_BASE = "https://di.hkex.com.hk/di/"
DI_LIST_URL = (DI_BASE + "NSNoticeSSList.aspx?sa2=ns&sid=6893&corpn=Tencent+Holdings+Ltd.&sd=01/01/2020&ed=26/10/2026"
               "&cid=0&sa1=cl&scsd=01%2f01%2f2020&sced=26%2f10%2f2026&sc=700&src=MAIN&lang=EN&g_lang=en&")
TS_URL = ("https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0&market=SEHK"
          "&stockId=7609&documentType=-1&fromDate=20261001&toDate=20261026&title=&searchType=0&t1code=-2&t2Gcode=-2"
          "&t2code=-2&rowRange=100&lang=E")
GL_URL = "https://www.hkex.com.hk/-/media/HKEX-Market/Listing/Rules-and-Guidance/Archive/Guidance-Letters/GL117_23.pdf"
RULE_URL = "https://en-rules.hkex.com.hk/rulebook/1006"
SB_START = "2025-10-27"          # 页面可回溯约 12 个月；2025-10-25 为最早可查日，首个交易日 10-27
CCASS_DATES = ["2025-10-31", "2025-12-31", "2026-06-30", "2026-09-30", "2026-10-16", "2026-10-23"]
WM = "内部准备材料，不构成公司口径"
UNOFFICIAL_PX = "非官方行情接口，原型用"

ARGS = None
NET = {"get": 0, "post": 0, "errors": 0, "cache_files_used": 0}
INPUTS = []


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def add_input(p):
    p = Path(p)
    if p.exists() and rel(p) not in {x["path"] for x in INPUTS}:
        INPUTS.append(input_record(p))


HKT = dt.timezone(dt.timedelta(hours=8))


def now_local():
    """抓取时间统一记为香港时间（不记录运行机器所在时区）。"""
    return dt.datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT")


def to_hkt(s):
    """把旧缓存中带本机时区偏移的时间戳（如 '2026-10-26 04:24 -0400'）统一换算为香港时间。"""
    if not isinstance(s, str):
        return s
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ([+-]\d{4})$", s)
    if not m:
        return s
    t = dt.datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M %z")
    return t.astimezone(HKT).strftime("%Y-%m-%d %H:%M HKT")


def norm_fetched_at(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "fetched_at":
                o[k] = to_hkt(v)
            else:
                norm_fetched_at(v)
    elif isinstance(o, list):
        for v in o:
            norm_fetched_at(v)
    return o


def to_int(s):
    return int(str(s).replace(",", "").strip())


def to_num(s):
    s = str(s).replace(",", "").strip()
    return float(s) if "." in s else int(s)


def dmy(s):
    return dt.datetime.strptime(s.strip(), "%d %B %Y").date().isoformat()


def r2(x, n=2):
    return None if x is None else round(x, n)


def yi(x):
    """港元 → 亿港元（保留 2 位）"""
    return None if x is None else round(x / 1e8, 2)


# ----------------------------------------------------------------------------- network
def net_get(url, delay=1.5, retries=3):
    if ARGS.offline:
        raise RuntimeError("offline")
    last = None
    for i in range(retries):
        try:
            b = http_get(url, delay=delay)
            NET["get"] += 1
            return b
        except urllib.error.HTTPError as e:
            NET["errors"] += 1
            if e.code in (403, 404):
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            NET["errors"] += 1
            last = e
        time.sleep(3 * (i + 1))
    raise last


def net_post(url, fields, delay=1.5, retries=3, timeout=90):
    """ASP.NET 表单 POST（common.http_get 只支持 GET）。沿用 common.USER_AGENT（通用 UA，无个人信息）与同样限速。"""
    if ARGS.offline:
        raise RuntimeError("offline")
    data = urllib.parse.urlencode(fields).encode()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            NET["post"] += 1
            time.sleep(delay)
            return body
        except Exception as e:  # noqa: BLE001
            NET["errors"] += 1
            last = e
            time.sleep(3 * (i + 1))
    raise last


def form_field(h, n):
    m = re.search(r'name="%s"[^>]*value="([^"]*)"' % n, h)
    return m.group(1) if m else ""


def load_cache(name, default):
    p = RAW / name
    if p.exists():
        NET["cache_files_used"] += 1
        obj = json.loads(p.read_text(encoding="utf-8"))
        before = json.dumps(obj, ensure_ascii=False)
        norm_fetched_at(obj)
        if json.dumps(obj, ensure_ascii=False) != before:  # 旧缓存时间戳换算为香港时间后回写
            save_cache(name, obj)
        return obj
    return default


def save_cache(name, obj):
    RAW.mkdir(parents=True, exist_ok=True)
    norm_fetched_at(obj)
    (RAW / name).write_text(json.dumps(obj, ensure_ascii=False, indent=0), encoding="utf-8")


def pdftext(path):
    """pdftotext -raw（相对路径，避免 Windows 长路径问题）。"""
    relp = rel(path)
    try:
        r = subprocess.run(["pdftotext", "-raw", relp, "-"], cwd=str(ROOT), capture_output=True, timeout=120)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", "ignore")
    except FileNotFoundError:
        pass
    raise RuntimeError("需要 pdftotext（poppler）来解析 PDF：" + relp)


# ----------------------------------------------------------------------------- sources
SRC = {}
SOURCES = []


def src(key, title, url, date, tier, note=None):
    sid = "S%02d" % (len(SOURCES) + 1)
    SRC[key] = sid
    d = {"id": sid, "title": title, "url": url, "date": date, "tier": tier}
    if note:
        d["note"] = note
    SOURCES.append(d)
    return sid


def S(*keys):
    return [SRC[k] for k in keys]


def build_sources():
    src("sb", "港交所披露易：沪深港通持股——港股通（南向）持股查询（腾讯 00700，按日）", SB_URL, AS_OF, 1,
        "沪、深港通合计；按 CCASS 结算口径（成交后 T+2 交收）；占比为港交所页面公布值（页面注明分母可能未及时更新）")
    src("ccass", "港交所披露易：中央结算系统（CCASS）持股纪录查询（00700，按参与者）", CCASS_URL, AS_OF, 1,
        "CCASS 参与者为托管行/券商/结算机构，不等于实益持有人")
    src("ds", "港交所：沪深港通每日统计（南向十大成交活跃股买入/卖出额）", DS_URL.format("YYYYMMDD"), AS_OF, 1,
        "仅当腾讯位列当日沪/深港通南向十大成交活跃股时有数据")
    src("yahoo", "Yahoo Finance 日线行情（0700.HK，收盘价）",
        "https://query1.finance.yahoo.com/v8/finance/chart/0700.HK", AS_OF, 4, UNOFFICIAL_PX)
    src("nddr", "港交所披露易：腾讯 2026 年翌日披露报表（FF305，98 份，逐份 PDF）",
        "https://www1.hkexnews.hk/search/titleSearchServlet.do?stockId=7609&fromDate=20260101&toDate=20261026", AS_OF, 1,
        "每份 PDF 原始 URL 见 buyback.reconciliation.files[].url")
    src("ts", "港交所披露易：腾讯公告标题检索（2026-10-01 至 2026-10-26，核查 10-15 之后有无新回购披露）", TS_URL, AS_OF, 1)
    src("ir26", "腾讯控股 2026 中期报告（主要股东权益、董事权益、购回股份月度表）",
        "https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf", "2026-08-25", 1)
    src("ar25", "腾讯控股 2025 年报（主要股东权益、2025 年购回股份月度表）",
        "https://static.www.tencent.com/uploads/2026/04/09/62d786fcf3d3c8cb7e54791ee95439ac.pdf", "2026-04-09", 1,
        "港交所同日刊发版：https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0409/2026040901231.pdf")
    src("di", "港交所权益披露（DI）：腾讯主要股东通知列表（2020-01-01 至 2026-10-26）", DI_LIST_URL, AS_OF, 1,
        "本模块只展示 Prosus N.V./Naspers 的申报；董事及其控制公司的申报不展示")
    src("di_all", "港交所权益披露（DI）：腾讯全部通知列表（2025-01-01 至 2026-10-26；上一轮保存的第 1 页，仅用于交叉核对）",
        DI_BASE + "NSAllFormList.aspx?sa2=an&sid=6893&corpn=Tencent+Holdings+Ltd.&sd=01/01/2025&ed=26/10/2026&cid=0&sa1=cl"
        "&scsd=01%2f01%2f2025&sced=26%2f10%2f2026&sc=700&src=MAIN&lang=EN&g_lang=en&", AS_OF, 1,
        "本地副本 data/src/market_raw/di/di2.html；页内董事申报不展示")
    src("diform", "港交所 DI 表格 CS20250728E00459（Prosus N.V.，原因代码 1113 释义与补充说明）",
        DI_BASE + "NSForm2.aspx?fn=CS20250728E00459", "2025-07-28", 1)
    src("prosus_sf", "Prosus FY2026 短式业绩公告（截至 2026-03-31 财年，2026-06-29 发布）", "", "2026-06-29", 1,
        "本地副本 data/src/market_raw/dl/webfetch-1792985490790-q0387r.pdf；原始下载 URL 未在本地记录；"
        "文中所指完整公告：https://senspdf.jse.co.za/documents/2026/jse/isse/PRXE/YE26.pdf")
    src("prosus_pres", "Prosus FY2026 业绩演示（含集团组织图，持股比例以图片呈现，未能文本提取）",
        "https://www.prosus.com/~/media/Files/P/prosus-corp-v2/results-reports-and-events-archive/annual-report/2026/"
        "fy2026-results-presentation.pdf", "2026-06-29", 2)
    src("oldmutual", "Old Mutual 对 Prosus FY2026 业绩点评（二手）", "", "2026-07-02", 4,
        "本地副本 data/src/market_raw/dl/webfetch-1792985491247-31qzj6.pdf；原始 URL 未在本地记录；媒体/券商转述（二手）")
    src("ppt3q25", "腾讯 2025 年第三季度业绩演示（PPT）",
        "https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf", "2025-11-13", 2,
        "用户提供链接")
    src("ppt4q25", "腾讯 2025 年第四季度及全年业绩演示（PPT）",
        "https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf", "2026-03-18", 2,
        "用户提供链接")
    src("ppt1q26", "腾讯 2026 年第一季度业绩演示（PPT）",
        "https://static.www.tencent.com/uploads/2026/05/13/e048dfed72bc718f7986a83f23c8e294.pdf", "2026-05-13", 2)
    src("ppt2q26", "腾讯 2026 年第二季度业绩演示（PPT）",
        "https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf", "2026-08-12", 2,
        "用户提供链接")
    src("tr3q25", "腾讯 2025 Q3 业绩会文字稿（StockAnalysis，非官方逐字稿）",
        "https://stockanalysis.com/quote/hkg/0700/transcripts/374535-q3-2025/", "2025-11-13", 3, "用户提供链接")
    src("tr4q25", "腾讯 2025 Q4 业绩会文字稿（StockAnalysis，非官方逐字稿）",
        "https://stockanalysis.com/quote/hkg/0700/transcripts/419871-q4-2025/", "2026-03-18", 3, "用户提供链接")
    src("tr1q26", "腾讯 2026 Q1 业绩会文字稿（StockAnalysis，非官方逐字稿）",
        "https://stockanalysis.com/quote/hkg/0700/transcripts/609405-q1-2026/", "2026-05-13", 3, "用户提供链接")
    src("tr2q26", "腾讯 2026 Q2 业绩会文字稿（StockAnalysis，非官方逐字稿）",
        "https://stockanalysis.com/quote/hkg/0700/transcripts/667897-q2-2026/", "2026-08-12", 3, "用户提供链接")
    src("irpage", "腾讯投资者关系——业绩页（定位官方业绩材料）", "https://www.tencent.com/investors/results/", AS_OF, 2,
        "用户提供链接；本地快照 data/src/market_raw/idx/tc_res.html")
    src("bm0924", "腾讯港交所公告：DATE OF BOARD MEETING（2026-11-18 董事会审议 Q3 业绩）",
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0924/2026092401585.pdf", "2026-09-24", 1)
    src("gl117", "港交所指引信 GL117-23（2023-10，2024-06 及 2025-08 更新），第 9 段引述《主板上市规则》第 10.06(2)(e) 条",
        GL_URL, "2025-08", 1)
    src("rule", "港交所《主板上市规则》第 10.06 条（规则手册页面）", RULE_URL, AS_OF, 1,
        "规则手册页面未纳入本地缓存；条文文字以 GL117-23 第 9 段引述（本地 PDF 逐字提取）为准")
    src("ts2026", "港交所披露易：腾讯 2026 年公告标题检索（2026-01-01 至 2026-10-26，138 条；含各次 DATE OF BOARD MEETING 公告）",
        "https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0&market=SEHK"
        "&stockId=7609&documentType=-1&fromDate=20260101&toDate=20261026&title=&searchType=0&t1code=-2&t2Gcode=-2"
        "&t2code=-2&rowRange=500&lang=E", AS_OF, 1, "本地副本 data/src/market_raw/nddr/list2026.json")


# ----------------------------------------------------------------------------- prices (Yahoo)
def get_prices():
    cache = RAW / "yahoo_0700HK_1d.json"
    if (not cache.exists() or ARGS.refresh) and not ARGS.offline:
        p1 = int(dt.datetime(2025, 10, 1, tzinfo=dt.timezone.utc).timestamp())
        p2 = int(dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc).timestamp())
        try:
            b = net_get("https://query1.finance.yahoo.com/v8/finance/chart/0700.HK?period1=%d&period2=%d&interval=1d"
                        % (p1, p2))
            json.loads(b)
            RAW.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(b)
        except Exception as e:  # noqa: BLE001
            log("Yahoo 获取失败：", e)
    files = [cache] if cache.exists() else []
    local = MR / "idx" / "yf.json"
    add_input(local)
    files.append(local)
    px = {}
    for f in reversed(files):  # 本地旧文件先读，缓存覆盖
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        r = d["chart"]["result"][0]
        off = r["meta"].get("gmtoffset", 28800)
        q = r["indicators"]["quote"][0]
        for t, c in zip(r["timestamp"], q["close"]):
            if c is None:
                continue
            day = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()
            if day < AS_OF:  # AS_OF 当日为盘中数据，不用
                px[day] = round(c, 3)
    # 自检：缓存与本地旧文件重叠日收盘价是否一致
    overlap_diff = None
    if cache.exists():
        old = json.loads(local.read_text(encoding="utf-8"))["chart"]["result"][0]
        diffs = []
        for t, c in zip(old["timestamp"], old["indicators"]["quote"][0]["close"]):
            day = dt.datetime.fromtimestamp(t + 28800, dt.timezone.utc).date().isoformat()
            if c is not None and day in px and day < AS_OF:
                diffs.append(abs(px[day] - round(c, 3)))
        overlap_diff = max(diffs) if diffs else None
        add_input(cache)
    return dict(sorted(px.items())), overlap_diff


# ----------------------------------------------------------------------------- southbound
def sb_parse(r):
    t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", r))
    d = re.search(r"Shareholding Date: (\d{4}/\d{2}/\d{2})", t)
    m = re.search(r"Stock Code: \| \| 700 \|.*?Shareholding in CCASS: \| \| ([\d,]+) \|.*?Issued Shares/Units: \| \| "
                  r"([\d.]+)%", t)
    a = re.search(r'name="alertMsg"[^>]*value="([^"]*)"', r)
    return (d.group(1).replace("/", "-") if d else None,
            to_int(m.group(1)) if m else None,
            float(m.group(2)) if m else None,
            (a.group(1) if a else "") or None)


def get_southbound(days):
    cache = load_cache("southbound_0700.json", {"url": SB_URL, "rows": {}})
    rows = cache["rows"]
    recent = set(days[-10:]) if ARGS.refresh else set()
    todo = [d for d in days if d not in rows or rows[d].get("shares") is None or d in recent]
    if todo and not ARGS.offline:
        log("南向持股：需抓取 %d 个交易日" % len(todo))
        h = net_get(SB_URL).decode("utf-8", "ignore")

        def base(h):
            return {"__EVENTTARGET": "btnSearch", "__EVENTARGUMENT": "", "__VIEWSTATE": form_field(h, "__VIEWSTATE"),
                    "__VIEWSTATEGENERATOR": form_field(h, "__VIEWSTATEGENERATOR"), "today": form_field(h, "today"),
                    "sortBy": "stockcode", "sortDirection": "asc",
                    "originalShareholdingDate": form_field(h, "originalShareholdingDate"),
                    "alertMsg": "", "btnSearch": "Search"}
        b = base(h)
        for i, d in enumerate(todo):
            try:
                r = net_post(SB_URL, dict(b, txtShareholdingDate=d.replace("-", "/"))).decode("utf-8", "ignore")
                pdate, sh, pct, alert = sb_parse(r)
                if sh is None and not alert:  # 视图状态可能过期，刷新一次
                    h = net_get(SB_URL).decode("utf-8", "ignore")
                    b = base(h)
                    r = net_post(SB_URL, dict(b, txtShareholdingDate=d.replace("-", "/"))).decode("utf-8", "ignore")
                    pdate, sh, pct, alert = sb_parse(r)
                rows[d] = {"page_date": pdate, "shares": sh, "pct": pct, "alert": alert, "fetched_at": now_local()}
            except Exception as e:  # noqa: BLE001
                log("  南向", d, "失败：", e)
            if i % 10 == 9:
                save_cache("southbound_0700.json", cache)
                log("  南向进度 %d/%d" % (i + 1, len(todo)))
        save_cache("southbound_0700.json", cache)
    if (RAW / "southbound_0700.json").exists():
        add_input(RAW / "southbound_0700.json")
    return rows


# ----------------------------------------------------------------------------- HKEX daily stat
def ds_parse(text):
    j = json.loads(text[text.find("["): text.rfind("]") + 1])
    out = {"status": "ok"}
    for m in j:
        if m.get("market") not in ("SSE Southbound", "SZSE Southbound"):
            continue
        k = "sse" if m["market"].startswith("SSE") else "szse"
        out["date"] = m.get("date")
        out[k + "_trading_day"] = m.get("tradingDay")
        for c in m.get("content", []):
            tb = c.get("table", {})
            if tb.get("classname") != "top10Table":
                continue
            for tr in tb.get("tr", []):
                td = tr["td"][0]
                if len(td) >= 6 and td[1] == "00700":
                    out[k] = {"rank": int(td[0]), "buy": to_int(td[3]), "sell": to_int(td[4]), "total": to_int(td[5])}
    return out


def get_dailystat(days):
    cache = load_cache("hkex_dailystat_0700.json", {"url": DS_URL, "rows": {}})
    rows = cache["rows"]
    for p in sorted((MR / "idx").glob("sc_*.js")):  # 上一轮已抓的本地文件
        d = re.search(r"sc_(\d{8})", p.name).group(1)
        d = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
        add_input(p)
        if d not in rows:
            rows[d] = ds_parse(p.read_text(encoding="utf-8"))
            rows[d]["from_local"] = rel(p)
    consecutive = 0
    for d in sorted(days, reverse=True):
        if d in rows and not (ARGS.refresh and d >= days[-5]):
            consecutive = consecutive + 1 if rows[d].get("status") == "404" else 0
        elif not ARGS.offline:
            try:
                rows[d] = ds_parse(net_get(DS_URL.format(d.replace("-", "")), delay=1.0).decode("utf-8", "ignore"))
                consecutive = 0
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    rows[d] = {"status": "404"}
                    consecutive += 1
            except Exception as e:  # noqa: BLE001
                log("  日统计", d, "失败：", e)
        if consecutive >= 12:  # 连续 12 个交易日 404，视为超出港交所保留期
            break
    save_cache("hkex_dailystat_0700.json", cache)
    add_input(RAW / "hkex_dailystat_0700.json")
    return rows


# ----------------------------------------------------------------------------- CCASS
def ccass_parse(r):
    t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " | ", r)))
    out = {}
    m = re.search(r"Shareholding Date:[\s|]*(\d{4}/\d{2}/\d{2})", t)
    out["page_date"] = m.group(1).replace("/", "-") if m else None
    out["summary"] = {}
    for cat, key in [("Market Intermediaries", "intermediaries"), ("Consenting Investor Participants", "consenting_ip"),
                     ("Non-consenting Investor Participants", "non_consenting_ip"), ("Total", "total")]:
        m = re.search(re.escape(cat) + r"[\s|]*Shareholding in CCASS[\s|]*([\d,]+)[\s|]*Number of Participants[\s|]*"
                      r"([\d,]+)[\s|]*% of the total number of Issued Shares/ Warrants/ Units[\s|]*([\d.]+)%", t)
        if m:
            out["summary"][key] = {"shares": to_int(m.group(1)), "participants": to_int(m.group(2)),
                                   "pct": float(m.group(3))}
    m = re.search(r"Total number of Issued Shares/Warrants/Units \(last updated figure\)[\s|]*([\d,]+)", t)
    out["issued_shares"] = to_int(m.group(1)) if m else None
    parts = []
    for pid, name, sh, pct in re.findall(
            r"Participant ID:[\s|]*([A-Z0-9]+)[\s|]*Name of CCASS Participant \(\* for Consenting Investor Participants \):"
            r"[\s|]*([^|]+?)[\s|]*Address:.*?Shareholding:[\s|]*([\d,]+)[\s|]*% of the total number of Issued Shares/ "
            r"Warrants/ Units:[\s|]*([\d.]+)%", t):
        # 只保留中介机构（A/B/C 开头）；剔除带 * 的投资者户口持有人（可能为自然人）
        if "*" in name or not re.match(r"^[ABC]\d{5}$", pid):
            continue
        parts.append([pid, name.strip(), to_int(sh), float(pct)])
    out["participants"] = parts
    return out


def get_ccass(dates):
    res = {}
    h = None
    for d in dates:
        name = "ccass_0700_%s.json" % d.replace("-", "")
        c = load_cache(name, None)
        if c is None and not ARGS.offline:
            try:
                if h is None:
                    h = net_get(CCASS_URL).decode("utf-8", "ignore")
                data = {"__EVENTTARGET": "btnSearch", "__EVENTARGUMENT": "", "__VIEWSTATE": form_field(h, "__VIEWSTATE"),
                        "__VIEWSTATEGENERATOR": form_field(h, "__VIEWSTATEGENERATOR"), "today": form_field(h, "today"),
                        "sortBy": "shareholding", "sortDirection": "desc", "alertMsg": "",
                        "txtShareholdingDate": d.replace("-", "/"), "txtStockCode": "00700", "txtStockName": "",
                        "txtParticipantID": "", "txtParticipantName": "", "txtSelPartID": ""}
                c = ccass_parse(net_post(CCASS_URL, data).decode("utf-8", "ignore"))
                c["fetched_at"] = now_local()
                if c["participants"]:
                    save_cache(name, c)
            except Exception as e:  # noqa: BLE001
                log("  CCASS", d, "失败：", e)
                c = None
        if c:
            add_input(RAW / name)
            res[d] = c
    return res


# ----------------------------------------------------------------------------- DI
def _clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", x))).strip()


def di_parse_list(b):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", b, re.S):
        tds = [_clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) >= 8 and re.match(r"^[A-Z]{2}\d{8}E\d{5}$", tds[0]):
            link = re.search(r'href="(NSForm[^"]+)"', tr)
            ml = re.search(r"([\d,]+)\(L\)", tds[5])
            mp = re.search(r"([\d.]+)\(L\)", tds[6])
            ms = re.search(r"([\d,]+)\(L\)", tds[3])
            mpx = re.search(r"HKD\s*([\d.]+)", tds[4])
            dd, mm, yy = tds[7].split("/")
            rows.append({"form": tds[0], "name": tds[1], "reason": tds[2].replace("(L)", "").strip(),
                         "shares_involved": to_int(ms.group(1)) if ms else None,
                         "avg_price_hkd": float(mpx.group(1)) if mpx else None,
                         "shares_interested": to_int(ml.group(1)) if ml else None,
                         "pct": float(mp.group(1)) if mp else None, "event_date": "%s-%s-%s" % (yy, mm, dd),
                         "link": html.unescape(link.group(1)) if link else None})
    return rows


def get_di():
    cache = load_cache("di_ss_notices.json", None)
    if (cache is None or ARGS.refresh) and not ARGS.offline:
        try:
            b = net_get(DI_LIST_URL).decode("utf-8", "ignore")
            rows = di_parse_list(b)
            pages = sorted(set(int(x) for x in re.findall(r"pg=(\d+)", b)))
            for pg in pages:
                if pg <= 1:
                    continue
                b2 = net_get(DI_LIST_URL + "&pg=%d" % pg).decode("utf-8", "ignore")
                rows += di_parse_list(b2)
            tot = re.search(r"Total records:\s*(\d+)", re.sub("<[^>]+>", " ", b))
            cache = {"url": DI_LIST_URL, "fetched_at": now_local(), "total_records": int(tot.group(1)) if tot else None,
                     "rows": rows}
            save_cache("di_ss_notices.json", cache)
        except Exception as e:  # noqa: BLE001
            log("DI 列表获取失败：", e)
    add_input(MR / "di" / "di2.html")
    if cache is None:  # 回退：上一轮保存的 2025-01-01 起"全部通知"页
        rows = di_parse_list((MR / "di" / "di2.html").read_text(encoding="utf-8", errors="ignore"))
        cache = {"url": "data/src/market_raw/di/di2.html", "fetched_at": None, "total_records": None, "rows": rows}
    else:
        add_input(RAW / "di_ss_notices.json")
    # 原因代码释义：每个代码取一份 Prosus N.V. 表格详情
    forms = {}
    for r in cache["rows"]:
        if r["name"].startswith("Prosus") and r["reason"] not in forms and r.get("link"):
            forms[r["reason"]] = r
    details = {}
    for code, r in forms.items():
        name = "di_form_%s.json" % r["form"]
        d = load_cache(name, None)
        if d is None and not ARGS.offline:
            try:
                t = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " | ", net_get(DI_BASE + r["link"]).decode(
                    "utf-8", "ignore"))))
                s = re.sub(r"(\|\s*)+", "| ", t)
                m = re.search(r"\| %s \| ([^|]+)\| ([^|]+)\|" % re.escape(code), s)
                desc = None
                if m:
                    g2 = m.group(2).strip()
                    desc = m.group(1).strip() + ("" if re.match(r"^\d{4}$", g2) else " " + g2)
                sup = re.search(r"Supplementary information \| : \| (.*?)\| 28\.", s)
                iss = re.search(r"Number of issued shares in class \| : \| ([\d,]+)", s)
                d = {"form": r["form"], "code": code, "description": desc,
                     "supplementary": sup.group(1).strip() if sup else None,
                     "issued_shares_in_class": to_int(iss.group(1)) if iss else None,
                     "url": DI_BASE + r["link"], "fetched_at": now_local()}
                save_cache(name, d)
            except Exception as e:  # noqa: BLE001
                log("DI 表格获取失败：", e)
        if d:
            add_input(RAW / name)
            details[code] = d
    return cache, details


# ----------------------------------------------------------------------------- title search (latest)
def get_titlesearch():
    name = "titlesearch_20261001_20261026.json"
    c = load_cache(name, None)
    if (c is None or ARGS.refresh) and not ARGS.offline:
        try:
            d = json.loads(net_get(TS_URL).decode("utf-8"))
            c = {"url": TS_URL, "fetched_at": now_local(), "rows": json.loads(d["result"]) if d.get("result") else []}
            save_cache(name, c)
        except Exception as e:  # noqa: BLE001
            log("公告检索失败：", e)
    if c:
        add_input(RAW / name)
    return c


def get_rule_text():
    p = RAW / "hkex_GL117_23.pdf"
    if not p.exists() and not ARGS.offline:
        try:
            b = net_get(GL_URL)
            RAW.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        except Exception as e:  # noqa: BLE001
            log("GL117-23 获取失败：", e)
    if not p.exists():
        return None
    add_input(p)
    t = re.sub(r"\s+", " ", pdftext(p))
    m = re.search(r"\(e\) an issuer shall not purchase its shares on the Exchange.*?unless the circumstances are "
                  r"exceptional", t)
    if not m:
        return None
    # 去掉跨页的脚注 4/5 与页眉（保留 "(ii)" 编号）
    q = re.sub(r" 4 In the UK.*?(?=\(ii\) the deadline)", " ", m.group(0))
    return re.sub(r"\s+", " ", q).strip()


# ----------------------------------------------------------------------------- NDDR parsing
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def parse_nddr(text):
    rec = {}
    m = re.search(r"Date Submitted:\s*(\d{1,2} \w+ \d{4})", text)
    rec["submitted"] = dmy(m.group(1)) if m else None
    rec["is_ff305"] = "Next Day Disclosure Return" in text
    rows = re.findall(r"\d+\)\.\s+(\d{1,2} \w+ \d{4})\s+([\d,]+)\s+On the Exchange\s+HKD\s+([\d.]+)\s+HKD\s+([\d.]+)"
                      r"\s+HKD\s+([\d,]+(?:\.\d+)?)", text)
    rec["repurchases"] = [{"date": dmy(a), "shares": to_int(b), "high": float(c), "low": float(d), "amount": to_num(e)}
                          for a, b, c, d, e in rows]
    m = re.search(r"repurchased\s+([\d,]+)\s+Aggregate price paid \$\s+HKD\s+([\d,]+(?:\.\d+)?)", text)
    rec["total_shares"] = to_int(m.group(1)) if m else None
    rec["total_amount"] = to_num(m.group(2)) if m else None
    m = re.search(r"Date of the resolution granting the repurchase mandate\s+(\d{1,2} \w+ \d{4})", text)
    rec["mandate_date"] = dmy(m.group(1)) if m else None
    m = re.search(r"authorised to repurchase under the repurchase mandate\s+([\d,]+)", text)
    rec["mandate_authorised"] = to_int(m.group(1)) if m else None
    m = re.search(r"under the repurchase mandate \(a\)\s+([\d,]+)", text)
    rec["mandate_used"] = to_int(m.group(1)) if m else None
    m = re.search(r"repurchase mandate\s+([\d.]+) %\s+5\)", text)
    rec["mandate_used_pct"] = float(m.group(1)) if m else None
    rec["partb_vwap"] = {dmy(a): {"shares": to_int(b), "vwap": float(c)} for a, b, c in re.findall(
        r"Date of changes (\d{1,2} \w+ \d{4})\s+([\d,]+) [\d.]+ % HKD ([\d.]+)", text)}
    m = re.search(r"Closing balance as at \(Notes 5 and 6\) (\d{1,2} \w+ \d{4}) ([\d,]+) ([\d,]+) ([\d,]+)", text)
    rec["closing_issued_shares"] = to_int(m.group(2)) if m else None
    rec["closing_date"] = dmy(m.group(1)) if m else None
    ev = re.search(r"A\. Changes in issued shares or treasury shares.*?Opening balance as at.*?\n1\)\.\s*(.*?)\n"
                   r"(?:Date of changes|.*?Date of changes)", text, re.S)
    rec["section1_event"] = re.sub(r"\s+", " ", ev.group(1)).strip()[:160] if ev else None
    return rec


def parse_month_table(text, start_kw, year):
    i = text.find(start_kw)
    seg = text[i:i + 4000]
    out = []
    for mo, sh, hi, lo, amt in re.findall(r"(%s) ([\d,]+) ([\d.]+) ([\d.]+) ([\d,]+\.\d+)" % "|".join(MONTHS), seg):
        out.append({"month": "%d-%02d" % (year, MONTHS.index(mo) + 1), "shares": to_int(sh), "high": float(hi),
                    "low": float(lo), "amount": float(amt.replace(",", ""))})
    m = re.search(r"Total:\s*([\d,]+)\s+([\d,]+\.\d+)", seg)
    tot = {"shares": to_int(m.group(1)), "amount": float(m.group(2).replace(",", ""))} if m else None
    return out, tot


# ----------------------------------------------------------------------------- helpers
def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return None if sx == 0 or sy == 0 else round(sxy / (sx * sy), 4)


def norm_ws(s):
    return re.sub(r"\s+", " ", re.sub(r"\s+,", ",", s)).strip()


def check_quote(path, quote, encoding="utf-8"):
    t = Path(path).read_text(encoding=encoding, errors="replace")
    return norm_ws(quote) in norm_ws(t)


def slide_of(path, kw):
    t = Path(path).read_text(encoding="latin-1")
    i = t.find(kw)
    return t[:i].count("\f") + 1 if i >= 0 else None


# ============================================================================= main build
def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ARGS = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    build_sources()
    checks = []

    def chk(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # ---------------- prices & calendar
    px, px_overlap = get_prices()
    tdays = [d for d in px if d < AS_OF]
    last = tdays[-1]
    chk("行情：缓存与本地旧行情（idx/yf.json）重叠日收盘价一致", px_overlap is not None and px_overlap < 0.01,
        "最大差 %s 港元" % px_overlap)

    # ---------------- southbound
    sb_days = [d for d in tdays if d >= SB_START]
    sbrows = get_southbound(sb_days)
    dsrows = get_dailystat([d for d in tdays if d >= "2025-10-27"])
    idx = {d: i for i, d in enumerate(tdays)}

    def ds_net(d):
        r = dsrows.get(d)
        if not r or r.get("status") != "ok":
            return None
        parts = [r.get(k) for k in ("sse", "szse")]
        if all(p is None for p in parts):
            return None
        return sum((p["buy"] - p["sell"]) for p in parts if p)

    series = []
    prev = None
    mismatch = []
    for d in sb_days:
        r = sbrows.get(d)
        if not r or r.get("shares") is None:
            continue
        if r.get("page_date") != d:
            mismatch.append(d)
        row = {"date": d, "shares": r["shares"], "pct": r["pct"]}
        if prev:
            ds_ = r["shares"] - prev["shares"]
            t2 = tdays[idx[d] - 2] if idx[d] >= 2 else None
            row.update({"d_shares": ds_, "d_pp": r2(r["pct"] - prev["pct"], 2),
                        "close": px.get(d), "trade_date_est": t2, "close_trade_date": px.get(t2),
                        "net_hkd_est": round(ds_ * px[t2]) if t2 in px else None,
                        "net_hkd_est_same_day_close": round(ds_ * px[d]) if d in px else None,
                        "hkex_turnover_net_trade_date": ds_net(t2) if t2 else None})
        row["src"] = S("sb", "yahoo", "ds")
        row["label"] = "计算" if prev else "结构化数据"
        series.append(row)
        prev = r
    sb_by = {r["date"]: r for r in series}
    chk("南向：覆盖 2025-10-31 与最新交易日", "2025-10-31" in sb_by and last in sb_by,
        "共 %d 个交易日，%s 至 %s" % (len(series), series[0]["date"] if series else None,
                                    series[-1]["date"] if series else None))
    chk("南向：抓取日期与页面返回日期一致", not mismatch, "不一致：%s" % mismatch[:5])
    mm = (MR / "hkex" / "mm_hk.html").read_text(encoding="utf-8", errors="ignore")
    add_input(MR / "hkex" / "mm_hk.html")
    _, mm_sh, mm_pct, _ = sb_parse(mm)
    chk("南向：最新值与上一轮本地快照（hkex/mm_hk.html，页面日期 2026-10-24）一致",
        sb_by.get(last, {}).get("shares") == mm_sh, "快照 %s 股 / %s%%；本次 %s" % (mm_sh, mm_pct,
                                                                           sb_by.get(last, {}).get("shares")))

    # 对齐检验：持股变动（D）与港交所成交净额（D-k）
    align = {}
    for k in range(0, 4):
        xs, ys = [], []
        for r in series[1:]:
            i = idx[r["date"]]
            if i - k < 0:
                continue
            t = tdays[i - k]
            n = ds_net(t)
            if n is not None and t in px:
                xs.append(r["d_shares"])
                ys.append(n / px[t])
        align["lag_%d" % k] = {"n": len(xs), "pearson": pearson(xs, ys)}
    best = max((v["pearson"] or -9, k) for k, v in align.items())[1]
    chk("南向：持股变动与港交所成交净额的最佳对齐为 T-2（结算滞后）", best == "lag_2",
        "相关系数 %s" % {k: v["pearson"] for k, v in align.items()})
    ov = [r for r in series[1:] if r.get("hkex_turnover_net_trade_date") is not None and r.get("net_hkd_est") is not None]
    sum_est = sum(r["net_hkd_est"] for r in ov)
    sum_ds = sum(r["hkex_turnover_net_trade_date"] for r in ov)

    # 港交所成交净额（按成交日）
    turnover = []
    for d in tdays:
        r = dsrows.get(d)
        if not r or r.get("status") != "ok":
            continue
        n = ds_net(d)
        turnover.append({"trade_date": d,
                         "sse_buy": (r.get("sse") or {}).get("buy"), "sse_sell": (r.get("sse") or {}).get("sell"),
                         "szse_buy": (r.get("szse") or {}).get("buy"), "szse_sell": (r.get("szse") or {}).get("sell"),
                         "sse_rank": (r.get("sse") or {}).get("rank"), "szse_rank": (r.get("szse") or {}).get("rank"),
                         "southbound_trading_day": [r.get("sse_trading_day"), r.get("szse_trading_day")],
                         "net_hkd": n, "net_yi": yi(n), "complete": bool(r.get("sse") and r.get("szse")),
                         "src": S("ds"), "label": "计算"})
    ds_avail = [t["trade_date"] for t in turnover]
    d1021 = next((t for t in turnover if t["trade_date"] == "2026-10-21"), None)
    if d1021:
        chk("南向：10-21 成交净额复算（沪+深港通买入−卖出）", d1021["net_yi"] is not None and abs(d1021["net_yi"] + 17.06) < 0.01,
            "复算 %s 亿港元；mkt.json 记为约 -17.1 亿" % d1021["net_yi"])

    def sb_change(a, b):
        ra, rb = sb_by.get(a), sb_by.get(b)
        if not ra or not rb:
            return None
        rng = [r for r in series if a < r["date"] <= b]
        return {"from": a, "to": b, "d_shares": rb["shares"] - ra["shares"], "d_pp": r2(rb["pct"] - ra["pct"]),
                "net_hkd_est_sum": sum(r.get("net_hkd_est") or 0 for r in rng),
                "net_yi_est_sum": yi(sum(r.get("net_hkd_est") or 0 for r in rng)),
                "src": S("sb", "yahoo"), "label": "计算"}
    ye = max(d for d in sb_by if d <= "2025-12-31")
    sep = max(d for d in sb_by if d <= "2026-09-30")
    w1 = tdays[idx[last] - 5]
    m1 = tdays[idx[last] - 20]
    pcts = [(r["pct"], r["date"]) for r in series]
    monthly_sb = []
    months = sorted(set(r["date"][:7] for r in series))
    prev_end = None
    for mo in months:
        rs = [r for r in series if r["date"][:7] == mo]
        end = rs[-1]
        monthly_sb.append({"month": mo, "end_date": end["date"], "end_shares": end["shares"], "end_pct": end["pct"],
                           "d_shares": end["shares"] - prev_end["shares"] if prev_end else None,
                           "net_yi_est_sum": yi(sum(r.get("net_hkd_est") or 0 for r in rs)) if prev_end else None,
                           "src": S("sb", "yahoo"), "label": "计算"})
        prev_end = end
    est_rows = [r for r in series if r.get("net_hkd_est") is not None]
    top_buy = sorted(est_rows, key=lambda r: -r["net_hkd_est"])[:5]
    top_sell = sorted(est_rows, key=lambda r: r["net_hkd_est"])[:5]
    to_rows = [t for t in turnover if t["net_hkd"] is not None]
    southbound = {
        "as_of": last,
        "definition": "港股通（沪+深）在 CCASS 中持有的腾讯 HKD 柜台股份；按结算口径，持股日 D 反映截至 D-2 个交易日的成交。"
                      "占比为港交所页面公布值（页面注明所用已发行股份数可能未及时更新，且显示为两位小数）。",
        "price_note": "收盘价来自 Yahoo Finance（%s）" % UNOFFICIAL_PX,
        "field_labels": {
            "shares": {"label": "结构化数据", "src": S("sb")}, "pct": {"label": "结构化数据", "src": S("sb")},
            "d_shares": {"label": "计算", "src": S("sb")}, "d_pp": {"label": "计算", "src": S("sb")},
            "close": {"label": "结构化数据", "src": S("yahoo"), "note": UNOFFICIAL_PX},
            "trade_date_est": {"label": "计算", "src": S("sb"), "note": "按 T+2 交收回推的成交日（港股交易日历取自行情数据）"},
            "close_trade_date": {"label": "结构化数据", "src": S("yahoo"), "note": UNOFFICIAL_PX},
            "net_hkd_est": {"label": "计算", "src": S("sb", "yahoo"),
                            "note": "主口径：股数变化 × 推定成交日（T-2）收盘价，港元；估算值，不等于实际成交额"},
            "net_hkd_est_same_day_close": {"label": "计算", "src": S("sb", "yahoo"),
                                           "note": "任务口径：股数变化 × 持股日当日收盘价，港元；估算值"},
            "hkex_turnover_net_trade_date": {"label": "计算", "src": S("ds"),
                                             "note": "港交所十大成交活跃股：推定成交日沪+深港通买入额−卖出额（港元）；腾讯未进十大时为空"}},
        "primary_net_field": "net_hkd_est",
        "latest": {"date": last, "shares": sb_by[last]["shares"], "pct": sb_by[last]["pct"],
                   "src": S("sb"), "label": "结构化数据"},
        "changes": {
            "since_2025_10_31": sb_change("2025-10-31", last),
            "ytd_since_%s" % ye: sb_change(ye, last),
            "since_%s" % sep: sb_change(sep, last),
            "last_5_trading_days": sb_change(w1, last),
            "last_20_trading_days": sb_change(m1, last)},
        "range_in_window": {"max_pct": max(pcts)[0], "max_pct_date": max(pcts)[1],
                            "min_pct": min(pcts)[0], "min_pct_date": min(pcts)[1], "src": S("sb"), "label": "计算"},
        "top_net_buy_days_est": [{"date": r["date"], "trade_date_est": r["trade_date_est"], "net_yi_est": yi(r["net_hkd_est"]),
                                  "d_shares": r["d_shares"], "src": S("sb", "yahoo"), "label": "计算"} for r in top_buy],
        "top_net_sell_days_est": [{"date": r["date"], "trade_date_est": r["trade_date_est"], "net_yi_est": yi(r["net_hkd_est"]),
                                   "d_shares": r["d_shares"], "src": S("sb", "yahoo"), "label": "计算"} for r in top_sell],
        "top_net_sell_days_hkex_turnover": [{"trade_date": t["trade_date"], "net_yi": t["net_yi"], "src": S("ds"),
                                             "label": "计算"} for t in sorted(to_rows, key=lambda t: t["net_hkd"])[:5]],
        "top_net_buy_days_hkex_turnover": [{"trade_date": t["trade_date"], "net_yi": t["net_yi"], "src": S("ds"),
                                            "label": "计算"} for t in sorted(to_rows, key=lambda t: -t["net_hkd"])[:5]],
        "alignment_check": {"method": "持股日 D 的股数变化 与 第 D-k 个交易日港交所成交净额/收盘价 的相关系数",
                            "result": align, "best": best,
                            "overlap_days": len(ov), "sum_net_hkd_est_yi": yi(sum_est), "sum_hkex_turnover_net_yi": yi(sum_ds),
                            "label": "计算", "src": S("sb", "ds", "yahoo")},
        "hkex_turnover_window": {"first": ds_avail[0] if ds_avail else None, "last": ds_avail[-1] if ds_avail else None,
                                 "days": len(ds_avail),
                                 "note": "港交所每日统计 JS 仅保留近几个月；更早日期返回 404（已记录于缓存）"},
        "monthly": monthly_sb,
        "series": series,
        "turnover_daily": turnover,
    }

    # ---------------- CCASS
    cc = get_ccass(CCASS_DATES)
    ccass = {"as_of": max(cc) if cc else None, "dates": sorted(cc), "note":"CCASS 参与者为托管行/券商/结算机构，持股不等于实益持有人；已剔除投资者户口持有人（可能为自然人）。"
                                           "A00003/A00004 为中国证券登记结算（沪/深港通南向）。", "summary": [], "top10": [],
             "top10_movers_1w": [], "southbound_crosscheck": [],
             "status": ("已取得 %d 个取样日：%s；未取得：%s" % (len(cc), "、".join(sorted(cc)),
                                                       "、".join(d for d in CCASS_DATES if d not in cc) or "无"))
             if cc else "未取得：CCASS 查询未返回数据（离线或网络失败），本节为空，不作替代估计"}
    if cc:
        latest_c = max(cc)
        ref_1w = "2026-10-16" if "2026-10-16" in cc else None
        maps = {d: {p[0]: p for p in c["participants"]} for d, c in cc.items()}
        for d in sorted(cc):
            c = cc[d]
            ccass["summary"].append({"date": d, "page_date": c.get("page_date"), "issued_shares": c.get("issued_shares"),
                                     **{k: v for k, v in c["summary"].items()}, "src": S("ccass"), "label": "结构化数据"})
            a3 = maps[d].get("A00003", [None, None, 0, 0])[2]
            a4 = maps[d].get("A00004", [None, None, 0, 0])[2]
            sbv = sb_by.get(d, {}).get("shares")
            ccass["southbound_crosscheck"].append({"date": d, "A00003": a3, "A00004": a4, "sum": a3 + a4,
                                                   "southbound_page": sbv, "diff": (a3 + a4 - sbv) if sbv else None,
                                                   "src": S("ccass", "sb"), "label": "计算"})
        chk("CCASS：A00003+A00004 等于南向持股页面值（各取样日）",
            all(x["diff"] == 0 for x in ccass["southbound_crosscheck"] if x["diff"] is not None),
            [(x["date"], x["diff"]) for x in ccass["southbound_crosscheck"]])
        L = maps[latest_c]

        def delta(pid, d):
            if d not in maps:
                return None
            o = maps[d].get(pid)
            return L[pid][2] - (o[2] if o else 0)
        for p in sorted(L.values(), key=lambda p: -p[2])[:10]:
            ccass["top10"].append({"participant_id": p[0], "name": p[1], "shares": p[2], "pct": p[3],
                                   "d_shares_vs_2026_10_16": delta(p[0], "2026-10-16"),
                                   "d_shares_vs_2026_09_30": delta(p[0], "2026-09-30"),
                                   "d_shares_vs_2025_12_31": delta(p[0], "2025-12-31"),
                                   "as_of": latest_c, "src": S("ccass"), "label": "结构化数据",
                                   "delta_label": "计算"})
        if ref_1w:
            allids = set(L) | set(maps[ref_1w])
            mv = []
            for pid in allids:
                a = L.get(pid)
                b = maps[ref_1w].get(pid)
                ch = (a[2] if a else 0) - (b[2] if b else 0)
                mv.append((abs(ch), pid, ch, (a or b)[1], a[2] if a else 0))
            for _, pid, ch, name, sh in sorted(mv, reverse=True)[:10]:
                ccass["top10_movers_1w"].append({"participant_id": pid, "name": name, "d_shares": ch,
                                                 "d_pct_of_issued": r2(ch / cc[latest_c]["issued_shares"] * 100, 3),
                                                 "shares_latest": sh, "from": ref_1w, "to": latest_c,
                                                 "src": S("ccass"), "label": "计算"})

    # ---------------- major holders
    ir_txt = (MR / "dl" / "tc_ir26.txt").read_text(encoding="utf-8")
    ar_txt = (MR / "dl" / "tc_ar25.txt").read_text(encoding="utf-8")
    add_input(MR / "dl" / "tc_ir26.pdf")
    add_input(MR / "dl" / "tc_ir26.txt")
    add_input(MR / "dl" / "tc_ar25.pdf")
    add_input(MR / "dl" / "tc_ar25.txt")

    def holders_from(txt, label_date):
        i = txt.find("INTERESTS OF SUBSTANTIAL SHAREHOLDERS")
        seg = txt[i:i + 3000]
        mih = re.search(r"MIH Internet Holdings B\.V\. Long position Corporate \(Note 1\) ([\d,]+) ([\d.]+)%", seg)
        ads = re.search(r"Long position Corporate \(Note 2\) ([\d,]+) ([\d.]+)%", seg)
        iss = re.search(r"total number of issued [Ss]hares(?: of the Company)? was ([\d,]+)", seg)
        return {"date": label_date, "mih_shares": to_int(mih.group(1)), "mih_pct": float(mih.group(2)),
                "ads_shares": to_int(ads.group(1)), "ads_pct": float(ads.group(2)), "issued": to_int(iss.group(1))}
    h26 = holders_from(ir_txt, "2026-06-30")
    h25 = holders_from(ar_txt, "2025-12-31")
    chk("主要股东：中报 MIH 持股 2,055,231,800 股 / 22.60%", h26["mih_shares"] == 2055231800 and h26["mih_pct"] == 22.60,
        h26)
    di, di_det = get_di()
    pros = sorted([r for r in di["rows"] if r["name"].startswith("Prosus")], key=lambda r: r["event_date"])
    nasp = {(r["event_date"], r["reason"]): r for r in di["rows"] if r["name"].startswith("Naspers")}
    paired = [r for r in pros if (r["event_date"], r["reason"]) in nasp]
    unpaired = [r["event_date"] for r in pros if (r["event_date"], r["reason"]) not in nasp]
    same = all(nasp[(r["event_date"], r["reason"])]["shares_interested"] == r["shares_interested"] and
               nasp[(r["event_date"], r["reason"])]["pct"] == r["pct"] for r in paired)
    chk("DI：Prosus N.V. 与 Naspers 同日同原因申报的股数/比例逐笔一致（同一批股份）", same and paired,
        "Prosus %d 笔，其中 %d 笔有 Naspers 同日申报且一致；列表中未见 Naspers 同日申报：%s" % (len(pros), len(paired), unpaired))
    # 与上一轮保存的"全部通知"页（2025-01-01 起，data/src/market_raw/di/di2.html）交叉核对 2025 年以来的 Prosus/Naspers 申报
    di2_rows = di_parse_list((MR / "di" / "di2.html").read_text(encoding="utf-8", errors="ignore"))
    k_di2 = {(r["form"], r["shares_interested"], r["pct"]) for r in di2_rows if r["name"].startswith(("Prosus", "Naspers"))}
    di2_from = min(r["event_date"] for r in di2_rows) if di2_rows else "9999"
    k_ss = {(r["form"], r["shares_interested"], r["pct"]) for r in di["rows"]
            if r["name"].startswith(("Prosus", "Naspers")) and r["event_date"] >= di2_from}
    chk("DI：%s 以来 Prosus/Naspers 申报与本地全部通知页（di2.html）逐笔一致" % di2_from, k_di2 == k_ss and k_ss,
        "主要股东列表 %d 笔；全部通知页 %d 笔（该页为上一轮保存的第 1 页，覆盖 %s 至 2026-10-26）" % (len(k_ss), len(k_di2), di2_from))
    excluded = {}
    for r in di["rows"]:
        if not (r["name"].startswith("Prosus") or r["name"].startswith("Naspers")):
            director = r["form"].startswith("DA") or "Advance Data" in r["name"] or "Ma Huateng" in r["name"]
            cat = "董事及其控制公司（不展示）" if director else "其他机构（不展示）"
            excluded[cat] = excluded.get(cat, 0) + 1
    di_parse_note = "主要股东通知列表页面显示总记录数 %s，本脚本解析 %d 条；差额未能定位（未保存原始页面）。%s 以来的 " \
                    "Prosus/Naspers 申报已与本地全部通知页交叉核对。" % (di.get("total_records"), len(di["rows"]), di2_from)
    last_di = pros[-1] if pros else None
    reason_desc = {code: d.get("description") for code, d in di_det.items()}
    steps = [{"event_date": r["event_date"], "form": r["form"], "reason_code": r["reason"],
              "reason_desc": reason_desc.get(r["reason"]), "shares_involved": r["shares_involved"],
              "avg_price_hkd": r["avg_price_hkd"], "shares_interested": r["shares_interested"], "pct": r["pct"],
              "src": S("di"), "label": "公开披露"} for r in pros]
    prosus_sf = (MR / "dl" / "webfetch-1792985490790-q0387r.txt")
    om = (MR / "dl" / "webfetch-1792985491247-31qzj6.txt")
    for p in [prosus_sf, MR / "dl" / "webfetch-1792985490790-q0387r.pdf", om, MR / "dl" / "webfetch-1792985491247-31qzj6.pdf",
              MR / "dl" / "prosus_fy26_pres.txt", MR / "dl" / "prosus_fy26_tr.txt"]:
        add_input(p)
    q_hold = "will be maintained for the foreseeable future"
    sf_text = norm_ws(prosus_sf.read_text(encoding="utf-8", errors="replace").replace("/uni00A0", " "))
    q_gain = "primarily driven by a US$1.3bn lower gain on the disposal of Tencent shares"
    om_text = norm_ws(om.read_text(encoding="utf-8", errors="replace"))
    q_om = "The group retained a 22.8% interest in Tencent."
    chk("Prosus 引语可在本地原文中检索到", q_hold in sf_text and q_gain in sf_text and q_om in om_text, "3 条")
    major = {
        "as_of": AS_OF,
        "note": "只展示主要股东持股与权益披露台阶；不展示董事个人交易。持股比例分母为各披露日已发行股份。",
        "table": [
            {"holder": "MIH Internet Holdings B.V.（Prosus N.V. 全资；Naspers 经 Prosus 控制，三方视为同一批股份）",
             "date": h26["date"], "shares": h26["mih_shares"], "pct": h26["mih_pct"], "src": S("ir26"), "label": "公开披露"},
            {"holder": "MIH Internet Holdings B.V.", "date": h25["date"], "shares": h25["mih_shares"], "pct": h25["mih_pct"],
             "src": S("ar25"), "label": "公开披露"},
            {"holder": "Advance Data Services Limited（马化腾全资持有；含经 Ma Huateng Global Foundation Limited 间接持有 95,000,000 股）",
             "date": h26["date"], "shares": h26["ads_shares"], "pct": h26["ads_pct"], "src": S("ir26"), "label": "公开披露"},
            {"holder": "Advance Data Services Limited", "date": h25["date"], "shares": h25["ads_shares"], "pct": h25["ads_pct"],
             "src": S("ar25"), "label": "公开披露"},
            {"holder": "港股通（南向，沪+深合计，CCASS 口径，非登记股东）", "date": last, "shares": sb_by[last]["shares"],
             "pct": sb_by[last]["pct"], "src": S("sb"), "label": "结构化数据"}],
        "issued_shares": [{"date": h25["date"], "shares": h25["issued"], "src": S("ar25"), "label": "公开披露"},
                          {"date": h26["date"], "shares": h26["issued"], "src": S("ir26"), "label": "公开披露"}],
        "derived": [
            {"item": "MIH 2026 上半年持股变动（股）", "value": h26["mih_shares"] - h25["mih_shares"],
             "src": S("ar25", "ir26"), "label": "计算"},
            {"item": "MIH 持股比例变动（百分点）", "value": r2(h26["mih_pct"] - h25["mih_pct"]), "src": S("ar25", "ir26"),
             "label": "计算"},
            {"item": "若按 2025-12-31 股本计，MIH 2026-06-30 股数对应比例（%）", "value": r2(h26["mih_shares"] / h25["issued"] * 100, 3),
             "src": S("ar25", "ir26"), "label": "计算", "note": "用于区分'股数减少'与'股本缩小'两种效应"},
            {"item": "Advance Data Services 持股股数变动（股）", "value": h26["ads_shares"] - h25["ads_shares"],
             "src": S("ar25", "ir26"), "label": "计算",
             "note": ("股数不变，比例由 %.2f%% 变为 %.2f%% 来自已发行股本变化" % (h25["ads_pct"], h26["ads_pct"]))
             if h26["ads_shares"] == h25["ads_shares"] else "股数有变化，见上两行原始披露"}],
        "prosus_di_steps": steps,
        "prosus_di_latest": {"event_date": last_di["event_date"], "pct": last_di["pct"], "shares": last_di["shares_interested"],
                             "form": last_di["form"], "src": S("di"), "label": "公开披露"} if last_di else None,
        "prosus_di_since_latest": {"text": "%s 之后至 %s，DI 列表中未见 Prosus N.V./Naspers 新申报（检索时间 %s）" % (
            last_di["event_date"] if last_di else "-", AS_OF, di.get("fetched_at")), "src": S("di"), "label": "公开披露"},
        "di_reason_codes": [{"code": c, "description": d.get("description"), "supplementary_example": d.get("supplementary"),
                             "form": d.get("form"), "src": S("diform") if d.get("form") == "CS20250728E00459" else S("di"),
                             "label": "公开披露"} for c, d in di_det.items()],
        "di_rule_note": {"text": "DI 表格 CS20250728E00459 补充说明原文：\"%s\"——即持股比例跨越整数百分比时须申报。" % (
            di_det.get("1113", {}).get("supplementary") or "未取得"), "src": S("diform"), "label": "公开披露"},
        "di_excluded_counts": {"counts": excluded, "src": S("di"), "label": "计算",
                               "note": "主要股东通知列表中非 Prosus/Naspers 的申报只计数、不展示明细"},
        "di_parse_note": {"text": di_parse_note, "src": S("di", "di_all"), "label": "计算"},
        "prosus_latest_disclosure": [
            {"text": "Prosus FY2026 短式业绩公告原文：\"Our significant holding in Tencent, a globally recognised leader in "
                     "technology, %s.\"" % q_hold, "date": "2026-06-29", "src": S("prosus_sf"), "label": "公开披露"},
            {"text": "同一公告：持续经营盈利下降\"%s\"。" % q_gain, "date": "2026-06-29", "src": S("prosus_sf"),
             "label": "公开披露"},
            {"text": "Prosus FY2026 业绩演示中持股比例以组织图（图片）呈现，可提取文本中未找到腾讯持股比例：未找到。", "date": "2026-06-29",
             "src": S("prosus_pres"), "label": "公开披露"},
            {"text": "Old Mutual 点评称\"%s\"（截至 2026-03-31 财年末口径，媒体/券商转述，二手）" % q_om, "date": "2026-07-02",
             "src": S("oldmutual"), "label": "公开披露"}],
    }

    # ---------------- buybacks: NDDR PDFs
    lst = load_json(MR / "nddr" / "list2026.json")
    add_input(MR / "nddr" / "list2026.json")
    bbj = load_json(MR / "nddr" / "buybacks2026.json")
    add_input(MR / "nddr" / "buybacks2026.json")
    by_file = {Path(x["FILE_LINK"]).name: x for x in lst}
    nddr_list = [x for x in lst if "Next Day Disclosure" in html.unescape(x["TITLE"])]
    files = []
    daily = {}
    partb = {}
    mandates = []
    pdfs = sorted((MR / "nddr").glob("*.pdf"))
    for p in pdfs:
        add_input(p)
        meta_l = by_file.get(p.name, {})
        title = html.unescape(meta_l.get("TITLE", ""))
        if "Next Day Disclosure" not in title:
            files.append({"file": p.name, "title": title, "type": "非翌日披露报表（不参与回购对账）",
                          "url": "https://www1.hkexnews.hk" + meta_l.get("FILE_LINK", "") if meta_l else None})
            continue
        rec = parse_nddr(pdftext(p))
        typ = "回购" if rec["repurchases"] else "股本变动（非回购）"
        f = {"file": p.name, "url": "https://www1.hkexnews.hk" + meta_l["FILE_LINK"], "published": meta_l.get("DATE_TIME"),
             "submitted": rec["submitted"], "type": typ, "repurchases": rec["repurchases"],
             "total_shares": rec["total_shares"], "total_amount": rec["total_amount"],
             "closing_issued_shares": rec["closing_issued_shares"], "closing_date": rec["closing_date"]}
        if not rec["repurchases"]:
            f["section1_event"] = rec["section1_event"]
        files.append(f)
        for r in rec["repurchases"]:
            if r["date"] in daily:
                f.setdefault("issues", []).append("重复日期 %s" % r["date"])
            daily[r["date"]] = dict(r, file=p.name, url=f["url"])
        for d, v in rec["partb_vwap"].items():
            partb.setdefault(d, v)
        if rec["mandate_date"]:
            mandates.append({"file": p.name, "as_of": rec["repurchases"][-1]["date"] if rec["repurchases"] else rec["submitted"],
                             "mandate_date": rec["mandate_date"], "authorised": rec["mandate_authorised"],
                             "used": rec["mandate_used"], "used_pct": rec["mandate_used_pct"]})
        if rec["repurchases"] and rec["total_shares"] is not None:
            if rec["total_shares"] != sum(r["shares"] for r in rec["repurchases"]) or \
                    abs(rec["total_amount"] - sum(r["amount"] for r in rec["repurchases"])) > 0.5:
                f.setdefault("issues", []).append("Section II 合计与明细不符")
    nddr_files_local = {x["file"] for x in files if x.get("type") in ("回购", "股本变动（非回购）")}
    missing_pdf = [Path(x["FILE_LINK"]).name for x in nddr_list if Path(x["FILE_LINK"]).name not in nddr_files_local]
    chk("NDDR：标题检索中的翌日披露报表与本地 PDF 一一对应", not missing_pdf and len(nddr_files_local) == len(nddr_list),
        "检索 %d 份；本地解析 %d 份；缺 %s" % (len(nddr_list), len(nddr_files_local), missing_pdf))
    days_sorted = sorted(daily)
    tot_sh = sum(daily[d]["shares"] for d in days_sorted)
    tot_amt = sum(daily[d]["amount"] for d in days_sorted)
    # 对账 buybacks2026.json
    jmap = {dmy(d): v for d, v in bbj}
    recon_rows = []
    for d in sorted(set(jmap) | set(daily)):
        a, b = daily.get(d), jmap.get(d)
        row = {"date": d, "in_pdf": a is not None, "in_json": b is not None}
        if a and b:
            row.update({"shares_match": a["shares"] == b[0], "high_match": a["high"] == b[1], "low_match": a["low"] == b[2],
                        "amount_pdf": a["amount"], "amount_json": b[3], "amount_diff": round(a["amount"] - b[3], 2)})
        recon_rows.append(row)
    json_tot_sh = sum(v[0] for _, v in bbj)
    json_tot_amt = sum(v[3] for _, v in bbj)
    diffs = [r for r in recon_rows if not (r["in_pdf"] and r["in_json"] and r["shares_match"] and r["high_match"]
                                           and r["low_match"] and abs(r["amount_diff"]) < 1)]
    amt_diff_rows = [r for r in recon_rows if r.get("amount_diff")]
    chk("回购：PDF 逐份解析 = 96 个交易日 / 68,276,700 股 / 约 324.44 亿港元",
        len(days_sorted) == 96 and tot_sh == 68276700 and round(tot_amt / 1e8, 2) == 324.44,
        "%d 天 / %s 股 / %.2f 港元" % (len(days_sorted), tot_sh, tot_amt))
    chk("回购：buybacks2026.json 与 PDF 逐日一致（股数、最高价、最低价完全一致；金额差 <1 港元）", not diffs,
        "不一致 %d 天；金额存在小数差 %d 天，合计 %.2f 港元（json 截去了 PDF 金额的小数位）" % (
            len(diffs), len(amt_diff_rows), sum(r["amount_diff"] for r in amt_diff_rows)))
    vw_bad = []
    for d in days_sorted:
        r = daily[d]
        r["vwap"] = round(r["amount"] / r["shares"], 4)
        if not (r["low"] - 1e-6 <= r["vwap"] <= r["high"] + 1e-6):
            vw_bad.append(d)
        pb = partb.get(d)
        if pb:
            r["vwap_partB"] = pb["vwap"]
    pb_cmp = [d for d in days_sorted if "vwap_partB" in daily[d]]
    pb_bad = [d for d in pb_cmp if abs(daily[d]["vwap_partB"] - daily[d]["vwap"]) > 0.001]
    # 均价越界：若 PDF 第一部分 B 段自身披露的均价与计算值相同，说明是原件数值本身不自洽（非解析错误），列入 data_anomalies
    anomalies = []
    for d in vw_bad:
        r = daily[d]
        anomalies.append({
            "date": d, "file": r["file"], "url": r["url"], "shares": r["shares"], "amount_hkd": r["amount"],
            "high": r["high"], "low": r["low"], "vwap_calc": r["vwap"], "vwap_partB": r.get("vwap_partB"),
            "confirmed_in_original": r.get("vwap_partB") is not None and abs(r["vwap_partB"] - r["vwap"]) < 0.001,
            "text": "%s 翌日披露报表：总代价 %s 港元 ÷ %s 股 = %.4f 港元，%s所报当日最低价 %s / 最高价 %s 港元；"
                    "报表第一部分 B 段所列均价为 %s 港元。原件数值不自洽，原因不作推断，未作任何改动。" % (
                        d, format(r["amount"], ","), format(r["shares"], ","), r["vwap"],
                        "低于" if r["vwap"] < r["low"] else "高于", r["low"], r["high"], r.get("vwap_partB")),
            "src": S("nddr"), "label": "计算"})
    chk("回购：均价（金额/股数）落在当日最高/最低价之间；越界日期均已确认为原件自身数值（列入 data_anomalies）",
        all(a["confirmed_in_original"] for a in anomalies),
        "越界 %s；%s" % (vw_bad, "均与原件第一部分 B 段均价一致（原件不自洽，非解析错误）" if vw_bad else "无"))
    chk("回购：计算均价与 PDF 第一部分 B 段披露的加权均价一致（可得日期）", not pb_bad,
        "可比 %d 天，不一致 %s" % (len(pb_cmp), pb_bad[:5]))
    mand_latest = max(mandates, key=lambda m: m["as_of"]) if mandates else None
    since_agm = sum(daily[d]["shares"] for d in days_sorted if d > "2026-05-13")
    if mand_latest:
        chk("回购：2026-05-13 授权下累计已回购股数 = 5-13 之后逐日加总", mand_latest["used"] == since_agm,
            "PDF %s；加总 %s" % (mand_latest["used"], since_agm))
    # 中报月度表
    ir_months, ir_tot = parse_month_table(ir_txt, "PURCHASE, SALE OR REDEMPTION OF THE COMPANY", 2026)
    ar_months, ar_tot = parse_month_table(ar_txt, "PURCHASE, SALE OR REDEMPTION OF THE COMPANY’S LISTED SECURITIES\nDuring", 2025)
    if not ar_months:
        ar_months, ar_tot = parse_month_table(ar_txt[ar_txt.find("During the year ended 31 December 2025, the Company "
                                                                 "repurchased") - 10:], "During the year", 2025)
    monthly = []
    for mo in sorted(set(d[:7] for d in days_sorted)):
        ds_ = [d for d in days_sorted if d[:7] == mo]
        sh = sum(daily[d]["shares"] for d in ds_)
        amt = sum(daily[d]["amount"] for d in ds_)
        row = {"month": mo, "days": len(ds_), "shares": sh, "amount_hkd": round(amt, 2), "amount_yi": yi(amt),
               "avg_per_day_yi": yi(amt / len(ds_)), "vwap": round(amt / sh, 4),
               "high": max(daily[d]["high"] for d in ds_), "low": min(daily[d]["low"] for d in ds_),
               "src": S("nddr"), "label": "计算"}
        im = next((x for x in ir_months if x["month"] == mo), None)
        if im:
            row["interim_report"] = {"shares": im["shares"], "amount_hkd": im["amount"], "high": im["high"], "low": im["low"],
                                     "shares_diff": sh - im["shares"], "amount_diff": round(amt - im["amount"], 2),
                                     "src": S("ir26"), "label": "公开披露"}
        monthly.append(row)
    for mo in ["2026-02"]:
        if mo not in {m["month"] for m in monthly}:
            monthly.append({"month": mo, "days": 0, "shares": 0, "amount_hkd": 0, "amount_yi": 0, "src": S("nddr"),
                            "label": "计算"})
    monthly.sort(key=lambda m: m["month"])
    h1_bad = [m["month"] for m in monthly if "interim_report" in m and
              (m["interim_report"]["shares_diff"] != 0 or abs(m["interim_report"]["amount_diff"]) > 1)]
    h1_sh = sum(daily[d]["shares"] for d in days_sorted if d <= "2026-06-30")
    h1_amt = sum(daily[d]["amount"] for d in days_sorted if d <= "2026-06-30")
    chk("回购：2026 上半年逐月（股数、金额、最高/最低价）与中报月度表一致",
        not h1_bad and ir_tot and h1_sh == ir_tot["shares"] and abs(h1_amt - ir_tot["amount"]) < 1,
        "上半年 PDF %s 股 / %.2f 港元；中报 %s" % (h1_sh, h1_amt, ir_tot))

    def qsum(a, b):
        ds_ = [d for d in days_sorted if a <= d <= b]
        return sum(daily[d]["shares"] for d in ds_), sum(daily[d]["amount"] for d in ds_), len(ds_)
    q1 = qsum("2026-01-01", "2026-03-31")
    q2 = qsum("2026-04-01", "2026-06-30")
    q3 = qsum("2026-07-01", "2026-09-30")
    q4 = qsum("2026-10-01", "2026-12-31")
    ar_q3 = sum(m["shares"] for m in ar_months if m["month"] in ("2025-07", "2025-08", "2025-09"))
    quarterly = [
        {"quarter": "2025Q3", "ppt_text": "Repurchased ~35 million shares with an aggregated cost of ~RMB19 billion during 3Q25",
         "ppt_slide": slide_of(DATA_SRC / "ir_official" / "3Q25_ppt.txt", "Repurchased ~35"),
         "computed_shares": ar_q3, "computed_from": "2025 年报月度表 7–9 月加总", "src": S("ppt3q25", "ar25"),
         "label": "计算"},
        {"quarter": "2026Q1", "ppt_text": "Repurchased ~13 million shares for a consideration of ~RMB6.7 billion during 1Q26",
         "ppt_slide": slide_of(DATA_SRC / "ir_official" / "1Q26_ppt.txt", "Repurchased ~13"),
         "computed_shares": q1[0], "computed_amount_hkd": round(q1[1], 2), "computed_days": q1[2],
         "computed_from": "翌日披露报表逐日加总", "src": S("ppt1q26", "nddr"), "label": "计算"},
        {"quarter": "2026Q2", "ppt_text": "Repurchased ~37 million shares for a consideration of ~RMB14.7 billion and paid "
                                          "cash dividend of ~RMB41.6 billion during 2Q26",
         "ppt_slide": slide_of(DATA_SRC / "ir_official" / "2Q26_ppt.txt", "Repurchased ~37"),
         "computed_shares": q2[0], "computed_amount_hkd": round(q2[1], 2), "computed_days": q2[2],
         "computed_from": "翌日披露报表逐日加总", "src": S("ppt2q26", "nddr"), "label": "计算"},
        {"quarter": "2026Q3", "ppt_text": "尚未发布（Q3 业绩 2026-11-18）", "computed_shares": q3[0],
         "computed_amount_hkd": round(q3[1], 2), "computed_amount_yi": yi(q3[1]), "computed_days": q3[2],
         "computed_from": "翌日披露报表逐日加总（7-01 至 9-30），供 Q3 业绩材料核对", "src": S("nddr"), "label": "计算"},
        {"quarter": "2026Q4 至今", "ppt_text": "—", "computed_shares": q4[0], "computed_amount_hkd": round(q4[1], 2),
         "computed_amount_yi": yi(q4[1]), "computed_days": q4[2], "computed_from": "10-01 至 10-15（最后一笔）",
         "src": S("nddr"), "label": "计算"}]
    chk("回购：季度股数与业绩 PPT 约数一致（3Q25≈35M、1Q26≈13M、2Q26≈37M）",
        round(ar_q3 / 1e6) == 35 and round(q1[0] / 1e6) == 13 and round(q2[0] / 1e6) == 37,
        "3Q25 %s；1Q26 %s；2Q26 %s" % (ar_q3, q1[0], q2[0]))
    chk("回购：2025 年报全年合计 153,415,000 股 / 约 800.36 亿港元（月度表加总）",
        ar_tot and ar_tot["shares"] == 153415000 and sum(m["shares"] for m in ar_months) == 153415000,
        ar_tot)

    # 日历热图（2026-01-02 至最新交易日）
    events = []
    for x in lst:
        t = html.unescape(x["TITLE"])
        if t.startswith("DATE OF BOARD MEETING") or t.startswith("ANNOUNCEMENT OF THE") and "RESULTS" in t:
            d, m_, y = x["DATE_TIME"][:10].split("/")
            events.append({"date": "%s-%s-%s" % (y, m_, d), "title": t, "url": "https://www1.hkexnews.hk" + x["FILE_LINK"]})
    results_days = sorted(e["date"] for e in events if e["title"].startswith("ANNOUNCEMENT"))
    bm_txt = (MR / "nddr" / "2026092401585.txt").read_text(encoding="utf-8")
    add_input(MR / "nddr" / "2026092401585.txt")
    mbm = re.search(r"Board meeting of the Company will be held on \w+, (\d{1,2} \w+ \d{4})", re.sub(r"\s+", " ", bm_txt))
    q3_board = dmy(mbm.group(1)) if mbm else None
    chk("规则窗口：董事会日期取自 2026-09-24 港交所公告原文", q3_board == "2026-11-18", q3_board)
    # (期间, 董事会日期, 董事会日期公告日, 上市规则业绩公告期限[年度=年结后3个月；中期=期结后2个月；季度无])
    boards = [("2025 年度业绩", "2026-03-18", None, "2026-03-31"),
              ("2026 年第一季度业绩", "2026-05-13", "2026-03-23", None),
              ("2026 年中期（第二季度）业绩", "2026-08-12", "2026-06-22", "2026-08-31"),
              ("2026 年第三季度业绩", q3_board, "2026-09-24", None)]
    windows = []
    for name, bd, notice, deadline in boards:
        anchor = min(bd, deadline) if deadline else bd
        b = dt.date.fromisoformat(anchor)
        start = (b - dt.timedelta(days=30)).isoformat()
        in_tdays = [d for d in tdays if start <= d <= bd]
        before = [d for d in days_sorted if d < start]
        after = [d for d in days_sorted if d > bd]
        last_bb = max(d for d in days_sorted if d <= bd) if any(d <= bd for d in days_sorted) else None
        first_after = min(after) if after else None
        gap_days = [d for d in tdays if last_bb and last_bb < d < start] if last_bb else []
        notice_e = next((e for e in events if e["date"] == notice and e["title"].startswith("DATE OF BOARD")), None)
        windows.append({
            "period": name,
            "board_date": {"value": bd, "label": "公开披露",
                           "src": S("bm0924") if notice == "2026-09-24" else S("ts2026"),
                           "notice_date": notice, "notice_url": notice_e["url"] if notice_e else None,
                           "note": None if notice else "2026 年公告检索（2026-01-01 起）中未见该次董事会日期公告；"
                                                       "按业绩公告日（%s，见公告检索）计" % bd},
            "rule_window": {"start": start, "end": bd, "first_trading_day": in_tdays[0] if in_tdays else None,
                            "label": "计算", "src": S("gl117", "rule"),
                            "basis": "取 (i) 董事会日期 %s 与 (ii) 上市规则业绩公告期限 %s 中较早者（%s），其前 30 日起至业绩公告日止" % (
                                bd, deadline or "无（季度业绩无上市规则期限）", anchor)},
            "observed": {"last_buyback_before": last_bb, "first_buyback_after": first_after,
                         "no_buyback_from": tdays[idx[last_bb] + 1] if last_bb and idx[last_bb] + 1 < len(tdays) else None,
                         "no_buyback_to": tdays[idx[first_after] - 1] if first_after else "%s（截至数据日，仍无新披露）" % last,
                         "trading_days_between_last_buyback_and_rule_window": gap_days,
                         "label": "公开披露", "src": S("nddr", "ts2026", "ts")},
            "cause": "未公开，不作推断"})
    # 10-15 之后有无新回购披露（最新检索）
    tsd = get_titlesearch()
    after_nddr = []
    if tsd:
        for x in tsd["rows"]:
            t = html.unescape(x["TITLE"])
            d, m_, y = x["DATE_TIME"][:10].split("/")
            if "Next Day Disclosure" in t and "%s-%s-%s" % (y, m_, d) > "2026-10-15":
                after_nddr.append({"date": "%s-%s-%s" % (y, m_, d), "title": t, "url": "https://www1.hkexnews.hk" + x["FILE_LINK"]})
    last_bb_all = days_sorted[-1]
    chk("回购：观察到的最后一笔回购日为 2026-10-15", last_bb_all == "2026-10-15", last_bb_all)
    rule_q = get_rule_text()
    chk("规则：GL117-23 引述第 10.06(2)(e) 条含\"30 days immediately preceding\"", bool(rule_q) and "30 days immediately "
        "preceding" in rule_q, (rule_q or "")[:80])
    win_q3 = windows[-1]
    rw_start, rw_first = win_q3["rule_window"]["start"], win_q3["rule_window"]["first_trading_day"]
    gap_q3 = win_q3["observed"]["trading_days_between_last_buyback_and_rule_window"]
    if rw_start in px:
        first_td_text = "%s 为港股交易日。" % rw_start
    elif rw_start < last:
        first_td_text = "%s 在行情数据中无交易记录（非港股交易日），窗口内首个交易日为 %s。" % (rw_start, rw_first)
    else:
        first_td_text = ""
    blackout = {
        "as_of": AS_OF,
        "rule": {"ref": "《主板上市规则》第 10.06(2)(e) 条", "quote_en": rule_q, "src": S("gl117", "rule"), "label": "公开披露",
                 "note": "引文取自 GL117-23 第 9 段（现行条文为\"30 days immediately preceding\"）。条文另规定：知悉内幕消息后至公布前不得回购。"
                         "GL117-23 同时说明交易所可就自动回购计划豁免该限制期；腾讯是否有此类安排未见公开资料，不作推断。"},
        "layers": {
            "rule_window_calc": {"start": rw_start, "end": win_q3["rule_window"]["end"],
                                 "first_trading_day": rw_first, "label": "计算",
                                 "src": S("gl117", "bm0924"),
                                 "text": "【计算】按第 10.06(2)(e) 条，%s 董事会对应的规则窗口为 %s 至 %s（董事会日期前 30 日起，至业绩公告日止）。%s" % (
                                     q3_board, rw_start, win_q3["rule_window"]["end"], first_td_text)},
            "observed_disclosure": {"last_buyback": last_bb_all, "shares": daily[last_bb_all]["shares"],
                                    "amount_hkd": daily[last_bb_all]["amount"], "high": daily[last_bb_all]["high"],
                                    "low": daily[last_bb_all]["low"], "label": "公开披露", "src": S("nddr"),
                                    "url": daily[last_bb_all]["url"],
                                    "text": "【公开披露】最后一笔回购在 %s：%s 股，每股 %s–%s 港元，共 %s 港元。" % (
                                        last_bb_all, format(daily[last_bb_all]["shares"], ","), daily[last_bb_all]["low"],
                                        daily[last_bb_all]["high"], format(daily[last_bb_all]["amount"], ","))},
            "observed_gap_before_window": {"trading_days": gap_q3,
                                           "label": "公开披露", "src": S("nddr", "ts"),
                                           "text": ("最后一笔回购（%s）之后、规则窗口（%s）之前的交易日 %s 无回购披露；原因未公开，不作推断。" % (
                                               last_bb_all, rw_start, "、".join(gap_q3)) if gap_q3 else
                                               "最后一笔回购与规则窗口之间无其他交易日。")},
            "post_10_15_check": {"new_nddr_after_10_15": after_nddr, "checked_at": tsd.get("fetched_at") if tsd else None,
                                 "label": "公开披露", "src": S("ts", "ts2026"),
                                 "text": ("截至检索时（%s），港交所公告检索中 %s 之后无新的翌日披露报表"
                                          "（2026 年腾讯 %d 份翌日披露报表刊发时间介于当日 %s–%s）。" % (
                                              tsd.get("fetched_at") if tsd else "-", last_bb_all, len(nddr_list),
                                              min(x["DATE_TIME"][11:] for x in nddr_list),
                                              max(x["DATE_TIME"][11:] for x in nddr_list)))
                                 if not after_nddr else "检索到 %s 之后的新翌日披露报表，请核对。" % last_bb_all}},
        "history_2026": windows,
        "do_not_write": "不要写\"回购暂停是因为禁止期\"；两层分开展示，原因未公开。",
    }

    calendar = []
    rw = [(w["rule_window"]["start"], w["rule_window"]["end"]) for w in windows]
    for d in [x for x in tdays if "2026-01-02" <= x <= last]:
        r = daily.get(d)
        calendar.append({"date": d, "weekday": dt.date.fromisoformat(d).isoweekday(),
                         "shares": r["shares"] if r else 0, "amount_hkd": r["amount"] if r else 0,
                         "amount_yi": yi(r["amount"]) if r else 0, "vwap": r["vwap"] if r else None,
                         "in_rule_window": any(a <= d <= b for a, b in rw), "results_day": d in results_days,
                         "src": S("nddr"), "label": "公开披露" if r else "计算"})
    # 无回购区间（≥5 个交易日）
    gaps = []
    run = []
    for c in calendar:
        if c["shares"] == 0:
            run.append(c["date"])
        else:
            if len(run) >= 5:
                gaps.append(run)
            run = []
    if len(run) >= 5:
        gaps.append(run)
    gap_list = [{"from": g[0], "to": g[-1], "trading_days": len(g), "ongoing": g[-1] == last,
                 "contains_results_day": [d for d in g if d in results_days],
                 "src": S("nddr"), "label": "计算"} for g in gaps]

    daily_out = [{"date": d, "shares": daily[d]["shares"], "amount_hkd": daily[d]["amount"], "amount_yi": yi(daily[d]["amount"]),
                  "high": daily[d]["high"], "low": daily[d]["low"], "vwap": daily[d]["vwap"],
                  "vwap_partB": daily[d].get("vwap_partB"), "file": daily[d]["file"], "url": daily[d]["url"],
                  "src": S("nddr"), "label": "公开披露", "vwap_label": "计算"} for d in days_sorted]
    fy25_amt = ar_tot["amount"] if ar_tot else None
    buyback = {
        "as_of": last_bb_all,
        "badge": {"text": "2026 年回购 %.2f 亿港元已逐份对账" % (tot_amt / 1e8), "days": len(days_sorted), "shares": tot_sh,
                  "amount_hkd": round(tot_amt, 2), "amount_yi": yi(tot_amt), "pdfs": len(nddr_files_local),
                  "src": S("nddr"), "label": "计算"},
        "ytd_vs_fy2025": {"ytd_amount_yi": yi(tot_amt), "fy2025_amount_yi": yi(fy25_amt),
                          "ratio_pct": r2(tot_amt / fy25_amt * 100, 1) if fy25_amt else None,
                          "ytd_shares": tot_sh, "fy2025_shares": ar_tot["shares"] if ar_tot else None,
                          "src": S("nddr", "ar25"), "label": "计算",
                          "note": "截至 2026-10-15 的累计回购金额 ÷ 2025 全年回购金额（2025 年报月度表）"},
        "mandate": dict(mand_latest, src=S("nddr"), label="公开披露") if mand_latest else None,
        "mandates_seen": [{"mandate_date": md, "authorised_shares": au, "src": S("nddr"), "label": "公开披露"}
                          for md, au in sorted({(m["mandate_date"], m["authorised"]) for m in mandates})],
        "daily": daily_out,
        "monthly": monthly,
        "quarterly_vs_ppt": quarterly,
        "fy2025_monthly": [dict(m, src=S("ar25"), label="公开披露") for m in ar_months],
        "fy2025_total": dict(ar_tot, src=S("ar25"), label="公开披露") if ar_tot else None,
        "interim_2026_total": dict(ir_tot, src=S("ir26"), label="公开披露") if ir_tot else None,
        "calendar": calendar,
        "no_buyback_runs_ge5": gap_list,
        "data_anomalies": anomalies,
        "reconciliation": {
            "target": {"days": 96, "shares": 68276700, "amount_yi_approx": 324.44},
            "pdf_parsed": {"days": len(days_sorted), "shares": tot_sh, "amount_hkd": round(tot_amt, 2)},
            "json": {"days": len(bbj), "shares": json_tot_sh, "amount_hkd": json_tot_amt},
            "amount_diff_pdf_minus_json_hkd": round(tot_amt - json_tot_amt, 2),
            "amount_diff_days": [{"date": r["date"], "amount_pdf": r["amount_pdf"], "amount_json": r["amount_json"],
                                  "diff": r["amount_diff"]} for r in amt_diff_rows],
            "mismatch_days": diffs,
            "nddr_in_title_search": len(nddr_list), "nddr_local_parsed": len(nddr_files_local),
            "non_repurchase_nddr": [{"file": f["file"], "published": f.get("published"), "event": f.get("section1_event"),
                                     "url": f["url"]} for f in files if f.get("type") == "股本变动（非回购）"],
            "files": files,
            "label": "计算", "src": S("nddr"),
            "method": "pdftotext -raw 逐份提取第二部分 A 段（交易日、股数、最高价、最低价、总代价）与 B 段（授权）；"
                      "第一部分 B 段（已回购未注销）加权均价用于交叉核对均价。"},
    }

    # ---------------- 已公开表述索引（回购/资本回报）——来自用户提供的业绩材料与实录
    tdir = DATA_PARSED
    for q in ["q3-2025", "q4-2025", "q1-2026", "q2-2026"]:
        add_input(tdir / ("%s.json" % q))
    for f in ["374535-q3-2025.html", "419871-q4-2025.html", "609405-q1-2026.html", "667897-q2-2026.html"]:
        add_input(DATA_SRC / "transcripts" / f)
    for f in ["3Q25_ppt.pdf", "3Q25_ppt.txt", "4Q25_ppt.pdf", "4Q25_ppt.txt", "1Q26_ppt.pdf", "1Q26_ppt.txt", "2Q26_ppt.pdf",
              "2Q26_ppt.txt", "manifest.tsv"]:
        add_input(DATA_SRC / "ir_official" / f)
    add_input(MR / "idx" / "tc_res.html")
    add_input(MR / "res" / "2804dbdae364ca25b82d21bc8304f1d3.pdf")
    TR = "非官方逐字稿，引用前以官方录音为准"
    stm = [
        ("2025-11-13", "3Q25 业绩 PPT 第 %s 页" % slide_of(DATA_SRC / "ir_official" / "3Q25_ppt.txt", "Repurchased ~35"), "公司",
         "Repurchased ~35 million shares with an aggregated cost of ~RMB19 billion during 3Q25",
         DATA_SRC / "ir_official" / "3Q25_ppt.txt", "ppt3q25", "公开披露", None,
         "2025 年报月度表 7–9 月合计 %s 股（计算）" % format(ar_q3, ",")),
        ("2025-11-13", "2025 Q3 业绩会", "John Lo（CFO）",
         "partially offset by share repurchases of CNY 19.2 billion", tdir / "q3-2025.json", "tr3q25", "公开披露", TR, None),
        ("2026-03-18", "4Q25 业绩 PPT 第 %s 页" % slide_of(DATA_SRC / "ir_official" / "4Q25_ppt.txt", "Repurchased ~153"), "公司",
         "Repurchased ~153 million shares for a consideration of ~HKD80 billion during FY2025",
         DATA_SRC / "ir_official" / "4Q25_ppt.txt", "ppt4q25", "公开披露", None,
         "2025 年报：153,415,000 股 / 80,036,299,578.20 港元"),
        ("2026-03-18", "4Q25 业绩 PPT 第 %s 页" % slide_of(DATA_SRC / "ir_official" / "4Q25_ppt.txt", "Given we see high"), "公司",
         "Given we see high return opportunities from investing in AI, we will likely buy back lower value of our shares "
         "versus 2025 to fund investment in AI, while increasing our dividends",
         DATA_SRC / "ir_official" / "4Q25_ppt.txt", "ppt4q25", "公开披露", None,
         "截至 10-15，2026 年累计回购 %.2f 亿港元，为 2025 全年的 %.1f%%（计算）" % (tot_amt / 1e8, tot_amt / fy25_amt * 100)),
        ("2026-03-18", "2025 Q4 业绩会", "John Lo（CFO）",
         "For the full year of 2025, we repurchased 153 million shares with a total consideration of HKD 80 billion.",
         tdir / "q4-2025.json", "tr4q25", "公开披露", TR, None),
        ("2026-03-18", "2025 Q4 业绩会", "John Lo（CFO）",
         "Given we see high return opportunities from investing in AI, we will likely buy back lower value of our shares "
         "versus 2025 to fund investment in AI while increasing our dividends.", tdir / "q4-2025.json", "tr4q25", "公开披露", TR,
         None),
        ("2026-05-13", "1Q26 业绩 PPT 第 %s 页" % slide_of(DATA_SRC / "ir_official" / "1Q26_ppt.txt", "Repurchased ~13"), "公司",
         "Repurchased ~13 million shares for a consideration of ~RMB6.7 billion during 1Q26",
         DATA_SRC / "ir_official" / "1Q26_ppt.txt", "ppt1q26", "公开披露", None,
         "翌日披露报表 1Q26 合计 %s 股 / %.2f 亿港元（计算）" % (format(q1[0], ","), q1[1] / 1e8)),
        ("2026-05-13", "2026 Q1 业绩会", "John Lo（CFO）",
         "partly offset by share repurchase of RMB 7.9 billion", tdir / "q1-2026.json", "tr1q26", "公开披露", TR,
         "与 PPT\"~RMB6.7 billion\"数值不同：二者口径（净现金变动中的回购支出 vs 季度回购代价）材料未说明，由财务按惯例确认"),
        ("2026-05-13", "2026 Q1 业绩会（分析师提问）", "William Packer（BNP Paribas）",
         "Could you talk through any implications for the share buyback in the second half of the year?",
         tdir / "q1-2026.json", "tr1q26", "公开披露", "第三方文字稿，待录音复核", None),
        ("2026-05-13", "2026 Q1 业绩会", "James Mitchell（首席战略官）",
         "We're accelerating the process of liquidizing some of that investment portfolio. That would enable us to sustain "
         "buybacks going through the rest of this year.", tdir / "q1-2026.json", "tr1q26", "公开披露", TR, None),
        ("2026-08-12", "2Q26 业绩 PPT 第 %s 页" % slide_of(DATA_SRC / "ir_official" / "2Q26_ppt.txt", "Repurchased ~37"), "公司",
         "Repurchased ~37 million shares for a consideration of ~RMB14.7 billion and paid cash dividend of ~RMB41.6 billion "
         "during 2Q26", DATA_SRC / "ir_official" / "2Q26_ppt.txt", "ppt2q26", "公开披露", None,
         "翌日披露报表 2Q26 合计 %s 股 / %.2f 亿港元；中报 4–6 月合计一致（计算）" % (format(q2[0], ","), q2[1] / 1e8)),
        ("2026-08-12", "2026 Q2 业绩会（分析师提问）", "Alex Liu（Bank of America）",
         "We noted that Tencent has recently increased the buyback. The buyback activity started from May.",
         tdir / "q2-2026.json", "tr2q26", "公开披露", "第三方文字稿，待录音复核", None),
        ("2026-08-12", "2026 Q2 业绩会", "James Mitchell（首席战略官）",
         "then we will steer more cash toward the capital expenditures than we had in the past, and therefore, potentially "
         "less cash toward buybacks. It will be a dynamic situation.", tdir / "q2-2026.json", "tr2q26", "公开披露", TR, None),
    ]
    statements = []
    bad_q = []
    for date, where, who, quote, path, skey, lab, caveat, check in stm:
        enc = "latin-1" if str(path).endswith("_ppt.txt") else "utf-8"
        ok = check_quote(path, quote, enc)
        if not ok:
            bad_q.append(quote[:40])
        statements.append({"date": date, "where": where, "speaker": who, "quote_en": quote, "verified_in_local_source": ok,
                           "local_source": rel(path), "src": S(skey), "label": lab, "tier": SOURCES[int(SRC[skey][1:]) - 1]["tier"],
                           "caveat": caveat, "cross_check": check})
    chk("已公开表述索引：%d 条引语均可在本地原文中逐字检索到" % len(stm), not bad_q, bad_q)
    so_days = [d for d in days_sorted if d[:7] in ("2026-09", "2026-10")]
    sep_oct_avg_yi = yi(sum(daily[d]["amount"] for d in so_days) / len(so_days)) if so_days else 0
    to_confirm = [
        {"item": "Q3 业绩材料如披露季度回购，与翌日披露报表计算值核对：7-01 至 9-30 共 %d 个交易日、%s 股、%.2f 亿港元（计算）" % (
            q3[2], format(q3[0], ","), q3[1] / 1e8), "src": S("nddr"), "label": "计算"},
        {"item": "1Q26 PPT\"~RMB6.7 billion\"与业绩会 CFO\"RMB 7.9 billion\"的口径差异是否需要统一说明（暂无已公开表述（工具只标注，不建议口径））",
         "src": S("ppt1q26", "tr1q26"), "label": "公开披露"},
        {"item": "2026 年回购节奏（截至 %s 累计约为 2025 全年 %.1f%%；9–10 月有回购交易日日均约 %.2f 亿港元）与\"likely buy back lower value ... "
                 "versus 2025\"、\"sustain buybacks going through the rest of this year\"等已公开表述的衔接——暂无已公开表述（工具只标注，不建议口径）"
                 % (last_bb_all, tot_amt / fy25_amt * 100, sep_oct_avg_yi), "src": S("nddr", "ar25", "ppt4q25", "tr1q26"),
         "label": "计算"},
        {"item": "规则窗口结束（业绩公告日 11-18）后是否恢复回购：只做监测，不作预测", "src": S("gl117", "bm0924"), "label": "计算"}]
    for a_ in anomalies:
        to_confirm.append({"item": "公司已刊发的 %s 翌日披露报表数值不自洽（总代价÷股数 %.4f 港元，不在所报最高/最低价 %s–%s 区间内），"
                                   "需公司秘书/IR 核对原件是否需要更正（只提示，不推断原因）" % (a_["date"], a_["vwap_calc"], a_["low"], a_["high"]),
                           "src": S("nddr"), "label": "计算"})

    # ---------------- 告警规则示例（只读监测）
    recent_to = [t for t in turnover if t["net_hkd"] is not None][-20:]
    a1 = [{"trade_date": t["trade_date"], "net_yi": t["net_yi"]} for t in recent_to if t["net_hkd"] <= -1e9]
    recent_sb = series[-60:]
    a2 = [{"date": r["date"], "d_pp": r.get("d_pp"), "d_shares": r.get("d_shares")} for r in recent_sb
          if r.get("d_pp") is not None and abs(r["d_pp"]) >= 0.05]
    streak = 0
    for r in reversed(series):
        if (r.get("d_shares") or 0) < 0:
            streak += 1
        else:
            break
    a6 = [m for m in ccass["top10_movers_1w"] if abs(m["d_pct_of_issued"] or 0) >= 0.2]
    in_win_bb = [d for d in days_sorted if any(a <= d <= b for a, b in rw)]
    a4_from = (dt.date.fromisoformat(AS_OF) - dt.timedelta(days=30)).isoformat()
    alerts = {
        "disclaimer": "只读监测示意，不构成交易建议；阈值为演示用参数，可调整。",
        "evaluated_at": AS_OF, "data_as_of": last,
        "rules": [
            {"id": "A1", "name": "南向单日净卖出超阈值", "condition": "港交所十大成交活跃股口径：沪+深港通（买入−卖出）≤ −10 亿港元",
             "window": "最近 20 个有数据的成交日", "triggered": bool(a1), "hits": a1, "src": S("ds"), "label": "计算"},
            {"id": "A2", "name": "南向持股比例单日变动", "condition": "|持股比例日变动| ≥ 0.05 个百分点（页面公布值，两位小数）",
             "window": "最近 60 个交易日", "triggered": bool(a2), "hits": a2, "src": S("sb"), "label": "计算"},
            {"id": "A3", "name": "南向连续减持", "condition": "持股股数连续 ≥5 个交易日下降", "current_streak": streak,
             "triggered": streak >= 5, "src": S("sb"), "label": "计算"},
            {"id": "A4", "name": "主要股东权益变动", "condition": "DI 出现 Prosus N.V./Naspers/MIH 新申报（持股比例跨越整数百分比时须申报）",
             "window": "最近 30 个自然日（%s 起）" % a4_from,
             "last_filing": last_di["event_date"] if last_di else None, "last_pct": last_di["pct"] if last_di else None,
             "triggered": bool(last_di and last_di["event_date"] >= a4_from),
             "status": "自 %s 以来无新申报（检索时间 %s）" % (last_di["event_date"] if last_di else "-", di.get("fetched_at")),
             "src": S("di", "diform"), "label": "公开披露"},
            {"id": "A5", "name": "回购恢复", "condition": "港交所出现 %s 之后交易日的回购翌日披露报表" % last_bb_all,
             "triggered": bool(after_nddr), "hits": after_nddr, "checked_at": tsd.get("fetched_at") if tsd else None,
             "context": "规则窗口（计算）至业绩公告日 %s 止；是否恢复不作预测" % q3_board, "src": S("ts", "nddr"), "label": "公开披露"},
            {"id": "A6", "name": "CCASS 托管商周度大额变动", "condition": "单一参与者 1 周持股变动 ≥ 已发行股份 0.2%",
             "triggered": bool(a6), "hits": a6, "src": S("ccass"), "label": "计算"},
            {"id": "A7", "name": "规则窗口内出现回购披露（合规核对）", "condition": "回购日落在按第 10.06(2)(e) 条计算的规则窗口内",
             "triggered": bool(in_win_bb), "hits": in_win_bb, "src": S("nddr", "gl117"), "label": "计算"}],
        "delivery_idea": "WorkBuddy 定时任务每日 09:00 运行 holders.py --refresh，命中规则时推送卡片（实机未运行，本地 Python 产出）",
    }

    # ---------------- 用户提供的链接与本模块用途
    man = {}
    for line in (DATA_SRC / "ir_official" / "manifest.tsv").read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 4:
            man[p[3]] = p[2]
    tc_res = (MR / "idx" / "tc_res.html").read_text(encoding="utf-8", errors="ignore")
    ups = []
    user_links = [
        ("https://stockanalysis.com/quote/hkg/0700/transcripts/374535-q3-2025/", ["data/src/transcripts/374535-q3-2025.html",
         "data/parsed/q3-2025.json"], "tr3q25", "已公开表述索引：CFO 3Q25 回购现金支出 CNY 19.2bn（与 3Q25 PPT 交叉核对）"),
        ("https://stockanalysis.com/quote/hkg/0700/transcripts/419871-q4-2025/", ["data/src/transcripts/419871-q4-2025.html",
         "data/parsed/q4-2025.json"], "tr4q25", "已公开表述索引：FY25 回购 153M 股/800 亿港元；\"likely buy back lower value ... versus 2025\""),
        ("https://stockanalysis.com/quote/hkg/0700/transcripts/609405-q1-2026/", ["data/src/transcripts/609405-q1-2026.html",
         "data/parsed/q1-2026.json"], "tr1q26", "已公开表述索引：CFO RMB 7.9bn（与 PPT 口径差异列入待确认）；BNP 提问与 CSO\"sustain buybacks\"回答"),
        ("https://stockanalysis.com/quote/hkg/0700/transcripts/667897-q2-2026/", ["data/src/transcripts/667897-q2-2026.html",
         "data/parsed/q2-2026.json"], "tr2q26", "已公开表述索引：美银提问\"buyback activity started from May\"与 CSO\"potentially less cash toward buybacks\""),
        ("https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf",
         ["data/src/ir_official/3Q25_ppt.pdf", "data/src/ir_official/3Q25_ppt.txt"], "ppt3q25",
         "季度回购核对：3Q25 ~35M 股 vs 2025 年报 7–9 月 35,360,000 股"),
        ("https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf",
         ["data/src/ir_official/4Q25_ppt.pdf", "data/src/market_raw/res/2804dbdae364ca25b82d21bc8304f1d3.pdf"], "ppt4q25",
         "FY25 回购基数（~153M 股/~800 亿港元）与 2026 回购指引原话；用于\"2026 年累计/2025 全年\"追踪"),
        ("https://www.tencent.com/investors/results/", ["data/src/market_raw/idx/tc_res.html"], "irpage",
         "定位官方业绩材料：脚本核验该页含 3Q25、4Q25、2Q26 PPT 链接"),
        ("https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf",
         ["data/src/ir_official/2Q26_ppt.pdf", "data/src/ir_official/2Q26_ppt.txt"], "ppt2q26",
         "季度回购核对：2Q26 ~37M 股 vs 翌日披露报表/中报 4–6 月 37,381,100 股"),
    ]
    for url, paths, skey, use in user_links:
        recs = []
        for pth in paths:
            p = ROOT / pth
            recs.append({"path": pth, "sha256": sha256_file(p) if p.exists() else None, "exists": p.exists()})
        verify = None
        if "static.www.tencent.com" in url:
            fn = man.get(url)
            verify = {"manifest_maps_to": fn, "on_ir_results_page": url.split("/")[-1].split("_")[0][:20] in tc_res}
        elif "stockanalysis" in url:
            tid = url.rstrip("/").split("/")[-1]
            verify = {"local_html_has_id": (ROOT / paths[0]).exists() and tid in (ROOT / paths[0]).read_text(
                encoding="utf-8", errors="ignore")}
        ups.append({"canonical_url": url, "source_id": SRC[skey],
                    "local_files": recs, "verify": verify, "used_in_m3": use})
    chk("用户提供的 8 个链接均有本地副本并已在本模块使用", all(all(r["exists"] for r in u["local_files"]) for u in ups),
        [u["source_id"] for u in ups])

    # ---------------- headline cards
    sb_l = sb_by[last]
    ytd = southbound["changes"]["ytd_since_%s" % ye]
    headline = [
        {"key": "southbound_pct", "text": "南向持股 %.2f%%（%s 亿股），截至 %s" % (sb_l["pct"], round(sb_l["shares"] / 1e8, 2), last),
         "value": sb_l["pct"], "unit": "%", "as_of": last, "src": S("sb"), "label": "结构化数据"},
        {"key": "southbound_ytd", "text": "年初以来（%s 起）南向持股 %+.2f 个百分点（%s 股），估算净%s约 %.0f 亿港元（股数变化×推定成交日收盘价逐日加总）" % (
            ye, ytd["d_pp"], format(ytd["d_shares"], "+,"), "买入" if ytd["net_yi_est_sum"] >= 0 else "卖出", abs(ytd["net_yi_est_sum"])),
         "value": ytd["d_pp"], "unit": "pp", "as_of": last, "src": S("sb", "yahoo"), "label": "计算"}]
    if d1021:
        headline.append({"key": "southbound_1021", "text": "10-21 南向净卖出约 %.2f 亿港元（港交所十大成交活跃股买入−卖出）" % (-d1021["net_yi"]),
                         "value": d1021["net_yi"], "unit": "亿港元", "as_of": "2026-10-21", "src": S("ds"), "label": "计算"})
    headline += [
        {"key": "prosus", "text": "MIH（Prosus）持股 22.60%%（2026-06-30 中报）；最近一次 DI 申报 %s（%.2f%%）" % (
            last_di["event_date"], last_di["pct"]), "value": 22.60, "unit": "%", "as_of": "2026-06-30",
         "src": S("ir26", "di"), "label": "公开披露"},
        {"key": "buyback_badge", "text": buyback["badge"]["text"] + "（%d 个交易日、%s 股）" % (len(days_sorted), format(tot_sh, ",")),
         "value": yi(tot_amt), "unit": "亿港元", "as_of": last_bb_all, "src": S("nddr"), "label": "计算"},
        {"key": "last_buyback", "text": "最后一笔回购 %s（公开披露）；规则窗口自 %s 起（计算），原因未公开" % (
            last_bb_all, win_q3["rule_window"]["start"]), "value": last_bb_all, "as_of": AS_OF, "src": S("nddr", "gl117"),
         "label": "公开披露"}]

    # ---------------- assemble
    payload = {
        "meta": {"module": MODULE, "title": "M3 股东·资金·回购", "as_of": AS_OF, "generated_by": "本地 Python",
                 "script": "demo/pipeline/holders.py", "inputs": INPUTS,
                 "notes": "南向持股/CCASS/DI/港交所日统计/行情为脚本联网抓取并缓存于 demo/data/raw/m3/（再次运行默认读缓存）；"
                          "回购为 98 份翌日披露报表 PDF 原件逐份解析。行情：%s。水印：%s。" % (UNOFFICIAL_PX, WM),
                 "watermark": WM, "data_as_of": {"southbound": last, "ccass": max(cc) if cc else None,
                                                 "buyback_last": last_bb_all, "di_checked": di.get("fetched_at"),
                                                 "title_search_checked": tsd.get("fetched_at") if tsd else None},
                 "network": dict(NET)},
        "sources": SOURCES,
        "headline": headline,
        "southbound": southbound,
        "ccass": ccass,
        "major_holders": major,
        "buyback": buyback,
        "blackout": blackout,
        "disclosed_statements_index": {"title": "已公开表述索引：回购与资本回报（只给原话/出处/核查状态）", "items": statements,
                                       "to_confirm_by_management": to_confirm},
        "alerts": alerts,
        "user_provided_sources": ups,
    }
    # ---------------- 随机抽查（回到原始文件，独立提取路径）+ 结构校验
    spots = spot_checks(daily, days_sorted, ir_months, h26, statements, turnover, sb_by, last, mm_sh)
    val = validate(payload)
    checks.append({"check": "所有 label 取值均在 公开披露/结构化数据/计算/推断 之内", "pass": not val["bad_labels"],
                   "detail": val["bad_labels"][:5]})
    checks.append({"check": "所有 src 引用的来源 id 均存在于 sources", "pass": not val["bad_src"], "detail": val["bad_src"][:5]})
    checks.append({"check": "每个数字所在对象（或其上级对象）带 src", "pass": not val["numbers_without_src"],
                   "detail": "数值字段 %d 个；无 src 覆盖 %d 个：%s" % (val["numbers_total"], len(val["numbers_without_src"]),
                                                          val["numbers_without_src"][:5])})
    checks.append({"check": "无禁用词（颠覆/革命性/首创/全面领先/赋能/取代IR）", "pass": not val["banned_hits"],
                   "detail": val["banned_hits"]})
    checks.append({"check": "无股价/估值评论用语（市盈率/目标价/估值/低估/高估/undervalued 等）", "pass": not val["valuation_hits"],
                   "detail": val["valuation_hits"]})
    checks.append({"check": "不展示董事个人交易（产物中无 DI 董事申报表格编号 DA…）", "pass": not val["director_forms"],
                   "detail": val["director_forms"][:5]})
    text = json.dumps(payload, ensure_ascii=False)
    abs_path = re.search(r"[A-Za-z]:\\\\Users\\\\|/c/Users/|AppData", text)
    import getpass
    try:
        uname = getpass.getuser()
    except Exception:  # noqa: BLE001
        uname = ""
    uhit = bool(uname) and len(uname) >= 3 and uname.lower() in text.lower()
    checks.append({"check": "产物中无邮箱（除通用占位）、本机绝对路径、运行账户名", "pass": abs_path is None and not uhit,
                   "detail": "已扫描（账户名运行时读取比对，不写入代码与产物）"})
    assert_no_email(text)
    payload["meta"]["self_check"] = {
        "summary": {"checks_total": len(checks), "checks_passed": sum(1 for c in checks if c["pass"]),
                    "spot_total": len(spots), "spot_passed": sum(1 for s in spots if s["pass"])},
        "spot_checks": spots,
        "checks": checks,
        "method": "spot_checks：以固定种子随机抽取回购日/中报月度行/引语等，用与主流程不同的提取路径（PyMuPDF 读 PDF 原件、"
                  "去标签读原始 HTML）回到原始文件核对；checks：全量规则校验（对账、交叉核对、标签、来源、禁用词、隐私）。"}
    out = write_module(MODULE, payload)
    n_pass = sum(1 for c in checks if c["pass"])
    log("写出 %s；自检 %d/%d 通过；抽查 %d/%d 通过" % (rel(out), n_pass, len(checks),
                                              sum(1 for s in spots if s["pass"]), len(spots)))
    for c in checks:
        if not c["pass"]:
            log("  未通过：", c["check"], c["detail"])
    for s in spots:
        if not s["pass"]:
            log("  抽查未通过：", s)
    log("网络：", NET)


# ----------------------------------------------------------------------------- self-check helpers
BANNED = ("颠覆", "革命性", "首创", "全面领先", "赋能", "取代IR")
VALUATION = ("市盈率", "目标价", "估值", "低估", "高估", "undervalued", "price target", "P/E")


def _numset(text):
    out = set()
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            out.add(round(float(tok.replace(",", "")), 4))
        except ValueError:
            pass
    return out


def _mupdf_text(path):
    import pymupdf  # 仅自检使用（与主流程 pdftotext 不同的提取器）
    doc = pymupdf.open(stream=Path(path).read_bytes(), filetype="pdf")
    try:
        return re.sub(r"\s+", " ", "\n".join(pg.get_text() for pg in doc))
    finally:
        doc.close()


def _html_text(path):
    h = Path(path).read_text(encoding="utf-8", errors="ignore")
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return norm_ws(t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"'))


def spot_checks(daily, days_sorted, ir_months, h26, statements, turnover, sb_by, last, mm_sh):
    import random
    rng = random.Random("m3-holders-" + AS_OF)  # 固定种子：可重现的随机抽样
    spots = []

    def add(item, ok, expected, found_in, how):
        spots.append({"item": item, "pass": bool(ok), "expected": expected, "raw_file": found_in, "method": how})

    # 1) 回购：随机 5 个交易日，PyMuPDF 重新读取对应翌日披露报表 PDF 原件
    for d in sorted(rng.sample(days_sorted, min(5, len(days_sorted)))):
        r = daily[d]
        p = MR / "nddr" / r["file"]
        try:
            t = _mupdf_text(p)
            ns = _numset(t)
            ds = dt.date.fromisoformat(d)
            dstr = "%d %s %d" % (ds.day, MONTHS[ds.month - 1], ds.year)
            ok = dstr in t and all(round(float(v), 4) in ns for v in (r["shares"], r["high"], r["low"], r["amount"]))
        except Exception as e:  # noqa: BLE001
            ok, t = False, str(e)
        add("回购 %s：股数/最高价/最低价/金额" % d, ok,
            {"shares": r["shares"], "high": r["high"], "low": r["low"], "amount_hkd": r["amount"]}, rel(p),
            "PyMuPDF 提取 PDF 全文，核对日期字样与 4 个数值均出现")
    # 2) 中报月度回购表：随机 2 个月，PyMuPDF 读中报 PDF
    ir_pdf = MR / "dl" / "tc_ir26.pdf"
    try:
        ir_t = _mupdf_text(ir_pdf)
        ir_ns = _numset(ir_t)
    except Exception:  # noqa: BLE001
        ir_t, ir_ns = "", set()
    for m in sorted(rng.sample(ir_months, min(2, len(ir_months))), key=lambda x: x["month"]):
        ok = all(round(float(v), 4) in ir_ns for v in (m["shares"], m["high"], m["low"], m["amount"]))
        add("中报月度回购表 %s" % m["month"], ok, m, rel(ir_pdf), "PyMuPDF 提取中报 PDF，核对股数/最高/最低/金额")
    # 3) 主要股东：MIH 股数与比例
    ok = "MIH Internet Holdings B.V." in ir_t and h26["mih_shares"] in {int(x) for x in ir_ns if x == int(x)} and \
        ("%.2f%%" % h26["mih_pct"]) in ir_t
    add("中报主要股东 MIH 持股", ok, {"shares": h26["mih_shares"], "pct": h26["mih_pct"]}, rel(ir_pdf),
        "PyMuPDF 提取中报 PDF，核对股数与百分比字样")
    ok = h26["ads_shares"] in {int(x) for x in ir_ns if x == int(x)} and ("%.2f%%" % h26["ads_pct"]) in ir_t
    add("中报主要股东 Advance Data Services 持股", ok, {"shares": h26["ads_shares"], "pct": h26["ads_pct"]}, rel(ir_pdf),
        "PyMuPDF 提取中报 PDF，核对股数与百分比字样")
    # 4) 南向最新值 vs 上一轮保存的披露易页面原文
    mm = MR / "hkex" / "mm_hk.html"
    add("南向持股最新值（%s）" % last, sb_by.get(last, {}).get("shares") == mm_sh and mm_sh is not None,
        {"shares": sb_by.get(last, {}).get("shares"), "pct": sb_by.get(last, {}).get("pct")}, rel(mm),
        "与本地保存的披露易港股通持股页面（页面日期 2026-10-24，非交易日沿用 10-23 持股）比对")
    # 5) 港交所每日统计：随机 1 个本地原始 JS 文件
    loc = [t for t in turnover if (MR / "idx" / ("sc_%s.js" % t["trade_date"].replace("-", ""))).exists()]
    if loc:
        t = rng.choice(loc)
        p = MR / "idx" / ("sc_%s.js" % t["trade_date"].replace("-", ""))
        raw = p.read_text(encoding="utf-8")
        rows = re.findall(r'\["\d+",\s*"00700",\s*"[^"]*",\s*"([\d,]+)",\s*"([\d,]+)",\s*"([\d,]+)"\]', raw)
        vals = {(to_int(a), to_int(b)) for a, b, _ in rows}
        exp = [(t["sse_buy"], t["sse_sell"]), (t["szse_buy"], t["szse_sell"])]
        ok = all(e in vals for e in exp if e[0] is not None)
        add("港交所每日统计 %s 腾讯南向买入/卖出额" % t["trade_date"], ok,
            {"sse": exp[0], "szse": exp[1], "net_yi": t["net_yi"]}, rel(p), "正则直接读取原始 JS 中 00700 行")
    # 6) 引语：随机 3 条，回到原始 HTML（实录）或 PPT PDF 原件
    for s in rng.sample(statements, min(3, len(statements))):
        src_path = ROOT / s["local_source"]
        if s["local_source"].startswith("data/parsed/"):
            q = s["local_source"].split("/")[-1].replace(".json", "")
            cand = sorted((DATA_SRC / "transcripts").glob("*-%s.html" % q))
            raw_p = cand[0] if cand else src_path
            txt = _html_text(raw_p)
            how = "去标签读取实录原始 HTML，空白归一后逐字检索"
        else:
            raw_p = Path(str(src_path).replace(".txt", ".pdf"))
            txt = norm_ws(_mupdf_text(raw_p).replace("’", "'")) if raw_p.exists() else ""
            how = "PyMuPDF 读取 PPT PDF 原件，空白归一后逐字检索"
        qn = norm_ws(s["quote_en"].replace("’", "'"))
        add("引语（%s，%s）" % (s["date"], s["speaker"]), qn in txt, s["quote_en"][:80], rel(raw_p), how)
    return spots


def validate(payload):
    ids = {s["id"] for s in payload["sources"]}
    res = {"bad_labels": [], "bad_src": [], "numbers_without_src": [], "numbers_total": 0, "banned_hits": [],
           "valuation_hits": [], "director_forms": []}
    skip_top = {"meta", "sources", "user_provided_sources"}

    def walk(o, path, covered):
        if isinstance(o, dict):
            has = covered or ("src" in o) or ("field_labels" in o)
            if "src" in o:
                for sid in (o["src"] if isinstance(o["src"], list) else [o["src"]]):
                    if sid not in ids:
                        res["bad_src"].append("%s.src=%s" % (path, sid))
            for k, v in o.items():
                if k in ("label", "vwap_label", "delta_label") and isinstance(v, str) and v not in LABELS:
                    res["bad_labels"].append("%s.%s=%s" % (path, k, v))
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    res["numbers_total"] += 1
                    if not has:
                        res["numbers_without_src"].append("%s.%s" % (path, k))
                else:
                    walk(v, path + "." + k, has)
        elif isinstance(o, (list, tuple)):
            for i, v in enumerate(o):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    res["numbers_total"] += 1
                    if not covered:
                        res["numbers_without_src"].append("%s[%d]" % (path, i))
                else:
                    walk(v, "%s[%d]" % (path, i), covered)

    for k, v in payload.items():
        if k not in skip_top:
            walk(v, "$." + k, False)
    body = json.dumps({k: v for k, v in payload.items() if k != "meta"}, ensure_ascii=False)
    res["banned_hits"] = [w for w in BANNED if w in body]
    res["valuation_hits"] = [w for w in VALUATION if w in body]
    res["director_forms"] = sorted(set(re.findall(r"\bDA\d{8}E\d{5}\b", body)))
    return res


if __name__ == "__main__":
    main()
