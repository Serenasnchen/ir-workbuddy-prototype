"""Open the built war-room in headless Edge, screenshot every panel, and report console errors.

Run from ROOT:  python -I demo/pipeline/snap.py [width] [--full]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "deliverables" / "Q3业绩准备台.html"
SHOTS = ROOT / "report" / "shots"
PANELS = ["brief", "peers", "radar", "holders", "gatekeeper", "eval"]


def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1440
    full = "--full" in sys.argv
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1.5)
        pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        pg.goto(HTML.as_uri())
        pg.wait_for_timeout(600)
        if full:
            pg.add_style_tag(content=".trace{position:static} .topbar{position:static}")
        for i, pid in enumerate(PANELS):
            pg.click(f".tab >> nth={i}")
            pg.wait_for_timeout(250)
            out = SHOTS / f"m{i}.png"
            pg.screenshot(path=str(out), full_page=full)
            h = pg.evaluate("document.querySelector('.panel.active').scrollHeight")
            print(f"{pid:11} -> {out.name}  panel height {h}px")
        # interaction check: open the first evidence chip on the radar panel
        pg.click(".tab >> nth=2")
        chips = pg.locator("#radar .ev")
        if chips.count():
            chips.first.click()
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(SHOTS / "drawer.png"))
            print("drawer title:", pg.inner_text("#drawer h4"))
        b.close()
    print("console errors/warnings:", len(errors))
    for e in errors[:20]:
        print("  ", e)


if __name__ == "__main__":
    main()
