"""M2a 业绩会实录分析（腾讯 12 个季度，2023Q3–2026Q2）。

运行（在 ROOT 下）：python -I demo/pipeline/transcripts.py
可选：--dump-slots  只打印修正后的"分析师提问时段"，供人工编码使用。

输入（只读）：
  data/parsed/<q>.json                 StockAnalysis 文字稿解析结果（speaker/title/text）
  data/src/transcripts/<id>-<q>.html   原始网页（取 canonical URL、日期）
  demo/pipeline/analyst_aliases.json   别名表（人工整理）
  demo/pipeline/m2_question_coding.json 问题单元人工编码 + 叙事演变引语选择（人工整理）
  data/src/ir_official/*_ppt.txt 等     腾讯官方业绩材料（用于文字稿数字保真抽查）
  data/src/market_raw/idx/tc_res.html  腾讯官网 Results 页面快照（核对 PPT 链接出自官网）
输出：
  data/parsed_fixed/<q>.json           修正发言人归属后的逐条发言（加 role / org）
  demo/data/m2_transcripts.json        热度、缺口、关键词、机构轨迹、回测、叙事演变、保真抽查
  demo/data/question_units.json        问题单元（人工编码）
本脚本不发起任何网络请求。
"""
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, "demo/pipeline")
from common import (AS_OF, DATA_PARSED, DATA_SRC, ROOT, assert_no_email,  # noqa: E402
                    input_record, load_json, write_module)

PIPE = ROOT / "demo" / "pipeline"
FIXED_DIR = ROOT / "data" / "parsed_fixed"
ALIAS_PATH = PIPE / "analyst_aliases.json"
CODING_PATH = PIPE / "m2_question_coding.json"
IR_DIR = DATA_SRC / "ir_official"
IR_PAGE = DATA_SRC / "market_raw" / "idx" / "tc_res.html"

QUARTERS = ["q3-2023", "q4-2023", "q1-2024", "q2-2024", "q3-2024", "q4-2024",
            "q1-2025", "q2-2025", "q3-2025", "q4-2025", "q1-2026", "q2-2026"]
REVIEW_NOTE = "第三方文字稿，待录音复核"
QUOTE_NOTE = "非官方逐字稿，引用前以官方录音为准"

TOPICS = OrderedDict([
    ("AI_CAPEX", "资本开支/算力投入"),
    ("AI_ROI", "投资回报/回本/变现时间"),
    ("AI_PRODUCTS", "自有AI产品(WorkBuddy/CodeBuddy/元宝/小微/智能体)"),
    ("MODELS", "混元/Hy模型能力"),
    ("COMPUTE", "芯片/GPU/算力供给"),
    ("CLOUD", "腾讯云/对外算力/Token定价"),
    ("MARGIN", "利润率/折旧/成本"),
    ("CAPITAL", "回购/派息/自由现金流/负债"),
    ("ADS", "营销服务/广告"),
    ("GAMES_DOM", "本土游戏"),
    ("GAMES_INTL", "国际游戏"),
    ("FINTECH", "金融科技与企业服务"),
    ("SOCIAL", "社交/视频号/内容/订阅"),
    ("REG", "监管/地缘/1260H"),
    ("PORTFOLIO", "投资组合/处置"),
])


def qlabel(q):
    n, y = q.split("-")
    return f"{y}Q{n[1]}"


def rel(p):
    return str(Path(p).relative_to(ROOT)).replace("\\", "/")


# ---------------------------------------------------------------------------
# 1. 发言人归属修正
# ---------------------------------------------------------------------------
FOOTER_RE = re.compile(r"\s*Data Source: Quartr.*$", re.S)
SPEAKER_N_RE = re.compile(r"^Speaker \d+$")
HANDOFF_KW_RE = re.compile(r"(question|next one|move (?:on )?to|reconnected with)", re.I)
FILLER_RE = re.compile(
    r"^(?:[A-Z][a-z]+, )?(?:your line is(?: now)? open|the line is open|line should be open|"
    r"you(?:'re| are) (?:unmuted|live|last)|go ahead|you (?:can|need to) unmute yourself|can you hear us)",
    re.I)
CLOSING_RE = re.compile(r"(Thank you,? (?:all|everyone)\b|We are now (?:ending|concluding))")
APPENDED_CUE_RE = re.compile(
    r"(taking my questions?|for the opportunity|my (?:first |main )?questions? (?:is|are)|good evening, management|congrat)", re.I)
SELF_ID_RE = re.compile(r"\bthis is ([A-Z][a-z]+ [A-Z][a-z]+)")
QUESTION_CUE_RE = re.compile(
    r"(thanks?(?: you)?,? (?:management,? )?for taking my question|my (?:first )?question is|"
    r"I have (?:a|one|two) (?:quick )?questions?|can you hear me)", re.I)


class Aliases:
    def __init__(self, path):
        self.raw = load_json(path)
        self.mgmt = set(self.raw["management"])
        self.moderators = set(self.raw["moderators"])
        self.analysts = {a["id"]: a for a in self.raw["analysts"]}
        self.by_string = {}
        for a in self.raw["analysts"]:
            self.by_string[a["name"]] = (a["id"], "高", None)
            for al in a.get("aliases", []):
                self.by_string[al["alias"]] = (a["id"], al["confidence"], al)
        names = sorted(self.by_string, key=len, reverse=True)
        self.name_re = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z])")
        org_pairs = [(s, org) for org, ss in self.raw["orgs"].items() for s in ss]
        org_pairs.sort(key=lambda x: len(x[0]), reverse=True)
        self.org_map = dict(org_pairs)
        self.org_re = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(s) for s, _ in org_pairs) + r")(?![A-Za-z])")
        self.flags = {(f["quarter"], f["src_i"]): f for f in self.raw.get("turn_flags", [])}

    def org_conflict(self, aid, quarter):
        for c in self.analysts[aid].get("org_conflicts", []):
            if c["quarter"] == quarter:
                return c
        return None

    def find_handoff(self, text):
        """最后一个"紧跟交接关键词"的分析师姓名/别名 → (analyst_id, alias, start, end, org_transcribed)。"""
        best = None
        for m in self.name_re.finditer(text):
            if HANDOFF_KW_RE.search(text[max(0, m.start() - 70):m.start()]):
                best = m
        if not best:
            return None
        alias = best.group(1)
        aid = self.by_string[alias][0]
        org_t = None
        after = self.org_re.search(text, best.end(), min(len(text), best.end() + 45))
        if after:
            org_t = self.org_map[after.group(1)]
        else:
            before = list(self.org_re.finditer(text, max(0, best.start() - 45), best.start()))
            if before:
                org_t = self.org_map[before[-1].group(1)]
        return {"analyst_id": aid, "alias": alias, "start": best.start(), "end": best.end(), "org_transcribed": org_t}

    def lookup_label(self, speaker):
        if speaker in self.by_string:
            return self.by_string[speaker]
        return None


