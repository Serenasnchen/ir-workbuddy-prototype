"""Copy the built war-room page into the Vercel folder as index.html, adding a noindex tag.

Run from ROOT after demo/pipeline/build.py:
    python -I tools/stage_vercel.py
    cd deploy/ir-q3-prep-desk && npx.cmd vercel deploy --prod --yes
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "deliverables" / "Q3业绩准备台.html"
DST = ROOT / "deploy" / "ir-q3-prep-desk" / "index.html"
ROBOTS = b'<meta name="robots" content="noindex, nofollow">'

if __name__ == "__main__":
    html = SRC.read_bytes()
    if ROBOTS not in html:
        html = html.replace(b'<meta charset="utf-8">', b'<meta charset="utf-8">\n' + ROBOTS, 1)
    assert ROBOTS in html, "charset tag not found; noindex not added"
    DST.write_bytes(html)
    print(f"staged {DST.relative_to(ROOT)} ({len(html) // 1024} KB)")
