"""Package the deliverables: skill zips, the WorkBuddy hands-on pack, and the source-code bundle.

Run from ROOT: python -I tools/make_packs.py
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIV = ROOT / "deliverables"
SKILLS = ROOT / "skills"
ROLE = {"mgmt": "管理层", "analyst": "分析师", "moderator": "主持人"}

# A short Chinese draft with two planted errors. The answer key is NOT shipped in the pack: in the
# 2026-10-26 real run the agent read it from inputs/README.txt and copied it into its own output.
DRAFT = (
    "二零二六年第二季，腾讯总收入为人民币2,048亿元，同比增长11%。\n"
    "资本开支为人民币582亿元，同比增加176%。\n"
    "非国际财务报告准则经营盈利为人民币756亿元，同比增长19%。\n"
    "本土市场游戏收入为人民币473亿元，同比增长17%。\n"
)
ANSWER = [
    "第 2 行：资本开支应为人民币 528 亿元（52,784 百万元），草稿写成 582 亿元——数字篡改。",
    "第 3 行：非国际财务报告准则经营盈利同比应为 +9%；+19% 是“剔除新 AI 产品”口径的增速——口径混用。",
    "第 1、4 行为正确数字，用来检查有无误报。",
]


def zipdir(src: Path, dst: Path):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(src.parent))


def build_skill_zips():
    out = DELIV / "IR技能包"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for d in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        zipdir(d, out / f"{d.name}.zip")
    shutil.copy(ROOT / "docs" / "技能包使用说明.md", out / "使用说明.md")
    return out


def build_wb_pack(skill_dir: Path):
    pack = DELIV / "_wb_pack"
    if pack.exists():
        shutil.rmtree(pack)
    for sub in ("inputs/transcripts", "inputs/meta", "skills", "截图"):
        (pack / sub).mkdir(parents=True)
    txt = ROOT / "demo" / "data" / "raw" / "m4" / "txt"
    shutil.copy(txt / "2Q26_release_en.txt", pack / "inputs" / "2Q26_release_en.txt")
    shutil.copy(txt / "2Q26_release_zh.txt", pack / "inputs" / "2Q26_release_zh.txt")
    for q in ("q3-2025", "q4-2025", "q1-2026", "q2-2026"):
        turns = json.loads((ROOT / "data" / "parsed_fixed" / f"{q}.json").read_text(encoding="utf-8"))["turns"]
        lines = [f"{t['speaker']}（{t.get('org') or ''}，{ROLE.get(t['role'], t['role'])}）：{t['text']}" for t in turns]
        (pack / "inputs" / "transcripts" / f"tencent_{q}.txt").write_text("\n\n".join(lines), encoding="utf-8")
    shutil.copy(ROOT / "data" / "src" / "peers" / "meta_q3_2026_release.pdf", pack / "inputs" / "meta" / "meta_q3_2026_release.pdf")
    meta_html = ROOT / "data" / "src" / "peers" / "meta_q3_2026_transcript_stockanalysis.html"
    if meta_html.exists():
        import html as _h
        s = meta_html.read_text(encoding="utf-8", errors="replace")
        s = s[s.find('id="transcript-panel-full"'):] if 'id="transcript-panel-full"' in s else s
        paras = [re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", "", p))).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", s, re.S)]
        (pack / "inputs" / "meta" / "meta_q3_2026_transcript.txt").write_text("\n".join(p for p in paras if p), encoding="utf-8")
    (pack / "inputs" / "draft_paragraph.txt").write_text(DRAFT, encoding="utf-8")
    (pack / "inputs" / "README.txt").write_text(
        "本文件夹只含公开资料，用于 WorkBuddy 实机运行。\n\n"
        "来源：腾讯投资者关系网站 2026Q2 中英文业绩新闻稿（PDF 转文本）；StockAnalysis 公开的腾讯业绩会文字稿（第三方，非官方逐字稿）；"
        "Meta 投资者关系网站 2026Q3 业绩新闻稿；StockAnalysis 公开的 Meta 业绩会文字稿（数据源 Quartr，第三方，非官方逐字稿）。\n\n"
        "draft_paragraph.txt 是模拟草稿，故意埋了 2 处错误。答案不放在工作空间内，以免智能体直接读到；运行完再对照。\n",
        encoding="utf-8")
    for z in sorted(skill_dir.glob("*.zip")):
        shutil.copy(z, pack / "skills" / z.name)
    shutil.copy(ROOT / "docs" / "WorkBuddy实机运行指引.md", pack / "WorkBuddy实机运行指引.md")
    dst = DELIV / "WorkBuddy实机包.zip"
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pack.rglob("*")):
            z.write(f, Path("IR_demo") / f.relative_to(pack))
    shutil.rmtree(pack)
    return dst


def build_source_bundle():
    dst = DELIV / "源代码与数据处理脚本.zip"
    include = [ROOT / "demo" / "pipeline", ROOT / "demo" / "web", ROOT / "report"]
    data_json = sorted((ROOT / "demo" / "data").glob("*.json"))
    skip_dirs = {"__pycache__", "pages", "shots"}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for base in include:
            for f in sorted(base.rglob("*")):
                if f.is_file() and not (set(f.parts) & skip_dirs) and f.suffix in (".py", ".js", ".css", ".html", ".md", ".json"):
                    z.write(f, Path("IR_Copilot") / f.relative_to(ROOT))
        for f in data_json:
            z.write(f, Path("IR_Copilot") / f.relative_to(ROOT))
        z.writestr("IR_Copilot/README.md", README)
        if (DELIV / "资料来源清单.csv").exists():
            z.write(DELIV / "资料来源清单.csv", "IR_Copilot/资料来源清单.csv")
    return dst


def build_sources_csv():
    """Merge every module's source list into one CSV (deduplicated by URL)."""
    import csv
    names = {"m1_peer": "同业矩阵", "m2_transcripts": "实录分析", "m2_radar": "问题雷达", "m3_holders": "股东·资金·回购", "m4_gatekeeper": "数字守门员"}
    seen, rows = {}, []
    for m, label in names.items():
        p = ROOT / "demo" / "data" / f"{m}.json"
        if not p.exists():
            continue
        for s in json.loads(p.read_text(encoding="utf-8")).get("sources", []):
            url = (s.get("url") or "").strip()
            key = url or s.get("title", "")
            if key in seen:
                seen[key][5] = seen[key][5] + "；" + label if label not in seen[key][5] else seen[key][5]
                continue
            row = [s.get("title", ""), url, s.get("date", ""), str(s.get("tier", "")), s.get("note", "") or "", label]
            seen[key] = row
            rows.append(row)
    man = ROOT / "data" / "src" / "ir_official" / "manifest.tsv"
    kind = {"release_en": "英文业绩新闻稿", "release_zh": "中文业绩新闻", "hkex_en": "港交所英文公告", "hkex_zh": "港交所中文公告", "ppt": "业绩演示"}
    for line in man.read_text(encoding="utf-8").splitlines():
        q, k, f, u = line.split("	")
        if u not in seen:
            seen[u] = [f"腾讯 {q} {kind.get(k, k)}", u, "", "1", "腾讯投资者关系网站", "数字守门员"]
            rows.append(seen[u])
    dst = DELIV / "资料来源清单.csv"
    with open(dst, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["标题", "链接", "日期", "来源层级（1 公告/2 官方/3 第三方文字稿/4 二手）", "备注", "用于模块"])
        w.writerows(rows)
    return dst, len(rows)


README = """# IR Copilot 原型：源代码与数据处理脚本

- `demo/pipeline/`：各模块脚本（transcripts.py 实录分析、radar.py 问题雷达、peer.py 同业矩阵、holders.py 股东与回购、gatekeeper.py / gk_core.py / inject.py 数字守门员、eval.py 评测、build.py 组装离线网页）及各模块说明 *_NOTES.md 与回归测试 test_*.py。
- `demo/web/`：离线网页的样式与脚本（无外部依赖）。
- `demo/data/`：各模块输出（所有数字带来源编号与证据标签）。
- `report/`：Word 报告与图表的生成脚本。

原始下载文件（业绩会文字稿网页、港交所 PDF 等）不随包分发，可按各模块 NOTES 中的网址重新获取。
所有脚本只用公开数据；网络请求使用通用 User-Agent，不含任何个人信息。
"""


if __name__ == "__main__":
    sk = build_skill_zips()
    print("skills ->", sorted(p.name for p in sk.iterdir()))
    print("pack   ->", build_wb_pack(sk).name)
    print("csv    ->", build_sources_csv())
    print("source ->", build_source_bundle().name)