def split_moderator(text, aliases):
    """主持人发言末尾若并入了分析师提问（文字稿常见错误），拆成两段。"""
    h = aliases.find_handoff(text)
    if not h:
        return [(text, "moderator")]
    # 交接句结束位置
    m = re.search(r"[.?!]\s", text[h["end"]:] + " ")
    cut = h["end"] + (m.end() if m else len(text) - h["end"])
    rest = text[cut:]
    # 跳过"your line is open"等填充句
    while True:
        s = rest.lstrip()
        fm = FILLER_RE.match(s)
        if not fm:
            break
        nm = re.search(r"[.?!]\s", s[fm.end():] + " ")
        step = fm.end() + (nm.end() if nm else len(s) - fm.end())
        cut += (len(rest) - len(s)) + step
        rest = text[cut:]
    resid = rest.strip()
    if len(resid) >= 80 and APPENDED_CUE_RE.search(resid):
        return [(text[:cut].strip(), "moderator"), (resid, "analyst_appended")]
    return [(text, "moderator")]


def split_closing(text):
    m = CLOSING_RE.search(text)
    if not m or m.start() == 0:
        return [(text, "closing_only" if m else "same")]
    return [(text[:m.start()].strip(), "same"), (text[m.start():].strip(), "moderator_closing")]


def fix_quarter(q, turns, aliases):
    quarter = qlabel(q)
    expanded = []
    for i, t in enumerate(turns):
        text = FOOTER_RE.sub("", t["text"]).strip()
        sp = t["speaker"]
        if sp in aliases.moderators:
            parts = split_moderator(text, aliases)
        elif re.search(r"(ending|concluding) the (webinar|call)", text):
            parts = split_closing(text)
        else:
            parts = [(text, "same")]
        for k, (ptxt, kind) in enumerate(parts):
            expanded.append({"src_i": i, "part": (k + 1) if len(parts) > 1 else None,
                             "speaker_raw": sp, "title_raw": t["title"], "text": ptxt, "kind": kind,
                             "footer_stripped": text != t["text"].strip()})

    out = []
    slot = None
    qa_started = False
    first_after_handoff = False
    for e in expanded:
        sp = e["speaker_raw"]
        fixes = []
        rec = {"i": len(out), "src_i": e["src_i"], "part": e["part"], "speaker": sp,
               "speaker_raw": sp, "title_raw": e["title_raw"], "role": None, "org": None,
               "analyst_id": None, "text": e["text"]}
        if e["footer_stripped"]:
            fixes.append({"rule": "R1", "note": "删除页面页脚（Data Source: Quartr… 等网站导航文字）", "confidence": "高"})

        def as_analyst(rule, note, conf):
            nonlocal slot
            a = aliases.analysts[slot["analyst_id"]]
            conf_alias = slot["alias_conf"]
            name = a["name"] if conf_alias != "低" else slot["alias"]
            rec.update(role="analyst", speaker=name, analyst_id=a["id"], org=a["org"])
            if conf_alias == "低":
                rec["alias_candidate"] = a["name"]
            if slot.get("org_conflict"):
                c = slot["org_conflict"]
                rec["org_note"] = f"文字稿写作 {c['transcribed_org']}，按 {c['basis']} 记为 {c['resolved_org']}"
            if rule and slot["alias"] != a["name"]:
                al = aliases.by_string[slot["alias"]][2]
                note = note + f"（别名 '{slot['alias']}' → {a['name']}：{al['basis'] if al else ''}）"
            if conf_alias == "低":
                fixes.append({"rule": "ALIAS", "note": f"姓名存疑：文字稿作 '{slot['alias']}'，候选 {a['name']}（{aliases.by_string[slot['alias']][2]['basis']}）；机构确定为 {a['org']}",
                              "confidence": "低"})
            if rule:
                worst = max([conf, conf_alias], key=lambda c: "高中低".index(c))
                fixes.append({"rule": rule, "note": note, "confidence": worst})

        is_mod = (sp in aliases.moderators and e["kind"] != "analyst_appended") or e["kind"] in ("moderator_closing", "closing_only")
        if is_mod:
            rec.update(role="moderator", org="Tencent IR")
            if sp not in aliases.moderators:
                rec["speaker"] = "Wendy Huang"
                fixes.append({"rule": "R8", "note": f"散场语误标为 {sp}，改为 IR 主持人", "confidence": "中"})
            h = aliases.find_handoff(e["text"])
            if h:
                slot = _make_slot(h, aliases, quarter)
                qa_started = True
                first_after_handoff = True
        elif e["kind"] == "analyst_appended":
            as_analyst("R3", f"主持人发言中并入了分析师提问，按交接语（'{slot['alias']}'）拆出并归属", "高")
            first_after_handoff = False
        elif sp in aliases.mgmt:
            h = aliases.find_handoff(e["text"])
            if h and len(e["text"]) < 300:
                rec.update(role="moderator", org="Tencent IR", speaker="Wendy Huang")
                fixes.append({"rule": "R4", "note": f"交接语误标为管理层 {sp}，改为 IR 主持人", "confidence": "高"})
                slot = _make_slot(h, aliases, quarter)
                qa_started = True
                first_after_handoff = True
            elif qa_started and first_after_handoff and slot and (SELF_ID_RE.search(e["text"]) or QUESTION_CUE_RE.search(e["text"])):
                sid = SELF_ID_RE.search(e["text"])
                why = f"自报姓名 '{sid.group(1)}'" if sid else "交接后第一条发言且为提问句式"
                as_analyst("R5", f"文字稿误标为管理层 {sp}；{why}，按交接语归属", "高")
                first_after_handoff = False
            else:
                rec.update(role="mgmt", org="Tencent")
                first_after_handoff = False
        elif SPEAKER_N_RE.match(sp):
            if slot and qa_started:
                as_analyst("R6", f"文字稿标为 '{sp}'，按主持人交接语（'{slot['alias']}'）归属", "高")
            else:
                rec.update(role="unknown")
                fixes.append({"rule": "R6", "note": "无法归属", "confidence": "低"})
            first_after_handoff = False
        else:
            lab = aliases.lookup_label(sp)
            if lab and slot:
                if lab[0] != slot["analyst_id"]:
                    fixes.append({"rule": "R7", "note": f"发言人标签 {sp} 与交接语 '{slot['alias']}' 不一致，按交接语归属", "confidence": "中"})
                as_analyst(None, None, "高")
                if sp != rec["speaker"]:
                    al = lab[2]
                    fixes.append({"rule": "R7", "note": f"标签姓名 '{sp}' 按别名表归一为 {rec['speaker']}" + (f"（{al['basis']}）" if al else ""),
                                  "confidence": lab[1]})
                if e["title_raw"] and slot and aliases.analysts[slot["analyst_id"]]["org"] not in _norm_org(e["title_raw"], aliases):
                    fixes.append({"rule": "R7", "note": f"标签机构 '{e['title_raw']}' 与别名表不一致，记为 {rec['org']}", "confidence": "中"})
            elif lab:
                rec.update(role="analyst", analyst_id=lab[0], org=aliases.analysts[lab[0]]["org"])
            else:
                rec.update(role="unknown")
                fixes.append({"rule": "R7", "note": f"未知发言人 {sp}", "confidence": "低"})
            first_after_handoff = False

        if rec["role"] == "analyst" and slot and slot.get("org_conflict") and not any(f.get("rule") == "R9" for f in fixes):
            c = slot["org_conflict"]
            fixes.append({"rule": "R9", "note": f"机构冲突：文字稿写作 {c['transcribed_org']}，记为 {c['resolved_org']}（{c['basis']}）", "confidence": c["confidence"]})
        flag = aliases.flags.get((quarter, e["src_i"]))
        if flag:
            fixes.append({"rule": "FLAG", "note": flag["note"], "confidence": flag["confidence"]})
        rec["fixes"] = fixes
        rec["needs_review"] = any(f["confidence"] != "高" for f in fixes) or rec["role"] == "analyst"
        if rec["role"] == "analyst":
            rec["review"] = REVIEW_NOTE
        if slot and rec["role"] in ("analyst",):
            rec["slot"] = slot["n"]
        out.append(rec)
    return out


