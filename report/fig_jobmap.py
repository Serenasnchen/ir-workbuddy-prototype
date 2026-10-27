"""Chapter 1 figure: where an agent helps across 18 secondary-market IR tasks (value x data risk)."""
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from style import AMBER, BLUE, GREY_1, GREY_2, GREY_3, GREY_4, INK, RED, setup, source_note

FIG = Path(__file__).resolve().parents[1] / "report" / "figures"

# (task, value 1-5 = frequency x time saved, data risk 1-3 = 公开/内部/内幕, stage)
TASKS = [
    ("全球同业速评与capex对标", 4.8, 1.0, 1),
    ("业绩会Q&A预测与已公开表述索引", 4.7, 1.25, 1),
    ("股东结构、南向与回购监测", 4.0, 1.1, 1),
    ("管理层问询与周报（先用公开知识）", 4.6, 1.55, 1),
    ("业绩后一致性复核、卖方修正汇总", 3.9, 1.35, 1),
    ("股价异动归因（只读预警）", 3.0, 1.45, 3),
    ("零售与社媒舆情监测", 2.9, 1.15, 3),
    ("投资者定位与路演排程", 3.0, 1.95, 2),
    ("会前简报（只引已公开口径）", 4.1, 2.1, 2),
    ("会后纪要与反馈汇总", 4.0, 2.3, 2),
    ("卖方研报追踪与可纠正事实清单", 3.8, 1.7, 2),
    ("认知调研的纪要编码", 2.0, 2.05, 2),
    ("ESG问卷预填", 2.1, 1.8, 2),
    ("业绩材料中英文数字勾稽", 4.9, 2.85, 2),
    ("一致预期与预期差（仅内部）", 3.7, 2.55, 2),
    ("讲稿措辞比对、机器读者测试", 3.1, 2.95, 2),
    ("内幕消息识别与对外材料预审", 3.2, 2.7, 2),
]

STAGE_COLOR = {1: BLUE, 2: INK, 3: AMBER}
STAGE_NAME = {1: "阶段1：公开数据，Q3 即可试点", 2: "阶段2：私有化就绪后接入", 3: "阶段3：常驻只读监测"}


def main():
    setup()
    fig, ax = plt.subplots(figsize=(8.4, 5.4))
    ax.axhspan(0.6, 1.5, color=GREY_4, zorder=0)
    ax.axhspan(2.5, 3.2, color="#FBEDEA", zorder=0)
    for name, v, r, st in TASKS:
        ax.scatter(v, r, s=58, color=STAGE_COLOR[st], zorder=3, edgecolor="white", linewidth=1)
        ha = "right" if v > 4.3 else "left"
        dx = -7 if ha == "right" else 7
        ax.annotate(name, (v, r), xytext=(dx, 0), textcoords="offset points", va="center", ha=ha, fontsize=8, color=GREY_1)
    ax.set_xlim(1.6, 5.2)
    ax.set_ylim(0.6, 3.2)
    ax.set_yticks([1, 2, 3], ["公开数据", "内部材料", "未公布/内幕"])
    ax.set_xlabel("智能体可带来的价值（频率 × 可节省时间，主观评估 1–5）")
    ax.set_ylabel("涉及的数据级别")
    ax.text(5.15, 0.68, "先做：价值高、只用公开数据", ha="right", fontsize=8.5, color=BLUE, fontweight="bold")
    ax.text(5.15, 3.12, "价值同样高，但必须等私有化部署", ha="right", va="top", fontsize=8.5, color=RED, fontweight="bold")
    for st, c in STAGE_COLOR.items():
        ax.scatter([], [], color=c, s=50, label=STAGE_NAME[st])
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.set_title("智能体做准备与核查，人做判断与表达：17 项二级市场 IR 任务的优先级", loc="left")
    source_note(fig, "注：任务清单依据 Q4、Nasdaq IR、Irwin 等发行人平台的功能拆解与港股 IR 规则整理；价值为主观评估。"
                     "对外问答机器人、自动群发、介入交易或回购、AI 数字人等不在范围内。")
    fig.savefig(FIG / "fig_jobmap.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
