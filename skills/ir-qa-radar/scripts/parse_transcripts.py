"""Parse earnings-call transcripts into speaker turns with roles, fixing mislabelled speakers from moderator hand-offs.

Usage:
  python parse_transcripts.py <input_dir> <output_dir> [--company Tencent]

Input: StockAnalysis-style HTML pages (one per quarter), or plain-text files (UTF-8, with or without BOM) with either
  - "Speaker（Org，角色）：text" turns (角色 = 管理层 / 分析师 / 主持人; full- or half-width brackets, comma and colon;
    one turn per paragraph, paragraphs separated by blank lines, continuation lines belong to the turn above), or
  - "Speaker Name: text" lines.
Output: <output_dir>/<file-stem>.json = {"turns": [{"i", "speaker", "speaker_raw", "title", "role", "org", "text", "fixes", "needs_review"}]}
Roles: mgmt (company executives), moderator (IR host / operator), analyst (everyone else). A stated 角色 is taken as given.
In a tagged file, a paragraph without a valid "（机构，角色）" tag still opens its own turn; its role is inferred and it is
marked needs_review with the reason in "review". A stated speaker name is kept: a moderator hand-off only fills a blank
org when it names the same person (or replaces a "Speaker N" placeholder); otherwise the turn is marked needs_review.
Third-party transcripts contain attribution errors; every analyst turn is marked "第三方文字稿，待录音复核".
"""
import argparse
import html
import json
import re
from pathlib import Path

BLOCK = re.compile(
    r'<div class="text-lg font-bold text-default md:text-xl">(?P<speaker>.*?)</div>\s*'
    r'(?:<!--\[\d*-->\s*<div class="text-sm italic text-muted">(?P<title>.*?)</div>\s*<!--\]-->)?'
    r'(?P<body>.*?)(?=<div class="text-lg font-bold text-default md:text-xl">|</article>|$)', re.S)
TAG = re.compile(r"<[^>]+>")
HANDOFF = re.compile(r"(?:question|next one|move on to|reconnected with)[^.]*?\bfrom\s+(?P<name>[A-Z][\w.'-]*(?:\s[A-Z][\w.'-]*)?)?"
                     r"(?:,?\s*(?:from|of|with)\s+)?(?P<org>[A-Z][\w&.'-]*(?:\s[A-Z][\w&.'-]*){0,3})?", re.I)
SPEAKER_N = re.compile(r"^Speaker \d+$")
MOD_TITLES = re.compile(r"investor relations|operator", re.I)
ROLE_CN = {"管理层": "mgmt", "分析师": "analyst", "主持人": "moderator"}
TAGGED = re.compile(r"^(?P<speaker>[^（(:：]{1,60}?)\s*[（(](?P<org>.*?)[，,]\s*(?P<role>管理层|分析师|主持人)\s*[）)]\s*[:：]\s*(?P<text>.*)$")
LOOSE = re.compile(r"^(?P<speaker>[^（(:：]{1,60}?)\s*(?:[（(](?P<inner>.*?)[）)])?\s*[:：]\s*(?P<text>.*)$")
PLAIN = re.compile(r"^([^:：]{2,40})[:：]\s*(.+)$")
ORG_END = re.compile(r"(?<!\b[A-Z])\.(?=\s|$)")
REVIEW = "第三方文字稿，待录音复核"


def clean(fragment):
    paras = re.findall(r"<p[^>]*>(.*?)</p>", fragment, re.S)
    return "\n".join(t for t in (re.sub(r"\s+", " ", html.unescape(TAG.sub("", p))).strip() for p in paras) if t)


def parse_html(path):
    s = path.read_text(encoding="utf-8", errors="replace")
    i = s.find('id="transcript-panel-full"')
    s = s[i:] if i >= 0 else s
    out = []
    for m in BLOCK.finditer(s):
        text = clean(m.group("body"))
        if text:
            out.append({"speaker": html.unescape(TAG.sub("", m.group("speaker"))).strip(),
                        "title": html.unescape(TAG.sub("", m.group("title") or "")).strip(), "text": text})
    return out


def untagged_turn(line, prev):
    """First line of a paragraph in a tagged file that lacks a valid "（机构，角色）" tag: it opens its own turn for review."""
    m = LOOSE.match(line)
    if m:  # e.g. "Name（Org）：", "Name（Org，其他角色）：" or "Operator：" -- the role is inferred in assign_roles
        inner = (m.group("inner") or "").strip()
        return {"speaker": m.group("speaker").strip(), "title": inner, "text": m.group("text").strip(),
                "tag": (None, re.split(r"[，,]", inner)[0].strip()), "untagged": "未按“发言人（机构，角色）”标注，角色为推断"}
    if not prev:
        return {"speaker": "", "title": "", "text": line, "untagged": "段落无发言人标注，角色为推断"}
    turn = {"speaker": prev["speaker"], "title": prev["title"], "text": line, "untagged": "段落无发言人标注，暂按上一位发言人归属"}
    if "tag" in prev:
        turn["tag"] = prev["tag"]
    return turn


