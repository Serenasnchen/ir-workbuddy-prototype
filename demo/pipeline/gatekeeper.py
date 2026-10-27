"""M4 数字守门员（Number Gatekeeper）：确定性抽取 · 五方勾稽 · capex 三口径 · 草稿检查 · 注入测试。

全部为正则 + 单位归一的确定性代码，不调用任何大模型；本脚本不发起网络请求
（capex 现金口径所需的 10-12 发债公告已在 data/src/ir_official/ 本地存在）。

运行（在 ROOT 下）：
  python -I demo/pipeline/gatekeeper.py extract            # 文本层 + 6 个季度的关键指标注册表
  python -I demo/pipeline/gatekeeper.py tieout             # 2Q26 五方勾稽矩阵 + capex 三口径
  python -I demo/pipeline/gatekeeper.py check --draft F [--lang en|zh] [--quarter 2Q26] [--twin G]
                                                          # 检查一份草稿（每段一行），打印红/黄告警
  python -I demo/pipeline/gatekeeper.py check --eval [--seed 7 --n 30]
                                                          # 注入测试召回率 + 其他季度干净段落误报率
  python -I demo/pipeline/gatekeeper.py all                # 依次执行以上全部并写 demo/data/m4_gatekeeper.json
输入（只读）：data/src/ir_official/{1Q25..2Q26}_{release_en,release_zh,hkex_en,hkex_zh,ppt}.pdf/.txt、manifest.tsv、
  2026-10-12_E700_Launch-Announcement.pdf/.txt；data/src/market_raw/dl/tc_ir26.txt（2026 中报）。
派生：demo/data/raw/m4/txt/*.txt（PyMuPDF UTF-8 文本层）、demo/data/raw/m4/inject/*（注入草稿与答案）。
"""
import argparse
import json
import re
import sys

sys.dont_write_bytecode = True  # 不写 .pyc（字节码文件会记录本机绝对路径）
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AS_OF, DATA_SRC, ROOT, assert_no_email, input_record, write_module  # noqa: E402
import gk_core as g  # noqa: E402

RAW = g.RAW
INJ_DIR = RAW / "inject"
LAUNCH_PDF = DATA_SRC / "ir_official" / "2026-10-12_E700_Launch-Announcement.pdf"
LAUNCH_TXT = DATA_SRC / "ir_official" / "2026-10-12_E700_Launch-Announcement.txt"
LAUNCH_URL = "https://www.tencent.com/wp-content/uploads/2026/10/E700_Launch-Announcement.pdf"
IR26_TXT = DATA_SRC / "market_raw" / "dl" / "tc_ir26.txt"
IR26_URL = "https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf"
RESULT_DATE = {"1Q25": "2025-05-14", "2Q25": "2025-08-13", "3Q25": "2025-11-13", "4Q25": "2026-03-18",
               "1Q26": "2026-05-13", "2Q26": "2026-08-12"}
TIER = {"release_en": 2, "release_zh": 2, "hkex_en": 1, "hkex_zh": 1, "ppt": 2}
BANNED = ["颠覆", "革命性", "首创", "全面领先", "赋能", "取代IR"]
VALUATION = re.compile(r"市盈率|目标价|估值|P/E|price target|低估|高估")
WATERMARK = "内部准备材料，不构成公司口径"


