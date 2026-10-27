"""M4 注入测试：把 2Q26 中英文业绩新闻稿当作"草稿"，用固定随机种子注入 7 类错误。

运行（在 ROOT 下）：python -I demo/pipeline/inject.py --seed 7 --n 30
输出：demo/data/raw/m4/inject/draft_injected_{en,zh}_seed<seed>.txt、answer_key_seed<seed>.json
（gatekeeper.py all / check --eval 会调用 make_injections 并给出召回率。）

候选位置只用通用正则选取（金额、增减表述、利润率、分部名称），不使用 gk_core 的指标别名表，
以免"出题人"偏向检查器认识的写法。7 类：
  tamper ①数字篡改 / unit ②单位错误 / yoy ③同比方向或幅度错误 / bilingual ④中英文不一致（只改一边）/
  sum ⑤分部之和≠合计 / pct ⑥百分比与数值不符 / new ⑦未披露的新数字（插入新句）
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True  # 不写 .pyc（字节码文件会记录本机绝对路径）
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gk_core as g  # noqa: E402

CATS = ["tamper", "unit", "yoy", "bilingual", "sum", "pct", "new"]
CAT_ZH = {"tamper": "①数字篡改", "unit": "②单位错误", "yoy": "③同比方向/幅度错误", "bilingual": "④中英文不一致（只改一边）",
          "sum": "⑤分部之和≠合计", "pct": "⑥百分比与数值不符", "new": "⑦未披露的新数字"}

RX = {
    "en": {
        "money": re.compile(r"RMB ?(?P<v>\d[\d,]*(?:\.\d+)?) ?(?P<u>billion)"),
        "growth": re.compile(r"\b(?P<w>up|down|increased by|decreased by|rose by|grew by|declined by)\s+(?P<v>\d+(?:\.\d+)?)%"),
        "margin": re.compile(r"[Mm]argin[^.;]{0,45}?(?P<v>\d+(?:\.\d+)?)%"),
        "pct": re.compile(r"(?<![\d.\w])(?P<v>\d+(?:\.\d+)?)%"),
        "count": re.compile(r"(?<![\d.\w])(?P<v>\d+(?:\.\d+)?) ?(?P<u>million)\b(?! ?(?:RMB|HKD))"),
        "seg": re.compile(r"(?:Domestic Games revenues|International Games revenues|Social Networks revenues|"
                          r"Revenues from Marketing Services|Revenues from FinTech and Business Services)[^.]*?"
                          r"RMB ?(?P<v>\d+\.\d) ?billion"),
    },
    "zh": {
        "money": re.compile(r"人民币 ?(?P<v>\d[\d,]*(?:\.\d+)?) ?(?P<u>亿元)"),
        "growth": re.compile(r"(?P<w>增长|下降|增加|减少)\s?(?P<v>\d+(?:\.\d+)?)%"),
        "margin": re.compile(r"利润率[^。;]{0,20}?(?P<v>\d+(?:\.\d+)?)%"),
        "pct": re.compile(r"(?<![\d.])(?P<v>\d+(?:\.\d+)?)%"),
        "count": re.compile(r"(?<![\d.])(?P<v>\d[\d,]*(?:\.\d+)?) ?(?P<u>万)(?=股|$|[^元港美])"),
        "seg": re.compile(r"(?:本土市场游戏收入|国际市场游戏收入|社交网络收入|营销服务\s?\dQ\d{4}\s?收入|"
                          r"金融科技及企业服务\s?\dQ\d{4}\s?收入)[^。]*?人民币 ?(?P<v>\d[\d,]*) ?亿元"),
    },
}
NEW_EN = ["Cloud services revenues grew {p}% year-on-year.", "WorkBuddy paying users exceeded {n} million.",
          "Weixin Mini Shops GMV increased {p}% year-on-year.", "Video Accounts advertising revenues reached RMB{x} billion.",
          "Hy model daily API calls averaged {n} billion."]
NEW_ZH = ["云服务收入同比增长{p}%。", "WorkBuddy 付费用户超过{n}万。", "微信小店GMV同比增长{p}%。",
          "视频号广告收入达人民币{x}亿元。", "混元大模型日均调用量达{n}亿次。"]
GROW_FLIP = {"up": "down", "down": "up", "increased by": "decreased by", "decreased by": "increased by",
             "rose by": "fell by", "grew by": "declined by", "declined by": "grew by",
             "增长": "下降", "下降": "增长", "增加": "减少", "减少": "增加"}


def _fmt_like(old, new_val):
    """按原数字的小数位与千分位格式输出新数字。"""
    dec = len(old.split(".")[1]) if "." in old else 0
    s = f"{new_val:,.{dec}f}" if "," in old else f"{new_val:.{dec}f}"
    return s


def _tamper_digits(rng, s):
    digits = [i for i, ch in enumerate(s) if ch.isdigit()]
    for _ in range(20):
        if rng.random() < 0.5 and len(digits) >= 2:
            k = rng.randrange(len(digits) - 1)
            a, b = digits[k], digits[k + 1]
            if s[a] != s[b]:
                t = list(s)
                t[a], t[b] = t[b], t[a]
                out = "".join(t)
                if not out.lstrip("0,.").startswith(",") and out[0] != "0":
                    return out
        else:
            a = rng.choice(digits)
            nd = str((int(s[a]) + rng.randint(1, 8)) % 10)
            if a == digits[0] and nd == "0":
                continue
            t = list(s)
            t[a] = nd
            return "".join(t)
    return None


def _in_quarter(paras, lang, q):
    """标出处于本季度口径章节、且非标题/非表格行的段落。"""
    ok, period = [], q
    for i, t in enumerate(paras):
        body = re.sub(r"^[▪•\-]\s+", "", t.strip())
        hp = g.heading_period(body, lang)
        if hp:
            period = hp
            ok.append(False)
            continue
        is_row = bool(re.search(r"(?:\s[\(\-+]?\d[\d,]*(?:\.\d+)?\)?%?){3,}$", body))
        ok.append(period == q and not is_row and len(body) > 25)
    return ok


def _candidates(paras, lang, q, avoid):
    okp = _in_quarter(paras, lang, q)
    av = {}
    for f in avoid or []:
        av.setdefault(f["para"], []).append((f["start"], f["end"]))
    c = {k: [] for k in CATS}
    R = RX[lang]

    def free(i, s, e):
        return all(e <= a or s >= b for a, b in av.get(i, []))

    for i, t in enumerate(paras):
        if not okp[i]:
            continue
        for m in R["money"].finditer(t):
            if free(i, m.start(), m.end()):
                c["tamper"].append((i, m.start("v"), m.end("v"), m.group("v")))
                c["unit"].append((i, m.start(), m.end(), m.group(0)))
        for m in R["growth"].finditer(t):
            if free(i, m.start(), m.end()):
                c["yoy"].append((i, m.start(), m.end(), m.group(0), m.group("w"), m.group("v")))
        for m in R["margin"].finditer(t):
            clause_end = len(t)
            for stop in (".", "。", ";"):
                k2 = t.find(stop, m.end())
                if k2 != -1 and k2 < clause_end and not (stop == "." and k2 + 1 < len(t) and t[k2 + 1].isdigit()):
                    clause_end = k2
            for mm in R["pct"].finditer(t, m.start("v"), clause_end):
                if free(i, mm.start("v"), mm.end("v") + 1):
                    c["pct"].append((i, mm.start("v"), mm.end("v"), mm.group("v")))
        for m in R["seg"].finditer(t):
            if free(i, m.start("v"), m.end("v")):
                c["sum"].append((i, m.start("v"), m.end("v"), m.group("v")))
        for m in R["pct"].finditer(t):
            if free(i, m.start("v"), m.end("v") + 1):
                c["bilingual"].append((i, m.start("v"), m.end("v"), m.group("v"), "pct"))
        for m in R["count"].finditer(t):
            if free(i, m.start("v"), m.end("v")):
                c["bilingual"].append((i, m.start("v"), m.end("v"), m.group("v"), "count"))
        if len(t) > 60:
            c["new"].append((i, len(t), len(t), ""))
    return c


def make_injections(en_paras, zh_paras, seed=7, n=30, q=g.TARGET, avoid=None):
    rng = random.Random(seed)
    drafts = {"en": list(en_paras), "zh": list(zh_paras)}
    cands = {lang: _candidates(drafts[lang], lang, q, (avoid or {}).get(lang)) for lang in ("en", "zh")}
    quotas = {c: n // len(CATS) for c in CATS}
    for c in CATS[: n - sum(quotas.values())]:
        quotas[c] += 1
    edits, used = [], {"en": {}, "zh": {}}

    def clash(lang, i, s, e):
        u = used[lang].get(i, [])
        return len(u) >= 2 or any(not (e + 8 <= a or s >= b + 8) for a, b in u)

    k = 0
    order = sorted(CATS, key=lambda c: (len(cands["en"][c]) + len(cands["zh"][c]), CATS.index(c)))
    for cat in order:
        for j in range(quotas[cat]):
            lang = ["en", "zh"][(k + j) % 2]
            pool = [x for x in cands[lang][cat] if not clash(lang, x[0], x[1], x[2])]
            if not pool:
                lang = "zh" if lang == "en" else "en"
                pool = [x for x in cands[lang][cat] if not clash(lang, x[0], x[1], x[2])]
            if not pool:
                continue
            x = rng.choice(pool)
            i, s, e = x[0], x[1], x[2]
            t = drafts[lang][i]
            before = t[s:e]
            if cat == "tamper":
                after = _tamper_digits(rng, before)
                desc = f"金额数字 {before} → {after}"
            elif cat == "unit":
                if lang == "en":
                    after = before.replace("billion", rng.choice(["million", "trillion"])) if rng.random() < 0.7 \
                        else before.replace("RMB", rng.choice(["HKD", "USD"]))
                else:
                    after = before.replace("亿元", rng.choice(["百万元", "万元"])) if rng.random() < 0.7 \
                        else before.replace("人民币", "港币")
                desc = f"单位/币种 {before} → {after}"
            elif cat == "yoy":
                w, v = x[4], x[5]
                if rng.random() < 0.5:
                    after = before.replace(w, GROW_FLIP[w], 1)
                    desc = f"方向反转 {before} → {after}"
                else:
                    nv = float(v) + rng.choice([5, 8, 10, 15])
                    after = before.replace(v + "%", _fmt_like(v, nv) + "%")
                    desc = f"幅度改变 {before} → {after}"
            elif cat == "bilingual":
                v = x[3]
                nv = float(v.replace(",", "")) + rng.choice([3, 5, 7, 10])
                after = _fmt_like(v, nv)
                desc = f"只改{'英文' if lang == 'en' else '中文'}一侧 {v} → {after}"
            elif cat == "sum":
                v = x[3]
                delta = rng.choice([1.2, 2.5, 3.1, 4.0]) * (1 if rng.random() < 0.5 else -1)
                if lang == "en":
                    after = _fmt_like(v, float(v) + delta)
                else:
                    after = _fmt_like(v, float(v.replace(",", "")) + delta * 10)
                desc = f"分部金额 {v} → {after}（合计未改）"
            elif cat == "pct":
                v = x[3]
                nv = float(v) + rng.choice([-6, -4, -3, 3, 4, 6])
                after = _fmt_like(v, nv)
                desc = f"利润率 {v}% → {after}%"
            else:  # new
                tpl = rng.choice(NEW_EN if lang == "en" else NEW_ZH)
                sent = tpl.format(p=rng.randint(12, 95), n=rng.randint(3, 60), x=rng.randint(50, 400))
                after = (" " + sent) if lang == "en" else sent
                desc = f"插入新句：{sent}"
            if not after or after == before:
                continue
            edits.append({"cat": cat, "lang": lang, "para": i, "start": s, "end": e, "before": before, "after": after,
                          "desc": desc})
            used[lang].setdefault(i, []).append((s, e))
        k += quotas[cat]
    # 应用编辑（同段按位置倒序），并计算编辑后坐标
    key = []
    for lang in ("en", "zh"):
        by_para = {}
        for ed in edits:
            if ed["lang"] == lang:
                by_para.setdefault(ed["para"], []).append(ed)
        for i, eds in by_para.items():
            t = drafts[lang][i]
            for ed in sorted(eds, key=lambda d: -d["start"]):
                t = t[:ed["start"]] + ed["after"] + t[ed["end"]:]
            drafts[lang][i] = t
            for ed in eds:
                shift = sum(len(o["after"]) - (o["end"] - o["start"]) for o in eds if o["start"] < ed["start"])
                ns = ed["start"] + shift
                ne = ns + len(ed["after"])
                if ed["cat"] == "new":
                    ns += 1 if lang == "en" else 0
                key.append({**ed, "cat_zh": CAT_ZH[ed["cat"]], "start": ns, "end": ne, "orig_start": ed["start"],
                            "orig_end": ed["end"]})
    key.sort(key=lambda d: (CATS.index(d["cat"]), d["lang"], d["para"], d["start"]))
    for j, d in enumerate(key):
        d["id"] = f"I{j + 1:02d}"
    return drafts["en"], drafts["zh"], key


def main(argv=None):
    ap = argparse.ArgumentParser(description="M4 注入测试：生成注入草稿与答案")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args(argv)
    import gatekeeper as gk
    q = g.TARGET
    en0, _ = gk.draft_paragraphs(q, "release_en")
    zh0, _ = gk.draft_paragraphs(q, "release_zh")
    regs_ref = gk.build_all_registries(g.REF_KINDS)
    corpus = gk.build_corpus(q, g.REF_KINDS)
    base = {"en": gk.check_draft(en0, "en", q, regs_ref[q], corpus, zh0, "zh")[0],
            "zh": gk.check_draft(zh0, "zh", q, regs_ref[q], corpus, en0, "en")[0]}
    en1, zh1, key = make_injections(en0, zh0, seed=args.seed, n=args.n, avoid=base)
    out = gk.INJ_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / f"draft_injected_en_seed{args.seed}.txt").write_text("\n".join(en1) + "\n", encoding="utf-8")
    (out / f"draft_injected_zh_seed{args.seed}.txt").write_text("\n".join(zh1) + "\n", encoding="utf-8")
    (out / f"answer_key_seed{args.seed}.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    cnt = {}
    for d in key:
        cnt[d["cat_zh"]] = cnt.get(d["cat_zh"], 0) + 1
    print(f"[inject] seed={args.seed} 注入 {len(key)} 处：{cnt}")
    for d in key:
        print(f"  {d['id']} {d['cat_zh']} [{d['lang']}] 段{d['para'] + 1} {d['desc']}")


if __name__ == "__main__":
    main()