_SLOT_COUNTER = {}


def _make_slot(h, aliases, quarter):
    n = _SLOT_COUNTER.get(quarter, 0) + 1
    _SLOT_COUNTER[quarter] = n
    aid = h["analyst_id"]
    conf = aliases.by_string[h["alias"]][1]
    s = {"n": n, "analyst_id": aid, "alias": h["alias"], "alias_conf": conf, "org_transcribed": h["org_transcribed"]}
    c = aliases.org_conflict(aid, quarter)
    if c:
        s["org_conflict"] = c
    elif h["org_transcribed"] and h["org_transcribed"] != aliases.analysts[aid]["org"]:
        s["org_conflict"] = {"transcribed_org": h["org_transcribed"], "resolved_org": aliases.analysts[aid]["org"],
                             "confidence": "低", "basis": "别名表默认机构"}
    return s


def _norm_org(title, aliases):
    return {aliases.org_map[m.group(1)] for m in aliases.org_re.finditer(title)}


def run_fix(aliases):
    _SLOT_COUNTER.clear()
    fixed = {}
    FIXED_DIR.mkdir(parents=True, exist_ok=True)
    for q in QUARTERS:
        turns = load_json(DATA_PARSED / f"{q}.json")
        fixed[q] = fix_quarter(q, turns, aliases)
    return fixed


def build_slots(fixed_q):
    """分析师提问时段：同一 slot 编号下的分析师发言（保持顺序）。"""
    slots = OrderedDict()
    for t in fixed_q:
        if t["role"] == "analyst" and t.get("slot"):
            s = slots.setdefault(t["slot"], {"slot": t["slot"], "analyst_id": t["analyst_id"], "speaker": t["speaker"],
                                             "org": t["org"], "turns": []})
            s["turns"].append(t)
    return slots


def dump_slots(fixed):
    for q in QUARTERS:
        for s in build_slots(fixed[q]).values():
            print(f"### {qlabel(q)} slot{s['slot']} {s['speaker']} | {s['org']}")
            for t in s["turns"]:
                print(f"  [{t['i']}/src{t['src_i']}] {t['text']}")
            print()


# ---------------------------------------------------------------------------
# 0. 来源登记
# ---------------------------------------------------------------------------
# 用户在对话中提供的链接（原样记录；登记时去掉 utm 跟踪参数）。
USER_PROVIDED_URLS = [
    "https://stockanalysis.com/quote/hkg/0700/transcripts/374535-q3-2025/?utm_source=chatgpt.com",
    "https://stockanalysis.com/quote/hkg/0700/transcripts/419871-q4-2025/?utm_source=chatgpt.com",
    "https://stockanalysis.com/quote/hkg/0700/transcripts/609405-q1-2026/?utm_source=chatgpt.com",
    "https://stockanalysis.com/quote/hkg/0700/transcripts/667897-q2-2026/?utm_source=chatgpt.com",
    "https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf?utm_source=chatgpt.com",
    "https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf?utm_source=chatgpt.com",
    "https://www.tencent.com/investors/results/?utm_source=chatgpt.com",
    "https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf?utm_source=chatgpt.com",
]
OFFICIAL_QUARTERS = ["3Q25", "4Q25", "1Q26", "2Q26"]
OFFICIAL_DATES = {"3Q25": "2025-11-13", "4Q25": "2026-03-18", "1Q26": "2026-05-13", "2Q26": "2026-08-12"}
IR_RESULTS_URL = "https://www.tencent.com/investors/results/"


def strip_utm(url):
    return re.sub(r"[?&]utm_[^&]+", "", url)


def read_manifest():
    rows = {}
    for line in (IR_DIR / "manifest.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            rows[(parts[0], parts[1])] = {"file": parts[2], "url": parts[3]}
    return rows


def build_sources():
    sources, by_q, inputs = [], {}, []
    user_set = {strip_utm(u) for u in USER_PROVIDED_URLS}
    files = {}
    for p in (DATA_SRC / "transcripts").glob("*.html"):
        m = re.match(r"\d+-(q\d-\d{4})\.html$", p.name)
        if m:
            files[m.group(1)] = p
    for k, q in enumerate(QUARTERS, start=1):
        p = files[q]
        h = p.read_text(encoding="utf-8")
        url = re.search(r'rel="canonical" href="([^"]+)"', h).group(1)
        title = re.search(r"<title>(.*?)</title>", h, re.S).group(1).replace("&amp;", "&")
        dates = re.findall(r'(?:date|Date)\w*\s*:\s*"(\d{4}-\d{2}-\d{2})', h)
        sid = f"S{k:02d}"
        sources.append({"id": sid, "title": f"{title}（StockAnalysis 页面，数据源 Quartr；第三方文字稿，非官方逐字稿）",
                        "url": url, "date": dates[0] if dates else "", "tier": 3,
                        "user_provided": url in user_set, "local_copy": rel(p)})
        by_q[q] = sid
        inputs.append(input_record(p))
    man = read_manifest()
    ir_html = IR_PAGE.read_text(encoding="utf-8", errors="replace")
    k = len(sources) + 1
    ir_sid = f"S{k:02d}"
    sources.append({"id": ir_sid, "title": "腾讯控股官网 投资者关系 · Results 页面（本地快照）", "url": IR_RESULTS_URL,
                    "date": AS_OF, "tier": 2, "user_provided": IR_RESULTS_URL in user_set, "local_copy": rel(IR_PAGE)})
    inputs.append(input_record(IR_PAGE))
    official = {}
    for oq in OFFICIAL_QUARTERS:
        for kind, label in (("ppt", "业绩演示材料（PPT）"), ("release_en", "英文业绩新闻稿")):
            if kind == "release_en" and oq != "2Q26":
                continue
            m = man[(oq, kind)]
            k += 1
            sid = f"S{k:02d}"
            txt = IR_DIR / m["file"].replace(".pdf", ".txt")
            sources.append({"id": sid, "title": f"腾讯 {oq} {label}", "url": m["url"], "date": OFFICIAL_DATES[oq],
                            "tier": 2, "user_provided": m["url"] in user_set,
                            "listed_on_ir_results_page": m["url"] in ir_html,
                            "local_copy": rel(IR_DIR / m["file"]), "text_used": rel(txt)})
            official[(oq, kind)] = {"sid": sid, "txt": txt}
            inputs.append(input_record(txt))
    url2sid = {s["url"]: s["id"] for s in sources}
    used_for = {
        "stockanalysis": "实录正文：发言人归属修正、问题单元编码、双轨热度、缺口、机构轨迹、回测、叙事演变",
        "ppt": "文字稿数字保真抽查：CFO/分析师口述的收入、毛利、资本开支与官方 PPT 逐项比对（见 transcript_fidelity）",
        "ir": "核对各季 PPT/新闻稿链接确实列于腾讯官网 Results 页面（本地快照 tc_res.html）",
    }
    user_rows = []
    for u in USER_PROVIDED_URLS:
        cu = strip_utm(u)
        kind = "stockanalysis" if "stockanalysis" in cu else ("ir" if cu == IR_RESULTS_URL else "ppt")
        sid = url2sid.get(cu)
        user_rows.append({"url_as_given": u, "url_registered": cu, "source_id": sid,
                          "used_for": used_for[kind], "status": "已使用" if sid else "未找到本地副本"})
    return sources, by_q, ir_sid, official, inputs, user_rows


# ---------------------------------------------------------------------------
# 2. 问题单元
# ---------------------------------------------------------------------------
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’&.-]*")


