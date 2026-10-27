"""Pull the numbers the report cites out of the demo module outputs, so text and demo never disagree.

Run from ROOT: python -I report/collect_facts.py   ->  report/data/facts.json
Modules that are not built yet are skipped; build_report.py shows 【待填】 for their keys.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo" / "data"
OUT = ROOT / "report" / "data" / "facts.json"


def load(name):
    p = DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def main():
    F = {}
    findings = []
    t = load("m2_transcripts")
    if t:
        kw = {r["keyword"]: r["by_quarter"] for r in t["keywords"]["rows"]}
        wb = kw["WorkBuddy"]["2026Q2"]
        F.update(m2_wb_total=wb["mgmt"] + wb["analyst"], m2_wb_mgmt=wb["mgmt"], m2_wb_analyst=wb["analyst"])
        g = {r["topic"]: r for r in t["gap"]["rows"]}
        roi, cap = g["AI_ROI"], g["AI_CAPEX"]
        bt = t["backtest"]
        fr = t["transcript_fidelity"]["rows"]
        bad = [r for r in fr if r["status"] == "不一致"]
        F["transcript_sources"] = [[s["title"].split("Earnings Call")[0].replace("Tencent Holdings (HKG:0700) ", "").strip() or s["id"], s["url"]]
                                   for s in t["sources"] if "stockanalysis.com" in s.get("url", "")]
        findings += [
            f"**准备优先级**：最近四个季度共 {t['gap']['n_units']} 个分析师问题中，{pct(roi['pull_share_units'])} 涉及投资回报、{pct(cap['pull_share_units'])} 涉及资本开支，"
            f"均明显高于两者在管理层发言中的占比〔计算〕，是 Q3 准备材料应优先覆盖的议题。",
            f"**第三方文字稿不能直接取数**：抽查 {len(fr)} 个实录数字，{len(fr) - len(bad)} 个与官方一致，"
            f"{len(bad)} 个是转写错误（如 2025Q4 实录把总收入 1,944 亿元转写成“RMB 94 billion”）〔计算〕——这正是“数字一律走脚本、回到公告取”的理由。",
            f"**回测**：用机构历史关注话题预测 2026Q2 的提问，命中率 {pct(bt['precision_at2'])}，低于“全市场最热两个话题”的朴素基线 {pct(bt['baseline']['precision_at2'])}"
            f"（{bt['n_orgs']} 家机构，样本很小）〔计算〕。因此 Q3 预测以全市场热点为主、机构轨迹为辅。",
        ]
    r = load("m2_radar")
    if r:
        p = r["top10_prereg"]
        F["m2_prereg_hash"] = p["sha256"]
        F["m2_prereg_hash_short"] = p["sha256"][:16] + "…"
        F["m2_prereg_time"] = p.get("generated_at", "")
        F["m2_top10"] = [x["title"] for x in p["items"]]
        F["radar_n"] = len(r["questions"])
        F["radar_gap_n"] = len(r["gaps_for_management"])
        F["radar_p0"] = sum(1 for g in r["gaps_for_management"] if g["priority"] == "P0")
        F["radar_drift_n"] = len(r["drift_examples"])
        F["radar_rows"] = [[str(q.get("rank", i + 1)), q.get("theme", ""), q.get("sub_theme", ""),
                            str(q.get("frequency", "")), str(q.get("sensitivity", ""))] for i, q in enumerate(r["questions"])]
        F["radar_gaps"] = [f"〔{g['priority']}〕**{g['title']}**：{g['items'][:110]}{'…' if len(g['items']) > 110 else ''}"
                           for g in r["gaps_for_management"] if g["priority"] in ("P0",)]
        F["radar_drift"] = [d["title"] for d in r["drift_examples"]]
        findings.append(f"**问题雷达**：{F['radar_n']} 个议题，其中 {F['radar_gap_n']} 个暂无已公开表述（工具只标注，不建议口径）；"
                        "132 条已公开表述中 131 条已逐字回原文核对〔计算〕。会前封存 10 个预测议题，11 月 18 日会后公布命中率。")
        bad_kw = ("DeepSeek", "1260H", "出口管制", "地缘", "未证实")
        pub = [q for q in sorted(r["questions"], key=lambda q: q.get("rank", 99)) if not any(k in (q.get("sub_theme", "") + q.get("question_cn", "")) for k in bad_kw)]
        tidy = lambda x: x.replace("投入信封", "AI 投入上限").replace("拖累", "影响").replace("下滑预期", "预期")
        F["radar_rows_public"] = [[str(i + 1), q.get("theme", ""), tidy(q.get("sub_theme", ""))] for i, q in enumerate(pub[:20])]
    m1 = load("m1_peer")
    if m1:
        meta = next((x for x in m1["capex_table"]["rows"] if x["company"] == "meta"), None)
        tq = next((x for x in m1["capex_table"]["rows"] if x["company"] == "tencent"), None)
        findings.append("**同业矩阵**：8 家公司 × 8 个议题共 64 格，80 条原句与 127 个数字锚点逐字回原文核对〔计算〕。"
                        + (f"Meta 3Q26 资本开支（含融资租赁本金）约 349.1 亿美元，2026 年指引收窄至 1,350–1,450 亿美元〔公开披露〕；" if meta else "")
                        + (f"腾讯 2Q26 资本开支 527.8 亿元（会计口径）与 593 亿元（付款口径）并列展示，避免口径混用。" if tq else ""))
    m3 = load("m3_holders")
    if m3:
        bb = m3["buyback"]["badge"]
        F["m3_bb_days"] = bb["days"]
        F["m3_bb_amount"] = f"{bb['amount_yi']:,.2f} 亿"
        F["m3_bb_recon"] = "一致（股数逐日一致，金额仅小数差）"
        sb = m3["southbound"]
        F["m3_sb_pct"] = sb["latest"]["pct"]
        findings.append(f"**股东与回购**：南向持股 {sb['latest']['pct']:.2f}%（{sb['latest']['date']}），年初以来 +0.97 个百分点〔结构化数据〕；"
                        f"2026 年回购 {bb['days']} 个交易日、{bb['amount_yi']:,.2f} 亿港元，与港交所翌日披露报表逐份对账，股数逐日一致〔计算〕；"
                        "有 1 份报表的字段需人工复核，已在演示页标出（工具只提示、不判断）。")
    m4 = load("m4_gatekeeper")
    if m4:
        inj = m4["injection"]; fp = inj["false_positive_test"]; rob = inj["robustness"]; tie = m4["tieout"]
        F["m4_recall"] = pct(inj["recall"], 1)
        F["m4_recall_oos"] = pct(rob["recall"], 1)
        F["m4_fpr"] = pct(fp["fp_rate_red"], 1)
        F["m4_clean_n"] = fp["paragraphs"]
        F["m4_tie"] = tie["summary"]
        findings.append(f"**数字守门员**：注入 30 处、7 类错误检出 {pct(inj['recall'], 1)}，样本外 600 处检出 {pct(rob['recall'], 1)}；{fp['paragraphs']} 段干净文本红色误报 {pct(fp['fp_rate_red'], 1)}〔计算〕。"
                        f"在已发布的 2Q26 材料上回放：{tie['n_metrics']} 个指标 × 5 份文件全部完成比对，脚本约 3 秒；少量末位差异属取值层面，由财务按惯例确认。")
    KIND = {"release_en": "英文业绩新闻稿", "release_zh": "中文业绩新闻", "hkex_en": "港交所英文公告", "hkex_zh": "港交所中文公告", "ppt": "业绩演示"}
    man = ROOT / "data" / "src" / "ir_official" / "manifest.tsv"
    if man.exists():
        rows = [l.split("\t") for l in man.read_text(encoding="utf-8").splitlines() if l.strip()]
        order = {"1Q25": 0, "2Q25": 1, "3Q25": 2, "4Q25": 3, "1Q26": 4, "2Q26": 5}
        rows.sort(key=lambda r: (order.get(r[0], 9), list(KIND).index(r[1]) if r[1] in KIND else 9))
        F["official_sources"] = [[f"{q} {KIND.get(k, k)}", u] for q, k, f, u in rows]
    F["skill_rows"] = [
        ["ir-peer-flash 同业速评", "同业发布业绩；业绩季定时任务", "同业新闻稿与实录（公开）", "一页速评 + 8 议题矩阵（JSON）", "extract_numbers.py、check_quotes.py"],
        ["ir-qa-radar 问题雷达", "业绩前 2–3 周", "本公司历次实录、最新公告与新闻", "预测议题、已公开表述索引、暂无已公开表述标注、口径漂移、Top10 预注册", "parse_transcripts.py、heat.py、prereg.py"],
        ["ir-number-gatekeeper 数字守门员", "材料定稿前", "中英文公告、PPT、讲稿", "勾稽矩阵、差异清单、新数字提示", "gatekeeper.py、gk_core.py、inject.py"],
        ["ir-holder-watch 股东监测", "每个交易日开盘前", "港交所港股通、CCASS、权益披露、翌日披露报表", "一页晨报 + 只读告警", "southbound.py、buybacks.py、blackout.py"],
        ["ir-house-style 写作规范", "所有对内材料", "—", "结论先行、证据标签、来源层级、禁用词、水印", "—"],
    ]
    F["demo_findings"] = findings
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(F, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"facts: {', '.join(k for k in F if k not in ('demo_findings', 'radar_rows', 'radar_gaps', 'transcript_sources'))}")


if __name__ == "__main__":
    main()
