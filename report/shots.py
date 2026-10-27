"""Element-level screenshots of the war-room for the Word report (cleaner than full-page captures)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "deliverables" / "Q3业绩准备台.html"
OUT = ROOT / "report" / "shots"

# (file, tab index, selector, optional action)
TARGETS = [
    ("r0_brief.png", 0, "#brief .hero", None),
    ("r1_matrix.png", 1, "#peers .block >> nth=0", None),
    ("r2_gap.png", 2, "#radar .grid-2 >> nth=0", None),
    ("r2_radar.png", 2, "#radar .block >> nth=2", "open_first_question"),
    ("r3_buyback.png", 3, "#holders .block >> nth=2", None),
    ("r4_checker.png", 4, "#gatekeeper .grid-2 >> nth=0", "edit_number"),
    ("r5_eval.png", 5, "#eval .block >> nth=0", None),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        pg.goto(HTML.as_uri())
        pg.add_style_tag(content=".trace{display:none} .topbar{position:static}")
        pg.wait_for_timeout(500)
        for name, tab, sel, action in TARGETS:
            pg.click(f".tab >> nth={tab}")
            pg.wait_for_timeout(200)
            if action == "open_first_question":
                pg.locator("#radar details.q").first.evaluate("d => d.open = true")
            if action == "edit_number":
                pg.fill("#gk-input", "资本开支为人民币582亿元，同比增加176%。\n二零二六年第二季的收入为人民币2,048亿元，同比增长11%。\nCapital expenditure was RMB52.8 billion, up 167% YoY.")
                pg.wait_for_timeout(200)
            el = pg.locator(sel).first
            el.scroll_into_view_if_needed()
            el.screenshot(path=str(OUT / name))
            print(name, el.bounding_box())
        b.close()


if __name__ == "__main__":
    main()
