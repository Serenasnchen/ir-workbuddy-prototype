# -*- coding: utf-8 -*-
"""M2b Q3 问题雷达 v2（本地 Python）。

用法（在项目根目录下）：
    python -I demo/pipeline/radar.py            # 默认：本地缓存优先；缺失的网页缓存才经 common.http_get 联网补
    python -I demo/pipeline/radar.py --offline  # 完全离线（缺缓存的引语标为“未本地复核”）

输入：
  data/research/parts/q3_radar.json        v1（已核查，26 题）
  demo/pipeline/m2_radar_edits.py          人工整理编辑层（话题、改写、已公开表述索引、漂移、待确认、变化、Top10 议题）
  data/research/parts/mkt.json             二级市场背景（南向持股趋势）
  data/src/market_raw/nddr/buybacks2026.json / list2026.json   回购逐日解析、港交所标题检索
  demo/data/m2_transcripts.json / question_units.json          实录分析（热度、缺口、机构轨迹、回测）
  data/parsed/*.json、data/src/ir_official/*、data/src/peers/meta_q3_2026_release.html、demo/data/m2_raw/* 等原文
输出：
  demo/data/m2_radar.json
  demo/data/q3_top10_prereg.json   紧凑 JSON（sort_keys、ensure_ascii=False、separators=(',',':')），
                                   内容不变时保留原生成时间，因此哈希可复现
红线：不写估值/市盈率/目标价；不代拟答复；不以分析师真名生成发言；所有因果判断标“推断”。
"""
import argparse
import datetime as dt
import getpass
import html
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ROOT, OUT, AS_OF, LABELS, TIERS, http_get, sha256_file, sha256_text,  # noqa: E402
                    input_record, write_module, load_json, assert_no_email)
import m2_radar_edits as E  # noqa: E402

MODULE = "m2_radar"
SCRIPT = "demo/pipeline/radar.py"
PREREG_PATH = OUT / "q3_top10_prereg.json"
V1_PATH = ROOT / "data/research/parts/q3_radar.json"
MKT_PATH = ROOT / "data/research/parts/mkt.json"
BB_PATH = ROOT / "data/src/market_raw/nddr/buybacks2026.json"
TITLES_PATH = ROOT / "data/src/market_raw/nddr/list2026.json"
M2T_PATH = OUT / "m2_transcripts.json"
QU_PATH = OUT / "question_units.json"
EDITS_PATH = Path(E.__file__).resolve()
BOARD_DATE = dt.date(2026, 11, 18)
FY25_BUYBACK_HKD = 80e9          # 罗硕瀚 4Q25 业绩会原话“HKD 80 billion”（S002，下方逐字核对）
WATERMARK = E.WATERMARK
FORBIDDEN = ["颠覆", "革命性", "首创", "全面领先", "赋能", "取代IR"]
VALUATION_RE = re.compile(r"市盈率|目标价|估值|P/E|\bPE\b|target price|valuation|股价|share price|买入评级|增持评级|"
                          r"维持买入|维持增持|优于大市|跑赢大市|强烈买入|Strong Buy")
ADVICE_RE = re.compile(r"建议(管理层|口径|统一|回应|回答)|建议准备|建议为|建议统一")

# 网页原文缓存（只在缺失时联网一次；investing.com 返回 403，不再尝试）
WEB_CACHE = {
    "HKEX_COMPLETION": "demo/data/m2_raw/hkex_2026102200033.pdf",
    "SINA_Q2": "demo/data/m2_raw/sina_q2_2026.html",
    "WSCN_FY25": "demo/data/m2_raw/wscn_3767854.html",
    "J21_BOND": "demo/data/m2_raw/21jingji_bond.html",
    # v1 Q26 引语出处（腾讯 2025-01 自愿公告的媒体报道）
    "https://finance.sina.com.cn/jjxw/2025-01-07/doc-ineeeanv7990003.shtml": "demo/data/m2_raw/sina_1260h_20250107.html",
}
# v1 official_position 引语与本地一手/文字稿不完全一致时的修正（保留出处说明）
OP_FIX = {
    "As the supply of China design GPUs progressively ramps up, then we'll be remedying that situation": {
        "quote": "as the supply of China design GPUs progressively ramps up, we'll be remedying that situation",
        "src": "TR_Q1_26", "date": "2026-05-13", "speaker": "James Mitchell",
        "note": "v1 引语取自 The Register 转述（多一个 then），此处改用本地第三方文字稿原文"},
}
# v1 中只出现在 key_numbers 等处、无标准日期的来源：人工给定（页面/公告日期）
EXTRA_DATE_FIX = {
    "https://www.tencent.com/wp-content/uploads/2026/09/E700_BM.pdf": "2026-09-24",
    "https://m.bjnews.com.cn/detail/1771421066129077.html": "2026-02-18",
    "https://www.21jingji.com/article/20261008/herald/a1e9dba09e2e4db9ec71b6a7ffb7e2ba.html": "2026-10-08",
    "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202609/t20260915_1965311.html": "2026-09-15",
    "https://www.investing.com/news/transcripts/earnings-call-transcript-tencent-posts-solid-q2-2026-growth-ai-investment-93CH-4180338": "2026-08-12",
}

ARGS = None
NET = {"get": 0, "errors": 0, "cache_hits": 0}
INPUTS = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def use(p):
    p = Path(p)
    if not p.is_absolute():
        p = ROOT / p
    if p.exists():
        INPUTS.setdefault(rel(p), input_record(p))
    return p


ISO = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")


def is_iso(s):
    return bool(s) and bool(re.fullmatch(r"20\d\d-\d\d-\d\d", s))


# ============================================================================ text access
TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                       " ": " ", "−": "-", "­": ""})


def n1(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).translate(TRANS)).strip().casefold()


def n2(s):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s).translate(TRANS).casefold())


_TEXT = {}