def trim(text, n=200):
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= n:
        return t
    cut = t[:n - 1]
    sp = cut.rfind(" ")
    if sp > n * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" ,;:") + "…"


def build_units(fixed, coding, aliases, src_by_q):
    units, errors = [], []
    by_key = {(c["quarter"], c["slot"]): c for c in coding["slots"]}
    seen = set()
    for q in QUARTERS:
        ql = qlabel(q)
        n_in_q = 0
        for sn, s in build_slots(fixed[q]).items():
            c = by_key.get((ql, sn))
            if not c:
                errors.append(f"{ql} slot{sn} {s['speaker']} 未编码")
                continue
            seen.add((ql, sn))
            full = "\n".join(t["text"] for t in s["turns"])
            starts = [full.find(u["anchor"]) for u in c["units"]]
            for u, p in zip(c["units"], starts):
                if p < 0:
                    errors.append(f"{ql} slot{sn} 锚点未找到: {u['anchor'][:60]}")
            if any(p < 0 for p in starts):
                continue
            if starts != sorted(starts):
                errors.append(f"{ql} slot{sn} 锚点顺序错误")
            first = s["turns"][0]
            for k, u in enumerate(c["units"]):
                end = starts[k + 1] if k + 1 < len(starts) else len(full)
                text = full[starts[k]:end].strip()
                for tp, ev in u["topics"].items():
                    if tp not in TOPICS:
                        errors.append(f"{ql} slot{sn} 未知话题 {tp}")
                    if ev not in text:
                        errors.append(f"{ql} slot{sn} 证据不在原文: {tp} '{ev}'")
                n_in_q += 1
                rec = OrderedDict([
                    ("q_id", f"{ql}-Q{n_in_q:02d}"), ("quarter", ql), ("analyst", s["speaker"]),
                    ("org", s["org"]), ("excerpt", trim(text)), ("topics", list(u["topics"].keys())),
                    ("evidence", u["topics"]),
                ])
                if first.get("alias_candidate"):
                    rec["analyst_note"] = f"文字稿姓名存疑，候选 {first['alias_candidate']}（低置信）"
                if first.get("org_note"):
                    rec["org_note"] = first["org_note"]
                rec.update({"slot": sn, "turn_ids": [t["i"] for t in s["turns"]], "unit_words": len(WORD_RE.findall(text)),
                            "review": REVIEW_NOTE, "excerpt_label": "公开披露", "label": "推断",
                            "label_note": "话题标签为人工逐条阅读编码（判断），非关键词自动匹配", "tier": 3,
                            "src": [src_by_q[q]]})
                units.append(rec)
    for key in by_key:
        if key not in seen:
            errors.append(f"编码表中的 {key} 在修正后文字稿中不存在")
    return units, errors


# ---------------------------------------------------------------------------
# 3/4. 双轨热度与缺口（管理层侧为词表计数）
# ---------------------------------------------------------------------------
_NOT_ADV = r"(?<!advertiser )(?<!advertisers' )(?<!marketing )(?<!merchants' )"
MGMT_LEXICON = OrderedDict([
    ("AI_CAPEX", [r"\bcap ?ex\b", r"\bcapital expenditures?\b", r"\bAI (?:infrastructure )?investments?\b",
                  r"\binvest(?:ing|ment|ments)? in (?:AI|compute|GPUs?|servers?)\b", r"\bfront-loaded investments?\b"]),
    ("AI_ROI", [_NOT_ADV + r"\bROI[CS]?\b", r"\breturn on (?:invested capital|investment|equity)\b", r"\bpayback\b",
                r"\bbreak-?even\b", r"\b(?:financial|economic|attractive) returns?\b", r"\bmonetiz\w* (?:AI|agents?|tokens?)\b"]),
    ("AI_PRODUCTS", [r"\bYuanbao\b", r"\bWork ?Buddy\b", r"\bCode ?Buddy\b", r"\bXiaowei\b", r"\bQClaw\b", r"\bOpenClaw\b",
                     r"\bclaws?\b", r"\bima\b", r"\bagents?\b", r"\bagentic\b", r"\bAI assistants?\b", r"\bchatbots?\b",
                     r"\bnew AI products?\b", r"\bAI-native\b"]),
    ("MODELS", [r"\bHun ?yuan\b", r"\bHy\b", r"\bLLMs?\b", r"\blarge language models?\b", r"\bfoundation models?\b",
                r"\bfrontier models?\b", r"\bSOTA\b", r"\bmultimodal\b", r"\bworld models?\b", r"\bWeLM\b",
                r"\bmodel (?:capabilit\w+|training)\b", r"\breasoning\b", r"\btext-to-\w+\b"]),
    ("COMPUTE", [r"\bGPUs?\b", r"\bchips?\b", r"\bH20\b", r"\bNvidia\b", r"\bASICs?\b", r"\bcompute\b",
                 r"\bcomputing (?:power|capacity|resources?)\b", r"\bservers?\b", r"\bdata cent(?:er|re)s?\b",
                 r"\bDRAM\b", r"\bHBM\b"]),
    ("CLOUD", [r"\bcloud\b", r"\btokens?\b", r"\bAPIs?\b", r"\bModel-as-a-Service\b", r"\bMaaS\b", r"\bIaaS\b", r"\bPaaS\b",
               r"\bneo ?clouds?\b"]),
    ("MARGIN", [r"\bmargins?\b", r"\bdepreciation\b", r"\bamorti[sz]ation\b", r"\bD&A\b", r"\boperating leverage\b",
                r"\bexpenses?\b", r"\bcost efficienc\w+\b", r"\bunit costs?\b", r"\bopex\b"]),
    ("CAPITAL", [r"\bbuy ?backs?\b", r"\bshare repurchases?\b", r"\brepurchased?\b", r"\bdividends?\b",
                 r"\bfree cash flow\b", r"\bnet cash\b", r"\bdebt\b", r"\bborrowings?\b", r"\bcapital allocation\b",
                 r"\bshareholder returns?\b"]),
    ("ADS", [r"\badvertis\w*", r"\bmarketing services?\b", r"\bads?\b", r"\beCPMs?\b", r"\bclick-through\b",
             r"\bAIM ?(?:Plus|\+)", r"\bAI Marketing Plus\b", r"\bad ?tech\b"]),
    ("GAMES_DOM", [r"\bdomestic games?\b", r"\bHonor of Kings\b", r"\bPeacekeeper Elite\b", r"\bDelta Force\b",
                   r"\bDungeon (?:&|and) Fighter\b", r"\bDNF\b", r"\bmini[- ]games?\b", r"\bBanhao\b", r"\bCross ?fire\b",
                   r"\bevergreen games?\b"]),
    ("GAMES_INTL", [r"\binternational games?\b", r"\bSupercell\b", r"\bRiot\b", r"\bBrawl Stars\b", r"\bClash\b",
                    r"\bPUBG MOBILE\b", r"\bVALORANT\b", r"\bLeague of Legends\b", r"\bPath of Exile\b", r"\bWhiteout Survival\b"]),
    ("FINTECH", [r"\bfin ?tech\b", r"\bpayments?\b", r"\bWeixin Pay\b", r"\bwealth management\b", r"\bconsumer loans?\b",
                 r"\bloan facilitation\b", r"\blending\b", r"\bbusiness services\b", r"\bWeCom\b", r"\bTencent Meeting\b",
                 r"\bTencent Docs\b", r"\bSaaS\b"]),
    ("SOCIAL", [r"\bVideo Accounts?\b", r"\bMini Programs?\b", r"\bMini Shops?\b", r"\be-commerce\b", r"\bMoments\b",
                r"\bOfficial Accounts?\b", r"\bQQ\b", r"\bTencent Video\b", r"\bmusic\b", r"\bsubscriptions?\b",
                r"\blive ?streaming\b", r"\bsocial networks?\b", r"\bWeixin ecosystem\b"]),
    ("REG", [r"\bregulat\w+", r"\bgeopolitic\w*", r"\bexport controls?\b", r"\b1260H\b", r"\bDepartment of Defense\b",
             r"\bsanctions?\b", r"\bBIS\b", r"\btariffs?\b", r"\bchip ban\b", r"\blicens\w+ requirements?\b",
             r"\banti-involution\b", r"\bantitrust\b", r"\bgovernment polic\w+", r"\bpolicymakers?\b"]),
    ("PORTFOLIO", [r"\binvestment portfolio\b", r"\binvestees?\b", r"\bdivest\w*", r"\bdisposals?\b", r"\bassociates?\b",
                   r"\bdistribution in specie\b", r"\bstrategic investments?\b"]),
])
MGMT_RE = {tp: re.compile("|".join(f"(?:{p})" for p in ps), re.I) for tp, ps in MGMT_LEXICON.items()}


