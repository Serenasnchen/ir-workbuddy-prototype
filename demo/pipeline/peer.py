"""M1 同业矩阵与速评 → demo/data/m1_peer.json

运行（在 ROOT 下）：
    python -I demo/pipeline/peer_fetch.py   # 只补下载缺失的原始材料（已有文件不重复下载）
    python -I demo/pipeline/peer.py         # 本脚本不发起任何网络请求

输入（只读）：
  demo/pipeline/peer_data.py         8 家×8 议题单元格（最新季+上一季快照）、capex 数值、来源表、数字锚点（人工整理）
  demo/pipeline/peer_flash_data.py   Meta 最新季、阿里最近一季速评（人工整理）
  data/src/peers/*                   同业原始材料：新闻稿、SEC 6-K、StockAnalysis 实录、发布日期页（peer_fetch.py 下载）
  data/src/ir_official/*.txt, data/parsed/*.json, data/src/transcripts/*.html   腾讯官方材料与实录
  data/research/parts/capex-cn.json, capex-us.json, peer-flash-alibaba.json      核查底稿（仅少数无本地原文的条目引用）

构建即校验（任一失败则不写输出、退出码 1）：
  - 每格 value_short ≤20 字；label ∈ LABELS；src 非空且 id 均在 sources 中；最新季 change_vs_prior 状态合法；
  - 每条引语（单元格与速评）英文 ≤25 词 / 中文 ≤40 字，且在其来源的本地文件中逐字出现
    （仅归一化空白、弯引号与连字符）；
  - 每个数字锚点（peer_data.NUMBER_ANCHORS 与速评关键数字表 anchors）在本地原文中逐字出现；
  - capex 表：人民币折美元与公司自行披露的美元折算值相差 ≤1 百万；披露的同比与计算值一致；
  - 产物中无禁用词、无估值/股价评论用语、无邮箱与本机用户路径。
自检（写入 meta.self_check）：固定种子随机抽取 ≥12 条数字/引语，用"不经解析器"的原始文件文本
  （HTML 去标签 / PDF 抽字 / TXT 原文）重新核对，并附上下文片段。
"""
import html
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, "demo/pipeline")
from common import AS_OF, LABELS, ROOT, assert_no_email, input_record, write_module  # noqa: E402
import peer_data as P  # noqa: E402
import peer_flash_data as F  # noqa: E402
from sa_transcript import parse_file  # noqa: E402

MODULE = "m1_peer"
SCRIPT = "demo/pipeline/peer.py"
CH_STATUS = ("实质变化", "口径变化", "无变化", "新增")
FORBIDDEN = ("颠覆", "革命性", "首创", "全面领先", "赋能", "取代IR")
VALUATION = ("市盈率", "目标价", "估值", "市值", "P/E", "price target", "valuation", "股价", "评级")
QUOTE_NOTE_T3 = "非官方逐字稿，引用前以官方录音为准"
REVIEW_NOTE = "第三方文字稿，待录音复核"
WATERMARK = "内部准备材料，不构成公司口径"
DISCLAIMER = ("仅使用公开信息；不评论股价与估值，不展示董事个人交易；第三方实录为非官方逐字稿；券商观点属二手信息；"
              "所有因果判断均为推断；本材料不构成投资意见，也不代表公司口径。")
LABEL_RANK = {"公开披露": 0, "结构化数据": 1, "计算": 2, "推断": 3}
# 公司公告中直接写明的同比（其余同比均为本脚本计算）
YOY_DISCLOSED = {("tencent", "company"): (176, "S02"), ("alibaba", "company"): (75, "S60")}

SRC = {s["id"]: s for s in P.SOURCES}
ERRORS = []


def err(msg):
    ERRORS.append(msg)


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


# ---------------------------------------------------------------------------
# 1. 原文读取与逐字比对
# ---------------------------------------------------------------------------
_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-",
                        "—": "-", "‑": "-", "−": "-", "\xa0": " ", "　": " "})
