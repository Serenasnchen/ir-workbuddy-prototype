"""Neutral-wording pass over the module outputs (demo/data/*.json).

Two IR rules are enforced deterministically instead of by hand:
  1. The tool only flags topics without a public statement; it never sets an agenda for management
     ("需管理层确认…" -> "暂无已公开表述（工具只标注，不建议口径）").
  2. No sell-side earnings forecasts or "market expectation" numbers for Tencent; sentences, evidence
     points and key numbers that carry them are dropped.

Run from ROOT:  python -I demo/pipeline/wording.py          (rewrite in place, idempotent)
                python -I demo/pipeline/wording.py --check  (exit 1 if anything is left)
build.py calls check() so a regenerated module cannot reintroduce the wording.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "demo" / "data"
FILES = ["m1_peer.json", "m2_transcripts.json", "m2_radar.json", "m3_holders.json", "m4_gatekeeper.json"]
# Sealed before the call: rewriting would break the SHA-256, so these subtrees are left untouched.
FROZEN_KEYS = {"top10_prereg"}
FLAG = "暂无已公开表述（工具只标注，不建议口径）"

RULES = [
    (r"需管理层确认是否回应、如何回应；本表不代拟口径", FLAG),
    (r"需管理层确认是否回应、如何回应", FLAG),
    (r"是否回应、如何回应需管理层确认", "是否回应、如何回应由部门按既定流程决定"),
    (r"需要新口径的写入“需管理层确认事项”。", "暂无已公开表述的只做标注，不建议口径。"),
    (r"列入需管理层确认事项", "由财务按惯例确认"),
    (r"需管理层在业绩前确认可以披露哪些量化口径：", "暂无已公开表述的量化口径（工具只标注，不建议口径）："),
    (r"需管理层在业绩前确认([一二三四五六七八九十]+)点。", r"暂无已公开表述的\1个方面（工具只标注，不建议口径）："),
    (r"需管理层(?:在业绩前)?确认：", FLAG + "："),
    (r"需管理层确认事项", "暂无已公开表述事项"),
    (r"需管理层确认。", "由部门按既定流程决定。"),
    (r"管理层主动讲得少", "管理层主动提及较少"),
    (r"多于管理层主动讲", "多于管理层主动提及"),
    (r"关切拉力\(归一\)", "分析师关注占比(归一)"),
    (r"关切拉力", "分析师关注占比"),
    (r"叙事推力", "管理层主动提及占比"),
]
RULES = [(re.compile(p), r) for p, r in RULES]

# A sentence or clause that carries a broker forecast / consensus number for Tencent.
BROKER = re.compile(r"(?:花旗|瑞银|大摩|摩根士丹利|高盛|摩根大通|中金|券商)[^。；]{0,40}?(?:预测|目标价|下调|上调)"
                    r"|市场预期|一致预期")
LEFTOVER = re.compile(r"需管理层|讲得少|被低估|被高估|叙事错位|建议管理层|主动管理预期")


def drop_broker_sentences(s: str) -> str:
    if not BROKER.search(s):
        return s
    # numbered clauses "(4) …。" first, then plain sentences / semicolon clauses
    s = re.sub(r"\(\d+\)[^()]*?(?:" + BROKER.pattern + r")[^()]*?。", "", s)
    parts = re.split(r"(?<=[。；])", s)
    s = "".join(p for p in parts if not BROKER.search(p)).strip()
    return s[:-1] + "。" if s.endswith("；") else s


def clean(o, key=None):
    if key in FROZEN_KEYS:
        return o
    if isinstance(o, dict):
        # evidence points and key-number rows that exist only to carry a forecast are dropped whole
        if any(isinstance(o.get(k), str) and BROKER.search(o[k]) for k in ("point", "metric")):
            return None
        if "metric" in o and isinstance(o.get("value"), str) and BROKER.search(o["value"]):
            return None
        out = {}
        for k, v in o.items():
            c = clean(v, k)
            if c is not None or v is None:
                out[k] = c
        return out
    if isinstance(o, list):
        return [c for c in (clean(v) for v in o) if c is not None]
    if isinstance(o, str):
        for pat, rep in RULES:
            o = pat.sub(rep, o)
        return drop_broker_sentences(o) if key not in ("notes", "check", "v2_changes") else o
    return o


def leftovers(o, path="", key=None):
    if key in FROZEN_KEYS:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leftovers(v, f"{path}.{k}", k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leftovers(v, f"{path}[{i}]", key)
    elif isinstance(o, str):
        m = LEFTOVER.search(o) or (BROKER.search(o) if key not in ("notes", "check", "v2_changes", "integrity") else None)
        if m:
            yield path, o[max(0, m.start() - 30): m.end() + 30]


def check(data: dict) -> list:
    """Return (file, path, context) for every remaining violation in loaded module data."""
    return [(name, p, ctx) for name, d in data.items() for p, ctx in leftovers(d)]


def main():
    only_check = "--check" in sys.argv
    data = {f: json.loads((DATA / f).read_text(encoding="utf-8")) for f in FILES if (DATA / f).exists()}
    if not only_check:
        for f, d in data.items():
            new = clean(d)
            if new != d:
                (DATA / f).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"rewrote {f}")
            data[f] = new
    bad = check(data)
    for f, p, ctx in bad:
        print(f"LEFT {f}{p}: …{ctx}…")
    print(f"{len(bad)} violation(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
