"""Verify that every quotation in a flash draft appears verbatim in the source text(s).

Usage:
  python check_quotes.py <draft.md> <source1.txt> [source2.txt ...]

Which spans are checked. A span inside “…”, "…" or ＂…＂ is a citation if ANY of these holds:
  - at least 6 whitespace-separated tokens (numbers count as words);
  - at least 12 Han characters in total (they need not be consecutive);
  - it contains a digit and has at least 3 tokens or 6 Han characters (figures are the riskiest
    thing to misquote);
  - it ends with terminal punctuation (. ? ! 。 ？ ！ …).
Anything else, e.g. “上调”, "含融资租赁本金" or “Q3”, is short emphasis: listed as [跳过], never a failure.
A quote that still contains a template placeholder 〈…〉 anywhere fails.
Use 「」 for Chinese emphasis so it is never mistaken for a quotation.

Pairing. Curly quotes pair by direction, may nest, and may run across blank lines. Straight quotes
pair left to right inside a paragraph; a paragraph with an odd count hands its last quote to the next
paragraph only if that paragraph is odd too (a quotation spanning a blank line). Anything left over
is reported as [未配对], because an unpaired quote can hide an unchecked citation.

Matching ignores case, full/half width (NFKC), quote and dash style, whitespace, and spaces next to
Han characters (PDF line breaks, "AI 赋能" vs "AI赋能"). An ellipsis splits a quote into fragments
that must all appear in order, each within 300 characters of the previous one. A quote that matches only after also ignoring all spaces and the
letters fi/fl/ff (ligatures that pdftotext drops, e.g. "nance" for "finance") is [已找到*]: it
passes, but should be compared with the PDF by eye.

Exit code: 0 = every citation found; 1 = a citation is missing, a quote is unpaired, or a template
placeholder 〈…〉 is left in a quote; 2 = usage or file error.
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

HAN = "[\u3400-\u4dbf\u4e00-\u9fff]"
CURLY_OPEN, CURLY_CLOSE = "“〝", "”〞〟"
CURLY = re.compile(f"[{CURLY_OPEN}{CURLY_CLOSE}]")
STRAIGHT = re.compile("[\"＂]")
BLANK_LINE = re.compile(r"\n[ \t\u3000]*\n")
QUOTE_CONT = re.compile(r"\n[ \t]*>[ \t>]*")      # Markdown blockquote marker on a continuation line
ELLIPSIS = re.compile(r"\.{3,}")                    # after NFKC, … and …… become dots
ELLIPSIS_GAP = 300                                   # max normalised chars elided by one ellipsis
PLACEHOLDER = re.compile(r"〈[^〈〉]*〉")
TERMINAL = (".", "?", "!", "。")                    # after NFKC: ？→? ！→! …→...
TRIM = " .,;:!?、"
LOOSE = re.compile(r"ffi|ffl|ff|fi|fl|\s")
TABLE = str.maketrans({**{c: "-" for c in "\u2014\u2013\u2212\u2010\u2011"}, "。": ".",
                       **{c: None for c in "\"'“”‘’「」『』〝〞〟"}})
HINT = "提示：中文强调请用「」，双引号只留给逐字原句。"
LABEL = {  # kind: (tag, display width, note)
    "exact": ("[已找到] ", 110, ""),
    "loose": ("[已找到*]", 110, "  （忽略空格与 fi/fl/ff 连字后才匹配，请对照 PDF 原文确认）"),
    "missing": ("[未找到] ", 110, ""),
    "skip": ("[跳过]   ", 40, "  （短强调，不作引语核查）"),
    "placeholder": ("[占位]   ", 40, "  （模板占位未替换）"),
    "unpaired": ("[未配对] ", 40, "  （引号未配对，无法核对）"),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(TABLE).lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(f" (?={HAN})|(?<={HAN}) ", "", s)    # PDF line breaks, Han-Latin spacing
    return s.strip()


def classify(q: str) -> str:
    q = unicodedata.normalize("NFKC", q).strip()
    if PLACEHOLDER.search(q):
        return "placeholder"
    if not re.search(r"\w", ELLIPSIS.sub("", q)):
        return "skip"                                # only dots or punctuation, e.g. “……”
    words, han = len(q.split()), len(re.findall(HAN, q))
    if (words >= 6 or han >= 12 or q.endswith(TERMINAL)
            or (re.search(r"\d", q) and (words >= 3 or han >= 6))):
        return "check"
    return "skip"


def in_order(frags, corpus: str) -> bool:
    """All fragments appear in order, each starting within ELLIPSIS_GAP chars of the previous one.

    Without the gap limit, “We expect … profitable” would pass by stitching together words from
    unrelated sentences anywhere in the sources.
    """
    frags = [f for f in frags if f]
    if not frags:
        return False
    start = corpus.find(frags[0])
    while start >= 0:
        pos, ok = start + len(frags[0]), True
        for f in frags[1:]:
            i = corpus.find(f, pos)
            if i < 0 or i - pos > ELLIPSIS_GAP:
                ok = False
                break
            pos = i + len(f)
        if ok:
            return True
        start = corpus.find(frags[0], start + 1)
    return False


def locate(q: str, corpus: str, loose_corpus: str):
    """Return 'exact', 'loose' or None."""
    frags = [f.strip(TRIM) for f in ELLIPSIS.split(norm(q))]
    if in_order(frags, corpus):
        return "exact"
    if in_order([LOOSE.sub("", f) for f in frags], loose_corpus):
        return "loose"
    return None


def quote_spans(text: str):
    """Return ([(offset, content)], [offset of each unpaired quote mark])."""
    spans, unpaired, stack = [], [], []
    for m in CURLY.finditer(text):
        if m.group() in CURLY_OPEN:
            stack.append(m.end())
        elif stack:
            start = stack.pop()
            spans.append((start, text[start:m.start()]))
        else:
            unpaired.append(m.start())
    unpaired += [s - 1 for s in stack]

    bounds = [0] + [m.end() for m in BLANK_LINE.finditer(text)] + [len(text)]
    carry = None
    for a, b in zip(bounds, bounds[1:]):
        marks = [m.start() for m in STRAIGHT.finditer(text, a, b)]
        if carry is not None:
            if len(marks) % 2:
                marks.insert(0, carry)
            else:
                unpaired.append(carry)
            carry = None
        if len(marks) % 2:
            carry = marks.pop()
        spans += [(i + 1, text[i + 1:j]) for i, j in zip(marks[::2], marks[1::2])]
    if carry is not None:
        unpaired.append(carry)
    return sorted(spans), sorted(unpaired)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="逐字核对速评中的引语")
    ap.add_argument("draft")
    ap.add_argument("sources", nargs="+")
    a = ap.parse_args()
    try:
        draft = Path(a.draft).read_text(encoding="utf-8", errors="replace")
        corpus = norm("\n".join(Path(p).read_text(encoding="utf-8", errors="replace") for p in a.sources))
    except OSError as e:
        print(f"无法读取文件：{e}")
        return 2
    loose_corpus = LOOSE.sub("", corpus)

    def row(off: int, kind: str, text: str):
        tag, width, note = LABEL[kind]
        lineno = draft.count("\n", 0, off) + 1
        return off, "%s L%-4d %s%s" % (tag, lineno, " ".join(text.split())[:width], note)

    spans, unpaired = quote_spans(draft)
    rows, count = [], {k: 0 for k in LABEL}
    for off, raw in spans:
        q = QUOTE_CONT.sub("\n", raw).strip()
        if not q:
            continue
        kind = classify(q)
        if kind == "check":
            kind = locate(q, corpus, loose_corpus) or "missing"
        count[kind] += 1
        rows.append(row(off, kind, q))
    rows += [row(off, "unpaired", draft[off:off + 40]) for off in unpaired]
    for _, r in sorted(rows):
        print(r)

    checked = count["exact"] + count["loose"] + count["missing"]
    summary = f"\n{checked - count['missing']}/{checked} 条引语可逐字匹配"
    if count["loose"]:
        summary += f"（其中 {count['loose']} 条为容错匹配）"
    summary += f"；跳过 {count['skip']} 处短强调"
    if unpaired:
        summary += f"；{len(unpaired)} 处引号未配对"
    if count["placeholder"]:
        summary += f"；{count['placeholder']} 处模板占位"
    print(summary)
    if count["missing"]:
        print("请把未找到的引语改为转述，或补充正确来源。")
    if unpaired:
        print("请把引号改成成对（不要混用中英文引号），再重新运行。")
    if count["placeholder"]:
        print("请把模板占位〈…〉换成实际内容。")
    if count["skip"] or unpaired:
        print(HINT)
    return 1 if count["missing"] or unpaired or count["placeholder"] else 0


if __name__ == "__main__":
    sys.exit(main())
