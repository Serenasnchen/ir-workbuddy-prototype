"""M1 同业矩阵：下载/登记原始来源到 data/src/peers/，并写 manifest.tsv。

用法（在 ROOT 下）：
    python -I demo/pipeline/peer_fetch.py            # 只下载缺失文件
    python -I demo/pipeline/peer_fetch.py --refresh  # 全部重新下载（发布新季度后重跑用）

- 网络请求一律走 common.http_get（通用 UA、限速），不带任何个人信息。
- 腾讯材料（用户提供的 StockAnalysis 实录 4 季、官网 PDF）已在 data/src/transcripts 与
  data/src/ir_official 中，本脚本不重复下载，只在 manifest 中登记其原始 URL 与本地路径。
- 重跑：同业发布新季度后，把新的 URL 追加到 FETCH 列表（或替换 latest 条目），再运行
  peer_fetch.py 与 peer.py 即可；议题列不变（详见 m1_peer_NOTES.md「重跑」）。
- 已存在的文件不会重复下载（除非 --refresh）；本地齐全时本脚本不发起任何网络请求。
"""
import sys
from pathlib import Path

sys.path.insert(0, "demo/pipeline")
from common import ROOT, http_get, sha256_file, AS_OF  # noqa: E402

PEERS = ROOT / "data" / "src" / "peers"

SA = "https://stockanalysis.com"
# (本地文件名, URL, 说明)
FETCH = [
    # Meta 最新季（2026-10-21 发布 Q3 2026）——速评主材料
    ("meta_q3_2026_release.html",
     "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Third-Quarter-2026-Results/default.aspx",
     "Meta Q3 2026 业绩新闻稿（IR 网页版）"),
    ("meta_q3_2026_release.pdf",
     "https://s21.q4cdn.com/399680738/files/doc_news/Meta-Reports-Third-Quarter-2026-Results-2026.pdf",
     "Meta Q3 2026 业绩新闻稿（PDF）"),
    ("meta_q3_2026_transcript_stockanalysis.html", SA + "/stocks/meta/transcripts/718643-q3-2026/",
     "Meta Q3 2026 业绩会实录（StockAnalysis，非官方逐字稿）"),
    ("meta_q2_2026_transcript_stockanalysis.html", SA + "/stocks/meta/transcripts/657318-q2-2026/",
     "Meta Q2 2026 业绩会实录（上一季，对比用）"),
    ("meta_transcripts_index.html", SA + "/stocks/meta/transcripts/", "Meta 实录目录页"),
    # 其余同业：最新季 + 上一季实录（分析师追问焦点与 change_vs_prior 用）
    ("googl_q2_2026_transcript_stockanalysis.html", SA + "/stocks/googl/transcripts/657320-q2-2026/", "Alphabet Q2 2026 实录"),
    ("googl_q1_2026_transcript_stockanalysis.html", SA + "/stocks/googl/transcripts/551989-q1-2026/", "Alphabet Q1 2026 实录"),
    ("msft_fy26q4_transcript_stockanalysis.html", SA + "/stocks/msft/transcripts/647770-q4-2026/", "Microsoft FY26Q4 实录"),
    ("msft_fy26q3_transcript_stockanalysis.html", SA + "/stocks/msft/transcripts/547930-q3-2026/", "Microsoft FY26Q3 实录"),
    ("amzn_q2_2026_transcript_stockanalysis.html", SA + "/stocks/amzn/transcripts/657334-q2-2026/", "Amazon Q2 2026 实录"),
    ("amzn_q1_2026_transcript_stockanalysis.html", SA + "/stocks/amzn/transcripts/552741-q1-2026/", "Amazon Q1 2026 实录"),
    ("baba_fy27q1_transcript_stockanalysis.html", SA + "/quote/hkg/9988/transcripts/667892-q1-2027/", "阿里 FY27Q1（2026-06季）实录"),
    ("baba_fy26q4_transcript_stockanalysis.html", SA + "/quote/hkg/9988/transcripts/541101-q4-2026/", "阿里 FY26Q4（2026-03季）实录"),
    ("bidu_q2_2026_transcript_stockanalysis.html", SA + "/quote/hkg/9888/transcripts/673679-q2-2026/", "百度 Q2 2026 实录"),
    ("bidu_q1_2026_transcript_stockanalysis.html", SA + "/quote/hkg/9888/transcripts/571599-q1-2026/", "百度 Q1 2026 实录"),
    ("jd_q2_2026_transcript_stockanalysis.html", SA + "/quote/hkg/9618/transcripts/666500-q2-2026/", "京东 Q2 2026 实录"),
    ("jd_q1_2026_transcript_stockanalysis.html", SA + "/quote/hkg/9618/transcripts/583093-q1-2026/", "京东 Q1 2026 实录"),
    # 中概三家最近一季业绩公告（SEC 6-K Ex99.1，一级来源；capex、FCF、美元折算汇率）
    ("baba_fy27q1_6k_ex991.htm", "https://www.sec.gov/Archives/edgar/data/1577552/000110465926099220/tm2623667d1_ex99-1.htm",
     "阿里 2026-06 季业绩公告（SEC 6-K Ex99.1）"),
    ("bidu_q2_2026_6k_ex991.htm", "https://www.sec.gov/Archives/edgar/data/0001329099/000119312526355431/d112854dex991.htm",
     "百度 Q2 2026 业绩公告（SEC 6-K Ex99.1）"),
    ("jd_q2_2026_6k_ex991.htm", "https://www.sec.gov/Archives/edgar/data/1549802/000119312526347753/d143720dex991.htm",
     "京东 Q2 2026 业绩公告（SEC 6-K Ex99.1）"),
    # 美股三家上一季官方业绩稿（capex 表的本季/上年同期/上一季数值逐字核对用）
    ("amzn_q2_2026_8k_ex991.htm", "https://www.sec.gov/Archives/edgar/data/0001018724/000101872426000024/amzn-20260630xex991.htm",
     "Amazon Q2 2026 业绩公告（SEC 8-K Ex99.1）"),
    ("googl_q2_2026_release.pdf", "https://s206.q4cdn.com/479360582/files/doc_financials/2026/q2/2026q2-alphabet-earnings-release.pdf",
     "Alphabet Q2 2026 业绩新闻稿（Exhibit 99.1 PDF）"),
    ("meta_q2_2026_release.pdf", "https://s21.q4cdn.com/399680738/files/doc_financials/2026/q2/Meta-06-30-2026-Exhibit-99-1-FINAL.pdf",
     "Meta Q2 2026 业绩新闻稿（Exhibit 99.1 PDF）"),
    # 实录目录页（核实是否已有更新季度；重跑时先看这里）
    ("googl_transcripts_index.html", SA + "/stocks/googl/transcripts/", "Alphabet 实录目录页"),
    ("msft_transcripts_index.html", SA + "/stocks/msft/transcripts/", "Microsoft 实录目录页"),
    ("amzn_transcripts_index.html", SA + "/stocks/amzn/transcripts/", "Amazon 实录目录页"),
    ("baba_transcripts_index.html", SA + "/quote/hkg/9988/transcripts/", "阿里 实录目录页"),
    ("bidu_transcripts_index.html", SA + "/quote/hkg/9888/transcripts/", "百度 实录目录页"),
    ("jd_transcripts_index.html", SA + "/quote/hkg/9618/transcripts/", "京东 实录目录页"),
    # 发布日期核实（官方 IR）
    ("msft_ir_fy27q1_event.html", "https://www.microsoft.com/en-us/investor/events/fy-2027/earnings-fy-2027-q1",
     "Microsoft IR：FY27Q1 业绩电话会 2026-10-28"),
    ("alphabet_q3_2026_date_announcement.html",
     "https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Date-of-Third-Quarter-2026-Financial-Results-Conference-Call-2026-8tpGZsLS6v/default.aspx",
     "Alphabet IR：Q3 2026 电话会 2026-10-28（2026-10-06 公告）"),
    ("amzn_q3_2026_date.html", "https://www.aboutamazon.com/news/company-news/amazon-earnings-q3-2026-report",
     "Amazon：Q3 2026 电话会 2026-10-29"),
]