def count_topics(text):
    out = {}
    for tp, rx in MGMT_RE.items():
        n = 0
        for m in rx.finditer(text):
            if m.group(0).lower() == "hy" and m.group(0) != "Hy":  # 'Hy'（混元新名）大小写敏感
                continue
            n += 1
        out[tp] = n
    return out


def qa_start_index(fixed_q):
    for t in fixed_q:
        if t["role"] == "moderator" and re.search(r"(open the floor|opening the floor)", t["text"], re.I):
            return t["i"]
    for t in fixed_q:
        if t["role"] == "analyst":
            return t["i"]
    return len(fixed_q)


def heat(fixed, units):
    rows = OrderedDict()
    for q in QUARTERS:
        ql = qlabel(q)
        qs = qa_start_index(fixed[q])
        w = {"total": 0, "prepared": 0, "qa": 0}
        c = {"total": Counter(), "prepared": Counter(), "qa": Counter()}
        aw = 0
        for t in fixed[q]:
            if t["role"] == "analyst":
                aw += len(WORD_RE.findall(t["text"]))
            if t["role"] != "mgmt":
                continue
            part = "prepared" if t["i"] < qs else "qa"
            nw = len(WORD_RE.findall(t["text"]))
            cnt = count_topics(t["text"])
            for k in ("total", part):
                w[k] += nw
                c[k].update(cnt)
        qu = [u for u in units if u["quarter"] == ql]
        acnt = Counter(tp for u in qu for tp in u["topics"])
        rows[ql] = {
            "mgmt": {"words": w["total"], "words_prepared": w["prepared"], "words_qa": w["qa"],
                     "mentions": {tp: c["total"][tp] for tp in TOPICS},
                     "per10k": {tp: round(c["total"][tp] / w["total"] * 1e4, 1) if w["total"] else None for tp in TOPICS},
                     "mentions_prepared": {tp: c["prepared"][tp] for tp in TOPICS},
                     "per10k_prepared": {tp: round(c["prepared"][tp] / w["prepared"] * 1e4, 1) if w["prepared"] else None for tp in TOPICS},
                     "mentions_qa": {tp: c["qa"][tp] for tp in TOPICS}},
            "analyst": {"n_units": len(qu), "analyst_words": aw, "n_orgs": len({u["org"] for u in qu}),
                        "counts": {tp: acnt[tp] for tp in TOPICS},
                        "share": {tp: round(acnt[tp] / len(qu), 3) if qu else None for tp in TOPICS}},
        }
    return rows


def gap(heat_rows, units, window):
    mg, mg_prep, words = Counter(), Counter(), 0
    for ql in window:
        mg.update(heat_rows[ql]["mgmt"]["mentions"])
        mg_prep.update(heat_rows[ql]["mgmt"]["mentions_prepared"])
        words += heat_rows[ql]["mgmt"]["words"]
    wu = [u for u in units if u["quarter"] in window]
    tags = Counter(tp for u in wu for tp in u["topics"])
    unit_has = Counter(tp for u in wu for tp in set(u["topics"]))
    tot_m, tot_p, tot_t = sum(mg.values()), sum(mg_prep.values()), sum(tags.values())
    rows = []
    for tp in TOPICS:
        push = mg[tp] / tot_m if tot_m else 0
        push_p = mg_prep[tp] / tot_p if tot_p else 0
        pull_norm = tags[tp] / tot_t if tot_t else 0
        rows.append({"topic": tp, "name": TOPICS[tp],
                     "mgmt_mentions": mg[tp], "push_share": round(push, 4), "push_share_prepared_only": round(push_p, 4),
                     "analyst_units": unit_has[tp], "pull_share_units": round(unit_has[tp] / len(wu), 4) if wu else None,
                     "pull_share_norm": round(pull_norm, 4),
                     "gap_pp": round((pull_norm - push) * 100, 1),
                     "gap_pp_prepared_only": round((pull_norm - push_p) * 100, 1)})
    pos = max(rows, key=lambda r: r["gap_pp"])
    neg = min(rows, key=lambda r: r["gap_pp"])
    for r in rows:
        r["flag"] = "分析师关注占比最大缺口" if r is pos else ("管理层主动提及占比最大缺口" if r is neg else "")
    return {"window": window, "n_units": len(wu), "n_tags": tot_t, "mgmt_words": words, "mgmt_topic_mentions": tot_m,
            "rows": rows, "max_pull_gap": pos["topic"], "max_push_gap": neg["topic"],
            "top3_pull_gap": [r["topic"] for r in sorted(rows, key=lambda r: -r["gap_pp"])[:3]],
            "top3_push_gap": [r["topic"] for r in sorted(rows, key=lambda r: r["gap_pp"])[:3]]}


KEYWORDS = OrderedDict([
    ("WorkBuddy", r"\bWork ?Buddy\b"), ("CodeBuddy", r"\bCode ?Buddy\b"), ("Yuanbao/元宝", r"\bYuanbao\b"),
    ("Hunyuan/混元", r"\bHun ?yuan\b"), ("Xiaowei/小微", r"\bXiaowei\b"), ("QClaw/OpenClaw/Claw", r"\b(?:QClaw|OpenClaw|claws?)\b"),
    ("agent/agentic/智能体", r"\bagent(?:s|ic)?\b"), ("token", r"\btokens?\b"), ("capex", r"\b(?:cap ?ex|capital expenditures?)\b"),
    ("ROI/ROIC/payback", r"\b(?:ROI[CS]?|payback)\b"), ("generative AI", r"\b(?:generative AI|Gen ?AI)\b"),
])


