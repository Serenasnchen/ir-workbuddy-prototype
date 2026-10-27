"""Report figures for the global landscape and tool selection chapters."""
import json
import sys
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

sys.path.insert(0, str(Path(__file__).parent))
from style import (AMBER, BLUE, BLUE_SOFT, GREEN, GREY_1, GREY_2, GREY_3, GREY_4, INK, RED,
                   setup, source_note)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "report" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
SYNTH = json.loads((ROOT / "data/research/parts/synth.json").read_text(encoding="utf-8"))

CAP_W = {"IR场景覆盖": 20, "金融数据覆盖": 15, "模型与执行": 15, "主动性与编排": 10}
FIT_W = {"工作环境集成": 15, "治理深度": 15, "开放标准": 5, "成本与落地": 5}

SHORT = {
    "Anthropic": "Claude Cowork", "OpenAI": "OpenAI dots / ChatGPT Work", "Microsoft": "Microsoft 365 Copilot",
    "AlphaSense": "AlphaSense", "腾讯 WorkBuddy": "WorkBuddy", "腾讯自建": "腾讯自建（混元API）",
    "OpenClaw": "OpenClaw（私有化）", "字节 ArkClaw": "字节 ArkClaw", "阿里 千问办公": "阿里 千问办公", "Meta Muse": "Meta Muse",
}


def short_name(n):
    for k, v in SHORT.items():
        if n.startswith(k):
            return v
    return n[:16]


def scores():
    rows = []
    for r in SYNTH["shortlist_scores"]:
        s = r["scores"]
        cap = sum(s[k] * w / 5 for k, w in CAP_W.items())
        fit = sum(s[k] * w / 5 for k, w in FIT_W.items())
        rows.append({"name": short_name(r["name"]), "cap": cap, "fit": fit, "total": cap + fit,
                     "pass": r["passes_hard_constraints"], "failed": r.get("failed_constraint", "")})
    return rows


def fig_capability_vs_fit():
    setup()
    rows = scores()
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    offsets = {"WorkBuddy": (6, 6), "Claude Cowork": (7, 3), "OpenAI dots / ChatGPT Work": (6, -12),
               "Microsoft 365 Copilot": (-7, 7), "AlphaSense": (6, -11), "腾讯自建（混元API）": (6, -11),
               "OpenClaw（私有化）": (6, 6), "字节 ArkClaw": (-6, 8), "阿里 千问办公": (6, -11), "Meta Muse": (6, 4)}
    for r in rows:
        is_wb = r["name"] == "WorkBuddy"
        color = BLUE if is_wb else (GREEN if r["pass"] else GREY_2)
        if r["pass"]:
            ax.scatter(r["cap"], r["fit"], s=150 if is_wb else 70, color=color, zorder=3, edgecolor="white", linewidth=1.2)
        else:
            ax.scatter(r["cap"], r["fit"], s=70, facecolor="white", edgecolor=RED, linewidth=1.6, zorder=3)
        dx, dy = offsets.get(r["name"], (6, 6))
        ax.annotate(r["name"], (r["cap"], r["fit"]), xytext=(dx, dy), textcoords="offset points",
                    ha="left" if dx > 0 else "right", fontsize=8.6,
                    color=BLUE if is_wb else (INK if r["pass"] else GREY_1),
                    fontweight="bold" if is_wb else "normal")
    ax.set_xlim(20, 60)
    ax.set_ylim(10, 40)
    ax.set_xlabel("能力分（IR场景覆盖、金融数据、模型与执行、主动性与编排；满分 60）")
    ax.set_ylabel("落地适配分（工作环境、治理、开放标准、成本；满分 40）")
    ax.scatter([], [], s=60, color=GREEN, label="通过四条硬约束")
    ax.scatter([], [], s=60, facecolor="white", edgecolor=RED, linewidth=1.6, label="未通过硬约束（合规可得、内幕可控、跨境、治理）")
    ax.legend(loc="lower right", frameon=False, fontsize=8.2)
    ax.set_title("能力最强的海外产品无法以腾讯主体签约使用；能用的候选里 WorkBuddy 综合最高", loc="left")
    source_note(fig, "注：主观评分（1–5 分 × 权重），评分依据与敏感性分析见附录。海外头部在能力维度高于 WorkBuddy，如实打分。"
                     "数据截至 2026-10-25。")
    fig.savefig(FIG / "fig_capability_vs_fit.png")
    plt.close(fig)
    return rows