# 用户提供、已在本地的腾讯材料（不重复下载，只登记）
TENCENT_LOCAL = [
    ("data/src/transcripts/374535-q3-2025.html", SA + "/quote/hkg/0700/transcripts/374535-q3-2025/", "腾讯 3Q25 业绩会实录（用户提供）"),
    ("data/src/transcripts/419871-q4-2025.html", SA + "/quote/hkg/0700/transcripts/419871-q4-2025/", "腾讯 4Q25 业绩会实录（用户提供）"),
    ("data/src/transcripts/609405-q1-2026.html", SA + "/quote/hkg/0700/transcripts/609405-q1-2026/", "腾讯 1Q26 业绩会实录（用户提供）"),
    ("data/src/transcripts/667897-q2-2026.html", SA + "/quote/hkg/0700/transcripts/667897-q2-2026/", "腾讯 2Q26 业绩会实录（用户提供）"),
    ("data/src/ir_official/3Q25_ppt.pdf", "https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf", "腾讯 3Q25 业绩 PPT（用户提供）"),
    ("data/src/ir_official/4Q25_ppt.pdf", "https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf", "腾讯 4Q25 业绩 PPT（用户提供）"),
    ("data/src/ir_official/2Q26_ppt.pdf", "https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf", "腾讯 2Q26 业绩 PPT（用户提供）"),
    ("data/src/results_page.html", "https://www.tencent.com/investors/results/", "腾讯 IR 业绩页（用户提供；材料索引）"),
]


def main(refresh=False):
    PEERS.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, url, desc in FETCH:
        dest = PEERS / name
        status = "cached"
        if refresh or not dest.exists():
            try:
                http_get(url, dest=dest, delay=1.5)
                status = "downloaded"
            except Exception as e:  # noqa: BLE001
                status = f"ERROR {type(e).__name__}: {e}"
        sha = sha256_file(dest) if dest.exists() else ""
        rows.append(("data/src/peers/" + name, url, desc, status, sha))
        print(f"[{status}] {name}")
    for rel, url, desc in TENCENT_LOCAL:
        p = ROOT / rel
        rows.append((rel, url, desc, "local(user-provided)" if p.exists() else "MISSING", sha256_file(p) if p.exists() else ""))
    out = PEERS / "manifest.tsv"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# as_of={AS_OF}\tgenerated_by=demo/pipeline/peer_fetch.py\n")
        f.write("path\turl\tdesc\tstatus\tsha256\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print("manifest ->", out.relative_to(ROOT))


if __name__ == "__main__":
    main(refresh="--refresh" in sys.argv)