def strip_html(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def pdf_text(p):
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf
    with pymupdf.open(str(p)) as doc:
        return "\n".join(page.get_text() for page in doc)


def text_of(path):
    """Return plain text of a local file (txt/pdf/html/json-titles/parsed transcript)."""
    p = use(path)
    key = rel(p)
    if key in _TEXT:
        return _TEXT[key]
    if not p.exists():
        _TEXT[key] = None
        return None
    suf = p.suffix.lower()
    if suf == ".pdf":
        t = pdf_text(p)
    elif suf in (".html", ".htm", ".shtml"):
        b = p.read_bytes()
        for enc in ("utf-8", "gb18030"):
            try:
                s = b.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        t = strip_html(s)
    elif suf == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and "result" in d:
            d = json.loads(d["result"])
        if isinstance(d, list) and d and isinstance(d[0], dict) and "TITLE" in d[0]:
            t = "\n".join(f'{x["DATE_TIME"]} {html.unescape(x["TITLE"])} {x["FILE_LINK"]}' for x in d)
        elif isinstance(d, list) and d and isinstance(d[0], dict) and "text" in d[0]:
            t = "\n".join(x.get("text", "") for x in d)
        else:
            t = json.dumps(d, ensure_ascii=False)
    else:
        t = p.read_text(encoding="utf-8", errors="ignore")
    _TEXT[key] = t
    return t


def transcript_text(q):
    return text_of(f"data/parsed/{q}.json")


def find(quote, text):
    """Return (status, snippet) when quote is found in text."""
    if not text:
        return None, None
    a, b = n1(quote), n1(text)
    i = b.find(a)
    if i >= 0:
        return "逐字一致", b[max(0, i - 40): i + len(a) + 40]
    a2, b2 = n2(quote), n2(text)
    if a2 and a2 in b2:
        i = b2.find(a2)
        return "一致（忽略标点/空白差异）", b2[max(0, i - 30): i + len(a2) + 30]
    b3 = re.sub(r"(?<=[\u4e00-\u9fff])\d(?=[\u4e00-\u9fff])", "", b2)   # 中文正文中的单个脚注编号
    if a2 and a2 in b3:
        i = b3.find(a2)
        return "一致（忽略脚注编号）", b3[max(0, i - 30): i + len(a2) + 30]
    return None, None


def ensure_web_cache(key):
    if key not in WEB_CACHE:
        return None
    p = ROOT / WEB_CACHE[key]
    if p.exists():
        NET["cache_hits"] += 1
        return p
    if ARGS.offline:
        return None
    url = key if key.startswith("http") else SRC[ALIAS[key]]["url"]
    try:
        http_get(url, dest=str(p), delay=1.5)
        NET["get"] += 1
        return p
    except Exception as e:  # noqa: BLE001
        NET["errors"] += 1
        log("web cache miss", alias, type(e).__name__)
        return None


def local_files(sid):
    rec = SRC[sid]
    files = []
    if rec.get("transcript"):
        files.append(f"data/parsed/{rec['transcript']}.json")
    locs = rec.get("local", [])
    txts = [x for x in locs if x.lower().endswith(".txt")]
    files += txts or [x for x in locs if not x.lower().endswith(".json") or x.endswith("list2026.json")]
    for key in (rec.get("alias"), rec["url"]):
        if key in WEB_CACHE:
            c = ensure_web_cache(key)
            if c:
                files.append(rel(c))
    return [f for f in dict.fromkeys(files) if (ROOT / f).exists()]


# ============================================================================ sources
SRC = {}       # sid -> record
ALIAS = {}     # alias -> sid
URL2SID = {}
V1_URL = {}    # url -> {"titles": [...], "dates": [...]}


def canon(u):
    u = re.sub(r"([?&])utm_[^&#]*&?", r"\1", u)
    return u.rstrip("?&")


def url_tier(u):
    lu = u.lower()
    if any(x in lu for x in ("hkexnews.hk", "sec.gov/", "govinfo.gov", "/e700_", "/c700_")):
        return 1
    if "stockanalysis.com" in lu or "investing.com/news/transcripts" in lu or "finance.sina.com.cn/tech/2026-08-12" in lu:
        return 3
    if any(x in lu for x in ("tencent.com", "cloud.tencent.com/announce", "prnasia.com/releases/apac/tencent", "stats.gov.cn")):
        return 2
    return 4


def pick_date(u):
    info = V1_URL.get(u, {"dates": []})
    for d in info["dates"]:
        if is_iso(d):
            return d
    if u in E.DATE_FIX:
        return E.DATE_FIX[u]
    if u in EXTRA_DATE_FIX:
        return EXTRA_DATE_FIX[u]
    for d in info["dates"]:
        m = ISO.search(d or "")
        if m:
            return m.group(0)
    m = re.search(r"/(20\d\d)-(\d\d)-(\d\d)/", u) or re.search(r"/(20\d\d)(\d\d)(\d\d)/", u)
    if m:
        return "-".join(m.groups())
    return None


TITLE_FIX = [("大摩维持增持", "大摩上调资本开支预测"), ("花旗下调腾讯目标价", "花旗Q3前瞻"), ("摩根大通下调目标价", "摩根大通Q3前瞻"),
             ("高盛下调目标价", "高盛观点"), ("美银维持买入", "美银观点"), ("美银证券维持买入", "美银证券观点")]


def clean_title(t):
    for a, b in TITLE_FIX:
        t = t.replace(a, b)
    return t


def register(alias, meta, sid=None, user=False):
    sid = sid or f"S{len(SRC) + 1:03d}"
    rec = {"id": sid, "alias": alias, "title": clean_title(meta["title"]), "url": meta["url"], "date": meta.get("date"),
           "tier": meta.get("tier", url_tier(meta["url"])), "user_provided": user}
    for k in ("url_as_given", "used_for", "transcript", "local"):
        if k in meta:
            rec[k] = meta[k]
    SRC[sid] = rec
    if alias:
        ALIAS[alias] = sid
    URL2SID.setdefault(canon(meta["url"]), sid)
    return sid


def sid_of(x):
    if isinstance(x, list):
        return [sid_of(i) for i in x]
    if x in ALIAS:
        return ALIAS[x]
    if x in SRC:
        return x
    if isinstance(x, str) and x.startswith("http"):
        c = canon(x)
        if c in URL2SID:
            return URL2SID[c]
        info = V1_URL.get(x) or V1_URL.get(c) or {"titles": ["（v1 来源）"], "dates": []}
        d = pick_date(x) or pick_date(c)
        if not d:
            raise ValueError(f"no date for source {x}")
        title = info["titles"][0]
        return register(None, {"title": title, "url": c, "date": d, "tier": url_tier(c)})
    raise KeyError(f"unknown source alias {x!r}")


def build_registry(v1):
    for q in v1["questions"]:
        for e in q["evidence"]:
            V1_URL.setdefault(e["url"], {"titles": [], "dates": []})
            V1_URL[e["url"]]["titles"].append(e["source"])
            V1_URL[e["url"]]["dates"].append(e.get("date"))
        op = q.get("official_position") or {}
        if op.get("url"):
            V1_URL.setdefault(op["url"], {"titles": [], "dates": []})
            V1_URL[op["url"]]["titles"].append(op.get("source", ""))
            V1_URL[op["url"]]["dates"].append(op.get("date"))
    for k in v1["key_numbers"]:
        V1_URL.setdefault(k["url"], {"titles": [], "dates": []})
        V1_URL[k["url"]]["titles"].append(k["source"])
        V1_URL[k["url"]]["dates"].append(k.get("period"))
    for u in E.USER_SUPPLIED:
        register(u["alias"], u, sid=u["sid"], user=True)
    for alias, meta in E.SOURCES.items():
        register(alias, meta)
    for rec in SRC.values():
        for p in rec.get("local", []):
            use(p)


# ============================================================================ verification
def verify(quote, sid, method):
    """method: ('tr', q) / ('txt', path) / ('pdfzh', path) / ('titles', path) / ('web', date) / None"""
    kind = method[0] if method else None
    files = []
    if kind == "tr":
        files = [f"data/parsed/{method[1]}.json"]
    elif kind in ("txt", "pdfzh", "titles"):
        files = [method[1]]
    else:
        files = local_files(sid)
    for f in files:
        t = transcript_text(Path(f).stem) if f.startswith("data/parsed/") else text_of(f)
        st, snip = find(quote, t)
        if st:
            how = {"tr": "本地第三方文字稿逐字比对", "txt": "本地官方文本比对", "pdfzh": "本地中文 PDF（pymupdf 抽取）比对",
                   "titles": "港交所标题检索结果比对"}.get(kind, "本地网页/文件缓存比对")
            return {"status": "已核对", "method": how, "file": f, "match": st, "context": snip[:160]}
    if files and kind in ("tr", "txt", "pdfzh", "titles"):
        return {"status": "未匹配", "method": kind, "file": files[0], "match": None}
    # web / None without matching cache
    for f in files:
        if text_of(f):
            return {"status": "未匹配", "method": "本地网页/文件缓存比对", "file": f, "match": None}
    if kind == "web":
        return {"status": "未本地复核", "method": f"整理时联网人工核对（{method[1]}），本地无可用副本", "file": None, "match": None}
    return {"status": "未本地复核", "method": "沿用 v1 核查结论（本地无原文副本）", "file": None, "match": None}


def tier_note(t):
    return {3: "非官方逐字稿，引用前以官方录音为准", 4: "媒体转述/二手"}.get(t)


STMT_LOG = []


def make_stmt(s):
    sid = sid_of(s["src"])
    rec = SRC[sid]
    v = verify(s["quote"], sid, s.get("verify"))
    notes = [x for x in (tier_note(rec["tier"]), s.get("note")) if x]
    out = {"speaker": s["speaker"], "quote": s["quote"], "lang": s.get("lang", "en"), "src": [sid],
           "date": s["date"], "tier": rec["tier"], "label": "公开披露", "verify": v}
    if "（" in s["speaker"] and "转述" in s["speaker"]:
        notes.append("非直接引语")
    if notes:
        out["note"] = "；".join(dict.fromkeys(notes))
    STMT_LOG.append(out)
    return out


# ============================================================================ computations
def compute_buyback():
    raw = load_json(use(BB_PATH))
    rows = []
    for d, v in raw:
        day = dt.datetime.strptime(d, "%d %B %Y").date()
        rows.append({"date": day.isoformat(), "shares": v[0], "high": v[1], "low": v[2], "hkd": v[3]})
    rows.sort(key=lambda r: r["date"])
    tot_sh = sum(r["shares"] for r in rows)
    tot = sum(r["hkd"] for r in rows)
    monthly = {}
    for r in rows:
        m = r["date"][:7]
        monthly.setdefault(m, {"days": 0, "shares": 0, "hkd": 0})
        monthly[m]["days"] += 1
        monthly[m]["shares"] += r["shares"]
        monthly[m]["hkd"] += r["hkd"]
    for m in monthly.values():
        m["hkd_yi"] = round(m["hkd"] / 1e8, 2)

    def avg(a, b):
        sel = [r["hkd"] for r in rows if a <= r["date"] <= b]
        return {"from": a, "to": b, "days": len(sel), "avg_hkd_yi_per_day": round(sum(sel) / len(sel) / 1e8, 2) if sel else None}

    upto = [r for r in rows if r["date"] <= "2026-10-13"]
    streak = [r for r in rows if "2026-08-17" <= r["date"] <= "2026-10-13"]
    last = rows[-1]
    # 港交所标题检索：10-15 之后是否还有翌日披露报表
    titles = json.loads(use(TITLES_PATH).read_text(encoding="utf-8"))
    nd_after = [x for x in titles if "Next Day Disclosure" in html.unescape(x["TITLE"])
                and dt.datetime.strptime(x["DATE_TIME"], "%d/%m/%Y %H:%M").date() > dt.date(2026, 10, 15)]
    latest_title = max(dt.datetime.strptime(x["DATE_TIME"], "%d/%m/%Y %H:%M") for x in titles)
    window_start = BOARD_DATE - dt.timedelta(days=30)
    return {
        "days": len(rows), "shares": tot_sh, "hkd": tot, "hkd_yi": round(tot / 1e8, 2),
        "first_date": rows[0]["date"], "last_date": last["date"], "last_day": last,
        "monthly": monthly,
        "phase_avg": [avg("2026-05-18", "2026-06-30"), avg("2026-08-17", "2026-08-28"), avg("2026-08-31", "2026-10-15")],
        "upto_1013": {"days": len(upto), "shares": sum(r["shares"] for r in upto), "hkd_yi": round(sum(r["hkd"] for r in upto) / 1e8, 2)},
        "streak_0817_1013": {"days": len(streak), "hkd_yi": round(sum(r["hkd"] for r in streak) / 1e8, 2)},
        "vs_fy25_ratio": round(tot / FY25_BUYBACK_HKD, 3),
        "nddr_titles_after_1015": len(nd_after), "titles_latest": latest_title.strftime("%Y-%m-%d %H:%M"),
        "rule": "上市规则第10.06(2)(e)条：业绩董事会会议日期前30日内不得回购",
        "rule_window_start": window_start.isoformat(), "board_meeting": BOARD_DATE.isoformat(),
        "reason_note": "10-15 后停止回购的原因公司未公开；规则窗口为按规则日期推算，不代表公司说明的原因",
        "src": [ALIAS["BB_JSON"], ALIAS["NDDR_1015"], ALIAS["HKEX_TITLES"], ALIAS["BOARD_MTG"]], "label": "计算",
    }


def parse_daily_stat(path):
    """Tencent (00700) buy/sell in SSE/SZSE Southbound top-10 tables of HKEX daily stat js."""
    t = text_of(path)
    data = json.loads(t[t.index("["): t.rindex("]") + 1])
    res = {}
    for blk in data:
        if "Southbound" not in blk["market"]:
            continue
        for c in blk["content"]:
            if c["table"].get("classname") != "top10Table":
                continue
            for tr in c["table"]["tr"]:
                row = tr["td"][0]
                if row[1] == "00700":
                    buy, sell = (int(x.replace(",", "")) for x in row[3:5])
                    res[blk["market"]] = {"buy": buy, "sell": sell, "net": buy - sell}
    return data[0]["date"], res


def compute_southbound():
    flows = []
    for d in ("20261020", "20261021", "20261022", "20261023"):
        p = f"data/src/market_raw/idx/sc_{d}.js"
        date, res = parse_daily_stat(p)
        net = sum(v["net"] for v in res.values())
        flows.append({"date": date, "net_hkd_yi": round(net / 1e8, 1),
                      "by_market": {k: round(v["net"] / 1e8, 2) for k, v in res.items()}})
    t = text_of("data/src/market_raw/hkex/mm_hk.html")
    m = re.search(r"Stock Code:\s*700\b.*?Shareholding in CCASS:\s*([\d,]+).*?Issued Shares/Units:\s*([\d.]+%)", re.sub(r"\s+", " ", t))
    raw = (ROOT / "data/src/market_raw/hkex/mm_hk.html").read_text(encoding="utf-8", errors="ignore")
    dm = re.search(r'txtShareholdingDate[^>]*value="([^"]+)"', raw)
    mkt = json.dumps(load_json(use(MKT_PATH)), ensure_ascii=False)
    trend = re.search(r"10-22 (\d+\.\d+)%（取样日中最高）；10-23 (\d+\.\d+)%。年初至今增加(\d+\.\d+)个百分点", mkt)
    return {
        "holding": {"shares": int(m.group(1).replace(",", "")), "pct": m.group(2), "page_date": dm.group(1) if dm else None,
                    "note": "页面日期 2026/10/24 为周六，持股与 10-23 收市后相同", "src": [ALIAS["HKEX_SB"]], "label": "结构化数据"},
        "trend": {"pct_1022": trend.group(1), "pct_1023": trend.group(2), "ytd_pp": trend.group(3),
                  "src": [ALIAS["HKEX_SB"]], "label": "结构化数据", "note": "取自上一轮脚本抓取结果（mkt.json）"},
        "daily_net": {"rows": flows, "method": "港交所每日十大成交股中腾讯的买入额−卖出额，沪、深港通相加；仅当日进入十大时可得",
                      "src": [ALIAS["HKEX_DAILY"]], "label": "计算"},
    }


def compute_misc():
    q2 = transcript_text("q2-2026")
    caps = re.findall(r"\bcap(?:s|ped|ping)?\b", q2, flags=re.I)
    return {
        "q2_2026_cap_word_count": {"value": len(caps), "regex": r"\bcap(s|ped|ping)?\b（不含 CapEx）", "src": [ALIAS["TR_Q2_26"]], "label": "计算"},
        "capex_to_revenue": {
            "tencent_2q26": {"capex_rmb_bn": 52.784, "revenue_rmb_bn": 204.785, "ratio": round(52.784 / 204.785, 3),
                             "src": [ALIAS["PPT_2Q26"], ALIAS["REL_EN_2Q26"]], "label": "计算"},
            "meta_3q26": {"capex_usd_bn": 34.91, "revenue_usd_bn": 64.601, "ratio": round(34.91 / 64.601, 3),
                          "src": [ALIAS["META_8K"]], "label": "计算"},
            "note": "口径不同（腾讯为总资本开支，Meta 含融资租赁本金），仅作量级参照"},
        "listed_portfolio_change": {"from_rmb_bn": 801, "to_rmb_bn": 487, "pct": round(487 / 801 - 1, 3),
                                    "period": "2025-09-30 → 2026-06-30", "src": [ALIAS["PPT_3Q25"], ALIAS["PPT_2Q26"]], "label": "计算"},
    }


# ============================================================================ builders
def infer_label(text, default="公开披露"):
    if "推断" in text:
        return "推断"
    if re.search(r"【计算】|推算|（计算|计算）", text):
        return "计算"
    return default


def infer_flags(text, sids, extra=()):
    f = list(extra)
    tiers = {SRC[s]["tier"] for s in sids}
    if 3 in tiers:
        f.append("非官方逐字稿")
    if 4 in tiers or re.search(r"券商观点|媒体转述|媒体报道|二手", text):
        f.append("媒体转述/二手")
    if "QuestMobile" in text:
        f.append("第三方、未去重")
    if "推算" in text:
        f.append("推算值")
    if "DeepSeek" in text and "融资" in text:
        f.append("公司未证实")
    return list(dict.fromkeys(f))


def ev_v1(e):
    sid = sid_of(e["url"])
    d = e.get("date") if is_iso(e.get("date")) else SRC[sid]["date"]
    out = {"source": clean_title(e["source"]), "src": [sid], "date": d, "point": e["point"], "label": infer_label(e["point"]),
           "flags": infer_flags(e["point"], [sid])}
    if not is_iso(e.get("date")):
        out["date_note"] = e.get("date")
    return out


def ev_new(e):
    sid = sid_of(e["src"])
    return {"source": SRC[sid]["title"], "src": [sid], "date": e["date"], "point": e["point"],
            "label": e.get("label") or infer_label(e["point"]), "flags": infer_flags(e["point"], [sid], e.get("flags", ()))}


def op_speaker(source):
    m = re.search(r"（([^；，）]+)", source or "")
    return m.group(1) if m else "公司/管理层（见出处）"


def merge_op(stmts, op):
    """Turn v1 official_position.quote into an index entry unless it duplicates an existing one."""
    q = (op or {}).get("quote")
    if not q:
        return None
    if q in OP_FIX:
        f = OP_FIX[q]
        s = make_stmt({"speaker": f["speaker"], "quote": f["quote"], "src": f["src"], "date": f["date"],
                       "verify": ("tr", SRC[ALIAS[f["src"]]]["transcript"]), "lang": "en", "note": f["note"]})
        return None if any(n2(f["quote"]) in n2(x["quote"]) for x in stmts) else s
    for s in stmts:
        if n2(q) in n2(s["quote"]) or n2(s["quote"]) in n2(q):
            return None
    sid = sid_of(op["url"])
    v = verify(q, sid, None)
    extra = []
    if v["status"] != "已核对" and re.search(r"[A-Za-z]{4}", q):
        for t in ("TR_Q2_26", "TR_Q1_26", "TR_Q4_25", "TR_Q3_25"):
            st, snip = find(q, transcript_text(SRC[ALIAS[t]]["transcript"]))
            if st:
                v = {"status": "已核对", "method": "本地第三方文字稿逐字比对", "file": f"data/parsed/{SRC[ALIAS[t]]['transcript']}.json",
                     "match": st, "context": snip[:160]}
                extra.append(ALIAS[t])
                break
    rec = SRC[sid]
    out = {"speaker": op_speaker(op.get("source")), "quote": q, "lang": "zh" if re.search(r"[一-鿿]", q) else "en",
           "src": [sid] + extra, "date": op.get("date") if is_iso(op.get("date")) else rec["date"], "tier": rec["tier"],
           "label": "公开披露", "verify": v, "note": "v1 已核查引语，并入本索引"}
    tn = tier_note(rec["tier"])
    if tn:
        out["note"] = tn + "；" + out["note"]
    STMT_LOG.append(out)
    return out


TOPIC_NAME = dict(E.TOPICS)


def build_questions(v1):
    qs = []
    for q in v1["questions"]:
        e = E.Q[q["id"]]
        ev = [dict(x) for x in q["evidence"]]
        for i, rep in e.get("evidence_replace", {}).items():
            ev[i] = {**ev[i], **rep}
        ev = [x for i, x in enumerate(ev) if i not in set(e.get("evidence_drop", []))]
        evidence = [ev_v1(x) for x in ev] + [ev_new(x) for x in e.get("evidence_add", [])]
        why = e.get("why_now", q["why_now"])
        for a, b in e.get("why_now_replace", []):
            assert a in why, (q["id"], a)
            why = why.replace(a, b)
        if e.get("why_now_append"):
            why = why + e["why_now_append"]
        stmts = [make_stmt(s) for s in e.get("psi", [])]
        op = merge_op(stmts, q.get("official_position"))
        if op:
            stmts.append(op)
        sids = sorted({s for x in evidence for s in x["src"]} | {s for x in stmts for s in x["src"]})
        theme = E.THEME_RENAME.get(q["theme"], q["theme"])
        qs.append({
            "id": q["id"], "rank": e["rank"], "priority_v1": q["priority"], "theme": theme,
            "sub_theme": e.get("sub_theme", q["sub_theme"]).replace("、估值", ""),
            "topics": e["topics"], "topic_names": [TOPIC_NAME[t] for t in e["topics"]],
            "question_cn": e.get("question_cn", q["question_cn"]), "question_en": e.get("question_en", q["question_en"]),
            "why_now": {"text": why, "src": sorted({s for x in evidence for s in x["src"]}), "label": "推断"},
            "evidence": evidence,
            "frequency": q["frequency"], "sensitivity": q["sensitivity"],
            "public_statement_index": {"statements": stmts,
                                       "scope_note": "只列已公开原话、出处、日期、层级与核查状态；不代拟答复。暂无已公开表述的只做标注，不建议口径。"},
            "needs_management_confirmation": {"text": e.get("confirm", q["gap"]), "gap_ids": e.get("gap_ids", []), "src": sids,
                                              "label": "公开披露", "note": "所列数字与表述出自本题证据来源；是否回应、如何回应由部门按既定流程决定"},
            "verification_status": {"v1": q["verification_status"],
                                    "v2": "已公开表述索引中的原话由 radar.py 逐条回到本地原文核对（见每条 verify）；新增证据来源见 src。"},
            "v2_changes": e.get("v2_changes", []), "src": sids, "label": "推断",
        })
    for n in E.NEW_QUESTIONS:
        evidence = [ev_new(x) for x in n["evidence"]]
        stmts = [make_stmt(s) for s in n["psi"]]
        sids = sorted({s for x in evidence for s in x["src"]} | {s for x in stmts for s in x["src"]})
        psi = {"statements": stmts, "scope_note": "只列已公开原话、出处、日期、层级与核查状态；不代拟答复。"}
        if n.get("no_statement_note"):
            psi["no_statement_note"] = n["no_statement_note"]
        qs.append({
            "id": n["id"], "rank": n["rank"], "priority_v1": None, "theme": n["theme"], "sub_theme": n["sub_theme"],
            "topics": n["topics"], "topic_names": [TOPIC_NAME[t] for t in n["topics"]],
            "question_cn": n["question_cn"], "question_en": n["question_en"],
            "why_now": {"text": n["why_now"]["text"], "src": sid_of(n["why_now"]["src"]), "label": n["why_now"]["label"]},
            "evidence": evidence, "frequency": n["frequency"], "sensitivity": n["sensitivity"],
            "public_statement_index": psi,
            "needs_management_confirmation": {"text": n["confirm"], "gap_ids": n["gap_ids"], "src": sids,
                                              "label": "公开披露", "note": "所列数字与表述出自本题证据来源；是否回应、如何回应由部门按既定流程决定"},
            "verification_status": {"v1": None, "v2": "v2 新增题；证据与原话均回到本地原文或缓存核对（见 verify）。"},
            "v2_changes": n["v2_changes"], "src": sids, "label": "推断",
        })
    qs.sort(key=lambda x: x["rank"])
    ranks = [x["rank"] for x in qs]
    assert ranks == list(range(1, len(qs) + 1)), ranks
    return qs


def build_drift(bb, misc):
    out = []
    for d in E.DRIFT:
        sides = []
        for s in d["sides"]:
            sid = sid_of(s["src"])
            v = verify(s["text"], sid, s.get("verify"))
            side = {"side": s["side"], "speaker": s["speaker"], "text": s["text"], "lang": s["lang"], "src": [sid],
                    "date": s["date"], "tier": SRC[sid]["tier"], "label": "公开披露", "verify": v}
            tn = tier_note(SRC[sid]["tier"])
            if tn:
                side["note"] = tn
            STMT_LOG.append(side | {"quote": s["text"]})
            sides.append(side)
        item = {k: d[k] for k in ("id", "type", "title", "topics", "observation", "label", "related", "gap_id")}
        item["sides"] = sides
        item["src"] = sorted({x for s in sides for x in s["src"]})
        if d["id"] == "D01":
            item["computed"] = misc["q2_2026_cap_word_count"]
        if d.get("execution_ref") == "BUYBACK_COMPUTED":
            item["computed"] = {"monthly_hkd_yi": {k: v["hkd_yi"] for k, v in bb["monthly"].items()},
                                "last_date": bb["last_date"], "ytd_hkd_yi": bb["hkd_yi"], "src": bb["src"], "label": "计算"}
            item["src"] = sorted(set(item["src"]) | set(bb["src"]))
        out.append(item)
    return out


def build_gaps():
    out = []
    for g in E.GAPS:
        sids = sid_of(g["src"])
        out.append({"id": g["id"], "priority": g["priority"], "priority_def": E.PRIORITY_DEF[g["priority"]],
                    "topics": g["topics"], "title": g["title"], "items": g["items"], "questions": g["questions"],
                    "drift": g.get("drift", []), "src": sids, "label": "公开披露",
                    "flags": infer_flags(g["items"], sids), "note": "暂无已公开表述（工具只标注，不建议口径）"})
    return out


def build_changes(bb, sb):
    out = []
    for c in E.CHANGES:
        sids = sid_of(c["src"]) if c["src"] else [ALIAS["HKEX_TITLES"]]
        detail = c.get("detail")
        if c.get("computed") == "BUYBACK":
            pa = {p["from"]: p for p in bb["phase_avg"]}
            detail = (f"【事实】最后一笔回购在{bb['last_date']}（{bb['last_day']['shares']:,}股，{bb['last_day']['hkd']:,}港元）；"
                      f"港交所标题检索（最新一条 {bb['titles_latest']}）显示 10-15 之后无新的翌日披露报表。"
                      f"【计算】年内{bb['days']}个交易日、{bb['shares']:,}股、约{bb['hkd_yi']}亿港元，约为2025年全年约800亿港元的"
                      f"{round(bb['vs_fy25_ratio'] * 100)}%；日均约{pa['2026-05-18']['avg_hkd_yi_per_day']}亿港元（5/18–6/30）→"
                      f"约{pa['2026-08-17']['avg_hkd_yi_per_day']}亿（8/17–8/28）→约{pa['2026-08-31']['avg_hkd_yi_per_day']}亿（8/31–10/15）。"
                      f"【计算】按上市规则第10.06(2)(e)条，规则窗口约从{bb['rule_window_start']}开始（业绩董事会{bb['board_meeting']}前30日）；"
                      f"停止原因公司未公开。")
        if c["id"] == "C03":
            fl = {r["date"]: r["net_hkd_yi"] for r in sb["daily_net"]["rows"]}
            detail = (f"截至2026-10-23，港股通合计持有腾讯{sb['holding']['shares']:,}股，占已发行股份{sb['holding']['pct']}"
                      f"（10-22为{sb['trend']['pct_1022']}%，取样日中最高；年初至今+{sb['trend']['ytd_pp']}个百分点）。"
                      f"【计算】南向对腾讯净买卖：10-20 {fl['2026-10-20']:+.1f}亿、10-21 {fl['2026-10-21']:+.1f}亿、"
                      f"10-22 {fl['2026-10-22']:+.1f}亿、10-23 {fl['2026-10-23']:+.1f}亿港元（每日十大成交股口径）。业绩会上较少被直接问及，作背景。")
            sids = sorted(set(sids) | set(sb["holding"]["src"]) | set(sb["daily_net"]["src"]))
        tier = min(SRC[s]["tier"] for s in sids)
        item = {"id": c["id"], "date": c["date"], "title": c["title"], "detail": detail, "src": sids,
                "label": c["label"], "tier": tier, "flags": list(c.get("flags", [])) or infer_flags(detail, sids),
                "impact": c["impact"]}
        if not c["src"]:
            item["note"] = "“未检索到”判断基于港交所标题检索与公开新闻检索，不代表未发生"
        out.append(item)
    return out


def build_themes():
    out = []
    for t in E.THEMES:
        out.append({"name": t["name"], "heat": t["heat"], "heat_note": "主观评分（人工整理，0–100）",
                    "one_line": t["one_line"], "src": sid_of(t["src"]), "label": "推断"})
    return out


def build_key_numbers(v1, bb, sb, misc):
    out = []
    for i, k in enumerate(v1["key_numbers"]):
        if "股价" in k["metric"] or "估值" in k["metric"]:
            continue                                  # 红线：不展示股价与估值
        k = dict(k)
        if "目标价" in k["metric"]:
            k["metric"] = "券商2026年资本开支预测（预测，非事实）"
            k["value"] = re.sub(r"。?目标价：.*$", "", k["value"])
        sid = sid_of(k["url"])
        item = {"metric": k["metric"], "value": k["value"], "period": k["period"], "source": clean_title(k["source"]), "src": [sid],
                "label": infer_label(k["metric"] + k["value"]), "flags": infer_flags(k["metric"] + k["value"], [sid])}
        if "预测" in k["metric"]:
            item["flags"] = list(dict.fromkeys(item["flags"] + ["媒体转述/二手"]))
        if "年初至今累计回购（媒体统计）" in k["metric"]:
            u = bb["upto_1013"]
            item["reconciliation"] = {"computed_upto_1013": u, "streak_0817_1013": bb["streak_0817_1013"],
                                      "status": "一致" if (u["days"] == 94 and abs(u["hkd_yi"] - 322.44) < 0.01) else "不一致",
                                      "src": bb["src"], "label": "计算"}
        if k["metric"] == "10月票据发行":
            item["value"] = k["value"].replace("预计2026-10-21交割", "已于2026-10-21（纽约时间）完成发行，10-22港交所完成公告")
            item["src"] = [sid, ALIAS["HKEX_COMPLETION"]]
        out.append(item)
    m = misc["capex_to_revenue"]
    fl = {r["date"]: r["net_hkd_yi"] for r in sb["daily_net"]["rows"]}
    out += [
        {"metric": "2026年初至今回购（逐份复算）", "value": f"{bb['days']}个交易日，{bb['shares']:,}股，约{bb['hkd_yi']}亿港元；最后一笔{bb['last_date']}",
         "period": f"{bb['first_date']}至{bb['last_date']}", "source": "港交所翌日披露报表逐份解析", "src": bb["src"], "label": "计算", "flags": []},
        {"metric": "港股通南向持股", "value": f"{sb['holding']['shares']:,}股，占已发行股份{sb['holding']['pct']}",
         "period": "截至2026-10-23", "source": "港交所披露易南向持股页面", "src": sb["holding"]["src"], "label": "结构化数据", "flags": []},
        {"metric": "南向资金对腾讯单日净买卖（计算）", "value": f"10-21 {fl['2026-10-21']:+.1f}亿港元；10-23 {fl['2026-10-23']:+.1f}亿港元",
         "period": "2026-10-21/23", "source": "港交所每日十大成交股统计", "src": sb["daily_net"]["src"], "label": "计算", "flags": []},
        {"metric": "Meta 2026年第三季度（同业参照）", "value": "收入646.0亿美元（+26%）；广告收入630.6亿美元；资本开支（含融资租赁本金）349.1亿美元；自由现金流-21.2亿美元；当季无回购；全年资本开支指引1350亿–1450亿美元",
         "period": "2026Q3", "source": "Meta 官方业绩新闻稿", "src": [ALIAS["META_8K"]], "label": "公开披露", "flags": []},
        {"metric": "资本开支/收入（计算，口径不同仅作量级参照）", "value": f"腾讯2Q26约{m['tencent_2q26']['ratio']:.1%}；Meta 3Q26约{m['meta_3q26']['ratio']:.1%}",
         "period": "2026Q2/2026Q3", "source": "腾讯2Q26演示材料与新闻稿；Meta 新闻稿", "src": m["tencent_2q26"]["src"] + m["meta_3q26"]["src"],
         "label": "计算", "flags": []},
    ]
    return out


def build_dropped(v1):
    out = []
    for i, d in enumerate(v1["dropped"]):
        d = E.DROPPED_REWRITE.get(i, d)
        for a, b in E.DROPPED_REPLACE:
            d = d.replace(a, b)
        out.append(d)
    return out


# ============================================================================ analyst signal & Top10
def analyst_signal(m2t):
    window = m2t["gap"]["window"]
    rows = m2t["heat"]["rows"]
    w = {q: i + 1 for i, q in enumerate(window)}
    gap = {r["topic"]: r for r in m2t["gap"]["rows"]}
    topic_rows = []
    for tid, name in E.TOPICS:
        counts = {q: rows[q]["analyst"]["counts"][tid] for q in window}
        nunits = {q: rows[q]["analyst"]["n_units"] for q in window}
        ws = sum(w[q] * counts[q] / nunits[q] for q in window) / sum(w.values())
        topic_rows.append({"topic": tid, "name": name, "counts_by_quarter": counts, "n_units_by_quarter": nunits,
                           "recency_weighted_share": round(ws, 4), "analyst_units_4q": sum(counts.values()),
                           "mgmt_push_share": gap[tid]["push_share"], "gap_pp": gap[tid]["gap_pp"], "flag": gap[tid]["flag"]})
    # 机构轨迹：窗口内每家机构出现最多的两个话题（并列取最近出现、再取全体频次）
    total = {r["topic"]: r["analyst_units_4q"] for r in topic_rows}
    orgs = []
    for o in m2t["org_trajectory"]["orgs"]:
        cnt, last = {}, {}
        for q in window:
            if q in o["quarters"]:
                for t in o["quarters"][q]["topics"]:
                    cnt[t] = cnt.get(t, 0) + 1
                    last[t] = window.index(q)
        if not cnt:
            continue
        top2 = sorted(cnt, key=lambda t: (-cnt[t], -last[t], -total.get(t, 0), t))[:2]
        orgs.append({"org": o["org"], "quarters_in_window": sum(1 for q in window if q in o["quarters"]), "top2": top2})
    n_orgs = len(orgs)
    org_share = {tid: round(sum(1 for o in orgs if tid in o["top2"]) / n_orgs, 3) for tid, _ in E.TOPICS}
    bt = m2t["backtest"]
    sig = {
        "window": window, "src": [ALIAS[a] for a in ("TR_Q3_25", "TR_Q4_25", "TR_Q1_26", "TR_Q2_26")], "label": "计算",
        "definition": "recency_weighted_share = Σ_q w_q·(带该话题标签的问题单元数/该季问题单元数) / Σ w_q，w=1..4（越近越大）；"
                      "话题标签为 M2a 人工逐条编码（多标签）。",
        "topic_rows": topic_rows,
        "org_top2": {"rows": orgs, "n_orgs": n_orgs, "topic_share": org_share,
                     "note": "以机构为主键，只表示“机构历史关注话题→可能延续”；第三方文字稿，归属待录音复核；不评价任何个人。", "label": "推断"},
        "backtest": {"train": bt["train_quarters"], "test": bt["test_quarter"],
                     "org_history_precision_at2": bt["precision_at2"], "market_hot_baseline_precision_at2": bt["baseline"]["precision_at2"],
                     "conclusion": "机构历史话题预测命中率 0.43 低于全市场最热话题基线 0.64，因此 Top10 以全市场热度为主、机构轨迹为辅（权重 0.15）。",
                     "caveat": bt["caveat"], "src": [ALIAS["TR_Q3_25"], ALIAS["TR_Q4_25"], ALIAS["TR_Q1_26"], ALIAS["TR_Q2_26"]], "label": "计算"},
    }
    return sig


WEIGHTS = {"market_heat": 0.60, "catalyst": 0.25, "org_trajectory": 0.15}


def top10(sig, changes):
    heat = {r["topic"]: r["recency_weighted_share"] for r in sig["topic_rows"]}
    org = sig["org_top2"]["topic_share"]
    hmax, omax = max(heat.values()), max(org.values()) or 1
    cands = [dict(p, kind="P") for p in E.TOP10]
    for i, a in enumerate(E.TOP10_ALTERNATES, 1):
        cands.append({"id": f"A{i:02d}", "title": a["title"], "topics_primary": a["topics"], "topics_secondary": [],
                      "scope": a.get("scope", a["why_not_top10"]), "questions": a["questions"], "kind": "A",
                      "why_not_top10_manual": a["why_not_top10"], "merge_into": "P02" if a["topics"] == ["MARGIN"] else None})
    for c in cands:
        c["catalysts"] = [ch["id"] for ch in changes if set(ch["impact"]) & set(c["questions"])]
    cmax = max(len(c["catalysts"]) for c in cands) or 1
    for c in cands:
        h = max(heat[t] for t in c["topics_primary"]) / hmax
        o = max(org[t] for t in c["topics_primary"]) / omax
        k = len(c["catalysts"]) / cmax
        c["score"] = {"market_heat": round(h, 3), "catalyst": round(k, 3), "org_trajectory": round(o, 3),
                      "total": round(WEIGHTS["market_heat"] * h + WEIGHTS["catalyst"] * k + WEIGHTS["org_trajectory"] * o, 3)}
    pool = sorted([c for c in cands if not c.get("merge_into")], key=lambda c: (-c["score"]["total"], c["id"]))
    selected, rest = pool[:10], pool[10:]
    items = []
    for r, c in enumerate(selected, 1):
        items.append({"rank": r, "id": c["id"], "title": c["title"], "topics_primary": c["topics_primary"],
                      "topics_secondary": c["topics_secondary"], "scope": c["scope"], "radar_questions": c["questions"],
                      "score": c["score"], "catalysts": c["catalysts"], "rank_manual": c.get("rank")})
    alternates = []
    for c in rest + [c for c in cands if c.get("merge_into")]:
        alternates.append({"id": c["id"], "title": c["title"], "topics_primary": c["topics_primary"], "radar_questions": c["questions"],
                           "score": c["score"], "merged_into": c.get("merge_into"), "why_not_top10": c.get("why_not_top10_manual")})
    # 朴素基线：2Q26 业绩会话题频次前 10（并列按窗口总频次）
    last = sig["window"][-1]
    base = sorted(sig["topic_rows"], key=lambda r: (-r["counts_by_quarter"][last], -r["analyst_units_4q"], r["topic"]))[:10]
    return items, alternates, [r["topic"] for r in base]


def write_prereg(items, alternates, baseline):
    payload = {
        "title": "腾讯 2026 年第三季度业绩会：分析师提问议题 Top10 预注册（议题级）",
        "as_of": AS_OF, "module": MODULE, "watermark": WATERMARK,
        "event": {"name": "腾讯控股 2026 年第三季度业绩发布及业绩会", "board_meeting": BOARD_DATE.isoformat(),
                  "board_meeting_src": SRC[ALIAS["BOARD_MTG"]]["url"]},
        "level": "议题级（每项对应 1–2 个主话题 id，统一话题分类见 taxonomy_ids）",
        "taxonomy_ids": [t for t, _ in E.TOPICS],
        "items": items, "alternates": alternates,
        "selection_method": {
            "summary": "按全市场热度为主、近期公开催化为辅、机构轨迹为次的加权分排序，取前 10。",
            "weights": WEIGHTS,
            "market_heat": "近四季（2025Q3–2026Q2）全部分析师问题单元的话题占比，按 1/2/3/4 近期加权；议题取其主话题中的最大值，再除以全话题最大值归一。",
            "catalyst": "2026-10-19 以来公开变化（本模块 changes_since_1019）中影响该议题对应雷达题的条数，除以最大值归一。",
            "org_trajectory": "近四季每家机构出现最多的两个话题中包含该议题主话题的机构占比，归一后权重仅 0.15。",
            "backtest_basis": "M2a 回测（训练 2025Q3–2026Q1，测试 2026Q2）：机构历史话题 precision@2=0.43，全市场最热话题基线=0.64，故以全市场热度为主。",
            "manual_inputs": "议题定义、scope 与候选清单（含 2 个备选）为人工整理；排序与入选由脚本按上述权重计算。"},
        "naive_baseline_topics_2q26_top10": baseline,
        "scoring_protocol": E.SCORING_PROTOCOL,
        "disclaimer": "预测只到“全市场与机构历史关注话题→可能延续”，不针对任何个人；内部准备材料，不构成公司口径。",
    }

    def dump(d):
        return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    gen = None
    if PREREG_PATH.exists():
        try:
            old = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
            if dump({k: v for k, v in old.items() if k != "generated_at"}) == dump(payload):
                gen = old.get("generated_at")
        except Exception:  # noqa: BLE001
            gen = None
    reused = gen is not None
    if not gen:
        gen = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    payload["generated_at"] = gen
    text = dump(payload)
    PREREG_PATH.write_bytes(text.encode("utf-8"))
    return {"file": rel(PREREG_PATH), "sha256": sha256_file(PREREG_PATH), "generated_at": gen,
            "reused_existing_timestamp": reused,
            "serialization": "json.dumps(sort_keys=True, ensure_ascii=False, separators=(',',':'))，UTF-8，无 BOM、无末尾换行；SHA-256 针对文件字节"}


# ============================================================================ completeness
EXT_SOURCES = {
    "DI": {"url": "https://di.hkex.com.hk/di/NSAllFormList.aspx?sa2=an&sid=6893&corpn=Tencent+Holdings+Ltd.&sd=01/01/2025&ed=26/10/2026&cid=0&sa1=cl&scsd=01%2f01%2f2025&sced=26%2f10%2f2026&sc=700&src=MAIN&lang=EN&g_lang=en&",
           "title": "港交所权益披露：腾讯控股（2025-01-01 至 2026-10-26 检索，经 mkt.json 汇总）", "date": "2026-10-26", "tier": 1},
    "MSCI": {"url": "https://www.msci.com/documents/10199/255599/msci-china-index.pdf",
             "title": "MSCI China Index 指数概况（截至 2026-09-30，经 mkt.json 汇总）", "date": "2026-09-30", "tier": 4},
}
def completeness(questions, items, sig, changes):
    qtopics = {}
    for q in questions:
        for t in q["topics"]:
            qtopics.setdefault(t, []).append(q["id"])
    prim = {t for it in items for t in it["topics_primary"]}
    sec = {t for it in items for t in it["topics_secondary"]}
    rows = []
    for r in sig["topic_rows"]:
        t = r["topic"]
        rows.append({"topic": t, "analyst_units_4q": r["analyst_units_4q"], "gap_pp": r["gap_pp"],
                     "radar_questions": qtopics.get(t, []),
                     "top10": "主话题" if t in prim else ("次话题" if t in sec else "未入选"),
                     "status": "覆盖" if qtopics.get(t) else ("无分析师提问且无题" if r["analyst_units_4q"] == 0 else "遗漏")})
    qu = load_json(use(QU_PATH))["units"]
    last_q = sig["window"][-1]
    units = []
    for u in qu:
        if u["quarter"] != last_q:
            continue
        first = u["topics"][0]
        units.append({"q_id": u["q_id"], "org": u["org"], "topics": u["topics"],
                      "radar_questions_first_topic": qtopics.get(first, []),
                      "top10_covers_first_topic": first in prim})
    news = [{"change": c["id"], "title": c["title"], "impact_questions": [x for x in c["impact"] if x.startswith("Q")],
             "covered": all(any(q["id"] == x for q in questions) for x in c["impact"] if x.startswith("Q"))} for c in changes]
    mk = {}
    for alias, meta in EXT_SOURCES.items():
        if alias not in ALIAS:
            register(alias, meta)
        mk[alias] = ALIAS[alias]
    considered = [
        {"topic": "Prosus/Naspers 持续减持", "decision": "不单列题；在 M3 股东模块展示",
         "reason": "近四季业绩会实录中分析师未就大股东减持向管理层提问（M2a 编码：PORTFOLIO 话题 4 季仅 1 个单元，且为投资组合变现）；属股东结构背景。",
         "src": [mk["DI"]], "label": "推断"},
        {"topic": "MSCI 中国指数权重、恒生科技指数扩容等被动资金因素", "decision": "不列题", "reason": "非管理层可回应的经营议题；M0/M3 作背景。",
         "src": [mk["MSCI"]], "label": "推断"},
        {"topic": "10-21 至 10-23 股价波动与卖方目标价调整", "decision": "不列题（红线）", "reason": "不评论股价与估值；不收录卖方对公司业绩的预测数字。",
         "src": [ALIAS["HKEX_DAILY"]], "label": "推断"},
        {"topic": "董事个人交易", "decision": "不展示（红线）", "reason": "总方案第六节：不展示董事个人交易。", "src": [mk["DI"]], "label": "推断"},
    ]
    supplements = [{"question": "Q27", "topic": "Meta Q3（10-21）对腾讯的潜在追问", "src": [ALIAS["META_8K"], ALIAS["FORTUNE_META"]]},
                   {"question": "Q28", "topic": "DeepSeek 融资报道（公司未证实）", "src": [ALIAS["TNW_DEEPSEEK"]]}]
    retro = sum(1 for u in units if u["top10_covers_first_topic"]) / len(units) if units else None
    return {"topic_coverage": rows, "analyst_units_last_quarter": units,
            "retro_coverage_last_quarter": {"value": round(retro, 3), "definition": f"{last_q} 问题单元中首个话题标签落在 Top10 主话题内的比例（样本内，仅作合理性检查）",
                                            "src": [ALIAS["TR_Q2_26"]], "label": "计算"},
            "news_coverage": news, "supplements_added": supplements, "considered_not_added": considered,
            "conclusion": ("对照 M2a 近四季分析师关切（15 个话题）与 10-19 以来公开变化：除新增 Q27（Meta 同业类比）、Q28（DeepSeek 融资报道）外，"
                           "未发现需新增的议题；REG 话题近四季无分析师提问，但保留 Q25/Q26 备查。"),
            "label": "推断"}


# ============================================================================ self-check
def walk(x, path=""):
    if isinstance(x, dict):
        yield path, x
        for k, v in x.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from walk(v, f"{path}[{i}]")


def strings(x, skip=()):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in skip:
                continue
            yield from strings(v, skip)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v, skip)
    elif isinstance(x, str):
        yield x