def fig_evolution():
    setup()
    cells = {
        (0, 0): ["Apple Siri AI", "腾讯元宝", "微信小微（灰度）", "S&P ChatIQ"],
        (0, 1): ["Hebbia Matrix", "LSEG Deep Research", "Wind Alice", "Perplexity Computer"],
        (1, 0): ["Lindy", "Copilot Analyst"],
        (1, 1): ["WorkBuddy", "Claude Cowork", "ChatGPT Work", "千问办公 · ArkClaw · Kimi Work", "Bloomberg ASKB"],
        (2, 0): ["OpenAI dots", "Meta Muse", "Gemini Tasks", "OpenClaw"],
        (2, 1): ["AlphaSense SuperAnalyst", "Hermes Agent", "豆包工作伙伴"],
        (2, 2): ["xAI Grok Bot", "Gemini agent", "Manus Cue", "Instinct"],
    }
    fig, ax = plt.subplots(figsize=(8.2, 5.6))
    for i in range(3):
        for j in range(3):
            face = BLUE_SOFT if (i, j) == (1, 1) else ("#F6F8FB" if (i + j) % 2 == 0 else "white")
            ax.add_patch(Rectangle((i, j), 1, 1, facecolor=face, edgecolor=GREY_3, linewidth=0.8))
            items = cells.get((i, j), [])
            for k, name in enumerate(items):
                is_wb = name == "WorkBuddy"
                ax.text(i + 0.06, j + 0.86 - k * 0.16, name, fontsize=8.6 if not is_wb else 9.6,
                        color=BLUE if is_wb else INK, fontweight="bold" if is_wb else "normal", va="top")
    arrow = FancyArrowPatch((1.74, 1.16), (2.22, 1.16), arrowstyle="-|>", mutation_scale=14, color=AMBER, linewidth=1.6)
    ax.add_patch(arrow)
    ax.text(1.98, 1.06, "IR 第三阶段：常驻只读监测\n（不自主对外）", fontsize=8.2, color=AMBER, ha="left")
    ax.set_xlim(0, 3)
    ax.set_ylim(0, 3)
    ax.set_xticks([0.5, 1.5, 2.5], ["被动：用户唤起", "定时或事件触发", "常驻：后台持续运行"])
    ax.set_yticks([0.5, 1.5, 2.5], ["单体", "专家团 / 子代理", "智能体之间通信"])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("主动性 →")
    ax.set_ylabel("协作性 →")
    ax.set_title("全球个人智能体正在向右上角演进；WorkBuddy 处在“定时 × 专家团”", loc="left")
    source_note(fig, "注：位置依据各产品官方发布与主流媒体报道，截至 2026-10-25；微信小微仍在灰度测试。")
    fig.savefig(FIG / "fig_evolution.png")
    plt.close(fig)


def fig_architecture():
    setup()
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    layers = [
        ("模型层", "混元 Hy3/Hy4 为主，按任务切换 DeepSeek / GLM / Kimi\n内幕任务只用私有化部署的模型", "模型白名单"),
        ("能力层", "IR 技能包：同业速评、问题雷达、数字守门员、股东监测\n连接器：腾讯文档、披露易、企业微信", "技能库 · 已公开表述库\n来源登记"),
        ("编排层", "定时任务：业绩季同业轮询、每日晨报\nIR 专家团：起草 → 事实核查 → 口径审核", "专家团模板"),
        ("载体层", "企业微信入口 · 桌面端本地执行 · 云端定时任务\n内幕材料只进私有化工作区", "部门租户与权限"),
        ("治理层", "数据三级分区（公开/内部/内幕）· 人审五道\n对外动作审批 · 操作日志 · 静默期与回购禁止期日历", "规则与日历由合规审定\n全员共用"),
    ]
    for k, (name, personal, shared) in enumerate(layers):
        y = 0.25 + k * 1.15
        ax.add_patch(FancyBboxPatch((0.0, y), 1.25, 0.95, boxstyle="round,pad=0.0,rounding_size=0.06",
                                    facecolor=INK, edgecolor="none"))
        ax.text(0.625, y + 0.475, name, color="white", ha="center", va="center", fontsize=10, fontweight="bold")
        ax.add_patch(FancyBboxPatch((1.4, y), 5.75, 0.95, boxstyle="round,pad=0.0,rounding_size=0.06",
                                    facecolor="white", edgecolor=GREY_3))
        ax.text(1.55, y + 0.475, personal, color=INK, ha="left", va="center", fontsize=8.3, linespacing=1.5)
        ax.add_patch(FancyBboxPatch((7.3, y), 2.7, 0.95, boxstyle="round,pad=0.0,rounding_size=0.06",
                                    facecolor=BLUE_SOFT, edgecolor="none"))
        ax.text(7.45, y + 0.475, shared, color=BLUE, ha="left", va="center", fontsize=8.3, linespacing=1.5)
    ax.text(1.4, 6.05, "每位 IR 同事的个人智能体（WorkBuddy）", fontsize=10, color=INK, fontweight="bold")
    ax.text(7.3, 6.05, "沉淀为部门资产", fontsize=10, color=BLUE, fontweight="bold")
    ax.set_title("个人智能体 × 部门资产：用同一套五层结构落地", loc="left", pad=22)
    source_note(fig, "注：五层结构由全球主流个人智能体的共性归纳而来；内幕材料的处理以法务与信息安全评估为前提。")
    fig.savefig(FIG / "fig_architecture.png")
    plt.close(fig)