def keyword_counts(fixed):
    out = []
    for kw, pat in KEYWORDS.items():
        rx = re.compile(pat, re.I)
        byq = OrderedDict()
        for q in QUARTERS:
            c = Counter()
            for t in fixed[q]:
                c[t["role"]] += len(rx.findall(t["text"]))
            byq[qlabel(q)] = {"mgmt": c["mgmt"], "analyst": c["analyst"], "moderator": c["moderator"]}
        out.append({"keyword": kw, "regex": pat, "by_quarter": byq,
                    "first_mgmt": next((ql for ql, v in byq.items() if v["mgmt"]), None),
                    "first_analyst": next((ql for ql, v in byq.items() if v["analyst"]), None), "label": "计算"})
    return out


# ---------------------------------------------------------------------------
# 5/6. 机构轨迹与回测
# ---------------------------------------------------------------------------
def org_trajectory(units):
    orgs = OrderedDict()
    for u in units:
        o = orgs.setdefault(u["org"], OrderedDict())
        q = o.setdefault(u["quarter"], {"topic_counts": Counter(), "analysts": [], "q_ids": []})
        q["topic_counts"].update(u["topics"])
        nm = u["analyst"] + ("（姓名存疑）" if u.get("analyst_note") else "")
        if nm not in q["analysts"]:
            q["analysts"].append(nm)
        q["q_ids"].append(u["q_id"])
    order = list(TOPICS)
    out = []
    for org, qs in orgs.items():
        row = {"org": org, "n_quarters": len(qs), "n_units": sum(len(v["q_ids"]) for v in qs.values()), "quarters": OrderedDict()}
        tot = Counter()
        for ql in [qlabel(q) for q in QUARTERS]:
            if ql in qs:
                v = qs[ql]
                tot.update(v["topic_counts"])
                row["quarters"][ql] = {"topics": sorted(v["topic_counts"], key=lambda tp: (-v["topic_counts"][tp], order.index(tp))),
                                       "analysts_note": "、".join(v["analysts"]) + f"（{REVIEW_NOTE}）", "q_ids": v["q_ids"]}
        row["top_topics_all"] = sorted(tot, key=lambda tp: (-tot[tp], order.index(tp)))[:3]
        out.append(row)
    out.sort(key=lambda r: (-r["n_quarters"], -r["n_units"], r["org"]))
    return out


def backtest(units, train, test):
    order = list(TOPICS)
    train_units = [u for u in units if u["quarter"] in train]
    glob = Counter(tp for u in train_units for tp in u["topics"])

    def rank(counter, last_seen):
        return sorted(counter, key=lambda tp: (-counter[tp], -last_seen.get(tp, -1), -glob[tp], order.index(tp)))

    baseline = rank(glob, {})[:2]
    test_orgs = OrderedDict()
    for u in units:
        if u["quarter"] == test:
            test_orgs.setdefault(u["org"], set()).update(u["topics"])
    rows, excluded = [], []
    hits = base_hits = any_hit = base_any = 0
    for org, actual in test_orgs.items():
        hist = [u for u in train_units if u["org"] == org]
        if not hist:
            excluded.append(org)
            continue
        c = Counter(tp for u in hist for tp in u["topics"])
        last = {}
        for u in hist:
            for tp in u["topics"]:
                last[tp] = max(last.get(tp, -1), train.index(u["quarter"]))
        pred = rank(c, last)[:2]
        h = [tp for tp in pred if tp in actual]
        bh = [tp for tp in baseline if tp in actual]
        hits += len(h)
        base_hits += len(bh)
        any_hit += bool(h)
        base_any += bool(bh)
        rows.append({"org": org, "history_units": len(hist), "history_quarters": sorted({u["quarter"] for u in hist}),
                     "history_topic_counts": dict(c.most_common()),
                     "predicted_top2": pred, "actual_topics": [tp for tp in order if tp in actual],
                     "hits": h, "baseline_hits": bh})
    n = len(rows)
    return {"train_quarters": train, "test_quarter": test, "n_orgs": n, "n_predictions": 2 * n,
            "excluded_orgs_no_history": excluded,
            "method": "每家机构取其训练期（2025Q3–2026Q1）问题单元中出现次数最多的 2 个话题（并列时取最近出现、再取全体频次），与该机构 2026Q2 实际话题集合比对",
            "precision_at2": round(hits / (2 * n), 3) if n else None, "org_hit_rate": round(any_hit / n, 3) if n else None,
            "hits": hits,
            "baseline": {"rule": "所有机构都预测训练期全体最常见的 2 个话题", "topics": baseline, "hits": base_hits,
                         "precision_at2": round(base_hits / (2 * n), 3) if n else None,
                         "org_hit_rate": round(base_any / n, 3) if n else None},
            "rows": rows, "label": "计算",
            "caveat": "仅作合理性检查：样本极小，话题为人工编码，不能据此评价任何个人；预测只表示'机构历史关注话题→可能延续'。"}


# ---------------------------------------------------------------------------
# 7. 叙事演变
# ---------------------------------------------------------------------------
NARRATIVE_FIRST = OrderedDict([
    ("AI（生成式AI）", r"\b(?:generative AI|Gen ?AI)\b"), ("混元 Hunyuan", r"\bHun ?yuan\b"), ("元宝 Yuanbao", r"\bYuanbao\b"),
    ("智能体 agent/agentic", r"\bagent(?:s|ic)?\b"), ("WorkBuddy", r"\bWork ?Buddy\b"), ("CodeBuddy", r"\bCode ?Buddy\b"),
    ("小微 Xiaowei", r"\bXiaowei\b"), ("capex", r"\b(?:cap ?ex|capital expenditures?)\b"),
])


def narrative(fixed, coding, src_by_q):
    first, errors = [], []
    for name, pat in NARRATIVE_FIRST.items():
        rx = re.compile(pat, re.I)
        hit = next(((q, t) for q in QUARTERS for t in fixed[q] if t["role"] == "mgmt" and rx.search(t["text"])), None)
        if hit:
            q, t = hit
            first.append({"keyword": name, "first_quarter_mgmt": qlabel(q), "turn_id": t["i"],
                          "speaker_as_transcribed": t["speaker"],
                          "note": "样本窗口起点为 2023Q3，首季即出现不代表历史首次" if q == QUARTERS[0] else "",
                          "src": [src_by_q[q]], "label": "计算"})
    quotes = []
    qmap = {qlabel(q): q for q in QUARTERS}
    for item in coding["narrative"]:
        q = qmap[item["quarter"]]
        found = next((t for t in fixed[q] if t["role"] == "mgmt" and item["quote"] in t["text"]), None)
        nw = len(item["quote"].split())
        if not found:
            errors.append(f"引语未在 {item['quarter']} 管理层发言中找到: {item['quote'][:50]}")
            continue
        if nw > 25:
            errors.append(f"引语超过 25 词: {item['quote'][:50]}")
        quotes.append({"quarter": item["quarter"], "group": item["group"], "kind": item["kind"], "quote": item["quote"],
                       "words": nw, "speaker_as_transcribed": found["speaker"], "turn_id": found["i"],
                       "tier": 3, "quote_note": QUOTE_NOTE,
                       "speaker_note": "管理层内部的发言人标签未修正，个别答复的具体发言人可能有误",
                       "src": [src_by_q[q]], "label": "公开披露"})
    return {"first_seen": first, "quotes": quotes}, errors


