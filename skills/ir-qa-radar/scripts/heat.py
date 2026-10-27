"""Two-track topic heat: what management talks about vs what analysts ask about, and the gap between them.

Usage:
  python heat.py <parsed_dir> [--units question_units.json] [--last 4] [--out heat.json]

- Management track: topic lexicon hits in management turns, per 10,000 management words.
- Analyst track: if --units is given (question units coded by reading, with "quarter" and "topics"), the share of
  question units tagged with each topic; otherwise falls back to lexicon hits in analyst turns.
  Quarters are matched by (year, quarter), so "2025Q3", "q3-2025", "tencent_q3-2025" and "3Q25" are the same quarter.
- Gap (pp) = analyst share − management share over the last N quarters (files are ordered by quarter, not by name).
  Each row carries a neutral direction label; describe gaps only by direction, never with evaluative labels.
The lexicon only assists; the analyst coding should come from reading each question (see references/taxonomy.md).
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

LEXICON = {
    "AI_CAPEX": r"\bcapex\b|capital expenditure|AI infrastructure|investment in (?:AI|GPUs?)",
    "AI_ROI": r"\bROI\b|return on (?:invest|capital)|payback|monetiz|\breturns?\b on",
    "AI_PRODUCTS": r"WorkBuddy|CodeBuddy|Yuanbao|Xiaowei|QClaw|\bagents?\b|agentic",
    "MODELS": r"Hunyuan|\bHy ?\d\b|foundation model|\bLLMs?\b",
    "COMPUTE": r"\bGPUs?\b|\bchips?\b|computing power|compute capacity",
    "CLOUD": r"\bcloud\b|\btokens?\b|\bMaaS\b",
    "MARGIN": r"\bmargins?\b|depreciation|cost of revenues?",
    "CAPITAL": r"buy ?backs?|repurchase|dividend|free cash flow|\bdebt\b",
    "ADS": r"advertis|marketing services|\beCPM\b",
    "GAMES_DOM": r"domestic games?|evergreen",
    "GAMES_INTL": r"international games?|Supercell",
    "FINTECH": r"fintech|payment|business services|WeCom",
    "SOCIAL": r"Weixin|WeChat|Video Accounts|\bQQ\b|subscriptions?",
    "REG": r"regulat|geopolit|export control|1260H",
    "PORTFOLIO": r"investment portfolio|disposal|\bstakes?\b",
}
RX = {k: re.compile(v, re.I) for k, v in LEXICON.items()}
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’&.-]*")
QUARTER = [(re.compile(r"(?<![a-z])q([1-4])[\s_-]*(20\d\d)(?!\d)", re.I), lambda m: (int(m[2]), int(m[1]))),
           (re.compile(r"(?<!\d)(20\d\d)[\s_-]*q([1-4])(?!\d)", re.I), lambda m: (int(m[1]), int(m[2]))),
           (re.compile(r"(?<!\d)([1-4])q(\d\d)(?!\d)", re.I), lambda m: (2000 + int(m[2]), int(m[1])))]
NEAR_PP = 1.0
DIRECTION = ("分析师关注度高于管理层主动提及", "管理层主动提及高于分析师关注度", "两者接近")


def count(text):
    return Counter({k: len(r.findall(text)) for k, r in RX.items()})


def quarter_key(label):
    """(year, quarter) from labels such as "2025Q3", "q3-2025", "tencent_q3-2025" or "3Q25"; None if absent."""
    for rx, key in QUARTER:
        m = rx.search(label or "")
        if m:
            return key(m)
    return None


def direction(gap_pp):
    return DIRECTION[0] if gap_pp >= NEAR_PP else DIRECTION[1] if gap_pp <= -NEAR_PP else DIRECTION[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parsed_dir")
    ap.add_argument("--units")
    ap.add_argument("--last", type=int, default=4)
    ap.add_argument("--out", default="heat.json")
    a = ap.parse_args()
    files = sorted(Path(a.parsed_dir).glob("*.json"), key=lambda f: (quarter_key(f.stem) or (0, 0), f.stem))
    per = {}
    for f in files:
        turns = json.loads(f.read_text(encoding="utf-8"))["turns"]
        mg = " ".join(t["text"] for t in turns if t["role"] == "mgmt")
        an = " ".join(t["text"] for t in turns if t["role"] == "analyst")
        mw = len(WORD.findall(mg)) or 1
        per[f.stem] = {"mgmt_words": mw, "mgmt_hits": count(mg), "analyst_hits": count(an),
                       "mgmt_per10k": {k: round(v * 10000 / mw, 1) for k, v in count(mg).items()}}
    window = [f.stem for f in files][-a.last:]
    m_tot = Counter(); a_tot = Counter()
    for q in window:
        m_tot.update(per[q]["mgmt_hits"])
        a_tot.update(per[q]["analyst_hits"])
    basis, n_units = "lexicon", None
    if a.units:
        units = json.loads(Path(a.units).read_text(encoding="utf-8"))
        units = units if isinstance(units, list) else units.get("units", [])
        keys = {quarter_key(q) for q in window} - {None}

        def in_window(u):
            q = u.get("quarter", "")
            k = quarter_key(q)
            return k in keys if k else any(w in q or w.replace("-", "") in q for w in window)

        picked = [u for u in units if in_window(u)]
        tags = Counter(t for u in picked for t in u["topics"])
        if tags:
            a_tot, basis, n_units = tags, "question_units", len(picked)
        else:
            print(f"warning: no question unit in {a.units} falls in the window; analyst track uses lexicon hits instead")
    ms, as_ = sum(m_tot.values()) or 1, sum(a_tot.values()) or 1
    gap = sorted(({"topic": k, "mgmt_share": round(m_tot[k] / ms, 4), "analyst_share": round(a_tot[k] / as_, 4),
                   "gap_pp": round((a_tot[k] / as_ - m_tot[k] / ms) * 100, 1)} for k in LEXICON), key=lambda r: -r["gap_pp"])
    for r in gap:
        r["direction"] = direction(r["gap_pp"])
    Path(a.out).write_text(json.dumps({"window": window, "analyst_basis": basis, "n_units": n_units, "n_analyst_tags": sum(a_tot.values()),
                                       "per_file": per, "gap": gap}, ensure_ascii=False, indent=1, default=dict), encoding="utf-8")
    print(f"window: {window}")
    print(f"analyst track: {basis}" + (f", {n_units} question units / {sum(a_tot.values())} topic tags" if n_units else ""))
    for r in gap:
        print(f"  {r['topic']:12} mgmt {r['mgmt_share']:.1%}  analyst {r['analyst_share']:.1%}  gap {r['gap_pp']:+.1f}pp  {r['direction']}")


if __name__ == "__main__":
    main()