def fig_roadmap():
    setup()
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    phases = [
        ("Q3 影子运行", date(2026, 10, 27), date(2026, 11, 28), GREY_2, "1–2 人、公开数据、不进入正式交付；11-18 会后复盘"),
        ("阶段 0 评估", date(2026, 11, 23), date(2026, 12, 31), GREY_1, "法务与信息安全评估，确认部署方式"),
        ("阶段 1 年度业绩试点", date(2027, 1, 11), date(2027, 3, 31), BLUE, "公开数据场景正式使用，建技能库"),
        ("阶段 2 接入内部材料", date(2027, 4, 1), date(2027, 6, 30), INK, "私有化就绪后接入"),
        ("阶段 3 常驻只读监测", date(2027, 7, 1), date(2027, 9, 30), AMBER, "同业、卖方、舆情"),
    ]
    base = date(2026, 10, 20)
    n = len(phases)
    for i, (name, a0, b0, c, note) in enumerate(phases):
        y = n - i
        ax.barh(y, (b0 - a0).days, left=(a0 - base).days, color=c, height=0.5)
        ax.text((a0 - base).days, y + 0.36, name, fontsize=9, color=INK, fontweight="bold", va="bottom")
        right = (b0 - base).days > 300
        ax.text((a0 - base).days - 3 if right else (b0 - base).days + 3, y, note, fontsize=8, color=GREY_1, va="center",
                ha="right" if right else "left")
    for d, lab in ((date(2026, 11, 18), "11-18 Q3 业绩"), (date(2027, 3, 18), "年度业绩（参考去年时点）")):
        m = (d - base).days
        ax.axvline(m, color=RED, linewidth=1, linestyle="--")
        ax.text(m + 3, n + 0.85, lab, color=RED, fontsize=8)
    ax.set_yticks([])
    ticks = [date(2026, 11, 1), date(2027, 1, 1), date(2027, 3, 1), date(2027, 5, 1), date(2027, 7, 1), date(2027, 9, 1)]
    ax.set_xticks([(t - base).days for t in ticks], [f"{t.year % 100}/{t.month:02d}" for t in ticks])
    ax.set_xlim(0, (date(2027, 10, 31) - base).days)
    ax.set_ylim(0.4, n + 1.3)
    ax.spines["left"].set_visible(False)
    ax.set_title("避开业绩季高峰：Q3 先影子运行，年度业绩周期再正式试点；永不代表公司对外沟通", loc="left")
    source_note(fig, "注：每个阶段设准入门槛（评测达标、零合规事件、日志可导出），未达标不进入下一阶段。年度业绩日期以公司公告为准。")
    fig.savefig(FIG / "fig_roadmap.png")
    plt.close(fig)


if __name__ == "__main__":
    rows = fig_capability_vs_fit()
    fig_evolution()
    fig_architecture()
    fig_roadmap()
    (ROOT / "report" / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "report" / "data" / "selection_scores.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in sorted(rows, key=lambda r: -r["total"]):
        print(f"{r['name']:28} cap={r['cap']:5.1f} fit={r['fit']:5.1f} total={r['total']:5.1f} pass={r['pass']}")