# ---------------------------------------------------------------------------
# 来源登记
# ---------------------------------------------------------------------------
def build_sources():
    man = {}
    for line in (g.IR / "manifest.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            man[(parts[0], parts[1])] = parts[3]
    sources, sid = [], {}

    def add(key, title, url, date, tier, local):
        i = f"S{len(sources) + 1:02d}"
        sources.append({"id": i, "title": title, "url": url, "date": date, "tier": tier, "local_copy": local})
        sid[key] = i

    for kind in g.KINDS:
        add((g.TARGET, kind), f"腾讯 {g.TARGET} {g.KIND_ZH[kind]}", man[(g.TARGET, kind)], RESULT_DATE[g.TARGET],
            TIER[kind], f"data/src/ir_official/{g.TARGET}_{kind}.pdf")
    add("ir26", "腾讯 2026 年中期报告（Interim Report 2026；董事会 2026-08-12 批准）", IR26_URL, "2026-08-12", 1,
        "data/src/market_raw/dl/tc_ir26.pdf")
    add("launch", "腾讯港交所公告：GMTN 计划下建议发行票据及财务资料摘录（发债 Launch Announcement）", LAUNCH_URL,
        "2026-10-12", 1, "data/src/ir_official/2026-10-12_E700_Launch-Announcement.pdf")
    for q in g.QUARTERS[:-1]:
        for kind in g.KINDS:
            add((q, kind), f"腾讯 {q} {g.KIND_ZH[kind]}（干净对照样本）", man[(q, kind)], RESULT_DATE[q], TIER[kind],
                f"data/src/ir_official/{q}_{kind}.pdf")
    return sources, sid


# ---------------------------------------------------------------------------
# extract：注册表
# ---------------------------------------------------------------------------
def build_all_registries(kinds):
    regs = {q: g.build_registry(q, kinds) for q in g.QUARTERS}
    return g.attach_priors(regs)


def claim_ref(c, sid, q=None):
    """把一条抽取结果整理成可点回原文的引用（派生文本行号 + 原 pdftotext 行号）。"""
    q = q or g.TARGET
    tok = c.num.token if c.num is not None else (c.growth[0].raw if c.growth else "")
    if c.mode in ("table", "row") and c.num is not None:
        tok = c.num.raw.strip("()+-")
    tl = g.orig_line(q, c.kind, c.page, (tok or "").strip("%"), c.text or c.quote or "") if c.page else None
    return {"doc": c.kind, "file": f"demo/data/raw/m4/txt/{q}_{c.kind}.txt", "line": c.line, "page": c.page,
            "orig_txt": f"data/src/ir_official/{q}_{c.kind}.txt", "txt_line": tl,
            "quote": (c.quote or "")[:220], "mode": c.mode, "src": [sid[(q, c.kind)]]}


def disp_value(e):
    cls, v, h = e["cls"], e["value"], e["half"]
    if cls in ("RMB", "HKD"):
        cur = "人民币" if cls == "RMB" else "港元"
        if h <= 1.0 + 1e-9:
            return f"{v:,.0f} 百万元（{cur}）" if cls == "RMB" else f"{v:,.0f} 百万港元"
        bn = v / 1000
        return f"{v / 100:,.0f} 亿元（{cur}{bn:,.1f}bn）" if cls == "RMB" else f"{v / 100:,.0f} 亿港元"
    if cls == "count":
        return f"{v:,.2f} 百万".replace(".00 ", " ") if h < 0.5 else f"{v:,.0f} 百万"
    if cls == "pct":
        return f"{v:.2f}%" if e.get("calc") else f"{v:g}%"
    return f"人民币 {v:g} 元"


def registry_payload(regs, sid):
    reg = regs[g.TARGET]
    out = []
    for m in g.METRICS:
        e = reg[m.id]
        if "value" not in e:
            continue
        item = {"id": m.id, "name_zh": m.zh, "name_en": m.en, "category": m.cat, "cls": m.cls, "headline": m.key,
                "value": round(e["value"], 6), "half_tol": round(e["half"], 6), "display": disp_value(e),
                "unit": {"RMB": "人民币百万元", "HKD": "港元百万", "count": "百万", "pct": "%", "RMB1": "人民币元/股"}[m.cls]}
        if e.get("calc"):
            parts = list(m.calc or m.calc_sum)
            srcs = set()
            for x in parts:
                if reg[x].get("src") is not None:
                    srcs |= set(claim_ref(reg[x]["src"], sid)["src"])
            how = (f"{parts[0]} / {parts[1]} × 100（区间传播四舍五入误差）" if m.calc else " + ".join(parts))
            item.update(label="计算", src=sorted(srcs), method=how)
        else:
            ref = claim_ref(e["src"], sid)
            item.update(label="公开披露", src=ref["src"], canonical=ref, support_docs=e["support"], n_mentions=e["n"])
        if m.note:
            item["note"] = m.note
        for kind in ("yoy", "qoq"):
            if kind in e:
                gs = e[kind]
                item[kind] = {"value": gs["value"], "half_tol": gs["half"], "label": "公开披露",
                              "src": claim_ref(gs["src"], sid)["src"], "support_docs": gs["support"]}
        for key, gk in (("prior_y", "prior_y_growth"), ("prior_q", "prior_q_growth")):
            if key in e:
                item[key] = {"quarter": e[key]["q"], "value": round(e[key]["value"], 6), "half_tol": round(e[key]["half"], 6),
                             "label": "公开披露" if not regs[e[key]["q"]][m.id].get("calc") else "计算",
                             "src": [sid[(e[key]["q"], regs[e[key]["q"]][m.id]["src"].kind)]]
                             if regs[e[key]["q"]][m.id].get("src") else []}
            if gk in e:
                item[gk.replace("prior_", "calc_").replace("_growth", "_growth_pct")] = {
                    "value": round(e[gk]["value"], 3), "half_tol": round(e[gk]["half"], 3), "label": "计算",
                    "src": item["src"] + item.get(key, {}).get("src", [])}
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# tieout：五方勾稽矩阵
# ---------------------------------------------------------------------------
def _cell_scale(c):
    pc = g.parse_cell(c.cells[c.col]) if c.cells else None
    if pc and pc[1]:
        return abs(c.num.value / pc[1]) if c.num.value else 1.0
    return 1.0


def _anchored(c, e):
    """表格行是否可认定为 2Q26 口径：首列与规范值一致，或第二列与上年同季/上一季规范值一致。"""
    m = g.MET[c.metric]
    if g.consistent(g.cval(m, c.num), c.num.half, e["value"], e["half"]):
        return True
    if c.col != 0 or not c.cells or len(c.cells) < 2:
        return False
    pc = g.parse_cell(c.cells[1])
    if not pc or pc[0] != ("pct" if m.cls == "pct" else "num"):
        return False
    sc = _cell_scale(c)
    v1 = pc[1] * sc
    v1 = v1 if m.signed else abs(v1)
    for key in ("prior_y", "prior_q"):
        p = e.get(key)
        if p and g.consistent(v1, pc[2] * sc, p["value"], p["half"]):
            return True
    return False


def hit_record(c, e, sid, typ, gr=None, q=None):
    m = g.MET[c.metric]
    rec = claim_ref(c, sid, q)
    if typ == "value":
        v, h = g.cval(m, c.num), c.num.half
        rv, rh = e["value"], e["half"]
        rec.update(type="value", raw=c.num.raw, norm=round(v, 6), half_tol=round(h, 6))
        if c.num.cls != m.cls:
            rec.update(verdict="不一致", judgement="单位/币种不同", ok=False)
            return rec
    else:
        ref = (e.get(gr.kind) or {})
        if not ref:
            return None
        v, h, rv, rh = gr.value, gr.half, ref["value"], ref["half"]
        rec.update(type=gr.kind, raw=gr.raw, norm=v, half_tol=h)
    ok = g.consistent(v, h, rv, rh)
    if ok:
        exact = abs(v - rv) < 1e-9 and abs(h - rh) < 1e-12
        rec.update(verdict="一致" if exact else "一致（四舍五入）", ok=True)
    else:
        rec.update(verdict="不一致", judgement=g.judge_mismatch(v, h, rv, rh), ok=False)
    rec["label"] = "公开披露"
    return rec


def tieout(regs, sid, q=None):
    q = q or g.TARGET
    reg = regs[q]
    rows, discrepancies, rounding = [], [], []
    full_hits = {}
    summary = {"一致": 0, "不一致": 0, "未出现": 0}
    unanchored = 0
    for m in g.METRICS:
        e = reg[m.id]
        if "value" not in e:
            continue
        row = {"id": m.id, "name_zh": m.zh, "cls": m.cls, "canonical": disp_value(e),
               "canonical_label": "计算" if e.get("calc") else "公开披露", "cells": {}}
        for kind in g.KINDS:
            hits = []
            for c in e["claims"]:
                if c.kind != kind or not c.period_ok:
                    continue
                if c.num is not None:
                    if c.mode == "table" and not _anchored(c, e):
                        unanchored += 1
                    else:
                        r = hit_record(c, e, sid, "value", None, q)
                        if r:
                            hits.append(r)
                for gr in c.growth or []:
                    if c.mode == "table" and c.num is not None and not _anchored(c, e):
                        continue
                    r = hit_record(c, e, sid, gr.kind, gr, q)
                    if r:
                        hits.append(r)
            # 去重：同一行同一取值只记一次
            seen, uniq = set(), []
            for h in hits:
                k = (h["type"], h["line"], h["raw"])
                if k not in seen:
                    seen.add(k)
                    uniq.append(h)
            status = "未出现" if not uniq else ("一致" if all(h["ok"] for h in uniq) else "不一致")
            summary[status] += 1
            shown = [h for h in uniq if not h["ok"]] + [h for h in uniq if h["ok"]]
            row["cells"][kind] = {"status": status, "n": len(uniq), "src": [sid[(q, kind)]], "label": "公开披露",
                                  "hits": [_compact(h) for h in shown[:(2 if status == "一致" else 4)]]}
            full_hits[(m.id, kind)] = uniq
            for h in uniq:
                if not h["ok"]:
                    canon = e.get(h["type"]) if h["type"] in ("yoy", "qoq") else None
                    csrc = canon["src"] if canon else e.get("src")
                    cref = claim_ref(csrc, sid, q) if csrc is not None else None
                    discrepancies.append({
                        "metric": m.id, "name_zh": m.zh, "type": h["type"], "doc": kind, "found": h["raw"],
                        "found_norm": h["norm"],
                        "expected": (f"{canon['value']:g}%" if canon else disp_value(e)),
                        "judgement": h["judgement"], "found_at": {k: h[k] for k in ("file", "line", "txt_line", "quote")},
                        "expected_at": ({k: cref[k] for k in ("doc", "file", "line", "txt_line", "quote")} if cref else
                                        {"method": "由注册表规范值计算"}),
                        "src": sorted(set(h["src"] + (cref["src"] if cref else []))), "label": "计算",
                        "note": _disc_note(m, h, e, q)})
        rows.append(row)
    # 四舍五入展示差异（判定一致）：同一指标在不同文件以不同精度出现的典型例子
    for row in rows:
        m = g.MET[row["id"]]
        for typ in ("value", "yoy", "qoq"):
            hs = [h for k in g.KINDS for h in full_hits[(row["id"], k)] if h["type"] == typ and h["ok"]]
            if not hs:
                continue
            if typ == "value" and m.cls in ("RMB", "HKD"):
                hs = [h for h in hs if h["half_tol"] >= 5]  # 只比较"十亿/亿元"级展示，略过百万元表格
            disp = {}
            for h in hs:
                disp.setdefault((h["norm"], h["half_tol"]), []).append(h)
            if len(disp) >= 2 and (typ != "value" or m.cls in ("pct", "count") or any(k[1] >= 400 for k in disp)):
                variants = [{"raw": v[0]["raw"], "docs": sorted(set(x["doc"] for x in v)),
                             "lines": [f"{x['doc']}:{x['line']}" for x in v][:4], "label": "公开披露",
                             "src": sorted(set(s for x in v for s in x["src"]))} for k, v in sorted(disp.items())]
                rounding.append({"metric": row["id"], "name_zh": row["name_zh"], "type": typ, "variants": variants,
                                 "judgement": "四舍五入（判定一致）", "label": "计算",
                                 "src": sorted(set(s for v in disp.values() for x in v for s in x["src"]))})
    return {"quarter": q, "docs": [{"kind": k, "name": g.KIND_ZH[k], "src": [sid[(q, k)]]} for k in g.KINDS],
            "summary": summary, "n_metrics": len(rows), "unanchored_table_rows_ignored": unanchored,
            "rows": rows, "discrepancies": discrepancies, "rounding_cases": rounding}


def _compact(h):
    out = {k: h[k] for k in ("type", "raw", "verdict", "line", "txt_line", "mode", "src", "label") if k in h}
    if h.get("judgement"):
        out["judgement"] = h["judgement"]
    out["quote"] = (h.get("quote") or "")[:90]
    return out


def _disc_note(m, h, e, q=None):
    """末位差异：给出同精度下的四舍五入值与截断值，供人工判断（对'截断取值'的解释标为推断）。"""
    if h.get("judgement") != "末位差异" or h["type"] != "value":
        return ""
    import math
    unit = 2 * h["half_tol"]
    rv = abs(e["value"])
    rounded = math.floor(rv / unit + 0.5) * unit
    trunc = math.floor(rv / unit) * unit
    found = abs(h["norm"])
    scale, name = (1000.0, "bn") if unit >= 100 - 1e-9 and unit < 1000 else (100.0, "亿") if unit >= 10 else (1.0, "")
    if abs(found - trunc) < 1e-6 * max(1, rv):
        how = "与截断取值一致（推断：文字表述按截断而非四舍五入取数）"
    else:
        how = "既非四舍五入也非截断，需 IR/财务确认取数来源"
    extra = ""
    if m.id == "ga_exp" and (q or g.TARGET) == g.TARGET:
        extra = "；PPT 经营开支 (50.6) 与 11,869+38,808=50,677 亦差 0.1"
    return (f"表格规范值 {rv:,.0f} 百万元，按文字同精度四舍五入应为 {rounded / scale:g}{name}、截断为 {trunc / scale:g}{name}，"
            f"文字为 {found / scale:g}{name}：{how}{extra}。不影响合计，建议定稿前统一口径")


# ---------------------------------------------------------------------------
# capex 三套口径
# ---------------------------------------------------------------------------
def _find_row(doc, label_rx, min_cells=5):
    for variants, cells, cl in g.table_rows(doc):
        for lab, lines in variants:
            if re.fullmatch(label_rx, lab.strip()) and len(cells) >= min_cells:
                return cells, [x + 1 for x in cl], lab
    return None


def _orig_text_lines(path, enc):
    return path.read_bytes().decode(enc).replace("\r", "").split("\n")


def capex_triad(regs, sid):
    rows, checks = [], []
    # A. 会计口径（港交所业绩公告"其他财务资料"表：三个月 2Q26/1Q26/2Q25 + 六个月 1H26/1H25）
    d = g.get_doc(g.TARGET, "hkex_en")
    cells, lines, lab = _find_row(d, r"Capital expenditures(?: \(d\))?")
    vals = [g.parse_cell(x)[1] for x in cells[:5]]
    q2, q1, q2y, h1, h1y = vals
    hk_lines = {"2Q26": lines[0], "1Q26": lines[1], "2Q25": lines[2], "1H26": lines[3], "1H25": lines[4]}
    ir_lines = _orig_text_lines(IR26_TXT, "utf-8")
    ir_ln = next((i + 1 for i, t in enumerate(ir_lines) if re.match(r"Capital expenditures \(d\) 52,784", t)), None)
    acc = [("2Q26", q2), ("1Q26", q1), ("2Q25", q2y), ("1H26", h1), ("1H25", h1y)]
    for per, v in acc:
        rows.append({"basis": "会计口径（资本开支，权责发生制）", "period": per, "value_rmb_m": v,
                     "display": f"{v / 100:,.1f} 亿元", "label": "公开披露",
                     "src": [sid[(g.TARGET, "hkex_en")]] + ([sid["ir26"]] if per in ("2Q26", "1H26") else []),
                     "at": {"file": f"demo/data/raw/m4/txt/{g.TARGET}_hkex_en.txt", "line": hk_lines[per],
                            "interim_report_txt": "data/src/market_raw/dl/tc_ir26.txt", "interim_report_line": ir_ln},
                     "definition": "Capital expenditures primarily consist of investments in IT infrastructure ..., data centres, "
                                   "land use rights, office premises and intellectual properties (excluding media content)"})
    checks.append({"check": "1H26 会计口径 = 1Q26 + 2Q26", "lhs": h1, "rhs": q1 + q2, "ok": abs(h1 - (q1 + q2)) <= 1.0,
                   "label": "计算", "src": [sid[(g.TARGET, "hkex_en")]]})
    # 全年会计口径（4Q25 港交所年度业绩公告同表，年度列）
    d4 = g.get_doc("4Q25", "hkex_en")
    c4, l4, _ = _find_row(d4, r"Capital expenditures(?: \(d\))?")
    fy25 = g.parse_cell(c4[3])[1]
    rows.append({"basis": "会计口径（资本开支，权责发生制）", "period": "FY2025", "value_rmb_m": fy25,
                 "display": f"{fy25 / 100:,.1f} 亿元", "label": "公开披露", "src": [sid[("4Q25", "hkex_en")]],
                 "at": {"file": "demo/data/raw/m4/txt/4Q25_hkex_en.txt", "line": l4[3]}})
    # B. 现金支付口径（10-12 发债公告：amount paid）
    lt = _orig_text_lines(LAUNCH_TXT, "latin-1")
    start = next(i for i, t in enumerate(lt) if "Our capital expenditures consist of the amount paid" in t)
    para = " ".join(x.strip() for x in lt[start:start + 8])
    mm = re.search(r"which amounted to (.*?) for the years\s+ended 31 December 2023, 2024 and 2025 and the six months "
                   r"ended 30 June 2025\s+and 2026, respectively", para)
    amts = re.findall(r"RMB\s?(\d+(?:\.\d+)?)\s+billion", mm.group(1))
    usd = re.search(r"\(US\$(\d+(?:\.\d+)?) billion\)", mm.group(1))
    cash = dict(zip(["FY2023", "FY2024", "FY2025", "1H25", "1H26"], [float(x) * 1000 for x in amts]))
    amt_line = {}
    for per, x in zip(["FY2023", "FY2024", "FY2025", "1H25", "1H26"], amts):
        amt_line[per] = next((start + k + 1 for k in range(8) if f"RMB{x}" in lt[start + k]), start + 1)
    for per in ("FY2023", "FY2024", "FY2025", "1H25", "1H26"):
        rows.append({"basis": "现金支付口径（发行文件：amount paid for investments）", "period": per,
                     "value_rmb_m": cash[per], "display": f"{cash[per] / 100:,.0f} 亿元", "label": "公开披露",
                     "src": [sid["launch"]],
                     "at": {"orig_txt": "data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt",
                            "txt_line": amt_line[per], "paragraph_start_line": start + 1, "quote": para[:420]},
                     "note": ("另注 US$" + usd.group(1) + " billion") if per == "1H26" and usd else ""})
    # C. 季度资本开支付款（自由现金流口径）
    e = regs[g.TARGET]["capex_pay"]
    pay_refs = [claim_ref(c, sid) for c in e["claims"] if c.num is not None and c.period_ok]
    pay_refs = [r for r in pay_refs if r["mode"] == "prose"]
    ir_pay = [i + 1 for i, t in enumerate(ir_lines) if "capital expenditure payments of RMB59.3" in t]
    rows.append({"basis": "季度资本开支付款（自由现金流计算口径）", "period": "2Q26", "value_rmb_m": e["value"],
                 "display": f"{e['value'] / 100:,.0f} 亿元", "label": "公开披露",
                 "verification": "已核实：2Q26 中英文新闻稿、港交所中英文业绩公告、2026 中报均有同一表述",
                 "src": sorted(set(s for r in pay_refs for s in r["src"])) + [sid["ir26"]],
                 "at": {"mentions": [{k: r[k] for k in ("doc", "file", "line", "txt_line", "quote")} for r in pay_refs],
                        "interim_report_lines": ir_pay},
                 "definition": "FCF = 经营活动现金净额 − 资本开支付款 − 媒体内容付款 − 租赁负债付款"})
    q1_implied = cash["1H26"] - e["value"]
    rows.append({"basis": "季度资本开支付款（自由现金流计算口径）", "period": "1Q26（推算）", "value_rmb_m": q1_implied,
                 "display": f"{q1_implied / 100:,.0f} 亿元", "label": "计算",
                 "src": [sid["launch"], sid[(g.TARGET, "hkex_en")]],
                 "note": "推算值 = 发债公告 1H26 现金口径 963 亿元 − 2Q26 资本开支付款 593 亿元；1Q26 材料未单独披露该数"})
    # 差异
    fcf = regs[g.TARGET]
    recon = fcf["ocf"]["value"] - fcf["capex_pay"]["value"] - fcf["media_pay"]["value"] - fcf["lease_pay"]["value"]
    checks.append({"check": "2Q26 FCF = 经营现金 527 − 资本开支付款 593 − 媒体内容 50 − 租赁 22（亿元）",
                   "lhs": fcf["fcf"]["value"], "rhs": round(recon, 1),
                   "ok": abs(fcf["fcf"]["value"] - recon) <= 200, "label": "计算", "src": [sid[(g.TARGET, "hkex_en")]]})
    diffs = [
        {"item": "1H26：现金口径 − 会计口径", "value_rmb_m": cash["1H26"] - h1,
         "display": f"{(cash['1H26'] - h1) / 100:,.1f} 亿元", "label": "计算", "src": [sid["launch"], sid[(g.TARGET, "hkex_en")]]},
        {"item": "FY2025：现金口径 − 会计口径", "value_rmb_m": cash["FY2025"] - fy25,
         "display": f"{(cash['FY2025'] - fy25) / 100:,.1f} 亿元", "label": "计算", "src": [sid["launch"], sid[("4Q25", "hkex_en")]]},
        {"item": "1H25：现金口径 − 会计口径", "value_rmb_m": cash["1H25"] - h1y,
         "display": f"{(cash['1H25'] - h1y) / 100:,.1f} 亿元", "label": "计算", "src": [sid["launch"], sid[(g.TARGET, "hkex_en")]]},
        {"item": "2Q26：资本开支付款 − 会计口径资本开支", "value_rmb_m": e["value"] - q2,
         "display": f"{(e['value'] - q2) / 100:,.1f} 亿元", "label": "计算", "src": [sid[(g.TARGET, "hkex_en")]]},
    ]
    return {"rows": rows, "differences": diffs, "checks": checks,
            "reading": ("三套数字口径不同、不可互相替代：会计口径按权责发生制确认（2Q26 528 亿元，1H26 847.2 亿元）；"
                        "发行文件按'已支付金额'统计（1H26 963 亿元、FY2025 883 亿元）；季度'资本开支付款'是自由现金流的扣减项"
                        "（2Q26 593 亿元）。对外引用时须写明口径。FY2025、1H26 现金口径分别高出会计口径约 91 亿、116 亿元，1H25 则"
                        "略低约 7 亿元；差异原因公司未逐项说明（推断：付款与确认的时间差），由财务按惯例确认。"),
            "reading_label": "推断"}


# ---------------------------------------------------------------------------
# check：草稿检查器
# ---------------------------------------------------------------------------
STOP_EN = set("""with that this were have been from year quarter quarters billion million which their there these those
compared same period last approximately about total also into over more than under versus during respectively such
other while where when being would could should company group second first third fourth increased decreased grew
rose growth higher lower mainly primarily driven reflecting basis including excluding""".split())
STOP_ZH = {"同比", "增长", "人民", "民币", "亿元", "二零", "零二", "年第", "第二", "季的", "环比", "下降", "百万", "万元",
           "我们", "本公司", "公司", "主要", "以及", "由于", "其中", "去年", "同期", "上季"}


SYN_EN = {"capex": {"capital", "expenditure"}, "expenditure": {"capex"}, "repurchased": {"repurchase", "shares"},
          "subscriptions": {"subscription"}, "subscription": {"subscriptions"}}


def ctx_tokens(text, s, e, lang):
    if lang == "en":
        w = text[max(0, s - 90):e + 60]
        toks = {x.lower() for x in re.findall(r"[A-Za-z][A-Za-z\-']{3,}", w)} - STOP_EN
        for t in list(toks):
            toks |= SYN_EN.get(t, set())
        return toks
    w = text[max(0, s - 30):e + 20]
    cjk = re.sub(r"[^\u4e00-\u9fff]+", " ", w).split()
    return {seg[i:i + 2] for seg in cjk for i in range(len(seg) - 1)} - STOP_ZH


def build_corpus(q, kinds):
    """参照文件中的全部数字（带上下文词），用于判定草稿数字是否"已披露"。"""
    out = []
    for kind in kinds:
        doc = g.get_doc(q, kind)
        for p in doc.paras:
            for n in g.parse_numbers(p.text, doc.lang):
                out.append((n.cls, n.value, n.half, doc.lang, ctx_tokens(p.text, n.start, n.end, doc.lang)))
        for variants, cells, cl in g.table_rows(doc):
            lab = variants[min(1, len(variants) - 1)][0]
            toks = ctx_tokens(lab, 0, len(lab), doc.lang) | ctx_tokens(variants[0][0], 0, len(variants[0][0]), doc.lang)
            u = g._lookback(doc, variants[0][1][0] + 1, g.RE_UNIT_HDR, 90)
            scale = 1000.0 if (u is not None and re.search("billion", doc.norm[u], re.I)) or (u is None and kind == "ppt") else 1.0
            for c in cells:
                pc = g.parse_cell(c)
                if not pc:
                    continue
                if pc[0] == "pct":
                    out.append(("pct", pc[1], pc[2], doc.lang, toks))
                elif pc[0] == "num":
                    out.append(("RMB", abs(pc[1]) * scale, pc[2] * scale, doc.lang, toks))
                    out.append(("count", abs(pc[1]), pc[2], doc.lang, toks))
                    out.append(("RMB1", abs(pc[1]), pc[2], doc.lang, toks))
                    out.append(("cell", pc[1], pc[2], doc.lang, toks))
    return out


ZH_EN_TERMS = {"现金": {"cash"}, "总现": {"total"}, "自由": {"free"}, "资本": {"capital", "capex"},
               "开支": {"expenditure", "expenses"}, "回购": {"repurchased", "repurchase"}, "股份": {"shares"},
               "万股": {"shares"}, "盈利": {"profit"}, "收入": {"revenues", "revenue"}, "毛利": {"gross"},
               "利润": {"margin", "profit"}, "股息": {"dividend"}, "派付": {"dividend"}, "净现": {"net"},
               "经营": {"operating"}, "公允": {"fair"}, "账面": {"book", "carrying"}, "上市": {"listed"},
               "订阅": {"subscriptions"}, "游戏": {"games"}, "营销": {"marketing"}, "云服": {"cloud"},
               "视频": {"video"}, "广告": {"advertising"}, "付款": {"payments"}, "媒体": {"media"},
               "租赁": {"lease"}, "代价": {"consideration"}, "摊薄": {"diluted"}, "基本": {"basic"},
               "每股": {"share"}, "用户": {"users", "user"}, "时长": {"time", "spent"}, "社交": {"social"},
               "金融": {"fintech"}, "科技": {"fintech"}, "企业": {"business"}, "分占": {"share"},
               "联营": {"associates"}, "所得": {"income"}, "税开": {"expense"}, "利息": {"interest"},
               "财务": {"finance"}, "成本": {"costs"}, "投资": {"investee", "investments"}}


def disclosed(n, toks, lang, corpus):
    """草稿数字是否已在参照文件中以"同类、四舍五入一致、且上下文至少共享 1 个实词"的形式出现。"""
    cls = n.cls
    toks_en = set()
    if lang == "zh":
        for t in toks:
            toks_en |= ZH_EN_TERMS.get(t, set())
    for (c, v, h, lg, ct) in corpus:
        if c != cls:
            continue
        if lg == lang:
            need_toks = toks
        elif lang == "zh" and lg == "en" and toks_en:
            need_toks = toks_en
        else:
            continue
        need = 2 if len(ct) > 3 and len(need_toks) > 3 else 1   # 表格行标签等短语境只要求 1 个共享实词
        if g.consistent(abs(v) if cls != "pct" else v, h, abs(n.value) if cls != "pct" else n.value, n.half) \
                and len(ct & need_toks) >= need:
            return True
    return False


class DPara:
    __slots__ = ("idx", "raw", "bullet", "body", "cells", "period", "heading")


def load_draft_paras(paras, lang, q):
    out, period = [], q
    for i, raw in enumerate(paras):
        p = DPara()
        p.idx, p.raw, p.cells, p.heading = i, raw, None, False
        t = g.normalize(raw.strip(), lang)
        m = re.match(r"^([▪•\-])\s+(.*)$", t)
        p.bullet, p.body = (m.group(1), m.group(2)) if m else (None, t)
        hp = g.heading_period(p.body, lang)
        if hp:
            period = hp
            p.heading = True
        rm = re.match(r"^(.*?[^\d\s,.%()+\-])\s+((?:[\(\-+]?\d[\d,]*(?:\.\d+)?\)?%?\s+){1,7}[\(\-+]?\d[\d,]*(?:\.\d+)?\)?%?)$",
                      p.body)
        if rm and len(rm.group(1)) <= 80 and not p.heading and len(rm.group(2).split()) >= 3:
            p.body, p.cells = rm.group(1), rm.group(2).split()
        p.period = period
        # 偏移：bullet 前缀长度（flag 坐标统一对齐到原始段落文本）
        out.append(p)
    return out


def _off(p):
    return len(p.raw) - len(p.raw.lstrip()) + ((len(p.bullet) + 1) if p.bullet else 0)


def _flag(p, s, e, rule, sev, cat, msg, **kw):
    o = _off(p)
    d = {"para": p.idx, "start": s + o, "end": e + o, "rule": rule, "severity": sev, "category": cat, "msg": msg,
         "text": p.raw[s + o:e + o]}
    d.update(kw)
    return d


def _draft_numbers(p, lang):
    full = p.body + ((" " + " ".join(p.cells)) if p.cells else "")
    nums = g.parse_numbers(full, lang)
    if p.cells:
        pos = len(p.body) + 1
        for c in p.cells:
            pc = g.parse_cell(c)
            if pc and pc[0] == "num":
                nums.append(g.Num("cell", pc[1], pc[2], c, pos, pos + len(c), token=c))
            pos += len(c) + 1
    return full, nums


def check_draft(paras, lang, q, reg, corpus, twin=None, twin_lang=None):
    """返回告警列表。红色：R1 数值不符 / R2 同比环比不符 / R3 中英文不一致 / R4 勾稽不平 / R5 百分比与数值不符 /
    R7 汇率换算不符；黄色：R6 参照文件中未找到同语境数字（疑似未披露新数字）。"""
    dps = load_draft_paras(paras, lang, q)
    flags, mentions, checked = [], {}, 0
    ctx = g.Ctx()
    for p in dps:
        if p.heading:
            continue
        full, nums = _draft_numbers(p, lang)
        claims = g.parse_para(p.body, lang, ctx, p.bullet, p.cells)
        resolved = []
        for c in claims:
            in_q = (p.period == q) and c.period_ok
            e = reg.get(c.metric, {})
            m = g.MET[c.metric]
            if c.num is not None:
                if in_q and "value" in e:
                    resolved.append((c.num.start, c.num.end))
                    checked += 1
                    rule = "R5" if m.cls == "pct" else "R1"
                    if c.num.cls != m.cls:
                        flags.append(_flag(p, c.num.start, c.num.end, rule, "red", "单位/币种错误",
                                           f"{m.zh}：草稿写作“{c.num.raw}”，单位或币种与已披露口径（{disp_value(e)}）不符",
                                           metric=m.id, expected=disp_value(e)))
                    else:
                        v = g.cval(m, c.num)
                        if not g.consistent(v, c.num.half, e["value"], e["half"]):
                            j = g.judge_mismatch(v, c.num.half, e["value"], e["half"])
                            flags.append(_flag(p, c.num.start, c.num.end, rule, "red",
                                               "单位/数量级错误" if j.startswith("数量级") else
                                               ("百分比与数值不符" if rule == "R5" else "数值不符"),
                                               f"{m.zh}：草稿“{c.num.raw}”≠ 已披露 {disp_value(e)}（{j}）",
                                               metric=m.id, expected=disp_value(e), judgement=j))
                    if c.prior is not None and e.get("prior_y"):
                        py = e["prior_y"]
                        resolved.append((c.prior.start, c.prior.end))
                        if not g.consistent(c.prior.value, c.prior.half, py["value"], py["half"]):
                            flags.append(_flag(p, c.prior.start, c.prior.end, "R5", "red", "百分比与数值不符",
                                               f"{m.zh}（上年同期）：草稿“{c.prior.raw}”≠ 按上年数据计算的 "
                                               f"{py['value']:.2f}%", metric=m.id))
                if in_q:
                    mentions.setdefault(c.metric, (p, c))
            for gr in c.growth or []:
                if not in_q:
                    continue
                ref = g.growth_ref(e, gr.kind) if e else None
                if ref is None:
                    continue
                resolved.append((gr.start, gr.end))
                checked += 1
                rv, rh, how = ref
                bad_sign = (gr.value > 0 > rv or gr.value < 0 < rv) and abs(rv) > rh and abs(gr.value) > gr.half
                if bad_sign or not g.consistent(gr.value, gr.half, rv, rh):
                    gs, ge = (gr.start, gr.end) if gr.end else (c.num.start, c.num.end) if c.num else (c.a_start, c.a_end)
                    if p.cells and not gr.end:
                        gs = ge = None
                        pos = len(p.body) + 1
                        for cc in p.cells:
                            if cc == gr.raw:
                                gs, ge = pos, pos + len(cc)
                            pos += len(cc) + 1
                        gs, ge = (gs, ge) if gs is not None else (c.a_start, c.a_end)
                    flags.append(_flag(p, gs, ge, "R2", "red", "同比/环比方向或幅度错误",
                                       f"{m.zh}{'同比' if gr.kind == 'yoy' else '环比'}：草稿 {gr.value:+g}% ≠ "
                                       f"{'已披露' if how == 'stated' else '按规范值推算'} {rv:+.1f}%", metric=m.id))
        resolved.extend((m.start(), m.end()) for m in RE_FX.finditer(full))
        # R7 汇率换算
        rate = None
        fx = re.search(r"USD ?1 to RMB ?(\d+\.\d+)|1\s?美元兑人民币\s?(\d+\.\d+)", " ".join(x.raw for x in dps))
        if fx:
            rate = float(fx.group(1) or fx.group(2))
        if rate:
            for i, n in enumerate(nums):
                if n.cls == "USD" and i > 0 and nums[i - 1].cls == "RMB" and 0 <= n.start - nums[i - 1].end <= 3:
                    r0 = nums[i - 1]
                    resolved.append((n.start, n.end))
                    if not g.consistent(n.value, n.half, r0.value / rate, r0.half / rate):
                        flags.append(_flag(p, n.start, n.end, "R7", "red", "汇率换算不符",
                                           f"{n.raw} 与 {r0.raw} 按 {rate} 换算不符", metric=None))
        # R6 未披露新数字
        for n in nums:
            if n.cls == "cell":
                continue
            if any(not (n.end <= a or n.start >= b) for a, b in resolved):
                continue
            if not disclosed(n, ctx_tokens(full, n.start, n.end, lang), lang, corpus):
                flags.append(_flag(p, n.start, n.end, "R6", "yellow", "未披露的新数字（参照文件中未找到同语境数值）",
                                   f"“{n.raw}”未在港交所公告/PPT 的同语境中出现，需确认出处或是否构成新信息"))
    # R4 勾稽（分部之和 = 合计；FCF；净现金；capex）
    for lhs, parts in g.RELATIONS:
        terms = [(lhs, 1)] + [(x.lstrip("-"), -1 if x.startswith("-") else 1) for x in parts]
        stated = [t for t in terms if t[0] in mentions]
        if lhs not in mentions or len(stated) < len(terms) - 1:
            continue
        total, tol, ok_all, desc = 0.0, 0.0, True, []
        for mid, sg in terms:
            if mid in mentions:
                c = mentions[mid][1]
                v, h = g.cval(g.MET[mid], c.num), c.num.half
                desc.append(f"{g.MET[mid].zh}={c.num.raw}")
            elif "value" in reg.get(mid, {}):
                v, h = reg[mid]["value"], reg[mid]["half"]
                desc.append(f"{g.MET[mid].zh}=注册表{v:,.0f}")
            else:
                ok_all = False
                break
            total += v if mid == lhs else -sg * v
            tol += h
        if ok_all and abs(total) > tol + 1e-6:
            for mid, sg in terms:
                if mid in mentions:
                    p, c = mentions[mid]
                    flags.append(_flag(p, c.num.start, c.num.end, "R4", "red", "分部之和≠合计（勾稽不平）",
                                       f"{g.MET[lhs].zh} 勾稽不平：{'；'.join(desc)}；差额 {total:,.0f} 百万元 > 容差 {tol:,.0f}",
                                       metric=mid, relation=lhs))
    # R3 中英文一致性（与另一语言版本逐数配对）
    if twin is not None:
        flags.extend(bilingual_flags(dps, lang, load_draft_paras(twin, twin_lang, q), twin_lang))
    flags.sort(key=lambda f: (f["para"], f["start"]))
    return flags, checked


RE_FX = re.compile(r"USD ?1 to RMB ?\d+\.\d+|1\s?美元兑人民币\s?\d+\.\d+\s?元")


def _all_numbers(dps, lang):
    """双语配对用：带单位的数字；增减表述中的百分比带上方向符号（"下降4%" = -4）。表格裸数字不参与。"""
    out = []
    for p in dps:
        if p.heading:
            continue
        full, nums = _draft_numbers(p, lang)
        grs = g.parse_growths(full, lang)
        fx = [(m.start(), m.end()) for m in RE_FX.finditer(full)]
        for n in nums:
            if n.cls == "cell" or (p.cells and n.start >= len(p.body)):
                continue
            if any(a <= n.start < b for a, b in fx):
                continue
            if n.cls == "pct":
                for gr in grs:
                    if gr.start <= n.start and n.end <= gr.end:
                        n = g.Num("pct", gr.value, n.half, n.raw, n.start, n.end, token=n.token, dec=n.dec)
                        break
            out.append((p, n))
    return out


def bilingual_flags(a_dps, a_lang, b_dps, b_lang):
    """逐数配对：同类数字中，四舍五入区间一致者才可配对；全局按（是否精确相等、段落相对位置距离）贪心配对，
    以免同值数字"串位"。A 中配不上的数字即告警。"""
    A, B = _all_numbers(a_dps, a_lang), _all_numbers(b_dps, b_lang)
    na, nb = max(1, len(A)), max(1, len(B))
    pairs = []
    for i, (p, n) in enumerate(A):
        for j, (q, m) in enumerate(B):
            if m.cls != n.cls or not g.consistent(m.value, m.half, n.value, n.half):
                continue
            exact = abs(m.value - n.value) < 1e-9
            pairs.append((0 if exact else 1, abs(i / na - j / nb), i, j))   # 位置 = 数字在全文数字序列中的相对序号
    pairs.sort()
    used_a, used_b = set(), set()
    for _, _, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
    out = []
    for i, (p, n) in enumerate(A):
        if i not in used_a:
            out.append(_flag(p, n.start, n.end, "R3", "red", "中英文不一致",
                             f"“{n.raw}”在{'中文' if b_lang == 'zh' else '英文'}版本中没有可配对的数字"))
    return out


def draft_paragraphs(q, kind):
    """新闻稿正文（至 About Tencent / 关于腾讯 之前）按段序列化为草稿：每段一行。"""
    doc = g.get_doc(q, kind)
    out, meta = [], []
    for p in doc.paras:
        if p.heading and g.RE_SECTION_STOP.match(p.text):
            break
        out.append(p.draft_text())
        meta.append({"line": p.lines[0] if p.lines else None, "page": p.page})
    return out, meta


# ---------------------------------------------------------------------------
# 注入测试 + 干净段落误报率
# ---------------------------------------------------------------------------
CAT_ZH = {"tamper": "①数字篡改", "unit": "②单位错误", "yoy": "③同比方向/幅度错误", "bilingual": "④中英文不一致（只改一边）",
          "sum": "⑤分部之和≠合计", "pct": "⑥百分比与数值不符", "new": "⑦未披露的新数字"}


def _overlap(f, k, slack=1):
    return f["para"] == k["para"] and f["start"] < k["end"] + slack and f["end"] > k["start"] - slack


def run_eval(regs_ref, corpora, sid, seed=7, n=30):
    import inject
    q = g.TARGET
    en0, en_meta = draft_paragraphs(q, "release_en")
    zh0, zh_meta = draft_paragraphs(q, "release_zh")
    reg = regs_ref[q]
    base_en, _ = check_draft(en0, "en", q, reg, corpora[q], zh0, "zh")
    base_zh, _ = check_draft(zh0, "zh", q, reg, corpora[q], en0, "en")
    baseline = {"en": base_en, "zh": base_zh}
    en1, zh1, key = inject.make_injections(en0, zh0, seed=seed, n=n, avoid=baseline)
    INJ_DIR.mkdir(parents=True, exist_ok=True)
    (INJ_DIR / "draft_clean_en.txt").write_text("\n".join(en0) + "\n", encoding="utf-8")
    (INJ_DIR / "draft_clean_zh.txt").write_text("\n".join(zh0) + "\n", encoding="utf-8")
    (INJ_DIR / f"draft_injected_en_seed{seed}.txt").write_text("\n".join(en1) + "\n", encoding="utf-8")
    (INJ_DIR / f"draft_injected_zh_seed{seed}.txt").write_text("\n".join(zh1) + "\n", encoding="utf-8")
    (INJ_DIR / f"answer_key_seed{seed}.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    fl_en, ck_en = check_draft(en1, "en", q, reg, corpora[q], zh1, "zh")
    fl_zh, ck_zh = check_draft(zh1, "zh", q, reg, corpora[q], en1, "en")
    flags = {"en": fl_en, "zh": fl_zh}
    per_cat, results = {}, []
    for k in key:
        hits = [f for f in flags[k["lang"]] if _overlap(f, k)]
        red = [f for f in hits if f["severity"] == "red"]
        det = bool(hits)
        pc = per_cat.setdefault(k["cat"], {"n": 0, "detected": 0, "detected_red": 0})
        pc["n"] += 1
        pc["detected"] += det
        pc["detected_red"] += bool(red)
        results.append({**k, "detected": det, "detected_red": bool(red),
                        "rules": sorted(set(f["rule"] for f in hits)), "flag_msgs": [f["msg"] for f in hits][:3]})
    # 稳健性：另取 20 个未在开发中使用过的种子（101–120）重复注入，汇总分类召回率与漏检样例
    rob_cat, rob_miss, rob_n, rob_det = {}, [], 0, 0
    for sd in range(101, 121):
        e1, z1, k1 = inject.make_injections(en0, zh0, seed=sd, n=n, avoid=baseline)
        fe, _ = check_draft(e1, "en", q, reg, corpora[q], z1, "zh")
        fz, _ = check_draft(z1, "zh", q, reg, corpora[q], e1, "en")
        ff = {"en": fe, "zh": fz}
        for kk in k1:
            hit = any(_overlap(f, kk) for f in ff[kk["lang"]])
            rc = rob_cat.setdefault(kk["cat"], [0, 0])
            rc[0] += 1
            rc[1] += hit
            rob_n += 1
            rob_det += hit
            if not hit and len(rob_miss) < 25:
                rob_miss.append({"seed": sd, "cat": kk["cat"], "cat_zh": CAT_ZH[kk["cat"]], "lang": kk["lang"],
                                 "desc": kk["desc"], "before": kk["before"], "after": kk["after"],
                                 "context": (e1 if kk["lang"] == "en" else z1)[kk["para"]][max(0, kk["start"] - 40):kk["end"] + 20]})
    robustness = {"seeds": "101-120", "n": rob_n, "detected": rob_det, "recall": round(rob_det / rob_n, 3) if rob_n else None,
                  "by_category": [{"cat": c, "name": CAT_ZH[c], "n": rob_cat.get(c, [0, 0])[0],
                                   "detected": rob_cat.get(c, [0, 0])[1],
                                   "recall": round(rob_cat[c][1] / rob_cat[c][0], 3) if rob_cat.get(c, [0])[0] else None,
                                   "label": "计算", "src": [sid[(q, "release_en")], sid[(q, "release_zh")]]}
                                  for c in ["tamper", "unit", "yoy", "bilingual", "sum", "pct", "new"]],
                  "miss_examples": rob_miss, "label": "计算",
                  "src": [sid[(q, "release_en")], sid[(q, "release_zh")]],
                  "note": "种子 7 在规则开发中被反复使用；101–120 为开发后一次性运行，作为样本外参考"}
    rel_src = [sid[(q, "release_en")], sid[(q, "release_zh")]]
    _tag(results, rel_src)
    _tag(rob_miss, rel_src)
    _tag(base_en, [sid[(q, "release_en")]])
    _tag(base_zh, [sid[(q, "release_zh")]])
    total = len(key)
    det_total = sum(r["detected"] for r in results)
    red_total = sum(r["detected_red"] for r in results)
    extra = [f for lang in ("en", "zh") for f in flags[lang] if not any(_overlap(f, k) for k in key if k["lang"] == lang)]
    misses = [r for r in results if not r["detected"]]
    cats = []
    for c in ["tamper", "unit", "yoy", "bilingual", "sum", "pct", "new"]:
        pc = per_cat.get(c, {"n": 0, "detected": 0, "detected_red": 0})
        cats.append({"cat": c, "name": CAT_ZH[c], "n": pc["n"], "detected": pc["detected"],
                     "recall": round(pc["detected"] / pc["n"], 3) if pc["n"] else None,
                     "recall_red_only": round(pc["detected_red"] / pc["n"], 3) if pc["n"] else None,
                     "label": "计算", "src": [sid[(q, "release_en")], sid[(q, "release_zh")]]})
    # 干净段落误报率：其他 5 个季度的中英文新闻稿正文，各以本季度港交所公告+PPT 为参照、以另一语言版本为对照
    fp_rows, fp_examples = [], []
    tot_p = tot_red = tot_any = 0
    for qq in g.QUARTERS[:-1]:
        for kind, tw, lang in (("release_en", "release_zh", "en"), ("release_zh", "release_en", "zh")):
            paras, meta = draft_paragraphs(qq, kind)
            twin, _ = draft_paragraphs(qq, tw)
            fl, ck = check_draft(paras, lang, qq, regs_ref[qq], corpora[qq], twin, "zh" if lang == "en" else "en")
            dps = load_draft_paras(paras, lang, qq)
            num_paras = [p.idx for p in dps if not p.heading and _draft_numbers(p, lang)[1]]
            red_p = {f["para"] for f in fl if f["severity"] == "red"}
            any_p = {f["para"] for f in fl}
            tot_p += len(num_paras)
            tot_red += len(red_p & set(num_paras))
            tot_any += len(any_p & set(num_paras))
            by_rule = {}
            for f in fl:
                by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
            fp_rows.append({"quarter": qq, "doc": kind, "paragraphs_with_numbers": len(num_paras),
                            "flagged_red": len(red_p & set(num_paras)), "flagged_any": len(any_p & set(num_paras)),
                            "claims_checked": ck, "flags_by_rule": by_rule, "src": [sid[(qq, kind)]], "label": "计算"})
            for f in fl:
                ex = {"quarter": qq, "doc": kind, "rule": f["rule"], "severity": f["severity"],
                      "msg": f["msg"], "text": f["text"], "line": meta[f["para"]]["line"],
                      "file": f"demo/data/raw/m4/txt/{qq}_{kind}.txt", "src": [sid[(qq, kind)]], "label": "计算"}
                if (qq, kind, f["text"]) in MANUAL_REVIEW:
                    ex["review"] = MANUAL_REVIEW[(qq, kind, f["text"])]
                fp_examples.append(ex)
    fp = {"paragraphs": tot_p, "flagged_red": tot_red, "flagged_any": tot_any,
          "fp_rate_red": round(tot_red / tot_p, 4) if tot_p else None,
          "fp_rate_any": round(tot_any / tot_p, 4) if tot_p else None, "by_doc": fp_rows,
          "examples": fp_examples, "label": "计算",
          "src": sorted(set(s for r in fp_rows for s in r["src"])),
          "design": ("误报测试样本 = 1Q25–1Q26 五个季度中英文新闻稿正文中含数字的全部段落（未注入）。每份稿件以同季度"
                     "港交所中英文公告 + PPT 抽取的注册表为'已披露'基准（不使用新闻稿自身），以另一语言新闻稿做双语配对。"
                     "只有在该季度口径章节中、且句内无'六个月/全年'等期间词的语句才做数值/同比核对。")}
    return {"seed": seed, "n": total, "categories": cats, "detected": det_total, "recall": round(det_total / total, 3),
            "detected_red": red_total, "recall_red_only": round(red_total / total, 3),
            "label": "计算", "src": [sid[(q, "release_en")], sid[(q, "release_zh")]],
            "injections": results, "misses": misses, "robustness": robustness,
            "extra_flags_on_injected": {"n": len(extra), "by_rule": _count_rules(extra),
                                        "note": "注入稿中未落在注入位置上的告警（含基线已有告警与双语对侧的连带告警）"},
            "baseline_2q26": {"en": base_en, "zh": base_zh,
                              "note": "未注入的 2Q26 中英文新闻稿本身的告警（以港交所公告+PPT 为基准）"},
            "false_positive_test": fp,
            "files": {"clean_en": "demo/data/raw/m4/inject/draft_clean_en.txt",
                      "clean_zh": "demo/data/raw/m4/inject/draft_clean_zh.txt",
                      "injected_en": f"demo/data/raw/m4/inject/draft_injected_en_seed{seed}.txt",
                      "injected_zh": f"demo/data/raw/m4/inject/draft_injected_zh_seed{seed}.txt",
                      "answer_key": f"demo/data/raw/m4/inject/answer_key_seed{seed}.json"}}


MANUAL_REVIEW = {
    ("4Q25", "release_zh", "20%"): ("人工复核：中文稿“企业服务收入同比增长接近20%”，英文稿对应句为“rose by a high-teens rate”"
                                   "（未给数字），属真实的中英文措辞差异，非规则误判；仍计入误报统计以保守起见"),
}


def _tag(items, src, label="计算"):
    for it in items:
        it.setdefault("src", src)
        it.setdefault("label", label)
    return items


def _count_rules(fl):
    out = {}
    for f in fl:
        out[f["rule"]] = out.get(f["rule"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# js_registry：网页实时检查器用的规范值 + 写法变体
# ---------------------------------------------------------------------------
def _variants(m, e):
    v, cls = e["value"], m.cls
    en, zh = [], []
    if cls == "RMB":
        bn, yi = v / 1000, v / 100
        sg = "-" if v < 0 else ""
        a = abs(bn)
        en = [f"RMB{a:.1f} billion", f"RMB {a:.1f} billion", f"RMB{a:.1f}bn", f"{a:.1f}"]
        zh = [f"{abs(yi):,.0f}亿元", f"{abs(yi):,.0f} 亿元", f"人民币{abs(yi):,.0f}亿元", f"{abs(yi):.0f}亿元"]
        if e["half"] <= 0.5:
            en.append(f"RMB{abs(v):,.0f} million")
            zh.append(f"{abs(v):,.0f}百万元")
            en.append(f"{'(' if v < 0 else ''}{abs(v):,.0f}{')' if v < 0 else ''}")
        if sg:
            en.insert(0, f"negative free cash flow of RMB{a:.1f} billion" if m.id == "fcf" else f"({a:.1f})")
            zh.insert(0, f"转负为人民币{abs(yi):,.0f}亿元" if m.id == "fcf" else f"({abs(yi):,.0f})")
    elif cls == "HKD":
        en = [f"HKD{v / 1000:.1f} billion"]
        zh = [f"{v / 100:,.0f}亿港元", f"约{v / 100:,.0f} 亿港元"]
    elif cls == "count":
        en = [f"{v:,.0f} million" if e["half"] >= 0.5 else f"{v:,.1f} million", f"{v:,.0f}m"]
        zh = [f"{v * 100:,.0f}万" if e["half"] < 0.5 else f"{v:,.0f}（百万）"]
    elif cls == "pct":
        en = [f"{v:.0f}%", f"{v:.1f}%"]
        zh = [f"{v:.0f}%", f"{v:.1f}%"]
    else:
        en = [f"RMB{v:.3f}"]
        zh = [f"人民币{v:.3f}元", f"{v:.3f}元"]
    return list(dict.fromkeys(en)), list(dict.fromkeys(zh))


def js_registry(regs, sid):
    reg = regs[g.TARGET]
    items = []
    for m in g.METRICS:
        e = reg[m.id]
        if "value" not in e:
            continue
        en, zh = _variants(m, e)
        it = {"id": m.id, "name_zh": m.zh, "name_en": m.en, "cls": m.cls, "value": round(e["value"], 6),
              "half_tol": round(e["half"], 6), "signed": m.signed, "variants_en": en, "variants_zh": zh,
              "aliases_en": m.al_src["en"], "aliases_zh": m.al_src["zh"],
              "label": "计算" if e.get("calc") else "公开披露",
              "src": (claim_ref(e["src"], sid)["src"] if e.get("src") else
                      sorted(set(claim_ref(reg[x]["src"], sid)["src"][0] for x in (m.calc or m.calc_sum)
                                 if reg[x].get("src"))))}
        for kind in ("yoy", "qoq"):
            r = g.growth_ref(e, kind)
            if r:
                it[kind] = {"value": round(r[0], 3), "half_tol": round(r[1], 3), "basis": r[2],
                            "label": "公开披露" if r[2] == "stated" else "计算", "src": it["src"]}
        items.append(it)
    return {
        "quarter": g.TARGET, "n": len(items), "metrics": items,
        "units": {"en": {"trillion": 1e6, "billion": 1000, "bn": 1000, "million": 1, "mn": 1, "m": 1},
                  "zh": {"万亿": 1e6, "亿": 100, "千万": 10, "百万": 1, "万": 0.01}},
        "base_unit": "金额：百万（人民币/港元）；数量：百万；百分比：%；每股：元",
        "nonifrs_remap": g.NONIFRS_REMAP,
        "rule": ("别名命中后，取其后（至下一个别名或句末）第一个同类数值，按单位表换算为基准单位；"
                 "若 |草稿值 − 规范值| 超出两者四舍五入半单位之和则标红；同比/环比用 yoy/qoq 区间同理。"
                 "'On a non-IFRS basis'/'按非国际财务报告准则' 段落后的 '-' 子条目按 nonifrs_remap 换成非国际口径。"),
        "demo": {"input_zh": "资本开支为人民币582亿元，同比增加176%。", "expect": "capex 标红（582 亿元 ≠ 528 亿元）",
                 "input_en": "Capital expenditure was RMB52.8 billion, up 176% YoY.", "expect_en": "全部为绿"},
        "checker_js_file": "demo/pipeline/m4_checker.js",
        "checker_js": (Path(__file__).resolve().parent / "m4_checker.js").read_text(encoding="utf-8"),
        "checker_api": "M4Check.check(text, js_registry, 'zh'|'en') → [{start,end,status:'ok'|'bad',metric,name,kind,found,expected,msg}]",
        "label": "公开披露", "src": [sid[(g.TARGET, k)] for k in g.KINDS]}


# ---------------------------------------------------------------------------
# 自检（随机抽查回到原文）
# ---------------------------------------------------------------------------
def self_check(payload, regs, seed=20261026):
    import random
    rng = random.Random(seed)
    sample = []
    reg = regs[g.TARGET]
    cands = [m.id for m in g.METRICS if reg[m.id].get("src") is not None]
    for mid in rng.sample(cands, 10):
        c = reg[mid]["src"]
        d = g.get_doc(g.TARGET, c.kind)
        line = d.raw[c.line - 1]
        tok = c.num.raw.strip("()") if c.mode == "table" else c.num.token
        ok_line = tok in g.normalize(line, d.lang) or tok in line
        tl = g.orig_line(g.TARGET, c.kind, c.page, tok.strip("%"), c.text or "")
        orig = g.orig_pages(g.TARGET, c.kind)
        ok_orig = bool(tl) and tok.strip("%") in orig[tl - 1][2]
        sample.append({"metric": mid, "value": reg[mid]["value"], "doc": c.kind, "line": c.line, "token": tok,
                       "derived_line_text": line.strip()[:120], "found_in_derived_line": ok_line,
                       "orig_txt_line": tl, "found_in_orig_txt": ok_orig})
    # 引语/文字核对：capex 现金口径原句、G&A 差异原句
    lt = _orig_text_lines(LAUNCH_TXT, "latin-1")
    quotes = [("RMB88.3", LAUNCH_TXT, "latin-1"), ("RMB96.3 billion", LAUNCH_TXT, "latin-1"),
              ("Capital expenditures (d) 52,784 31,936 19,107 84,720 46,583", IR26_TXT, "utf-8"),
              ("capital expenditure payments of RMB59.3", IR26_TXT, "utf-8")]
    qchk = []
    for qt, path, enc in quotes:
        lines = _orig_text_lines(path, enc)
        hit = [i + 1 for i, t in enumerate(lines) if qt in t]
        qchk.append({"quote": qt, "file": str(path.relative_to(ROOT)).replace("\\", "/"), "lines": hit[:3], "ok": bool(hit)})
    del lt
    # 结构性检查：src 存在、label 合法、禁用词、估值评论、邮箱
    ids = {s["id"] for s in payload["sources"]}
    bad_src, bad_label, n_num = [], [], 0

    def walk(o, path=""):
        nonlocal n_num
        if isinstance(o, dict):
            if "src" in o:
                n_num += 1
                for s in o["src"]:
                    if s not in ids:
                        bad_src.append((path, s))
                if "label" in o and o["label"] not in ("公开披露", "结构化数据", "计算", "推断"):
                    bad_label.append((path, o["label"]))
            for k, v in o.items():
                if k in ("baseline_2q26", "examples", "injections", "misses"):
                    continue
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk({k: v for k, v in payload.items() if k != "meta"})
    num_keys = {"value", "value_rmb_m", "raw", "found", "display", "norm", "recall", "fp_rate_red", "lhs"}
    missing = []

    def walk2(o, path=""):
        if isinstance(o, dict):
            if num_keys & set(o) and not ("src" in o and "label" in o):
                missing.append(path)
            for k, v in o.items():
                if k in ("checker_js", "variants_en", "variants_zh", "aliases_en", "aliases_zh", "units"):
                    continue
                walk2(v, path + "/" + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk2(v, f"{path}[{i}]")

    walk2({k: v for k, v in payload.items() if k != "meta"})
    txt = json.dumps({k: v for k, v in payload.items() if k != "meta"}, ensure_ascii=False)
    own_text = json.dumps({k: payload.get(k) for k in ("capex", "tieout")}, ensure_ascii=False)
    banned = [w for w in BANNED if w in own_text]
    val = VALUATION.findall(own_text)
    try:
        assert_no_email(txt)
        email_ok = True
    except ValueError:
        email_ok = False
    user_path = bool(re.search(r"[A-Za-z]:\\\\Users\\\\|/c/Users/|AppData", txt))
    return {"spot_checks": sample, "spot_checks_pass": sum(s["found_in_derived_line"] and s["found_in_orig_txt"] for s in sample),
            "quote_checks": qchk, "objects_with_src": n_num, "unknown_src_ids": bad_src[:10], "illegal_labels": bad_label[:10],
            "numeric_objects_missing_src_or_label": missing[:20], "n_numeric_objects_missing": len(missing),
            "banned_words_found": banned, "valuation_terms_found": val, "no_email": email_ok,
            "no_user_path": not user_path,
            "note": ("抽查方法：固定种子随机抽 10 个注册表指标，回到派生文本行与原 pdftotext .txt 行比对数字字面；"
                     "另核对 4 条原句。banned/valuation 只扫描本模块自撰文字（capex 解读、勾稽说明），不扫描官方原文引语。")}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def cmd_extract():
    for q in g.QUARTERS:
        for k in g.KINDS:
            g.ensure_text(q, k)
    regs = build_all_registries(g.KINDS)
    sources, sid = build_sources()
    reg = registry_payload(regs, sid)
    print(f"[extract] 2Q26 注册表指标数：{len(reg)}（其中网页首屏指标 {sum(1 for r in reg if r['headline'])}）")
    return regs, sources, sid


def cmd_all(seed=7, n=30):
    regs, sources, sid = cmd_extract()
    to = tieout(regs, sid)
    print(f"[tieout] {to['n_metrics']} 个指标 × 5 文件：{to['summary']}；不一致 {len(to['discrepancies'])} 条")
    hist = []
    for qq in g.QUARTERS[:-1]:
        for dsc in tieout(regs, sid, qq)["discrepancies"]:
            dsc["quarter"] = qq
            hist.append(dsc)
    to["other_quarters_discrepancies"] = {
        "items": hist, "label": "计算", "src": sorted(set(s for d0 in hist for s in d0["src"])),
        "note": "同一套规则对 1Q25–1Q26 五个季度各自的五份文件做勾稽，只列不一致项（供参考；规则未针对这些季度逐项人工复核）"}
    print(f"[tieout] 其他季度不一致 {len(hist)} 条")
    cx = capex_triad(regs, sid)
    regs_ref = build_all_registries(g.REF_KINDS)
    corpora = {q: build_corpus(q, g.REF_KINDS) for q in g.QUARTERS}
    ev = run_eval(regs_ref, corpora, sid, seed=seed, n=n)
    print(f"[check] 注入 {ev['n']} 处，检出 {ev['detected']}（召回 {ev['recall']:.1%}，仅红色 {ev['recall_red_only']:.1%}）；"
          f"干净段落 {ev['false_positive_test']['paragraphs']} 段，红色误报段 {ev['false_positive_test']['flagged_red']}"
          f"（{ev['false_positive_test']['fp_rate_red']:.1%}），含黄色 {ev['false_positive_test']['flagged_any']}")
    inputs = []
    for q in g.QUARTERS:
        for k in g.KINDS:
            inputs.append(input_record(g.IR / f"{q}_{k}.pdf"))
            inputs.append(input_record(g.IR / f"{q}_{k}.txt"))
    inputs += [input_record(LAUNCH_PDF), input_record(LAUNCH_TXT), input_record(IR26_TXT),
               input_record(g.IR / "manifest.tsv")]
    payload = {
        "meta": {"module": "m4_gatekeeper", "title": "M4 数字守门员：五方勾稽 · capex 三口径 · 注入记分牌 · 实时检查器注册表",
                 "as_of": AS_OF, "generated_by": "本地 Python", "script": "demo/pipeline/gatekeeper.py",
                 "scripts": ["demo/pipeline/gatekeeper.py", "demo/pipeline/gk_core.py", "demo/pipeline/inject.py",
                             "demo/pipeline/test_gatekeeper.py"],
                 "inputs": inputs,
                 "text_layer": {"method": "PyMuPDF page.get_text() 重新抽取 UTF-8 文本，落盘 demo/data/raw/m4/txt/",
                                "reason": "原 data/src/ir_official/*.txt 为 pdftotext Latin-1 输出：中文全部丢失、英文表格列被打散",
                                "line_numbers": "line=派生文本行号；txt_line=原 pdftotext .txt 中同页含该数字的行号（交叉核对用）",
                                "pymupdf": _pymupdf_version()},
                 "notes": ("全部为确定性代码（正则 + 单位归一 + 四舍五入区间比较），不靠大模型判断。2Q26 注册表以五份文件"
                           "取共识、取最精确者为规范值；草稿检查与注入测试以港交所中英文公告 + PPT 为'已披露'基准（不含新闻稿）。"
                           "本脚本未发起网络请求：10-12 发债公告已在本地。" + WATERMARK),
                 "watermark": WATERMARK},
        "sources": sources,
        "registry": {"quarter": g.TARGET, "n": None, "n_headline": None, "metrics": registry_payload(regs, sid),
                     "method": "各文件逐句/逐表行抽取 → 单位归一到百万/% → 按四舍五入区间聚类 → 支持文件最多的簇中取最精确者",
                     "label": "公开披露", "src": [sid[(g.TARGET, k)] for k in g.KINDS]},
        "tieout": to,
        "capex": cx,
        "injection": ev,
        "js_registry": js_registry(regs, sid),
    }
    payload["registry"]["n"] = len(payload["registry"]["metrics"])
    payload["registry"]["n_headline"] = sum(1 for r in payload["registry"]["metrics"] if r["headline"])
    payload["meta"]["self_check"] = self_check(payload, regs)
    sc = payload["meta"]["self_check"]
    print(f"[self_check] 抽查 {len(sc['spot_checks'])} 个数字通过 {sc['spot_checks_pass']}；未知 src {len(sc['unknown_src_ids'])}；"
          f"非法 label {len(sc['illegal_labels'])}；禁用词 {sc['banned_words_found']}；无邮箱 {sc['no_email']}；"
          f"无用户路径 {sc['no_user_path']}")
    path = write_module("m4_gatekeeper", payload)
    print(f"[write] {path.relative_to(ROOT)}")
    return payload


def _pymupdf_version():
    try:
        import pymupdf
        return pymupdf.VersionBind
    except Exception:  # noqa: BLE001
        return "n/a"


def cmd_check(args):
    regs_ref = build_all_registries(g.REF_KINDS)
    q = args.quarter
    corpus = build_corpus(q, g.REF_KINDS)
    paras = [x for x in Path(args.draft).read_text(encoding="utf-8").splitlines() if x.strip()]
    lang = args.lang or ("zh" if sum(g.is_cjk(ch) for ch in "".join(paras)) > 20 else "en")
    twin = None
    if args.twin:
        twin = [x for x in Path(args.twin).read_text(encoding="utf-8").splitlines() if x.strip()]
    flags, checked = check_draft(paras, lang, q, regs_ref[q], corpus, twin, ("en" if lang == "zh" else "zh") if twin else None)
    print(f"[check] {args.draft}：{len(paras)} 段，核对 {checked} 处已登记指标；红 {sum(f['severity'] == 'red' for f in flags)}，"
          f"黄 {sum(f['severity'] == 'yellow' for f in flags)}")
    for f in flags:
        print(f"  [{f['severity']}/{f['rule']}] 段{f['para'] + 1}「{f['text']}」{f['msg']}")
    return flags


def main(argv=None):
    ap = argparse.ArgumentParser(description="M4 数字守门员")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract")
    sub.add_parser("tieout")
    c = sub.add_parser("check")
    c.add_argument("--draft")
    c.add_argument("--twin")
    c.add_argument("--lang", choices=["en", "zh"])
    c.add_argument("--quarter", default=g.TARGET)
    c.add_argument("--eval", action="store_true")
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--n", type=int, default=30)
    a = sub.add_parser("all")
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--n", type=int, default=30)
    args = ap.parse_args(argv)
    if args.cmd == "extract":
        regs, sources, sid = cmd_extract()
        for r in registry_payload(regs, sid):
            print(f"  {r['id']:22s} {r['display']:28s} {r['label']} {r['src']}")
    elif args.cmd == "tieout":
        regs, sources, sid = cmd_extract()
        to = tieout(regs, sid)
        print(f"[tieout] {to['summary']}")
        for d in to["discrepancies"]:
            print(f"  不一致 {d['name_zh']}[{d['type']}] {d['doc']}：{d['found']} vs {d['expected']}（{d['judgement']}）"
                  f" @{d['found_at']['file']}:{d['found_at']['line']}")
        cx = capex_triad(regs, sid)
        for r in cx["rows"]:
            print(f"  capex {r['basis']} {r['period']}: {r['display']}")
    elif args.cmd == "check":
        if args.eval:
            regs, sources, sid = cmd_extract()
            regs_ref = build_all_registries(g.REF_KINDS)
            corpora = {q: build_corpus(q, g.REF_KINDS) for q in g.QUARTERS}
            ev = run_eval(regs_ref, corpora, sid, seed=args.seed, n=args.n)
            for c in ev["categories"]:
                print(f"  {c['name']}: {c['detected']}/{c['n']}")
            print(f"  总召回 {ev['recall']:.1%}；误报段 {ev['false_positive_test']['flagged_red']}/"
                  f"{ev['false_positive_test']['paragraphs']}")
            for m in ev["misses"]:
                print(f"  漏检 {CAT_ZH[m['cat']]} [{m['lang']}] {m['before']!r} -> {m['after']!r}")
        elif args.draft:
            cmd_check(args)
        else:
            ap.error("check 需要 --draft 或 --eval")
    elif args.cmd == "all":
        cmd_all(seed=args.seed, n=args.n)


if __name__ == "__main__":
    main()