CJK = re.compile(r"[一-鿿]")


def norm(s):
    return re.sub(r"\s+", " ", s.translate(_TRANS)).strip()


def strip_html(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(raw)


def pdf_text(path):
    import pymupdf  # 仅在需要时导入
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _json_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _json_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_strings(v, out)


def _read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


_PRIMARY = {}


def source_text(sid):
    """构建校验用文本：实录走解析器（与网页展示一致），其余按文件类型抽字。"""
    if sid in _PRIMARY:
        return _PRIMARY[sid]
    s = SRC[sid]
    path = ROOT / s["local"]
    kind = s["kind"]
    if kind == "txt":
        t = _read(path)
    elif kind == "html":
        t = strip_html(_read(path))
    elif kind == "sa":
        t = "\n".join(f"{x['speaker']}: {x['text']}" for x in parse_file(path))
    elif kind == "tparsed":
        t = "\n".join(f"{x.get('speaker', '')}: {x.get('text', '')}" for x in json.loads(_read(path)))
    elif kind == "json":
        parts = []
        _json_strings(json.loads(_read(path)), parts)
        t = "\n".join(parts)
    elif kind == "bin":
        t = pdf_text(path)
    else:
        raise ValueError(kind)
    _PRIMARY[sid] = norm(t)
    return _PRIMARY[sid]


_RAW = {}


def raw_text(sid):
    """自检用文本：只读原始文件、不经实录解析器；核查底稿（json）返回 None。"""
    if sid in _RAW:
        return _RAW[sid]
    s = SRC[sid]
    if s["kind"] == "json":
        return None
    p = ROOT / (s.get("raw") or s["local"])
    suf = p.suffix.lower()
    if suf == ".pdf":
        t = pdf_text(p)
    elif suf in (".html", ".htm"):
        t = strip_html(_read(p))
    else:
        t = _read(p)
    _RAW[sid] = norm(t)
    return _RAW[sid]


def find_in(needle, hay):
    """返回命中位置（-1 表示未命中）。中文引语额外允许忽略空白（PDF/网页抽字常在汉字间断行）。"""
    n = norm(needle)
    i = hay.find(n)
    if i >= 0 or not CJK.search(needle):
        return i
    return hay.replace(" ", "").find(n.replace(" ", ""))


def snippet(hay, needle, width=60):
    i = find_in(needle, hay)
    if i < 0:
        return ""
    n = len(norm(needle))
    return hay[max(0, i - width): i + n + width]


def quote_len_ok(q):
    if CJK.search(q):
        return len(CJK.findall(q)) <= 40
    return len(q.split()) <= 25


def check_src_ids(ids, where):
    if not ids:
        err(f"{where}: src 为空")
    for i in ids:
        if i not in SRC:
            err(f"{where}: 未登记来源 {i}")


def check_label(label, where):
    if label not in LABELS:
        err(f"{where}: label 非法 {label!r}")


QUOTE_LOG = []   # (where, sid, text)
ANCHOR_LOG = []  # (where, sid, text)


def check_quote(q, sid, where):
    if not q:
        return
    if sid not in SRC:
        err(f"{where}: 引语来源 {sid} 未登记")
        return
    if not quote_len_ok(q):
        err(f"{where}: 引语超长（英文≤25词/中文≤40字）：{q[:40]}…")
    if find_in(q, source_text(sid)) < 0:
        err(f"{where}: 引语在 {sid}（{SRC[sid]['local']}）中找不到：{q}")
    QUOTE_LOG.append((where, sid, q))


def check_anchor(sid, text, where):
    if sid not in SRC:
        err(f"{where}: 锚点来源 {sid} 未登记")
        return
    if find_in(text, source_text(sid)) < 0:
        err(f"{where}: 数字锚点在 {sid} 中找不到：{text}")
    ANCHOR_LOG.append((where, sid, text))


def quote_obj(text, speaker, sid):
    if not text:
        return None
    tier = SRC[sid]["tier"]
    o = {"text": text, "speaker": speaker, "src": [sid], "tier": tier, "label": "公开披露"}
    if tier == 3:
        o["note"] = QUOTE_NOTE_T3
    elif tier == 4:
        o["note"] = "媒体转述/二手"
    return o


# ---------------------------------------------------------------------------
# 2. 单元格
# ---------------------------------------------------------------------------
def build_cells():
    cells = []
    topic_ids = [t["id"] for t in P.TOPICS]
    for cid in P.ORDER:
        c = P.C[cid]
        latest, prior = c["latest"], c["prior"]
        snaps = c["snapshots"]
        for per in (latest, prior):
            if per not in snaps:
                err(f"{cid}: 缺快照 {per}")
        for tid in topic_ids:
            cur = snaps[latest].get(tid)
            old = snaps[prior].get(tid)
            where = f"{cid}:{tid}"
            if cur is None:
                err(f"{where}: 最新季缺单元格")
                continue
            for per, cell in ((latest, cur), (prior, old)):
                if cell is None:
                    err(f"{where}@{per}: 缺单元格")
                    continue
                w = f"{where}@{per}"
                if len(cell["v"]) > 20:
                    err(f"{w}: value_short 超过20字（{len(cell['v'])}）：{cell['v']}")
                check_label(cell["label"], w)
                check_src_ids(cell["src"], w)
                if cell.get("q"):
                    check_quote(cell["q"], cell["qsrc"], w)
                    if cell["qsrc"] not in cell["src"]:
                        err(f"{w}: 引语来源 {cell['qsrc']} 未列入 src")
            ch = cur.get("ch")
            if not ch or ch.get("status") not in CH_STATUS or not ch.get("note"):
                err(f"{where}: change_vs_prior 缺失或状态非法")
                ch = ch or {"status": "", "note": ""}
            cells.append({
                "id": where, "company": cid, "topic": tid,
                "period": latest, "period_label": c["periods"][latest]["label"],
                "value_short": cur["v"], "detail": cur.get("d", ""),
                "src": cur["src"], "label": cur["label"], "label_note": cur.get("ln", ""),
                "quote": quote_obj(cur.get("q"), cur.get("qs", ""), cur.get("qsrc")) if cur.get("q") else None,
                "change_vs_prior": {"status": ch["status"], "note": ch["note"],
                                    "text": f"{ch['status']}：{ch['note']}"},
                "auto_diff": {"value_short_changed": bool(old) and old["v"] != cur["v"]},
                "prior": None if old is None else {
                    "period": prior, "period_label": c["periods"][prior]["label"],
                    "value_short": old["v"], "detail": old.get("d", ""),
                    "src": old["src"], "label": old["label"],
                    "quote": quote_obj(old.get("q"), old.get("qs", ""), old.get("qsrc")) if old.get("q") else None,
                },
            })
    return cells


# ---------------------------------------------------------------------------
# 3. capex 对比表
# ---------------------------------------------------------------------------
def amt_text(ccy, m):
    if m is None:
        return "未披露"
    if ccy == "RMB":
        return f"{m / 100:,.1f}亿元"
    return f"{m / 1000:,.2f}bn美元"


def pct(cur, base):
    if cur is None or not base:
        return None
    return round((cur / base - 1) * 100, 1)


def build_capex_table():
    fx = P.FX["rmb_per_usd"]
    rows = []
    for cid in P.ORDER:
        k = P.CAPEX[cid]
        c = P.C[cid]
        ccy = k["ccy"]
        check_src_ids(k["src"], f"capex:{cid}")
        basis = {}
        for b in ("company", "cash"):
            v = k.get(b)
            base = k.get(f"base_{b}")
            prev = k.get(f"prior_{b}")
            usd = None if v is None else (round(v / fx) if ccy == "RMB" else v)
            yoy = pct(v, base)
            yoy_label = "计算"
            if (cid, b) in YOY_DISCLOSED:
                d, sid = YOY_DISCLOSED[(cid, b)]
                if yoy is None or round(yoy) != d:
                    err(f"capex:{cid}:{b}: 披露同比 {d}% 与计算值 {yoy}% 不符")
                yoy_label = "公开披露"
            basis[b] = {
                "value_m": v, "display": amt_text(ccy, v),
                "usd_m": usd,
                "usd_display": "未披露" if usd is None else f"{usd / 1000:,.2f}bn美元",
                "usd_label": "公开披露" if ccy == "USD" else ("公开披露" if cid in P.DISCLOSED_USD_M and b == "company" else "计算"),
                "base_m": base, "base_display": amt_text(ccy, base) if base is not None else "未披露",
                "yoy_pct": yoy, "yoy_display": "未披露" if yoy is None else f"{yoy:+.1f}%", "yoy_label": yoy_label,
                "prior_q_m": prev, "prior_q_display": amt_text(ccy, prev) if prev is not None else "未披露",
                "qoq_pct": pct(v, prev), "qoq_label": "计算",
                "definition": k[f"{b}_def"],
                "src": k["src"], "label": "公开披露",
            }
            if v is None:
                basis[b]["note"] = "公司未披露该口径"
        if ccy == "RMB" and cid in P.DISCLOSED_USD_M:
            got, want = basis["company"]["usd_m"], P.DISCLOSED_USD_M[cid]
            if abs(got - want) > 1:
                err(f"capex:{cid}: 折算美元 {got} 与公司披露 {want} 相差>1")
        same = k.get("company") == k.get("cash")
        rows.append({
            "company": cid, "name": c["name"], "period": c["latest"],
            "period_label": c["periods"][c["latest"]]["label"], "report_date": c["periods"][c["latest"]]["report_date"],
            "ccy": ccy, "company_basis": basis["company"], "cash_basis": basis["cash"],
            "same_basis": same,
            "basis_note": "公司只披露一个 capex 数，即现金口径（两列相同）" if same else "两套口径数值不同，见各自定义",
            "guidance": {"text": k["guidance"], "src": k["src"], "label": "公开披露"},
            "comparability": k.get("note", ""),
        })
    return {
        "fx": {"rmb_per_usd": fx, "date": "2026-06-30", "basis": P.FX["basis"], "src": P.FX["src"], "label": "公开披露"},
        "units": "原币百万（value_m）；展示：人民币亿元、美元十亿（bn）",
        "rows": rows,
        "notes": [
            "公司口径＝公司在业绩材料中称为 capex/资本开支的数；现金口径＝现金流量表购置物业设备（或公司 FCF 对账扣减项）。",
            "同比、环比除注明“公开披露”外均为本脚本按原币百万计算；腾讯现金口径按 0.1 十亿元精度计算。",
            "人民币按美联储 H.10 2026-06-30 汇率 6.7851 折美元：阿里/百度/京东与公司公告折算值逐一核对（差≤1 百万）；腾讯为本脚本计算。",
            "各家口径差异较大（含/不含融资租赁、含物流与开发物业等），跨公司比较请先看 definition 与 comparability。",
        ],
    }


YOY_RE = re.compile(r"同比约?([+\-−])(\d+(?:\.\d+)?)%")


def crosscheck_t1(cells, capex_table):
    """T1 单元格中的同比须与 capex 表计算值（公司口径或现金口径）相差 ≤1pp；非公告直接披露的同比自动加注。"""
    rows = {r["company"]: r for r in capex_table["rows"]}
    for c in cells:
        if c["topic"] != "T1":
            continue
        m = YOY_RE.search(c["value_short"])
        if not m:
            err(f"{c['id']}: T1 未写同比")
            continue
        v = float(m.group(2)) * (-1 if m.group(1) in "-−" else 1)
        r = rows[c["company"]]
        hit = [b for b in ("company_basis", "cash_basis")
               if r[b]["yoy_pct"] is not None and abs(r[b]["yoy_pct"] - v) <= 1.0]
        if not hit:
            err(f"{c['id']}: T1 同比 {v}% 与 capex 表计算值不符")
            continue
        if r[hit[0]]["yoy_label"] != "公开披露" and not c["label_note"]:
            c["label_note"] = f"金额为公开披露；同比为计算值（{r[hit[0]]['yoy_display']}，见 capex_table）"


def build_trajectory():
    out = []
    for r in P.TENCENT_TRAJECTORY:
        check_src_ids(r["src"], f"trajectory:{r['q']}")
        out.append({"quarter": r["q"], "capex_bn": r["capex"], "capex_paid_bn": r["paid"], "fcf_bn": r["fcf"],
                    "gap_bn": round(r["paid"] - r["capex"], 1), "gap_label": "计算",
                    "src": r["src"], "label": "公开披露", "call_src": r["call"]})
    return {"unit": "十亿元人民币", "rows": out,
            "note": "资本开支（公司口径）vs CAPEX Paid（现金付款）；差额为计算值。来源：腾讯各季业绩 PPT 与港交所公告。"}


# ---------------------------------------------------------------------------
# 4. 速评
# ---------------------------------------------------------------------------
def worst_label(labels):
    return max(labels, key=lambda x: LABEL_RANK.get(x, 9))


def build_flashes():
    out = []
    for fl in F.FLASHES:
        fid = fl["id"]
        for sec in ("conclusions", "ai_capex_guidance", "implications_for_tencent", "tencent_q3_questions"):
            for n, item in enumerate(fl[sec]):
                w = f"flash:{fid}:{sec}[{n}]"
                check_label(item["label"], w)
                check_src_ids(item["src"], w)
        if len(fl["conclusions"]) != 3:
            err(f"flash:{fid}: 结论先行应为 3 条")
        if len(fl["implications_for_tencent"]) != 3 or any(x["label"] != "推断" for x in fl["implications_for_tencent"]):
            err(f"flash:{fid}: 对腾讯口径的启示应为 3 条且均标“推断”")
        if len(fl["tencent_q3_questions"]) != 3:
            err(f"flash:{fid}: 腾讯Q3可能被追问的问题应为 3 条")
        if not 2 <= len(fl["quotes"]) <= 3:
            err(f"flash:{fid}: 管理层短引语应为 2–3 条")
        cell_ids = {f"{c}:{t['id']}" for c in P.ORDER for t in P.TOPICS}
        for n, q in enumerate(fl["tencent_q3_questions"]):
            for ref in q.get("public_statement_refs", []):
                if ref not in cell_ids:
                    err(f"flash:{fid}: 问题 {n} 引用了不存在的单元格 {ref}")
        for n, row in enumerate(fl["key_numbers"]):
            w = f"flash:{fid}:key_numbers[{n}]"
            check_label(row["label"], w)
            check_src_ids(row["src"], w)
            if not row.get("anchors"):
                err(f"{w}: 关键数字缺原文锚点")
            for sid, text in row.get("anchors", []):
                check_anchor(sid, text, w)
        quotes = []
        for n, q in enumerate(fl["quotes"]):
            w = f"flash:{fid}:quotes[{n}]"
            check_quote(q["text"], q["src"], w)
            o = quote_obj(q["text"], q["speaker"], q["src"])
            o["context"] = q.get("context", "")
            quotes.append(o)
        for extra, w in ((fl["why"], f"flash:{fid}:why"), (fl["analyst_focus"]["summary"], f"flash:{fid}:analyst_focus.summary")):
            check_label(extra["label"], w)
            check_src_ids(extra["src"], w)
        for n, a in enumerate(fl["analyst_focus"]["items"]):
            w = f"flash:{fid}:analyst_focus[{n}]"
            check_label(a["label"], w)
            check_src_ids(a["src"], w)
            if a.get("q"):
                check_quote(a["q"], a["qsrc"], w)
        o = {k: v for k, v in fl.items() if k != "quotes"}
        o["quotes"] = quotes
        o["key_numbers"] = [{k: v for k, v in r.items() if k != "anchors"} | {
            "anchors": [{"src": s, "text": t} for s, t in r["anchors"]]} for r in fl["key_numbers"]]
        o["watermark"] = WATERMARK
        out.append(o)
    return out


# ---------------------------------------------------------------------------
# 5. 公司、来源、重跑
# ---------------------------------------------------------------------------
RERUN_METHOD = [
    "1. 在 demo/pipeline/peer_fetch.py 的 FETCH 中加入新季度新闻稿（或 SEC 文件）与实录 URL，运行 python -I demo/pipeline/peer_fetch.py（只下载缺失文件）。",
    "2. 在 demo/pipeline/peer_data.py 该公司 snapshots 中新增期间快照，latest 改为新期间、prior 改为原 latest；同步更新 CAPEX、SOURCES、NUMBER_ANCHORS。",
    "3. 逐格人工填写 change_vs_prior（实质变化/口径变化/无变化/新增＋说明）。",
    "4. 运行 python -I demo/pipeline/peer.py：自动重算同比/折算，并逐条校验引语与数字锚点；任何一条找不到原文即构建失败。",
]


def build_companies_and_rerun():
    rerun_by = {r["company"]: r for r in P.RERUN}
    companies, rerun = [], []
    for cid in P.ORDER:
        c = P.C[cid]
        if c["status_src"]:
            check_src_ids(c["status_src"], f"company:{cid}")
        r = rerun_by.get(cid)
        rr = None
        if r:
            if r["src"]:
                check_src_ids(r["src"], f"rerun:{cid}")
            rr = {"event": r["event"], "date": r["date"], "confirmed": r["confirmed"], "src": r["src"],
                  "label": "公开披露" if r["confirmed"] else "推断",
                  "how": "发布后按 rerun_method 四步重跑；议题列 T1–T8 不变。"
                         + ("" if r["confirmed"] else "日期为参考上年同期的推断；公司公告发布日期后先更新 peer_data.RERUN。")}
            rerun.append({"company": cid, "name": c["name"], **rr})
        companies.append({
            "id": cid, "name": c["name"], "ticker": c["ticker"], "group": c["group"],
            "latest": c["latest"], "latest_label": c["periods"][c["latest"]]["label"],
            "latest_report_date": c["periods"][c["latest"]]["report_date"],
            "prior": c["prior"], "prior_label": c["periods"][c["prior"]]["label"],
            "status": c["status"], "status_src": c["status_src"],
            "rerun": rr,
        })
    rerun.sort(key=lambda x: (not x["confirmed"], x["date"]))
    return companies, rerun


def build_sources():
    out = []
    seen = set()
    for s in P.SOURCES:
        if s["id"] in seen:
            err(f"来源 id 重复：{s['id']}")
        seen.add(s["id"])
        if s["tier"] not in (1, 2, 3, 4):
            err(f"{s['id']}: tier 非法")
        if not (ROOT / s["local"]).exists():
            err(f"{s['id']}: 本地文件不存在 {s['local']}")
        o = {k: s[k] for k in ("id", "title", "url", "date", "tier")}
        o["local_copy"] = s["local"]
        if s.get("raw"):
            o["raw_copy"] = s["raw"]
        o["user_provided"] = bool(s.get("user_provided"))
        if s["kind"] == "json":
            o["verified_via"] = "核查底稿（data/research/parts），无本地原文；引语/数字以底稿中的核查记录为准"
        if s["tier"] == 3:
            o["note"] = QUOTE_NOTE_T3
        elif s["tier"] == 4:
            o["note"] = "媒体转述/二手"
        out.append(o)
    return out


# ---------------------------------------------------------------------------
# 6. 产物扫描与自检
# ---------------------------------------------------------------------------
def scan_text(text, where):
    hits = {"forbidden": [w for w in FORBIDDEN if w in text],
            "valuation": [w for w in VALUATION if w.lower() in text.lower()]}
    try:
        assert_no_email(text)
        hits["email"] = []
    except ValueError as e:
        hits["email"] = [str(e)]
    priv = []
    home = Path.home().name
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    for token in {home, user}:
        if token and len(token) >= 3 and token.lower() in text.lower():
            priv.append("本机用户名")
    if re.search(r"(?:[A-Za-z]:[\\/]{1,2}|/[a-z]/)Users[\\/]", text) or str(ROOT) in text:
        priv.append("绝对路径")
    hits["privacy"] = sorted(set(priv))
    for k, v in hits.items():
        if v:
            err(f"{where}: 扫描命中 {k}：{v}")
    return hits


def self_check(n_target=14, seed=20261026):
    pool = []
    for where, sid, text in QUOTE_LOG:
        if SRC[sid]["kind"] != "json":
            pool.append(("引语", where, sid, text))
    for where, sid, text in ANCHOR_LOG:
        if SRC[sid]["kind"] != "json":
            pool.append(("数字", where, sid, text))
    rng = random.Random(seed)
    nums = [p for p in pool if p[0] == "数字"]
    quotes = [p for p in pool if p[0] == "引语"]
    pick = rng.sample(nums, min(len(nums), n_target // 2)) + rng.sample(quotes, min(len(quotes), n_target - n_target // 2))
    results = []
    for kind, where, sid, text in pick:
        hay = raw_text(sid)
        ok = find_in(text, hay) >= 0
        if not ok:
            err(f"自检失败：{where} {sid} {text}")
        s = SRC[sid]
        results.append({"kind": kind, "where": where, "src": sid,
                        "file": s.get("raw") or s["local"], "text": text, "found": ok,
                        "context": snippet(hay, text, 50)})
    return results, len(pool)


def main():
    sources = build_sources()
    cells = build_cells()
    for n, (sid, text) in enumerate(P.NUMBER_ANCHORS):
        check_anchor(sid, text, f"NUMBER_ANCHORS[{n}]")
    capex_table = build_capex_table()
    crosscheck_t1(cells, capex_table)
    trajectory = build_trajectory()
    flashes = build_flashes()
    companies, rerun = build_companies_and_rerun()

    used = set()
    for c in cells:
        used.update(c["src"])
        if c["prior"]:
            used.update(c["prior"]["src"])
    for fl in flashes:
        for sec in ("conclusions", "ai_capex_guidance", "implications_for_tencent", "tencent_q3_questions", "key_numbers"):
            for it in fl[sec]:
                used.update(it["src"])
    unused = sorted(set(SRC) - used - {x for r in P.TENCENT_TRAJECTORY for x in r["src"]}
                    - {x for k in P.CAPEX.values() for x in k["src"]} - {x for c in P.C.values() for x in c["status_src"]}
                    - {x for r in P.RERUN for x in r["src"]} - {u["src"] for u in P.USER_PROVIDED} - set(P.FX["src"]))

    inputs = sorted({s["local"] for s in P.SOURCES} | {s["raw"] for s in P.SOURCES if s.get("raw")}
                    | {"demo/pipeline/peer_data.py", "demo/pipeline/peer_flash_data.py", "demo/pipeline/sa_transcript.py",
                       "data/src/peers/manifest.tsv"})
    payload = {
        "meta": {
            "module": MODULE,
            "title": "M1 同业矩阵与速评：8 家 × 8 议题 · capex 双口径 · Meta / 阿里速评",
            "as_of": AS_OF,
            "generated_by": "本地 Python",
            "content_by": "单元格与速评文字为人工整理；数字、引语由本脚本逐条比对本地原文后写出",
            "script": SCRIPT,
            "inputs": [input_record(ROOT / p) for p in inputs],
            "watermark": WATERMARK,
            "disclaimer": DISCLAIMER,
            "notes": ("截至 2026-10-26：Meta 已发布 2026Q3（10-21），矩阵用最新季；Alphabet、Microsoft、Amazon 分别于 10-28、10-28、10-29 发布，"
                      "暂用上一季并在 rerun 写明重跑方法；腾讯 Q3 董事会 11-18；阿里/百度/京东 9 月季度日期未公告。"
                      "第三方实录（StockAnalysis 等）为非官方逐字稿，分析师归属待录音复核；所有因果判断标“推断”。"
                      "已应用 capex-cn / capex-us / peer-flash-alibaba 核查中的更正与删除项（见 NOTES）。"),
            "labels": list(LABELS),
            "tiers": {"1": "公司公告/港交所/SEC", "2": "官方新闻稿/官方 webcast/官方 PPT", "3": "第三方文字稿（非官方逐字稿）", "4": "媒体/券商转述（二手）"},
        },
        "sources": sources,
        "user_provided_sources": P.USER_PROVIDED,
        "companies": companies,
        "topics": P.TOPICS,
        "cells": cells,
        "capex_table": capex_table,
        "tencent_capex_trajectory": trajectory,
        "flashes": flashes,
        "rerun": rerun,
        "rerun_method": RERUN_METHOD,
    }

    # 免责声明本身含"股价/估值"字样，扫描时剔除该字段
    scan_payload = {**payload, "meta": {k: v for k, v in payload["meta"].items() if k != "disclaimer"}}
    scan = scan_text(json.dumps(scan_payload, ensure_ascii=False), "m1_peer.json")
    picks, pool_n = self_check()

    n_cells = len(cells)
    n_quotes = len(QUOTE_LOG)
    n_anchor = len(ANCHOR_LOG)
    json_quotes = sum(1 for _, sid, _ in QUOTE_LOG if SRC[sid]["kind"] == "json")
    payload["meta"]["self_check"] = {
        "status": "pass" if not ERRORS else "fail",
        "cells": f"{n_cells} 格（{len(P.ORDER)} 家 × {len(P.TOPICS)} 议题）全部具备 value_short(≤20字)/src/label/change_vs_prior；上一季快照 {sum(1 for c in cells if c['prior'])} 格",
        "quotes_verified": f"{n_quotes} 条引语逐字比对通过（其中 {n_quotes - json_quotes} 条对本地原始文件，{json_quotes} 条仅能对核查底稿）",
        "anchors_verified": f"{n_anchor} 个数字锚点逐字比对通过",
        "src_ids": "所有 src 均存在于 sources；label 均属 公开披露/结构化数据/计算/推断",
        "fx_check": "阿里/百度/京东人民币折美元与公司披露值差 ≤1 百万；腾讯、阿里披露同比与计算一致",
        "scan": {"forbidden_words_hits": len(scan["forbidden"]), "valuation_terms_hits": len(scan["valuation"]),
                 "email_hits": len(scan["email"]), "privacy_hits": len(scan["privacy"]),
                 "note": "禁用词按 CONTRACT.md 第4节；估值/股价类用语另设词表扫描；隐私扫描含邮箱、本机用户名与绝对路径"},
        "random_spot_check": {"method": f"固定种子随机抽取（种子 {20261026}），从 {pool_n} 条可回溯到本地原始文件的数字/引语中抽 {len(picks)} 条，"
                                        "用不经解析器的原始文件文本重新查找",
                              "passed": sum(1 for p in picks if p["found"]), "total": len(picks), "items": picks},
        "manual_spot_check": F.MANUAL_SPOT_CHECK,
        "unused_sources": unused,
    }

    if ERRORS:
        print(f"构建失败：{len(ERRORS)} 个问题")
        for e in ERRORS:
            print(" -", e)
        sys.exit(1)
    path = write_module(MODULE, payload)
    print(f"OK -> {rel(path)} | cells={n_cells} quotes={n_quotes} anchors={n_anchor} "
          f"spot_check={sum(1 for p in picks if p['found'])}/{len(picks)} unused_sources={unused}")


if __name__ == "__main__":
    main()