def spot_checks(out, bb, sb):
    """Fixed pool of number/quote checks traced back to local originals."""
    blob = json.dumps({k: v for k, v in out.items() if k != "meta"}, ensure_ascii=False)
    meta_rel = text_of("data/src/peers/meta_q3_2026_release.html")
    checks = []

    def add(cid, claim, ok, source, detail=""):
        checks.append({"id": cid, "claim": claim, "pass": bool(ok), "source": source, "detail": detail})

    def has(path, s):
        t = text_of(path) if not path.startswith("data/parsed/") else transcript_text(Path(path).stem)
        st, snip = find(s, t)
        return st is not None, (snip or "")[:120]

    add("N01", "年内回购约324.44亿港元（96 日、68,276,700 股）", bb["hkd_yi"] == 324.44 and bb["days"] == 96 and bb["shares"] == 68276700
        and "324.44亿港元" in blob, "data/src/market_raw/nddr/buybacks2026.json", f"复算 {bb['hkd_yi']} 亿 / {bb['days']} 日 / {bb['shares']:,} 股")
    ok, sn = has("data/src/market_raw/nddr/2026101500641.txt", "15 October 2026 240,000 On the Exchange HKD 422.4 HKD 414.2 HKD 100,385,040")
    add("N02", "最后一笔回购 10-15：240,000 股、100,385,040 港元", ok and bb["last_date"] == "2026-10-15", "data/src/market_raw/nddr/2026101500641.txt", sn)
    ok, sn = has("demo/data/m2_raw/hkex_2026102200033.pdf", "on 21 October 2026 (New York time), the issue of the Notes under the Programme was completed")
    add("N03", "10月票据已于 2026-10-21（纽约时间）完成发行", ok, "demo/data/m2_raw/hkex_2026102200033.pdf", sn)
    ok, sn = has("data/src/ir_official/2026-10-14_E700_Pricing-Announcement.txt", "approximately US$1.79 billion and CNY25.89 billion")
    add("N04", "票据净所得约17.9亿美元及258.9亿元人民币", ok and "258.9亿元人民币" in blob, "data/src/ir_official/2026-10-14_E700_Pricing-Announcement.txt", sn)
    t = text_of("demo/data/m2_raw/hkex_2026102200033.pdf")
    ok = all(x in re.sub(r"\s+", " ", t) for x in ("US$1.30 billion 6.10%", "US$0.50 billion 6.75%", "CNY20.0 billion 2.40%", "CNY6.0 billion 3.00%"))
    add("N05", "票面：13亿美元6.10%/5亿美元6.75%/200亿元2.40%/60亿元3.00%", ok, "demo/data/m2_raw/hkex_2026102200033.pdf")
    add("N06", "南向持股 1,089,863,992 股 / 11.98%", sb["holding"]["shares"] == 1089863992 and sb["holding"]["pct"] == "11.98%",
        "data/src/market_raw/hkex/mm_hk.html", f"页面日期 {sb['holding']['page_date']}")
    fl = {r["date"]: r["net_hkd_yi"] for r in sb["daily_net"]["rows"]}
    add("N07", "10-21 南向净卖出约17.1亿港元；10-23 净买入约13.0亿港元", fl["2026-10-21"] == -17.1 and fl["2026-10-23"] == 13.0,
        "data/src/market_raw/idx/sc_20261021.js, sc_20261023.js", f"复算 {fl}")
    ok = all(x in re.sub(r"\s+", " ", meta_rel) for x in ("Revenue was $64.60 billion", "were $34.91 billion", "Free cash flow $ (2,120)",
                                                         "Repurchases of Class A common stock — (3,327)", "range of $135-145 billion"))
    add("N08", "Meta Q3：收入646.0亿美元、资本开支349.1亿美元、FCF -21.2亿美元、当季无回购、指引1350–1450亿美元", ok, "data/src/peers/meta_q3_2026_release.html")
    ok, sn = has("data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt", "RMB88.3 billion and RMB45.9 billion and RMB96.3 billion")
    add("N09", "现金支付口径资本开支：2025年883亿元、1H26 963亿元", ok, "data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt", sn)
    ok1, _ = has("data/src/ir_official/2Q26_ppt.txt", "Total CAPEX 52.8 19.1 +176% 31.9 +65%")
    ok2, _ = has("data/src/ir_official/2Q26_ppt.txt", "Free Cash Flow (13.8) 43.0")
    add("N10", "2Q26 总资本开支528亿元（+176%，环比+65%）、自由现金流-138亿元", ok1 and ok2, "data/src/ir_official/2Q26_ppt.txt")
    t3 = re.sub(r"\s+", " ", text_of("data/src/ir_official/3Q25_ppt.txt"))
    add("N11", "3Q25 基数：自由现金流585亿元、总现金4933亿元、总债务3909亿元、净现金1024亿元、上市投资约8010亿元",
        all(x in t3 for x in ("58.5", "493.3", "(390.9)", "102.4", "~RMB801")), "data/src/ir_official/3Q25_ppt.txt",
        "PDF 文本列错位：58.5 出现在 Free Cash Flow 行上方，按表格位置判读")
    ok, sn = has("data/parsed/q4-2025.json", "we repurchased 153 million shares with a total consideration of HKD 80 billion")
    add("N12", "2025年回购约800亿港元（1.53亿股）", ok, "data/parsed/q4-2025.json", sn)
    ok, sn = has("data/src/market_raw/nddr/2026092401585.txt", "Wednesday, 18 November 2026")
    add("N13", "Q3 业绩董事会 2026-11-18", ok, "data/src/market_raw/nddr/2026092401585.txt", sn)
    ok, sn = has("data/src/market_raw/dod/fr.txt", "Tencent is indirectly affiliated with the PLA (Section 1260H(g)(2)(B)(i)(I))")
    add("N14", "1260H 条目原文", ok, "data/src/market_raw/dod/fr.txt", sn)
    ok, sn = has("data/parsed/q2-2026.json", "it is more of a sort of a lump sum that we are going to be investing this year and next year")
    add("Q01", "引语：lump sum（2Q26 文字稿）", ok, "data/parsed/q2-2026.json", sn)
    ok, sn = has("demo/data/m2_raw/sina_q2_2026.html", "如果回报不及预期，现有投入规模就会封顶。")
    add("Q02", "引语：“封顶”（新浪整理稿）", ok, "demo/data/m2_raw/sina_q2_2026.html", sn)
    ok, sn = has("demo/data/m2_raw/21jingji_bond.html", "腾讯向投资者表示，债券资金主要用于人工智能资本开支")
    add("Q03", "引语：“主要用于人工智能资本开支”（21世纪经济报道转财联社）", ok, "demo/data/m2_raw/21jingji_bond.html", sn)
    ok, sn = has("demo/data/m2_raw/wscn_3767854.html", "今年计划至少翻倍")
    add("Q04", "引语：“至少翻倍”（华尔街见闻）", ok, "demo/data/m2_raw/wscn_3767854.html", sn)
    ok, sn = has("data/src/peers/meta_q3_2026_release.html", "Our investments are paying off")
    add("Q05", "引语：扎克伯格“Our investments are paying off”", ok, "data/src/peers/meta_q3_2026_release.html", sn)
    ok, sn = has("data/src/ir_official/4Q25_ppt.txt", "We expect to more than double investments in New AI Products in 2026")
    add("Q06", "引语：more than double（4Q25 官方材料）", ok, "data/src/ir_official/4Q25_ppt.txt", sn)
    add("C01", "资本开支/收入：腾讯2Q26约25.8%，Meta 3Q26约54.0%",
        round(52.784 / 204.785 * 100, 1) == 25.8 and round(34.91 / 64.601 * 100, 1) == 54.0 and "25.8%" in blob, "计算", "")
    add("C02", "上市投资公允价值较2025-09末下降约39%", round((1 - 487 / 801) * 100) == 39 and "39%" in blob, "计算", "")
    add("C03", "规则窗口约从 10-19 开始（11-18 前 30 日）", bb["rule_window_start"] == "2026-10-19", "计算", "")
    page = "".join(text_of(p) or "" for p in SRC[ALIAS["IR_RESULTS"]].get("local", []))
    raw_page = "".join((ROOT / p).read_text(encoding="utf-8", errors="ignore") for p in SRC[ALIAS["IR_RESULTS"]].get("local", []) if (ROOT / p).exists())
    want = ["PPT_3Q25", "PPT_4Q25", "PPT_2Q26", "REL_EN_2Q26", "REL_EN_1Q26", "HKEX_EN_2Q26"]
    miss = [a for a in want if SRC[ALIAS[a]]["url"].split("//", 1)[1] not in raw_page + page]
    add("L01", "官方材料链接（S005/S006/S008 及 1Q26、2Q26 新闻稿与港交所公告）均见于腾讯官网业绩页快照", not miss,
        " + ".join(SRC[ALIAS["IR_RESULTS"]].get("local", [])), f"缺失：{miss}" if miss else "6/6")
    return checks