# ---------------------------------------------------------------------------
# 8. 文字稿数字保真抽查（官方 PPT / 新闻稿）
# ---------------------------------------------------------------------------
FIDELITY_ITEMS = [
    ("总收入（十亿元）", r"total revenue was (?:RMB|CNY) ?([\d.]+) billion", "ppt", r"^Revenue\s+([\d.]+)"),
    ("毛利（十亿元）", r"Gross profit was (?:RMB|CNY) ?([\d.]+) billion", "ppt", r"^Gross profit\s+([\d.]+)"),
    ("经营性资本开支（十亿元）", r"[Oo]perating CapEx was (?:RMB|CNY) ?([\d.]+) billion", "ppt", r"^Operating CAPEX\s+([\d.]+)"),
]
FIDELITY_EXTRA = [
    # (季度, 说明, 文字稿正则, 发言角色, 官方材料, 官方正则)
    ("2025Q3", "分析师口述：当季资本开支付现（十亿元）", r"cash payment for CapEx was CNY ([\d.]+) billion", "analyst", "ppt",
     r"Less: CAPEX Paid\s+\(([\d.]+)\)"),
    ("2026Q2", "分析师口述：当季资本开支（十亿元）", r"latest quarter's CapEx, RMB ([\d.]+) billion", "analyst", "ppt",
     r"^Total CAPEX\s+([\d.]+)"),
    ("2026Q2", "CFO 口述：资本开支付现（十亿元）", r"capital expenditure payments of RMB ([\d.]+) billion", "mgmt", "release_en",
     r"capital expenditure payments of RMB\s?([\d.]+) billion"),
]
OQ = {"2025Q3": "3Q25", "2025Q4": "4Q25", "2026Q1": "1Q26", "2026Q2": "2Q26"}


