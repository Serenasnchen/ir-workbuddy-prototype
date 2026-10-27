"""Extract financial figures (amount + unit + context line) from an earnings release.

Usage:
  python extract_numbers.py <release.txt|release.pdf|release.html> [--out numbers.json] [--keywords capex,revenue]

Standard library only. PDF input needs `pdftotext` on PATH; otherwise convert to text first.
The converted text is saved next to --out (never next to the source, which may be read-only),
so check_quotes.py can use it as a source.
Every figure keeps its line number so the flash can cite it.

pdftotext drops fi/fl/ff ligatures in some fonts ("finance" -> "nance", "free cash flow" ->
"free cash ow"). Keyword matching therefore ignores spaces and those letter pairs, and a warning
is printed when the converted text shows the problem.
"""
import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

AMOUNT = re.compile(
    r"(?P<cur>US\$|USD|RMB|HK\$|HKD|\$|¥|人民币)?\s?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
    r"(?P<unit>billion|million|thousand|bn|mn|亿元|亿港元|亿美元|百万元|万元|亿|%|percentage points?|ppts?|个百分点)?",
    re.I,
)
DEFAULT_KEYS = ["revenue", "operating income", "operating profit", "net income", "capital expenditure", "capex",
                "free cash flow", "cloud", "advertising", "depreciation", "margin", "buyback", "repurchase", "dividend",
                "收入", "经营利润", "资本开支", "自由现金流", "毛利", "净利润"]
LOOSE = re.compile(r"ffi|ffl|ff|fi|fl|\s")
LIGATURE_LOSS = re.compile(r"\b(?:nanc(?:e|es|ed|ing|ial|ially)|cash ows?|pro ts?|e ective\w*|signi cant\w*)\b", re.I)


def loose(s: str) -> str:
    return LOOSE.sub("", s.lower())


def read_text(path: Path, txt_dir: Path) -> str:
    if path.suffix.lower() == ".pdf":
        out = txt_dir / (path.stem + ".txt")
        try:
            subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(path), str(out)], check=True)
        except FileNotFoundError:
            sys.exit("未找到 pdftotext：请先把 PDF 转成文本（.txt）再运行。")
        except subprocess.CalledProcessError as e:
            sys.exit(f"pdftotext 转换失败（退出码 {e.returncode}）：请检查 PDF，或先手工转成文本。")
        print(f"PDF text -> {out}")
        text = out.read_text(encoding="utf-8", errors="replace")
        if LIGATURE_LOSS.search(text):
            print("注意：转出的文本丢失了 fi/fl/ff 连字（如 nance = finance）。关键词匹配已容错；"
                  "check_quotes.py 遇到此类差异会标为 [已找到*]，请对照 PDF 原文确认。")
        return text
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        raw = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", raw, flags=re.I)
        raw = re.sub(r"<br\s*/?>|</p>|</tr>|</div>", "\n", raw, flags=re.I)
        raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return raw


def extract(text: str, keys):
    rows = []
    loose_keys = [(k, loose(k)) for k in keys]
    # split on "\n" only: splitlines() also breaks on the form feeds pdftotext puts between pages,
    # which would make cited line numbers drift from what an editor or `grep -n` shows
    for ln, line in enumerate(text.split("\n"), 1):
        low = loose(line)
        hit = [k for k, lk in loose_keys if lk in low]
        if not hit:
            continue
        for m in AMOUNT.finditer(line):
            if not (m.group("cur") or m.group("unit")):
                continue  # bare numbers (years, page numbers) are noise
            rows.append({
                "line": ln, "keywords": hit, "currency": m.group("cur") or "", "value": m.group("num"),
                "unit": m.group("unit") or "", "text": line.strip()[:300],
            })
    return rows


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default="numbers.json")
    ap.add_argument("--keywords", default="")
    a = ap.parse_args()
    keys = [k.strip() for k in a.keywords.split(",") if k.strip()] or DEFAULT_KEYS
    out_dir = Path(a.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = extract(read_text(Path(a.source), out_dir), keys)
    Path(a.out).write_text(json.dumps({"source": a.source, "figures": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} figures -> {a.out}")
    for r in rows[:15]:
        print(f"  L{r['line']:<5} {r['currency']}{r['value']} {r['unit']:<10} | {r['text'][:90]}")


if __name__ == "__main__":
    sys.exit(main())