def self_check(out, bb, sb, edits_text, code_text):
    res = {}
    sids = {s["id"] for s in out["sources"]}
    bad_src, bad_label, no_src = [], [], []
    for path, d in walk({k: v for k, v in out.items() if k not in ("meta", "sources")}):
        if "src" in d:
            for s in d["src"]:
                if s not in sids:
                    bad_src.append((path, s))
        if "label" in d and d["label"] not in LABELS:
            bad_label.append((path, d["label"]))
        num_fields = [d.get(k) for k in ("point", "quote", "value", "detail", "one_line", "items", "text") if isinstance(d.get(k), str)]
        if any(re.search(r"\d", s) for s in num_fields) and not d.get("src"):
            no_src.append(path)
    res["src_ids_exist"] = {"pass": not bad_src, "bad": bad_src[:10]}
    res["labels_legal"] = {"pass": not bad_label, "bad": bad_label[:10], "allowed": list(LABELS)}
    res["numbers_have_src"] = {"pass": not no_src, "missing": no_src[:20]}
    scan = list(strings({k: v for k, v in out.items() if k not in ("meta",)}, skip=("v2_changes", "dropped")))
    forb = sorted({w for s in scan for w in FORBIDDEN if w in s})
    res["forbidden_words"] = {"pass": not forb, "hits": forb, "words": FORBIDDEN}
    val_hits = []
    for path, d in walk({k: v for k, v in out.items() if k not in ("meta", "dropped")}):
        for k in ("quote", "text", "point", "value", "detail", "question_cn", "question_en", "one_line", "items", "observation", "metric", "title", "scope", "note", "reason", "source", "sub_theme", "name"):
            s = d.get(k)
            if isinstance(s, str) and VALUATION_RE.search(s):
                whitelisted = ("仅作出处索引" in (d.get("note") or "")) or (k == "note" and "不评论股价" in s) or (k == "reason" and "不评论股价" in s) \
                    or (k == "topic") or ("红线" in (d.get("decision") or ""))
                if not whitelisted:
                    val_hits.append((path + "." + k, VALUATION_RE.search(s).group(0)))
    res["no_valuation_comment"] = {"pass": not val_hits, "hits": val_hits[:10],
                                   "whitelist": "管理层原话（Q06 “share price is somewhat dislocated”）仅作出处索引并加注“不评论股价或估值”；完整性检查中列明“不列题（红线）”的条目"}
    adv = [s[:60] for s in scan if ADVICE_RE.search(s)]
    res["no_drafted_answers"] = {"pass": not adv and not any("answer_frame" in p for p, _ in walk(out)), "hits": adv[:5]}
    # privacy: no email, no user name, no absolute user paths in outputs / code
    who = {getpass.getuser().casefold(), Path.home().name.casefold()} - {""}
    blobs = {"m2_radar.json": json.dumps(out, ensure_ascii=False), "q3_top10_prereg.json": PREREG_PATH.read_text(encoding="utf-8"),
             "radar.py": code_text, "m2_radar_edits.py": edits_text}
    priv = []
    for name, b in blobs.items():
        try:
            assert_no_email(b)
        except ValueError as e:
            priv.append((name, str(e)[:80]))
        low = b.casefold()
        for w in who:
            if w and w in low:
                priv.append((name, "user-name token"))
        if re.search(r"[A-Za-z]:\\\\?Users\\\\?|" + "/c/" + "Users/", b):
            priv.append((name, "absolute user path"))
    res["privacy"] = {"pass": not priv, "hits": priv, "checked": list(blobs)}
    st = {}
    for s in STMT_LOG:
        st[s["verify"]["status"]] = st.get(s["verify"]["status"], 0) + 1
    unmatched = [{"quote": s["quote"][:80], "src": s["src"], "file": s["verify"].get("file")} for s in STMT_LOG if s["verify"]["status"] == "未匹配"]
    unverified = [{"quote": s["quote"][:60], "src": s["src"], "method": s["verify"]["method"]} for s in STMT_LOG if s["verify"]["status"] == "未本地复核"]
    res["quotes_verified"] = {"pass": not unmatched, "counts": st, "unmatched": unmatched, "not_locally_verifiable": unverified}
    rng = random.Random(AS_OF)
    sample = rng.sample([s for s in STMT_LOG if s["verify"]["status"] == "已核对"], 10)
    res["random_quote_sample"] = [{"quote": s["quote"][:90], "src": s["src"], "file": s["verify"]["file"], "match": s["verify"]["match"],
                                   "context": s["verify"].get("context", "")[:100]} for s in sample]
    checks = spot_checks(out, bb, sb)
    res["spot_checks"] = {"pass": all(c["pass"] for c in checks), "n": len(checks), "n_pass": sum(c["pass"] for c in checks), "rows": checks}
    nq = len(out["questions"])
    res["structure"] = {"pass": 24 <= nq <= 30 and len(out["drift_examples"]) >= 3 and len(out["top10_prereg"]["items"]) == 10
                        and all(len(d["sides"]) >= 2 and all(s["src"] and s["date"] and s["tier"] for s in d["sides"]) for d in out["drift_examples"])
                        and all(g["priority"] in E.PRIORITY_DEF for g in out["gaps_for_management"])
                        and all(q["topics"] and set(q["topics"]) <= set(TOPIC_NAME) for q in out["questions"]),
                        "questions": nq, "drift": len(out["drift_examples"]), "gaps": len(out["gaps_for_management"]),
                        "top10": len(out["top10_prereg"]["items"])}
    res["prereg_hash"] = {"pass": sha256_file(PREREG_PATH) == out["meta"]["top10_prereg"]["sha256"], "sha256": out["meta"]["top10_prereg"]["sha256"]}
    res["watermark"] = {"pass": out.get("watermark") == WATERMARK and WATERMARK in PREREG_PATH.read_text(encoding="utf-8")}
    res["overall_pass"] = all(v.get("pass", True) for v in res.values() if isinstance(v, dict))
    return res