def fidelity(fixed, official, src_by_q):
    qmap = {qlabel(q): q for q in QUARTERS}

    def tx_value(ql, pat, role):
        for t in fixed[qmap[ql]]:
            if t["role"] == role:
                m = re.search(pat, t["text"])
                if m:
                    return float(m.group(1)), m.group(0)
        return None, None

    def off_value(oq, kind, pat):
        o = official.get((oq, kind))
        if not o:
            return None, None
        m = re.search(pat, o["txt"].read_text(encoding="utf-8", errors="replace"), re.M)
        return (float(m.group(1)) if m else None), o["sid"]

    specs = [(ql, name, tpat, "mgmt", kind, opat) for ql in OQ for name, tpat, kind, opat in FIDELITY_ITEMS] + FIDELITY_EXTRA
    rows = []
    for ql, name, tpat, role, kind, opat in specs:
        tv, tquote = tx_value(ql, tpat, role)
        ov, osid = off_value(OQ[ql], kind, opat)
        if tv is None or ov is None:
            status = "未找到"
        elif abs(tv - ov) < 0.05:
            status = "一致"
        elif abs(tv - ov) <= 0.5 and round(ov) == tv:
            status = "取整后一致"
        else:
            status = "不一致"
        rows.append({"quarter": ql, "item": name, "speaker_role": role, "transcript_value": tv, "transcript_phrase": tquote,
                     "official_value": ov, "official_doc": f"{OQ[ql]} {kind}", "status": status,
                     "src": [src_by_q[qmap[ql]]] + ([osid] if osid else []), "label": "计算"})
    return {"rows": rows, "n_items": len(rows), "n_consistent": sum(r["status"] in ("一致", "取整后一致") for r in rows),
            "note": "抽查第三方文字稿中的数字是否与腾讯官方 PPT / 新闻稿一致，用于评估文字稿转写质量；不替代官方口径。"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
RULES = {"R1": "删除网页页脚", "R3": "拆出被并入主持人发言的分析师提问", "R4": "管理层标签下的交接语→主持人",
         "R5": "管理层标签下的提问→分析师（自报姓名/交接后提问句式）", "R6": "'Speaker N'→按交接语归属分析师",
         "R7": "标签姓名/机构按别名表归一", "R8": "散场语→主持人", "R9": "交接语机构与别名表冲突",
         "ALIAS": "低置信别名（不合并姓名）", "FLAG": "人工标记的存疑发言（保留原标签）"}


def attribution_summary(fixed):
    by_rule, review, per_q = Counter(), [], OrderedDict()
    for q in QUARTERS:
        n_fix = 0
        for t in fixed[q]:
            rules = [f["rule"] for f in t["fixes"] if f["rule"] != "R1"]
            by_rule.update(rules)
            n_fix += bool(rules)
            low = [f for f in t["fixes"] if f["confidence"] in ("中", "低")]
            if low:
                review.append({"quarter": qlabel(q), "turn_id": t["i"], "src_i": t["src_i"], "speaker": t["speaker"],
                               "speaker_raw": t["speaker_raw"], "role": t["role"],
                               "notes": [f"{f['rule']}[{f['confidence']}] {f['note']}" for f in low]})
        per_q[qlabel(q)] = {"turns": len(fixed[q]), "turns_fixed": n_fix, "roles": dict(Counter(t["role"] for t in fixed[q]))}
    return {"rules": RULES, "fix_counts": dict(by_rule), "per_quarter": per_q, "needs_review_待录音复核": review,
            "alias_table": "demo/pipeline/analyst_aliases.json", "fixed_dir": "data/parsed_fixed/",
            "note": "只修正角色层面（管理层/分析师/主持人）与分析师姓名机构；管理层内部谁答了哪题的标签未修正。"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    aliases = Aliases(ALIAS_PATH)
    coding = load_json(CODING_PATH)
    fixed = run_fix(aliases)
    sources, src_by_q, ir_sid, official, src_inputs, user_rows = build_sources()

    for q in QUARTERS:
        payload = {"quarter": qlabel(q), "source": src_by_q[q], "review": REVIEW_NOTE,
                   "generated_by": "demo/pipeline/transcripts.py", "rules": RULES, "turns": fixed[q]}
        (FIXED_DIR / f"{q}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    units, unit_errors = build_units(fixed, coding, aliases, src_by_q)
    heat_rows = heat(fixed, units)
    window = [qlabel(q) for q in QUARTERS[-4:]]
    gap_res = gap(heat_rows, units, window)
    kw = keyword_counts(fixed)
    wb = next(k for k in kw if k["keyword"] == "WorkBuddy")["by_quarter"]["2026Q2"]
    traj = org_trajectory(units)
    bt = backtest(units, ["2025Q3", "2025Q4", "2026Q1"], "2026Q2")
    narr, narr_errors = narrative(fixed, coding, src_by_q)
    fid = fidelity(fixed, official, src_by_q)
    attr = attribution_summary(fixed)

    # ---- 自检 ----
    checks = OrderedDict()
    t39 = next(t for t in fixed["q2-2026"] if t["src_i"] == 39)
    checks["2026Q2 第39条归属"] = {"expect": "analyst / Morgan Stanley", "got": f"{t39['role']} / {t39['org']} / {t39['speaker']}",
                               "pass": t39["role"] == "analyst" and t39["org"] == "Morgan Stanley"}
    checks["问题单元编码错误数"] = {"expect": 0, "got": len(unit_errors), "pass": not unit_errors, "details": unit_errors[:30]}
    checks["叙事引语校验错误数"] = {"expect": 0, "got": len(narr_errors), "pass": not narr_errors, "details": narr_errors}
    checks["excerpt 长度≤200"] = {"pass": all(len(u["excerpt"]) <= 200 for u in units),
                                "got": max((len(u["excerpt"]) for u in units), default=0)}
    unknown = [(qlabel(q), t["i"]) for q in QUARTERS for t in fixed[q] if t["role"] == "unknown" or SPEAKER_N_RE.match(t["speaker"])]
    checks["未归属发言（含残留 Speaker N）"] = {"expect": 0, "got": len(unknown), "pass": not unknown, "details": unknown}
    checks["2026Q2 WorkBuddy 计数复核"] = {"expect": "管理层27/分析师4（任务给定值）", "got": wb,
                                     "pass": wb["mgmt"] == 27 and wb["analyst"] == 4}
    checks["用户提供链接全部登记"] = {"pass": all(r["source_id"] for r in user_rows), "got": [r["source_id"] for r in user_rows]}
    checks["官方材料链接见于官网 Results 页面"] = {
        "pass": all(s.get("listed_on_ir_results_page", True) for s in sources),
        "got": {s["id"]: s.get("listed_on_ir_results_page") for s in sources if "listed_on_ir_results_page" in s}}
    checks["保真抽查无'不一致'"] = {"pass": all(r["status"] != "不一致" for r in fid["rows"]),
                               "got": f"{fid['n_consistent']}/{fid['n_items']}"}

    inputs = [input_record(DATA_PARSED / f"{q}.json") for q in QUARTERS] + src_inputs + \
             [input_record(ALIAS_PATH), input_record(CODING_PATH)]
    meta_common = {"as_of": AS_OF, "generated_by": "本地 Python", "script": "demo/pipeline/transcripts.py", "inputs": inputs}
    n_units_q = {ql: heat_rows[ql]["analyst"]["n_units"] for ql in heat_rows}

    m2 = OrderedDict()
    m2["meta"] = dict(module="m2_transcripts", title="M2a 业绩会实录分析：发言人修正 · 双轨热度 · 缺口 · 机构轨迹 · 叙事演变",
                      notes=("12 个季度（2023Q3–2026Q2）StockAnalysis 第三方文字稿（非官方逐字稿）。分析师归属依主持人交接语修正，"
                             "均为'第三方文字稿，待录音复核'。话题标签：分析师侧为人工逐条阅读编码；管理层侧为词表计数（见 NOTES）。"
                             "用户提供的 4 个季度文字稿链接与 3 份官方 PPT、官网 Results 页面均已登记并使用（见 user_provided_sources）。"
                             "预测只到'机构历史关注话题→可能延续'，不对个人评价。内部准备材料，不构成公司口径。"),
                      **meta_common)
    m2["sources"] = sources
    m2["user_provided_sources"] = user_rows
    m2["taxonomy"] = [{"id": k, "name": v} for k, v in TOPICS.items()]
    m2["attribution"] = attr
    m2["heat"] = {"quarters": list(heat_rows), "rows": heat_rows,
                  "definition": {"mgmt": "管理层全部发言（含开场陈述与问答答复）中各话题词表命中次数 ÷ 管理层词数 × 10000；另给仅开场陈述口径",
                                 "analyst": "该季问题单元中带该话题标签的单元数 ÷ 问题单元总数 n（多标签，列和可>1）"},
                  "sample_sizes": {ql: {"mgmt_words": heat_rows[ql]["mgmt"]["words"], "n_units": n_units_q[ql],
                                        "n_orgs": heat_rows[ql]["analyst"]["n_orgs"]} for ql in heat_rows},
                  "src": list(src_by_q.values()), "label": "计算"}
    m2["gap"] = dict(gap_res, definition=("管理层主动提及占比=窗口内管理层话题词表命中占全部话题命中的比例；分析师关注占比(归一)=话题标签数占全部标签数的比例；"
                                          "gap_pp=分析师关注占比(归一)−管理层主动提及占比，单位百分点；正值=分析师追问多于管理层主动提及，负值反之。"
                                          "pull_share_units 为未归一的'问题单元占比'。"),
                     src=[src_by_q[q] for q in QUARTERS[-4:]], label="计算")
    m2["keywords"] = {"rows": kw, "check_2026Q2_WorkBuddy": dict(
        wb, total=sum(wb.values()), status="复核一致" if wb["mgmt"] == 27 and wb["analyst"] == 4 else "与任务给定值不一致",
        wording="2026Q2 业绩会提及 WorkBuddy %d 次，其中管理层 %d 次、分析师 %d 次【计算】" % (sum(wb.values()), wb["mgmt"], wb["analyst"]),
        src=[src_by_q["q2-2026"]], label="计算")}
    m2["org_trajectory"] = {"orgs": traj, "note": f"以机构为主键；姓名只作附注（{REVIEW_NOTE}）。话题按该季出现次数排序。",
                            "src": list(src_by_q.values()), "label": "推断"}
    m2["backtest"] = bt
    m2["narrative"] = dict(narr, note=f"引语均为管理层原话（≤25 词英文），tier=3，{QUOTE_NOTE}。")
    m2["transcript_fidelity"] = fid
    m2["self_check"] = checks

    qu = OrderedDict()
    qu["meta"] = dict(module="question_units", title="M2a 问题单元（分析师提问逐题人工编码）",
                      notes=(f"共 {len(units)} 个问题单元。excerpt 为文字稿原文截取（≤200 字符）；topics 为人工阅读编码，evidence 为原文证据短语。"
                             f"分析师姓名与机构：{REVIEW_NOTE}。"), **meta_common)
    qu["sources"] = [s for s in sources if s["tier"] == 3]
    qu["taxonomy"] = m2["taxonomy"]
    qu["n_units_by_quarter"] = n_units_q
    qu["units"] = units

    banned = ["颠覆", "革命性", "首创", "全面领先", "赋能", "取代IR"]
    hits = []
    for obj in (m2, qu):
        txt = json.dumps(obj, ensure_ascii=False)
        assert_no_email(txt)
        hits += [w for w in banned if w in txt]
    checks["禁用词扫描"] = {"pass": not hits, "got": hits}
    p1 = write_module("m2_transcripts", m2)
    p2 = write_module("question_units", qu)

    print(f"写出 {rel(p1)}、{rel(p2)}、data/parsed_fixed/*.json（12 个季度）")
    print(f"问题单元 {len(units)} 个；各季 n = {n_units_q}")
    print(f"缺口窗口 {window}：分析师关注占比最大缺口={gap_res['max_pull_gap']}，管理层主动提及占比最大缺口={gap_res['max_push_gap']}")
    print(f"2026Q2 WorkBuddy：{wb}")
    print(f"回测：precision@2={bt['precision_at2']}，机构命中率={bt['org_hit_rate']}；"
          f"基线 precision@2={bt['baseline']['precision_at2']}，机构命中率={bt['baseline']['org_hit_rate']}（n={bt['n_orgs']} 家）")
    print(f"保真抽查：{fid['n_consistent']}/{fid['n_items']} 项一致")
    bad = [k for k, v in checks.items() if not v.get("pass")]
    for k in bad:
        print(f"  未通过：{k} → {checks[k].get('got')} {checks[k].get('details', '')}")
    print("自检：" + ("全部通过" if not bad else f"{len(bad)} 项未通过"))
    return 0 if not bad else 1


if __name__ == "__main__":
    if "--dump-slots" in sys.argv:
        dump_slots(run_fix(Aliases(ALIAS_PATH)))
        sys.exit(0)
    sys.exit(main())
