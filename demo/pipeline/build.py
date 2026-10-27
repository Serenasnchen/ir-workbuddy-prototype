"""Assemble the single-file, offline war-room HTML from the web template and module JSON.

Run from ROOT:  python -I demo/pipeline/build.py
Fails loudly if any module output contains an email address, an absolute local user path,
or wording that breaks the IR rules (see wording.py).
"""
import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import AS_OF, OUT, ROOT
from wording import check as wording_check

WEB = ROOT / "demo" / "web"
TARGET = ROOT / "deliverables" / "Q3业绩准备台.html"
MODULES = ["m1_peer", "m2_transcripts", "question_units", "m2_radar", "m3_holders", "m4_gatekeeper", "m5_eval"]
JS_FILES = ["core.js", "m4_checker.js", "m0.js", "m1.js", "m2.js", "m3.js", "m4.js", "m5.js"]

LEAK_PATTERNS = [
    re.compile(r"[\w.+-]+@(?!example\.com)(?!tencent\.com)[\w-]+\.[\w.]+"),
    re.compile(r"[A-Za-z]:\\\\?Users\\\\?[^\\\"]+", re.I),
    re.compile(r"/c/Users/", re.I),
]


def slim(name, obj):
    """Drop fields the page never reads, to keep the single file small."""
    if name == "m4_gatekeeper":
        obj.get("js_registry", {}).pop("checker_js", None)
    return obj


def load_modules():
    data = {}
    for m in MODULES:
        p = OUT / f"{m}.json"
        if p.exists():
            data[m] = slim(m, json.loads(p.read_text(encoding="utf-8")))
        else:
            print(f"[build] missing module: {m} (panel will show a placeholder)")
    return data


def check_leaks(blob):
    for pat in LEAK_PATTERNS:
        m = pat.search(blob)
        if m:
            raise SystemExit(f"[build] refusing to build: possible leak matched {pat.pattern!r}: {m.group(0)[:60]}")


def main():
    data = load_modules()
    bad = wording_check(data)
    if bad:
        name, path, ctx = bad[0]
        raise SystemExit(f"[build] refusing to build: {len(bad)} wording violation(s), e.g. {name}{path}: {ctx}"
                         " — run python -I demo/pipeline/wording.py")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    check_leaks(blob)
    blob = blob.replace("</", "<\\/")
    css = (WEB / "style.css").read_text(encoding="utf-8")
    shutil.copyfile(ROOT / "demo" / "pipeline" / "m4_checker.js", WEB / "m4_checker.js")
    missing = [f for f in JS_FILES if not (WEB / f).exists()]
    if missing:
        raise SystemExit(f"[build] missing JS files: {missing}")
    import subprocess
    for f in JS_FILES:  # fail fast on a syntax error instead of shipping a blank page
        r = subprocess.run(["node", "--check", str(WEB / f)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"[build] JS syntax error in {f}:\n{r.stderr[-600:]}")
    js = "\n;\n".join((WEB / f).read_text(encoding="utf-8") for f in JS_FILES if (WEB / f).exists())
    built = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M（北京时间）")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = (html.replace("{{CSS}}", css).replace("{{JS}}", js).replace("{{DATA}}", blob)
                .replace("{{AS_OF}}", AS_OF).replace("{{BUILT_AT}}", built))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    print(f"[build] wrote {TARGET.relative_to(ROOT)} ({len(html) / 1024:.0f} KB), modules: {', '.join(data)}")


if __name__ == "__main__":
    main()