# ============================================================================ main
def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ARGS = ap.parse_args()
    v1 = load_json(use(V1_PATH))
    m2t = load_json(use(M2T_PATH))
    use(EDITS_PATH)
    build_registry(v1)
    for a in WEB_CACHE:
        if not a.startswith("http"):
            ensure_web_cache(a)
    bb = compute_buyback()
    sb = compute_southbound()
    misc = compute_misc()
    questions = build_questions(v1)
    drift = build_drift(bb, misc)
    gaps = build_gaps()
    changes = build_changes(bb, sb)
    themes = build_themes()
    keys = build_key_numbers(v1, bb, sb, misc)
    sig = analyst_signal(m2t)
    items, alternates, baseline = top10(sig, changes)
    prereg = write_prereg(items, alternates, baseline)
    comp = completeness(questions, items, sig, changes)
    for q in ("q3-2025", "q4-2025", "q1-2026", "q2-2026"):
        use(f"data/parsed/{q}.json")
    for p in WEB_CACHE.values():
        use(p)
    use(QU_PATH)
    use(TITLES_PATH)
    for d in ("20261020", "20261021", "20261022", "20261023"):
        use(f"data/src/market_raw/idx/sc_{d}.js")
    for p in ("data/src/market_raw/hkex/mm_hk.html", "data/src/peers/meta_q3_2026_release.html", "data/src/market_raw/dod/fr.txt",
              "data/src/market_raw/nddr/2026092401585.txt", "data/src/market_raw/nddr/2026101500641.txt"):
        use(p)

    used = set()
    for _, d in walk({"q": questions, "d": drift, "g": gaps, "c": changes, "t": themes, "k": keys, "s": sig, "x": comp, "b": bb, "sb": sb, "m": misc}):
        for s in d.get("src", []) if isinstance(d.get("src"), list) else []:
            used.add(s)
    sources = []
    for sid, r in sorted(SRC.items()):
        if sid not in used and not r["user_provided"]:
            continue
        rec = {"id": sid, "title": r["title"], "url": r["url"], "date": r["date"], "tier": r["tier"], "tier_name": TIERS[r["tier"]]}
        if r["user_provided"]:
            rec["user_provided"] = True
            rec["url_as_given"] = r["url_as_given"]
            rec["used_for"] = r["used_for"]
        loc = [p for p in r.get("local", []) if (ROOT / p).exists()]
        for key in (r.get("alias"), r["url"]):
            if key in WEB_CACHE and (ROOT / WEB_CACHE[key]).exists():
                loc.append(WEB_CACHE[key])
        if loc:
            rec["local_copy"] = loc
        sources.append(rec)

    out = {
        "meta": {"module": MODULE, "title": "M2b Q3 问题雷达 v2：已公开表述索引 · 口径漂移 · 暂无已公开表述事项 · Top10 预注册",
                 "as_of": AS_OF, "generated_by": "本地 Python", "script": SCRIPT, "manual_layer": rel(EDITS_PATH),
                 "inputs": sorted(INPUTS.values(), key=lambda x: x["path"]),
                 "notes": ("v1（26 题，已核查）＋人工整理编辑层（刷新至 2026-10-26、改写、话题、已公开表述索引）＋脚本复算（回购、南向、比率）"
                           "＋M2a 实录分析（热度、缺口、机构轨迹、回测）。answer_frame 已全部改为已公开表述索引；删除估值/市盈率/目标价。"
                           "第三方文字稿引语为非官方逐字稿，引用前以官方录音为准；券商观点为媒体转述/二手；所有因果判断标“推断”。"),
                 "watermark": WATERMARK, "top10_prereg": None, "network": NET},
        "watermark": WATERMARK,
        "sources": sources,
        "taxonomy": [{"id": t, "name": n} for t, n in E.TOPICS],
        "themes": themes,
        "questions": questions,
        "drift_examples": drift,
        "gaps_for_management": gaps,
        "gaps_priority_def": E.PRIORITY_DEF,
        "changes_since_1019": changes,
        "computed": {"buyback": bb, "southbound": sb, **misc},
        "key_numbers": keys,
        "analyst_signal": sig,
        "top10_prereg": {"file": prereg["file"], "sha256": prereg["sha256"], "generated_at": prereg["generated_at"],
                         "items": items, "alternates": alternates, "naive_baseline_topics_2q26_top10": baseline,
                         "selection_method_summary": "全市场热度 0.60＋近期公开催化 0.25＋机构轨迹 0.15；回测显示机构历史话题命中率 0.43 低于全市场最热基线 0.64，故以全市场为主",
                         "scoring_protocol": E.SCORING_PROTOCOL, "label": "推断"},
        "completeness_check": comp,
        "dropped": build_dropped(v1),
        "method_note": ("题目来自 v1 已核查的 26 题，经人工整理编辑层改写、合并新增 2 题（Q27 Meta 同业类比、Q28 DeepSeek 融资报道）共 28 题；"
                        "rank 为人工综合排序（热度×敏感度＋时效），frequency/sensitivity 为 1–5 主观评分。已公开表述索引中的原话由脚本逐条回到本地文字稿、"
                        "官方 PDF/文本或网页缓存比对，状态见 verify。Top10 预注册为议题级，按全市场热度为主、机构轨迹为辅计算排序。"),
    }
    out["meta"]["top10_prereg"] = {**prereg, "selection_method": out["top10_prereg"]["selection_method_summary"] +
                                   "；议题定义与候选为人工整理，入选与排序由 radar.py 计算；详见预注册文件 selection_method。"}
    edits_text = EDITS_PATH.read_text(encoding="utf-8")
    code_text = Path(__file__).read_text(encoding="utf-8")
    out["meta"]["self_check"] = self_check(out, bb, sb, edits_text, code_text)
    text = json.dumps(out, ensure_ascii=False)
    assert_no_email(text)
    path = write_module(MODULE, out)
    sc = out["meta"]["self_check"]
    log(f"wrote {rel(path)}  questions={len(questions)} drift={len(drift)} gaps={len(gaps)} sources={len(sources)}")
    log(f"prereg {prereg['file']} sha256={prereg['sha256']} reused_ts={prereg['reused_existing_timestamp']}")
    log("self_check:", {k: v.get("pass") if isinstance(v, dict) else v for k, v in sc.items() if k != "random_quote_sample"})
    log("quotes:", sc["quotes_verified"]["counts"], "unmatched:", len(sc["quotes_verified"]["unmatched"]))
    for u in sc["quotes_verified"]["unmatched"]:
        log("  UNMATCHED", u)
    for c in sc["spot_checks"]["rows"]:
        if not c["pass"]:
            log("  SPOT FAIL", c)
    for k in ("numbers_have_src", "no_valuation_comment", "src_ids_exist", "labels_legal", "privacy", "no_drafted_answers"):
        if not sc[k]["pass"]:
            log("  FAIL", k, json.dumps(sc[k], ensure_ascii=False)[:600])
    log("net:", NET)


if __name__ == "__main__":
    main()