def parse_text(path):
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()]
    # Once a file uses "Speaker（Org，角色）：" tags, only tagged lines and paragraph starts open a turn, so a colon inside the
    # text cannot split it; a paragraph that does not follow the tag format still gets its own turn (flagged for review).
    tagged = any(TAGGED.match(line) for line in lines)
    out, para_start = [], True
    for line in lines:
        if not line:
            para_start = True
            continue
        m = (TAGGED if tagged else PLAIN).match(line)
        if m and tagged:
            org = m.group("org").strip()
            out.append({"speaker": m.group("speaker").strip(), "title": f"{org}，{m.group('role')}", "text": m.group("text").strip(),
                        "tag": (ROLE_CN[m.group("role")], org)})
        elif m:
            out.append({"speaker": m.group(1).strip(), "title": "", "text": m.group(2).strip()})
        elif tagged and para_start:
            out.append(untagged_turn(line, out[-1] if out else None))
        elif out:
            out[-1]["text"] = f"{out[-1]['text']}\n{line}" if out[-1]["text"] else line
        para_start = False
    return out


def same_name(handoff_name, speaker):
    """True if the hand-off names this speaker ("Gary" also matches "Gary Yu")."""
    a, b = (re.sub(r"[\W_]+", " ", s).casefold().split() for s in (handoff_name, speaker))
    return bool(a) and b[:len(a)] == a


def assign_roles(turns, company):
    last_handoff = None
    for i, t in enumerate(turns):
        t.update({"i": i, "speaker_raw": t["speaker"], "fixes": [], "needs_review": False})
        title = t["title"]
        role, org = t.pop("tag", (None, ""))
        untagged = t.pop("untagged", None)
        strict = bool(role or untagged)  # tagged files: stated names are kept and hand-off orgs are trimmed at the full stop
        if untagged:
            t["needs_review"], t["review"] = True, f"{untagged}，待录音复核"
        if role == "moderator" or (role is None and (MOD_TITLES.search(title) or t["speaker"].lower() == "operator")):
            t["role"], t["org"] = "moderator", org or (company + " IR" if company else "IR")
            h = HANDOFF.search(t["text"])
            if h:
                last_handoff = {"name": (h.group("name") or "").strip(), "org": (h.group("org") or "").strip()}
            continue
        if role == "mgmt" or (role is None and company and company.lower() in title.lower()):
            t["role"], t["org"] = "mgmt", org or company
            continue
        t["role"] = "analyst"
        t["org"] = org if role or org else (title.split(",")[-1].strip() if "," in title else title)
        placeholder = SPEAKER_N.match(t["speaker"])
        if placeholder or not t["org"]:
            h = last_handoff or {"name": "", "org": ""}
            h_org = ORG_END.split(h["org"])[0].strip(" .") if strict else h["org"]
            # an org stated in the tag is never overridden; in tagged files a hand-off naming someone else is not applied
            if h_org and not org and (not strict or placeholder or same_name(h["name"], t["speaker"])):
                t["org"] = h_org
                if h["name"] and (not strict or placeholder):
                    t["speaker"] = h["name"]
                t["fixes"].append("按主持人交接语归属")
            else:
                t["needs_review"] = True
        t.setdefault("review", REVIEW)
    return turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("output_dir")
    ap.add_argument("--company", default="Tencent")
    a = ap.parse_args()
    src, dst = Path(a.input_dir), Path(a.output_dir)
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(list(src.glob("*.htm*")) + list(src.glob("*.txt"))):
        turns = parse_html(f) if f.suffix.startswith(".htm") else parse_text(f)
        turns = assign_roles(turns, a.company)
        (dst / f"{f.stem}.json").write_text(json.dumps({"source_file": f.name, "turns": turns}, ensure_ascii=False, indent=1), encoding="utf-8")
        roles = {r: sum(1 for t in turns if t["role"] == r) for r in ("mgmt", "analyst", "moderator")}
        fixed = sum(1 for t in turns if t["fixes"])
        review = sum(1 for t in turns if t["needs_review"])
        print(f"{f.name}: {len(turns)} turns {roles}; fixed {fixed}; needs review {review}")


if __name__ == "__main__":
    main()
