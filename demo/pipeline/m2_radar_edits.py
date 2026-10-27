# -*- coding: utf-8 -*-
"""M2b 问题雷达 v2 的人工整理编辑层（只含数据，由 radar.py 读入合并）。

分工：
- 本文件 = 人工整理：话题分类、改写后的题面、已公开表述索引（原话+出处）、口径漂移、
  暂无已公开表述事项、10-19 以来变化、Top10 预注册议题。
- radar.py = 本地 Python：读入 v1、合并本文件、复算回购、核验引语、编码分析师话题、算哈希、输出。

约定：
- src 一律写来源别名（见 SOURCES）或 v1 中已有的 URL；radar.py 统一换成 Sxxx 编号。
- verify：("tr", "q2-2026") 在本地第三方文字稿中逐字比对；("txt", 路径) 在本地文本中比对；
  ("pdfzh", 路径) 用 pymupdf 抽取本地中文 PDF 后比对；("titles", 路径) 在港交所标题检索结果（list2026.json）中比对；
  ("web", "YYYY-MM-DD") 表示本次整理时联网打开原网页人工核对；None 表示沿用 v1 核查结论。
- 本文件不得出现任何个人信息；不写估值、市盈率、目标价；不替管理层拟答复。
"""

WATERMARK = "内部准备材料，不构成公司口径"
AS_OF = "2026-10-26"
WEB = ("web", "2026-10-26")


def TR(q):
    return ("tr", q)


def TXT(p):
    return ("txt", p)


def PZH(p):
    return ("pdfzh", p)


def S(speaker, quote, src, date, verify=None, lang="en", note=None):
    return {"speaker": speaker, "quote": quote, "src": src, "date": date,
            "verify": verify, "lang": lang, "note": note}


def EV(src, date, point, label="公开披露", flags=()):
    return {"src": src, "date": date, "point": point, "label": label, "flags": list(flags)}


# ---------------------------------------------------------------- 话题分类（全模块共用）
TOPICS = [
    ("AI_CAPEX", "资本开支/算力投入"),
    ("AI_ROI", "投资回报/回本/变现时间"),
    ("AI_PRODUCTS", "自有AI产品（WorkBuddy/CodeBuddy/元宝/小微/智能体）"),
    ("MODELS", "混元/Hy模型能力"),
    ("COMPUTE", "芯片/GPU/算力供给"),
    ("CLOUD", "腾讯云/对外算力/Token定价"),
    ("MARGIN", "利润率/折旧/成本"),
    ("CAPITAL", "回购/派息/自由现金流/负债"),
    ("ADS", "营销服务/广告"),
    ("GAMES_DOM", "本土游戏"),
    ("GAMES_INTL", "国际游戏"),
    ("FINTECH", "金融科技与企业服务"),
    ("SOCIAL", "社交/视频号/内容/订阅"),
    ("REG", "监管/地缘/1260H"),
    ("PORTFOLIO", "投资组合/处置"),
]

# 分析师提问粗粒度关键词编码规则（早期草稿；radar.py 已改用 M2a 人工逐条编码结果，本表仅留作参考，不参与计算）
TOPIC_KEYWORDS = {
    "AI_CAPEX": r"capex|capital expenditure|lump sum|compute investment",
    "AI_ROI": r"\bROI\b|ROIC|return on investment|payback|monetiz|drag|envelope|investment mode|harvest|profitab|\breturns?\b",
    "AI_PRODUCTS": r"WorkBuddy|CodeBuddy|Yuanbao|Xiaowei|QClaw|SkillHub|agentic|\bagents?\b|AI products?|harness",
    "MODELS": r"Hunyuan|HunYuan|\bHy\d|foundation model|frontier|SOTA|state-of-the-art|parameter",
    "COMPUTE": r"GPU|\bchips?\b|ASIC|semiconductor|inferenc(e|ing) capacity|compute constrain|DRAM|HBM",
    "CLOUD": r"\bcloud\b|token prices?|MaaS|Model-as-a-Service|\bAPI\b",
    "MARGIN": r"margin|D&A|depreciation|operating leverage|eating into earnings",
    "CAPITAL": r"buy ?backs?|dividend|capital allocation|free cash flow|\bdebt\b|balance sheet|capital return",
    "ADS": r"advertis|ad load|AIM|marketing services|eCPM",
    "GAMES_DOM": r"domestic gam|Honor of Kings|Delta Force|\bgam(e|es|ing)\b",
    "GAMES_INTL": r"international gam|Supercell|overseas gam|shooter|Battlefield|Arc Raiders",
    "FINTECH": r"fintech|\bFBS\b|payment|consumer loan|wealth",
    "SOCIAL": r"Video Accounts|Tencent Video|mini program|Weixin|WeChat|drama|subscription|social",
    "REG": r"regulat|Apple|commission|export control|sanction|1260H|policy",
    "PORTFOLIO": r"investment portfolio|portfolio|divest|\bstakes?\b",
}

# ---------------------------------------------------------------- 来源别名
# 用户提供的 8 个链接固定为 S001–S008（url_as_given 保留用户原样链接，canonical 去掉跟踪参数）
USER_SUPPLIED = [
    {"sid": "S001", "alias": "TR_Q3_25",
     "url_as_given": "https://stockanalysis.com/quote/hkg/0700/transcripts/374535-q3-2025/?utm_source=chatgpt.com",
     "url": "https://stockanalysis.com/quote/hkg/0700/transcripts/374535-q3-2025/",
     "title": "StockAnalysis：腾讯 2025年第三季度业绩会文字稿（第三方，非官方逐字稿）", "date": "2025-11-13", "tier": 3,
     "local": ["data/src/transcripts/374535-q3-2025.html", "data/parsed/q3-2025.json"], "transcript": "q3-2025",
     "used_for": "3Q25 业绩会：2025 年资本开支指引下调及原因（芯片可得性）；“GPU 内部够用”的表述；国际游戏一次性买断与并表带来的高基数；投资组合“减持大于投资”；eCPM 约贡献一半广告增长；近四季分析师话题编码。"},
    {"sid": "S002", "alias": "TR_Q4_25",
     "url_as_given": "https://stockanalysis.com/quote/hkg/0700/transcripts/419871-q4-2025/?utm_source=chatgpt.com",
     "url": "https://stockanalysis.com/quote/hkg/0700/transcripts/419871-q4-2025/",
     "title": "StockAnalysis：腾讯 2025年第四季度及全年业绩会文字稿（第三方，非官方逐字稿）", "date": "2026-03-18", "tier": 3,
     "local": ["data/src/transcripts/419871-q4-2025.html", "data/parsed/q4-2025.json"], "transcript": "q4-2025",
     "used_for": "4Q25 业绩会：新AI产品 70 亿/180 亿元与“more than double”；2025 年回购 800 亿港元与“回购少于 2025”；算力来源（租赁/进口/国产 GPU）；供应链提前锁定；近四季分析师话题编码。"},
    {"sid": "S003", "alias": "TR_Q1_26",
     "url_as_given": "https://stockanalysis.com/quote/hkg/0700/transcripts/609405-q1-2026/?utm_source=chatgpt.com",
     "url": "https://stockanalysis.com/quote/hkg/0700/transcripts/609405-q1-2026/",
     "title": "StockAnalysis：腾讯 2026年第一季度业绩会文字稿（第三方，非官方逐字稿）", "date": "2026-05-13", "tier": 3,
     "local": ["data/src/transcripts/609405-q1-2026.html", "data/parsed/q1-2026.json"], "transcript": "q1-2026",
     "used_for": "1Q26 业绩会：资本开支“substantial increase…second half”；“sustain buybacks…rest of this year”与加快投资组合变现；AI 回报框架；视频号广告加载率 4%-5%；游戏递延收入；海外同业对比提问先例；近四季分析师话题编码。"},
    {"sid": "S004", "alias": "TR_Q2_26",
     "url_as_given": "https://stockanalysis.com/quote/hkg/0700/transcripts/667897-q2-2026/?utm_source=chatgpt.com",
     "url": "https://stockanalysis.com/quote/hkg/0700/transcripts/667897-q2-2026/",
     "title": "StockAnalysis：腾讯 2026年第二季度业绩会文字稿（第三方，非官方逐字稿）", "date": "2026-08-12", "tier": 3,
     "local": ["data/src/transcripts/667897-q2-2026.html", "data/parsed/q2-2026.json"], "transcript": "q2-2026",
     "used_for": "2Q26 业绩会：lump sum、“only keep on investing if it generates a great return”、envelope、“a prudent level of debt capacity”、30% 转售溢价、云增速、WorkBuddy 订阅与毛利、小微分阶段、Hy4 年内发布等；绝大多数题目的已公开表述索引与 5 例口径漂移；近四季分析师话题编码。"},
    {"sid": "S005", "alias": "PPT_3Q25",
     "url_as_given": "https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf?utm_source=chatgpt.com",
     "url": "https://static.www.tencent.com/uploads/2025/11/13/3ff004e913507e0309f3f62a553185b2.pdf",
     "title": "腾讯 2025年第三季度业绩演示材料（官方）", "date": "2025-11-13", "tier": 2,
     "local": ["data/src/ir_official/3Q25_ppt.pdf", "data/src/ir_official/3Q25_ppt.txt"],
     "used_for": "Q3 同比基数（第21页）：3Q25 总资本开支 130 亿元、自由现金流 585 亿元、净现金 1,024 亿元、上市投资公允价值约 8,010 亿元、回购约 190 亿元人民币。"},
    {"sid": "S006", "alias": "PPT_4Q25",
     "url_as_given": "https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf?utm_source=chatgpt.com",
     "url": "https://static.www.tencent.com/uploads/2026/03/18/2804dbdae364ca25b82d21bc8304f1d3.pdf",
     "title": "腾讯 2025年第四季度及全年业绩演示材料（官方）", "date": "2026-03-18", "tier": 2,
     "local": ["data/src/ir_official/4Q25_ppt.pdf", "data/src/ir_official/4Q25_ppt.txt"],
     "used_for": "第11页：新AI产品成本及费用（4Q25 70 亿、2025 年 180 亿元，仅含混元与元宝）、“more than double”、“现有业务利润增长应能覆盖增量投入”；第30页：回购少于 2025、提高股息。"},
    {"sid": "S007", "alias": "IR_RESULTS",
     "url_as_given": "https://www.tencent.com/investors/results/?utm_source=chatgpt.com",
     "url": "https://www.tencent.com/investors/results/",
     "title": "腾讯投资者关系·业绩页（官方，本地页面快照）", "date": "2026-10-26", "tier": 2,
     "local": ["data/src/market_raw/idx/tc_res.html", "data/src/results_page.html"],
     "used_for": "官方材料链接索引：核对 S005、S006、S008 及各季新闻稿/公告链接确为腾讯官网列示（脚本逐条比对页面快照）。"},
    {"sid": "S008", "alias": "PPT_2Q26",
     "url_as_given": "https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf?utm_source=chatgpt.com",
     "url": "https://static.www.tencent.com/website-2026-upload/2Q26-earnings-PPT_20260812_1800-88b183.pdf",
     "title": "腾讯 2026年第二季度业绩演示材料（官方）", "date": "2026-08-12", "tier": 2,
     "local": ["data/src/ir_official/2Q26_ppt.pdf", "data/src/ir_official/2Q26_ppt.txt"],
     "used_for": "第5页“clear downside protection”与护城河（含 regulatory requirements）；第20页“still compute constrained”；第26页资本开支/自由现金流/净现金表、回购与派息、上市投资公允价值约 4,870 亿元。"},
]

# 其他来源（别名 -> 元数据）。v1 已有的 URL 不必全部列出，radar.py 会按 URL 自动登记。
SOURCES = {
    "REL_EN_2Q26": {"url": "https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf",
                    "title": "腾讯2Q26业绩新闻稿（英文，官方）", "date": "2026-08-12", "tier": 2,
                    "local": ["data/src/ir_official/2Q26_release_en.pdf", "data/src/ir_official/2Q26_release_en.txt"]},
    "REL_ZH_2Q26": {"url": "https://www.tencent.com/wp-content/uploads/2026/08/%E8%85%BE%E8%AE%AF%E5%85%AC%E5%B8%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E5%85%AD%E5%B9%B4%E7%AC%AC%E4%BA%8C%E5%AD%A3%E4%B8%9A%E7%BB%A9.pdf",
                    "title": "腾讯2Q26业绩新闻稿（中文，官方）", "date": "2026-08-12", "tier": 2,
                    "local": ["data/src/ir_official/2Q26_release_zh.pdf"]},
    "REL_EN_1Q26": {"url": "https://static.www.tencent.com/uploads/2026/05/13/47382ae415a209fd161bc19a1f9b3704.pdf",
                    "title": "腾讯1Q26业绩新闻稿（英文，官方）", "date": "2026-05-13", "tier": 2,
                    "local": ["data/src/ir_official/1Q26_release_en.pdf", "data/src/ir_official/1Q26_release_en.txt"]},
    "HKEX_EN_2Q26": {"url": "https://www.tencent.com/wp-content/uploads/2026/08/E700_IRA.pdf",
                     "title": "腾讯2026年第二季度业绩公告（港交所，英文）", "date": "2026-08-12", "tier": 1,
                     "local": ["data/src/ir_official/2Q26_hkex_en.pdf", "data/src/ir_official/2Q26_hkex_en.txt"]},
    "IR26": {"url": "https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf",
             "title": "腾讯2026年中期报告（英文）", "date": "2026-08-12", "tier": 1,
             "local": ["data/src/market_raw/dl/tc_ir26.pdf", "data/src/market_raw/dl/tc_ir26.txt"]},
    "LAUNCH": {"url": "https://www.tencent.com/wp-content/uploads/2026/10/E700_Launch-Announcement.pdf",
               "title": "腾讯票据发行公告（Launch Announcement，港交所）", "date": "2026-10-12", "tier": 1,
               "local": ["data/src/ir_official/2026-10-12_E700_Launch-Announcement.pdf", "data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt"]},
    "PRICING": {"url": "https://www.tencent.com/wp-content/uploads/2026/10/E700_Pricing-Announcement.pdf",
                "title": "腾讯票据定价公告（港交所）", "date": "2026-10-14", "tier": 1,
                "local": ["data/src/ir_official/2026-10-14_E700_Pricing-Announcement.pdf", "data/src/ir_official/2026-10-14_E700_Pricing-Announcement.txt"]},
    "HKEX_COMPLETION": {"url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1022/2026102200033.pdf",
                        "title": "腾讯：完成发行18亿美元及260亿元人民币票据公告（港交所 2026102200033）", "date": "2026-10-22", "tier": 1,
                        "local": ["demo/data/m2_raw/hkex_2026102200033.pdf"]},
    "HKEX_TITLES": {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0&market=SEHK&stockId=7609&documentType=-1&fromDate=20260101&toDate=20261026&title=&searchType=0&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=500&lang=E",
                    "title": "港交所披露易标题检索：腾讯 2026-01-01 至 2026-10-26 全部公告（上一轮抓取的 JSON，最新一条为 10-22 12:03）", "date": "2026-10-26", "tier": 1,
                    "local": ["data/src/market_raw/nddr/list2026.json"]},
    "NDDR_1015": {"url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1015/2026101500641.pdf",
                  "title": "腾讯翌日披露报表（2026-10-15，回购）", "date": "2026-10-15", "tier": 1,
                  "local": ["data/src/market_raw/nddr/2026101500641.txt", "data/src/market_raw/nddr/2026101500641.pdf"]},
    "BB_JSON": {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0&market=SEHK&stockId=7609&documentType=-1&fromDate=20260101&toDate=20261026&title=&searchType=0&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=500&lang=E",
                "title": "港交所翌日披露报表 2026 年逐份解析（本地结构化数据 buybacks2026.json，由标题检索结果逐份下载 PDF 后解析）", "date": "2026-10-15", "tier": 1,
                "local": ["data/src/market_raw/nddr/buybacks2026.json"]},
    "BOARD_MTG": {"url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0924/2026092401585.pdf",
                  "title": "腾讯董事会会议日期公告（港交所，2026-09-24）", "date": "2026-09-24", "tier": 1,
                  "local": ["data/src/market_raw/nddr/2026092401585.txt"]},
    "HKEX_SB": {"url": "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk",
                "title": "港交所披露易：港股通南向持股（按日；最新页面快照 mm_hk.html，趋势取自上一轮脚本抓取结果 mkt.json）", "date": "2026-10-23", "tier": 1,
                "local": ["data/src/market_raw/hkex/mm_hk.html"]},
    "HKEX_DAILY": {"url": "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_20261023e.js",
                   "title": "港交所沪深港通每日十大成交股统计（10-20至10-23本地副本，radar.py 复算）", "date": "2026-10-23", "tier": 1,
                   "local": ["data/src/market_raw/idx/sc_20261020.js", "data/src/market_raw/idx/sc_20261021.js", "data/src/market_raw/idx/sc_20261022.js", "data/src/market_raw/idx/sc_20261023.js"]},
    "META_8K": {"url": "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Third-Quarter-2026-Results/default.aspx",
                "title": "Meta Platforms：Meta Reports Third Quarter 2026 Results（官方业绩新闻稿，本地副本）", "date": "2026-10-21", "tier": 2,
                "local": ["data/src/peers/meta_q3_2026_release.html", "data/src/peers/meta_q3_2026_release.pdf"]},
    "FORTUNE_META": {"url": "https://fortune.com/2026/10/21/meta-q3-earnings-mark-zuckerberg-capex-muse/",
                     "title": "Fortune：Meta Q3 earnings（capex、Muse）", "date": "2026-10-21", "tier": 4},
    "TNW_DEEPSEEK": {"url": "https://thenextweb.com/news/deepseek-reportedly-raises-15bn-from-tencent-and-catl-ahead-of-ipo",
                     "title": "The Next Web（转引彭博）：DeepSeek 据报完成约1000亿元融资", "date": "2026-10-23", "tier": 4},
    "QM_SINA": {"url": "https://finance.sina.cn/stock/jdts/2026-10-21/detail-inivyaaw4800872.d.html",
                "title": "新浪财经/36氪转载 QuestMobile 2026年三季度AI应用报告", "date": "2026-10-21", "tier": 4},
    "YB_SEARCH": {"url": "https://news.qq.com/rain/a/20261020A0BQ0Z00",
                  "title": "腾讯新闻：元宝搜索升级并通过腾讯云对外开放", "date": "2026-10-20", "tier": 4},
    "CONF_CHINADAILY": {"url": "https://cn.chinadaily.com.cn/a/202609/16/WS6aaa3a82e4b09a165c78a6c0.html",
                        "title": "中国日报网：2026腾讯全球数字生态大会官宣", "date": "2026-09-16", "tier": 4},
    "CONF_DEVCLOUD": {"url": "https://developer.cloud.tencent.com/article/2746250",
                      "title": "腾讯云开发者社区：2026腾讯全球数字生态大会前瞻（写作10月29-30日）", "date": "2026-10-13", "tier": 4},
    "HUXIU_XW": {"url": "https://www.huxiu.com/article/4898417.html",
                 "title": "虎嗅：微信小微体验报道", "date": "2026-10-18", "tier": 4},
    "SINA_Q2": {"url": "https://finance.sina.com.cn/tech/2026-08-12/doc-ininarrc3408590.shtml",
                "title": "新浪科技《全文|腾讯Q2业绩会实录》（媒体整理稿，非官方逐字稿）", "date": "2026-08-12", "tier": 3},
    "WSCN_FY25": {"url": "https://wallstreetcn.com/articles/3767854",
                  "title": "华尔街见闻：腾讯年度业绩会报道", "date": "2026-03-18", "tier": 4},
    "INV_FY25": {"url": "https://www.investing.com/news/stock-market-news/tencent-shares-slide-as-ai-spending-plans-overshadow-strong-q4-earnings-4569751",
                 "title": "Investing.com：腾讯2025年度业绩会报道", "date": "2026-03-19", "tier": 4},
    "J21_BOND": {"url": "https://www.21jingji.com/article/20261014/herald/3a864d83e2ae6eb64f1e139a69a40e13.html",
                 "title": "21世纪经济报道（转财联社）：腾讯点心债与AI资本开支", "date": "2026-10-14", "tier": 4},
    "FR_1260H": {"url": "https://www.govinfo.gov/content/pkg/FR-2026-06-10/pdf/2026-11571.pdf",
                 "title": "美国《联邦公报》2026-11571号（1260H 清单）", "date": "2026-06-10", "tier": 1,
                 "local": ["data/src/market_raw/dod/fr.pdf", "data/src/market_raw/dod/fr.txt"]},
}

# v1 中日期非标准的来源，人工给定 YYYY-MM-DD
DATE_FIX = {
    "https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf": "2026-08-12",
    "https://www.tencent.com/wp-content/uploads/2026/08/C700_IR.pdf": "2026-08-12",
    "https://m.jiemian.com/article/14927165.html": "2026-08-13",
}

# ---------------------------------------------------------------- 主题（去掉估值表述）
THEMES = [
    {"name": "AI投入与财务回报", "heat": 95,
     "one_line": "二季度资本开支528亿元、自由现金流-138亿元，按推算新AI产品对经营利润的拖累约105亿元（推算）。Q3是折旧和AI费用集中进入报表的季度，“投多少、何时回本、利润何时恢复”仍是主线；10-21 Meta 同样呈现“广告高增长+资本开支大增+自由现金流转负”，海外同业类比追问的概率上升（推断）。",
     "src": ["PPT_2Q26", "REL_EN_2Q26", "META_8K"]},
    {"name": "股东回报、资本结构与监管", "heat": 82,
     "one_line": "10月票据（18亿美元+260亿元人民币）已于10-21完成发行；回购最后一笔在10-15，年内合计约324.44亿港元（计算，约为2025年的四成）。“发债投AI、回购减少”的取舍、杠杆边界和发债用途表述会被追问；地缘与国内监管问得少，但敏感度高。",
     "src": ["HKEX_COMPLETION", "BB_JSON", "TR_Q4_25"]},
    {"name": "混元模型与AI产品变现", "heat": 82,
     "one_line": "WorkBuddy 生态、小微灰度、Hy4 preview 之后，公司仍未披露用户、付费和收入；第三方数据（QuestMobile 9月 WorkBuddy 月活 3,235.3 万，未去重）已在市场流传。10-29 数字生态大会预告发布百余项 Agent 新品，可能形成新的追问素材（推断）。",
     "src": ["REL_EN_2Q26", "QM_SINA", "CONF_CHINADAILY"]},
    {"name": "核心业务基本盘", "heat": 68,
     "one_line": "券商预计Q3广告约18%-19%、本土游戏11%-13%、海外游戏转为下滑（媒体转述/二手）。基本盘利润增速被市场当作AI投入可承受度的参照（推断）；Q2电话会上几乎没人问，Q3这类问题的占比可能上升。",
     "src": ["https://cj.sina.com.cn/articles/view/5835524730/15bd30a7a02002bbyi", "https://cn.investing.com/news/stock-market-news/article-3605137", "https://m.gelonghui.com/news/5322485"]},
]
THEME_RENAME = {"股东回报、监管与估值": "股东回报、资本结构与监管"}

# ---------------------------------------------------------------- 逐题编辑
# 字段：rank（v2 排序）、topics、可选覆盖 theme/sub_theme/question_cn/question_en/why_now/confirm、
# why_now_replace（字符串替换）、evidence_drop（v1 证据下标）、evidence_replace（下标->新 point/source）、
# evidence_add、psi（已公开表述索引）、gap_ids、v2_changes。
Q = {}

Q["Q01"] = {
    "rank": 1, "topics": ["AI_CAPEX"],
    "question_cn": "二季度总资本开支528亿元，同比增长176%；经营性资本开支518亿元，同比增长190%，年化已超过2000亿元。业绩后券商对2026年的预测在2000亿到2500亿元之间（媒体转述/二手）。管理层把AI原生部分定性为“今明两年一次性集中投入”。请问能否给出2026年和2027年资本开支的大致区间？三季度会不会继续环比提升？集中投入结束后，资本开支回落到什么水平？另外，10月发债文件按现金支付口径披露上半年资本开支为963亿元（2025年全年883亿元），和中期报告会计口径的847亿元怎么对应？",
    "why_now": "事实：二季度资本开支环比增长65%。用户提供的四季实录显示资本开支表述持续演变：2025-11-13（3Q25）CFO称2025年资本开支将低于此前“占收入低双位数百分比”的指引区间，总裁称原因是AI芯片可得性；2026-05-13（1Q26）称将“substantial increase…especially in the second half”；2026-08-12（2Q26）称AI原生部分是“this year and next year”的一次性投入。10月12日港交所发债公告首次给出现金支付口径：上半年963亿元，2025年全年883亿元。券商2026年预测：大摩2000亿元（10月上调到2060亿元），高盛2100亿元，瑞银2500亿元（媒体转述/二手）。Q3业绩董事会定于11月18日。推断：卖方会继续追问区间、节奏和口径差异。",
    "evidence_replace": {2: {"point": "事实：发行文件原文按“amount paid”口径列示资本开支：2023、2024、2025年分别为227亿、721亿、883亿元，2025年及2026年上半年分别为459亿、963亿元（本地副本逐字核对，不再依赖路透转述）。"}},
    "evidence_add": [
        EV("TR_Q3_25", "2025-11-13", "CFO罗硕瀚：2025年资本开支将低于此前指引区间（占收入低双位数百分比），但金额高于2024年；刘炽平：原因是AI芯片可得性变化，不是AI战略或Token需求预期变化。"),
        EV("TR_Q1_26", "2026-05-13", "James Mitchell：此前指引今年资本开支高于去年，现在“more affirmative, more confident”；下半年随国产ASIC逐月到货将大幅增加。"),
    ],
    "psi": [
        S("刘炽平（Martin Lau）", "it is more of a sort of a lump sum that we are going to be investing this year and next year", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "We will only keep on investing if it generates a great return.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "投向 AI 原生业务的资本开支，主要是今年和明年一次性集中投入，大家不要默认我们每年都会维持同等大额投入。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("James Mitchell", "We and you should expect a substantial increase in CapEx, especially in the second half of this year as more China-designed ASICs become available to us month by month through the year.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("罗硕瀚（John Lo）", "The 2025 CapEx will be lower to our previous guided range, but the amount will be higher than that of 2024.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        S("刘炽平（Martin Lau）", "It is indeed a change in terms of the AI chip availability.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        S("公司发债文件", "which amounted to RMB22.7 billion, RMB72.1 billion and RMB88.3 billion and RMB45.9 billion and RMB96.3 billion (US$14.2 billion) for the years ended 31 December 2023, 2024 and 2025 and the six months ended 30 June 2025 and 2026, respectively", "LAUNCH", "2026-10-12", TXT("data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt")),
    ],
    "confirm": "暂无已公开表述的四个方面（工具只标注，不建议口径）：(1) 2026、2027年资本开支是否给出数字区间或量级，还是继续不给。(2) “集中投入”的时间边界，以及之后的常态水平。(3) 三套口径的对外解释：会计口径（上半年847亿元）、现金支付口径（上半年963亿元，2025全年883亿元）、季度资本开支付款（Q2为593亿元）；内部可备一张口径对照表。(4) “封顶”的中文媒体稿与英文文字稿表述不一致（见口径漂移 D01），对外以哪一版为准需确认。",
    "gap_ids": ["G01", "G08"],
    "v2_changes": ["answer_frame 改为已公开表述索引", "补入 3Q25/1Q26/2Q26 三季实录中的资本开支表述（S001/S003/S004）", "963亿元改为引用本地发债公告原文"],
}

Q["Q02"] = {
    "rank": 2, "topics": ["AI_ROI", "AI_PRODUCTS", "MARGIN"],
    "question_cn": "按公告口径推算，新AI产品对经营利润的差额从一季度约88亿元扩大到二季度约105亿元（推算）。大摩预计Q3 AI业务经营亏损约150亿元，瑞银预计AI运营支出约160亿元（媒体转述/二手）。请问：这个差额是否包含共享算力的折旧分摊？一季度公告写明剔除的是新AI产品的“收入、成本及费用”，二季度只写“新AI产品以Hy、元宝、CodeBuddy、WorkBuddy及小微为主”，定义和范围（QClaw换成小微）是否一致、有没有同口径重述？“集团利润一定比例”的投入信封具体是多少？拖累峰值在哪个季度？3月官方材料称2025年新AI产品成本及费用为180亿元（仅含混元和元宝）、2026年将“more than double”，这与今年的差额口径是否可比，全年预算是否已上调？",
    "question_en": "Your ex-new-AI disclosure implies the gap widened from about RMB8.8bn in 1Q to RMB10.5bn in 2Q, and brokers expect RMB15–16bn in 3Q. In 1Q you defined it as excluding revenues, costs and expenses of new AI products; in 2Q the footnote only lists the products, with QClaw replaced by Xiaowei. Is the definition unchanged, does it include allocated shared-compute depreciation, and can you size the envelope as a share of group profit? In March you said 2025 costs and expenses for new AI products were RMB18bn (Hunyuan and Yuanbao only) and would more than double in 2026 — is that comparable with this year's gap, and has the budget been raised?",
    "why_now_replace": [["推断：这个口径本身已成为估值分歧点，Q3会被逐项拆解。", "推断：这个口径本身已成为卖方模型的分歧点，Q3会被逐项拆解。"]],
    "evidence_replace": {7: {"point": "管理层（媒体转述）：“去年腾讯有180亿投资在AI新产品上”，“今年计划至少翻倍”。Investing.com英文报道（2026-03-19）的说法是AI投入“effectively double”；官方演示材料措辞为“more than double”（S006，见口径漂移 D02）。"}},
    "evidence_add": [
        EV("PPT_4Q25", "2026-03-18", "事实（官方演示材料第11页）：2025年新AI产品成本及费用4Q25为70亿元、全年180亿元，范围为混元的人才、数据、训练及元宝的推理与营销，不含支持现有业务的AI投入及对外云GPU采购；“We expect to more than double investments in New AI Products in 2026”。"),
        EV("TR_Q4_25", "2026-03-18", "刘炽平：70亿元/180亿元“only for HunYuan and Yuanbao”，2026年将“more than double these investments in HunYuan, Yuanbao, and other new AI products”（2026年范围扩至其他新AI产品）。"),
        EV("REL_EN_1Q26", "2026-05-13", "事实（官方脚注）：剔除口径为“Excludes revenues, costs and expenses for new AI products (Hy, Yuanbao, CodeBuddy, WorkBuddy, and QClaw)”，即差额是收入抵减后的净影响。"),
        EV("TR_Q2_26", "2026-08-12", "James Mitchell 提到“RMB 8 billion in the first quarter”与“RMB 10.5 billion in the second quarter”；同场分析师引用的是约88亿元——文字稿的“8 billion”与推算值不一致，待官方录音复核。"),
    ],
    "psi": [
        S("公司演示材料", "Costs and expenses for our new AI products were RMB7 billion in 4Q25 and RMB18 billion in 2025", "PPT_4Q25", "2026-03-18", TXT("data/src/ir_official/4Q25_ppt.txt")),
        S("公司演示材料", "We expect to more than double investments in New AI Products in 2026", "PPT_4Q25", "2026-03-18", TXT("data/src/ir_official/4Q25_ppt.txt")),
        S("公司新闻稿脚注（1Q26）", "Excludes revenues, costs and expenses for new AI products (Hy, Yuanbao, CodeBuddy, WorkBuddy, and QClaw)", "REL_EN_1Q26", "2026-05-13", TXT("data/src/ir_official/1Q26_release_en.txt")),
        S("公司新闻稿脚注（2Q26）", "New AI products primarily consist of Hy, Yuanbao, CodeBuddy, WorkBuddy, and Xiaowei", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("刘炽平（Martin Lau）", "It will be a certain percentage of our profit", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "Yeah, you can assume there is an envelope at the back of our mind.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "we aggressively prioritized WorkBuddy while deprioritizing some of the other products in that new AI product portfolio", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "整体投入会控制在集团利润固定比例区间内，但如果能预判业务会产生巨额回报，我们会加大投入。", "SINA_Q2", "2026-08-12", WEB, "zh"),
    ],
    "confirm": "暂无已公开表述的六个方面（工具只标注，不建议口径）：(1) 差额的构成：共享算力折旧和成本如何在新老业务之间分摊；1Q26定义为剔除新AI产品“收入、成本及费用”，2Q26是否沿用同一定义。(2) 产品范围从QClaw换成小微后，有没有同口径重述。(3) 信封的具体比例或上限。(4) 全年AI投入是否超过3月“more than double”的口径；中文媒体“至少翻倍”、英文媒体“effectively double”与官方措辞不一（见 D02）；2025年180亿元为成本及费用（仅混元和元宝），与2026年差额口径不同（见 D05）。(5) Q3是否继续披露这个口径，什么时候退出。(6) 是否、如何回应券商150亿到160亿元的预测，由部门按既定流程决定。",
    "gap_ids": ["G02", "G03"],
    "v2_changes": ["补入 4Q25 演示材料与 1Q26 新闻稿的口径定义（S006）", "新增口径漂移 D02、D05", "删除“估值分歧点”表述"],
}

Q["Q03"] = {
    "rank": 3, "topics": ["MARGIN", "AI_ROI"],
    "why_now": "事实：10月9日到16日，花旗、大摩、瑞银、摩根大通相继发布Q3前瞻，下调或维持偏低的盈利预测（媒体转述/二手）；摩根大通把2027年EPS预测下调10%，大摩8月把2027年非IFRS经营利润预测下调12.3%。3月官方演示材料称“现有业务的利润增长应能覆盖新AI产品的增量投入”（S006），Q3是这一表述的检验点之一。Q2电话会上，大摩Gary Yu问过含AI的利润增速什么时候能超过剔除口径的增速，管理层没有给时间表。推断：如果券商预测兑现，Q3可能是本轮首次非IFRS利润同比下滑（研究员推断，不是券商原话）。",
    "evidence_replace": {
        1: {"source": "格隆汇：花旗Q3前瞻", "point": "券商观点：花旗预测Q3收入2089亿元（+8.3%）、非公认会计准则净利润640亿元（-9.2%）；文中称市场预期为收入2110亿元、净利润683亿元，但没有注明口径来源。"},
        2: {"point": "券商观点：瑞银预计Q3经调整净利润650亿元（-7%），经调整营业利润710亿元（-2%），原因是折旧增加和AI运营支出。"},
        3: {"source": "格隆汇：摩根大通Q3前瞻", "point": "券商观点：摩根大通将2026、2027年EPS预测分别下调2%和10%，认为AI回报需要更长时间、成本会提前出现。"},
        4: {"point": "券商观点：大摩把2026、2027年非IFRS经营利润预测分别下调1.8%和12.3%。"},
    },
    "evidence_add": [
        EV("PPT_4Q25", "2026-03-18", "事实（官方演示材料第11页）：“Increased profits from our existing businesses should more than cover incremental investments in these New AI Products”。"),
    ],
    "psi": [
        S("刘炽平（新浪中文整理稿）", "关于盈利时间指引，现阶段我们不会给出精确量化目标。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("刘炽平（Martin Lau）", "In terms of guidance, I do not think we are in the business of actually providing that specific guidance right now.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("公司演示材料", "Increased profits from our existing businesses should more than cover incremental investments in these New AI Products", "PPT_4Q25", "2026-03-18", TXT("data/src/ir_official/4Q25_ppt.txt")),
        S("公司新闻稿", "Operating margin excluding new AI products contributions increased to 42% from 39% last year.", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
    ],
    "confirm": "暂无已公开表述的四个方面（工具只标注，不建议口径）：(1) 如果Q3非IFRS利润同比下滑，是否、如何定性（投入期主动选择还是一次性因素）。(2) 3月“现有业务利润增长应能覆盖新AI产品增量投入”的表述是否仍适用。(3) 2027年利润增长有没有方向性判断；信封比例会不会随利润放缓而收紧。(4) 市场预期683亿元的来源和口径不明，是否回应券商或一致预期数字由部门按既定流程决定。",
    "gap_ids": ["G04", "G03"],
    "v2_changes": ["删除全部目标价表述", "补入 4Q25 演示材料“利润增长覆盖增量投入”表述（S006）"],
}

Q["Q04"] = {
    "rank": 4, "topics": ["CAPITAL", "AI_CAPEX"],
    "question_cn": "二季度自由现金流为-138亿元，净现金从一季度末的1469亿元降到582亿元，总债务4530亿元，环比增长17%；流动借款从年初的426亿元升到863亿元。继6月发债之后，10月票据（18亿美元加260亿元人民币，约合57亿美元）已于10月21日（纽约时间）完成发行。请问自由现金流什么时候恢复为正？下半年还会不会有大额算力预付款？刘炽平说的“审慎的债务能力”能不能量化，公司能否接受净负债？维持现有信用评级是不是硬约束？公告写的是“一般企业用途”，媒体则报道公司向投资者表示资金主要用于AI资本开支，这两种说法怎么理解？",
    "question_en": "FCF was negative RMB13.8bn in 2Q, net cash fell from RMB146.9bn to RMB58.2bn, and after the June deal you completed another US$1.8bn plus RMB26bn of notes on 21 October. When does FCF turn positive, should we expect more large compute prepayments in 2H, and can you quantify the 'prudent level of debt capacity' — would you accept net debt, and is keeping the A1/A+ ratings a binding constraint? How should we read 'general corporate purposes' in the filing versus reports that the proceeds are mainly for AI capex?",
    "why_now": "事实：10月14日定价公告，10月21日（纽约时间）完成发行，10月22日发布完成公告、上市通告及定价补充文件（港交所），Q3业绩会是发债后第一次业绩沟通。6月腾讯已发行近47亿美元债券（彭博，经21财经报道）。路透报道这批票据预计获得穆迪A1、标普A+评级。根据资产负债表计算，流动借款较年初翻倍。大摩认为短期资金缺口会用债务而不是股权来补（媒体转述/二手）。10月21日Meta披露单季自由现金流为-21.2亿美元（官方新闻稿）。推断：Q3的自由现金流和净现金，是对“现金流压力在Q2至Q3见顶”这一判断的第一次检验。",
    "evidence_add": [
        EV("HKEX_COMPLETION", "2026-10-22", "事实（港交所公告）：标题“COMPLETION OF US$1.8 BILLION AND CNY26 BILLION ISSUE OF NOTES UNDER THE GLOBAL MEDIUM TERM NOTE PROGRAMME”；正文称票据发行已于2026年10月21日（纽约时间）完成。"),
        EV("HKEX_TITLES", "2026-10-26", "事实（港交所标题检索）：2026-10-22 同日另有上市通告（07:40）及定价补充文件（12:03）。"),
        EV("LAUNCH", "2026-10-12", "事实（发债文件）：公司称现有现金及现金等价物、经营现金流和定期存款足以满足未来至少12个月的经营与资本开支需要。"),
        EV("PPT_3Q25", "2025-11-13", "事实（3Q25演示材料第21页，Q3同比基数）：3Q25自由现金流585亿元，总现金4933亿元，总债务3909亿元，净现金1024亿元。"),
    ],
    "psi": [
        S("公司新闻稿", "Excluding the prepayments for compute procurement, our free cash flow would have been RMB37.6 billion.", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("刘炽平（Martin Lau）", "It should be measured against how much cash we have on our balance sheet, how much investment portfolio we have on our balance sheet, and then the operating cash flow, and then a prudent level of debt capacity.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("公司公告（定价）", "The Company intends to use the net proceeds for general corporate purposes.", "PRICING", "2026-10-14", TXT("data/src/ir_official/2026-10-14_E700_Pricing-Announcement.txt")),
        S("公司公告（完成发行，标题）", "COMPLETION OF US$1.8 BILLION AND CNY26 BILLION ISSUE OF NOTES UNDER THE GLOBAL MEDIUM TERM NOTE PROGRAMME", "HKEX_COMPLETION", "2026-10-22", ("titles", "data/src/market_raw/nddr/list2026.json")),
        S("公司发债文件", "We believe that our existing cash and cash equivalents, cash flows from operations and term deposits will be sufficient to meet the anticipated cash needs for our operating activities and capital expenditures for at least the next 12 months.", "LAUNCH", "2026-10-12", TXT("data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt")),
    ],
    "confirm": "暂无已公开表述的七个方面（工具只标注，不建议口径）：(1) 自由现金流恢复为正的时间判断。(2) 下半年还有没有大额算力预付款。(3) “审慎债务能力”能不能量化，比如净负债/EBITDA的上限，能否接受净负债；中文媒体稿未出现“债务”一词（见 D04）。(4) 维持A级评级是否是约束条件。(5) 发债定位：期限匹配还是常态融资渠道；“一般企业用途”（公告）与“主要用于AI资本开支”（媒体转述）的关系（见 D03）。(6) 863亿元流动借款的再融资安排。(7) Q3末净现金的大致方向。",
    "gap_ids": ["G05", "G06"],
    "v2_changes": ["票据发行已完成（10-21），引用港交所完成公告", "补入 3Q25 同比基数（S005）"],
}

Q["Q05"] = {
    "rank": 6, "topics": ["AI_ROI", "CLOUD"],
    "evidence_add": [
        EV("TR_Q1_26", "2026-05-13", "James Mitchell：腾讯按组合和全生命周期管理产品，不以季度或12个月的回报目标约束单个新产品；投入广告技术的GPU回报周期较短，投入混元基础模型属于长期视角。"),
        EV("TR_Q1_26", "2026-05-13", "刘炽平：MaaS或算力出租类云收入“there's a clear ROI”（折旧成本加利润率）；模型训练是面向未来的投入，短期回报不明显。"),
    ],
    "psi": [
        S("公司演示材料", "clear downside protection as most of investment is in AI infrastructure, which we can choose to rent externally at attractive prices via Tencent Cloud if needed", "PPT_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_ppt.txt")),
        S("刘炽平（Martin Lau）", "today, we can actually sell that at more than 30% profit compared to the price that we paid just a few months ago.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "If we just switch the model to just renting out compute, it would be actually not loss-making, it would be profitable.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "We manage the portfolio, and we manage the products on a full life cycle basis.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("刘炽平（Martin Lau）", "If you look at the business revenue or the Cloud revenue in the sense of a MaaS or rental of compute, then there's a clear ROI, right?", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
    ],
    "gap_ids": ["G11"],
    "v2_changes": ["补入 1Q26 实录中的回报框架表述（S003）"],
}

Q["Q06"] = {
    "rank": 5, "topics": ["CAPITAL"], "sub_theme": "回购与股息",
    "question_cn": "Q2业绩后回购明显放缓：5月中旬至6月多数交易日约5亿港元，8月17日至28日约3亿港元/日，8月31日起约1亿港元/日；最后一笔在10月15日。按港交所翌日披露报表汇总，年内共96个交易日回购约6,827.67万股、合计约324.44亿港元（计算），约为2025年全年约800亿港元的四成。请问3月提出的“回购金额低于2025年、同时提高股息”的框架是否不变？全年回购有没有区间或下限？5月业绩会上管理层表示正加快投资组合变现、以支撑全年持续回购，8月又表示可能把更少现金用于回购——现在资本配置的优先级怎么排？资本开支上升之后，股息还会继续增长吗？",
    "question_en": "Daily buybacks fell from about HK$500m in May–June to about HK$300m in late August and about HK$100m from 31 August, with the last purchase on 15 October; HKEX next-day returns sum to about HK$32.4bn over 96 trading days year-to-date, roughly 40% of 2025's HK$80bn. Is the March framework — lower buybacks than 2025 but a higher dividend — still intact, and is there a range or floor for 2026? In May you talked about accelerating portfolio monetisation to sustain buybacks through the year; in August you said less cash might go to buybacks. How do you rank capital allocation priorities now, and will the dividend keep growing as capex rises?",
    "why_now": "事实：3月18日CFO表示2026年回购金额可能低于2025年、同时提高股息（S006演示材料第30页、S002文字稿）。5月13日James Mitchell称正加快投资组合变现，“sustain buybacks going through the rest of this year”（S003）。8月12日Mitchell称可能“less cash toward buybacks”（S004）。执行层面（计算，港交所翌日披露报表逐份汇总）：年内96个交易日、68,276,700股、约324.44亿港元，最后一笔在10月15日，10月16日至检索时未见新的回购报表。按上市规则第10.06(2)(e)条，业绩董事会（11-18）前30日内不得回购，【计算】规则窗口约从10月19日开始；10月15日后停止回购的原因公司未公开。10月21日完成约57亿美元等值发债；同日Meta披露三季度未进行股份回购（官方新闻稿现金流量表）。推断：“发债投AI、回购减少”的取舍会被追问。",
    "evidence_drop": [9],
    "evidence_replace": {
        0: {"point": "CFO罗硕瀚称2026年回购金额可能低于2025年，以支持AI投资，同时提高股息（媒体报道；原话见已公开表述索引，S002/S006）。"},
        3: {"point": "管理层称“现阶段也是开展股份回购的好时机”（媒体报道；英文原话见已公开表述索引，S003）。"},
        8: {"point": "10月13日回购约1.00亿港元；8月17日以来连续41日回购，合计61.15亿港元；年内共94次，合计6779.97万股、322.44亿港元（媒体统计；已用港交所翌日披露报表逐份复核一致，见本题计算项）。"},
    },
    "evidence_add": [
        EV("PPT_4Q25", "2026-03-18", "事实（官方演示材料第30页）：回购金额可能低于2025年、同时提高股息；建议2025年度股息每股5.30港元（同比+18%）。"),
        EV("TR_Q1_26", "2026-05-13", "James Mitchell（回答法巴William Packer）：将加大AI投入，但公司现金流强、投资组合规模大，正加快投资组合变现，以支撑全年持续回购。"),
        EV("TR_Q2_26", "2026-08-12", "James Mitchell（回答美银Alex Liu）：若算力回报更高，会把更多现金投向资本开支，“potentially less cash toward buybacks. It will be a dynamic situation.”"),
        EV("WSCN_FY25", "2026-03-18", "媒体转述（非直接引语）：刘炽平称去年因买不到“卡”在回购上花了较多钱，今年要是能买到“卡”，可能会适当减少回购、增加资本开支。"),
        EV("META_8K", "2026-10-21", "同业事实：Meta 2026年三季度未进行股份回购，派息及等价物13.6亿美元，自由现金流-21.2亿美元。"),
    ],
    "psi": [
        S("公司演示材料", "Given we see high return opportunities from investing in AI, we will likely buy back lower value of our shares versus 2025 to fund investment in AI, while increasing our dividends", "PPT_4Q25", "2026-03-18", TXT("data/src/ir_official/4Q25_ppt.txt")),
        S("罗硕瀚（John Lo）", "For the full year of 2025, we repurchased 153 million shares with a total consideration of HKD 80 billion.", "TR_Q4_25", "2026-03-18", TR("q4-2025")),
        S("James Mitchell", "We're accelerating the process of liquidizing some of that investment portfolio. That would enable us to sustain buybacks going through the rest of this year.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("James Mitchell", "at this point in time, we believe our share price is somewhat dislocated and, you know, therefore it's an opportune time for buybacks.", "TR_Q1_26", "2026-05-13", TR("q1-2026"),
          note="管理层原话，仅作出处索引；本材料不评论股价或估值。"),
        S("James Mitchell", "then we will steer more cash toward the capital expenditures than we had in the past, and therefore, potentially less cash toward buybacks. It will be a dynamic situation.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（华尔街见闻转述，非直接引语）", "今年要是能买到“卡”，可能就会适当减少股份回购，去增加资本开支", "WSCN_FY25", "2026-03-18", WEB, "zh"),
    ],
    "confirm": "暂无已公开表述的五个方面（工具只标注，不建议口径）：(1) 2026年全年回购有没有金额区间或下限。(2) 5月“加快投资组合变现、支撑全年持续回购”与8月“可能减少回购资金”如何衔接，以及Q2后回购节奏变化与发债、资本开支付款的关系（见 D06）。(3) 2026财年“提高股息”是否维持、幅度多少（3月只说了increasing）。(4) 投资组合变现的进展与用途。(5) 10月15日后停止回购的原因未公开；业绩后何时恢复是否对外说明，由部门按既定流程决定。",
    "gap_ids": ["G07", "G21"],
    "v2_changes": ["删除股价、市盈率表述", "回购合计改用 buybacks2026.json 复算（324.44 亿港元，截至 10-15）", "补入 S002/S003/S004/S006 四处回购表述，新增 D06"],
}

Q["Q07"] = {
    "rank": 7, "topics": ["AI_PRODUCTS", "CLOUD"],
    "evidence_replace": {5: {"point": "券商观点：高盛认为短期情绪要等混元、WorkBuddy、CodeBuddy和小微取得更多进展后才有望改善。"}},
    "evidence_add": [
        EV("QM_SINA", "2026-10-21", "第三方数据：QuestMobile称9月WorkBuddy月活3,235.3万，为典型办公Agent第一；AI办公赛道合计活跃用户1.42亿（各端直接相加、未跨端去重）。公司未披露用户数。", flags=["第三方、未去重"]),
        EV("TR_Q2_26", "2026-08-12", "James Mitchell：付费WorkBuddy用户与MaaS的毛利率已与腾讯云整体相当，整体毛利率偏低是因为补贴免费用户；现金收款正大幅爬坡，年内将转化为腾讯云报表收入。"),
    ],
    "psi": [
        S("马化腾（公司新闻稿）", "our WorkBuddy AI office productivity service and CodeBuddy AI coding tool are achieving breakout user growth and are the clear leaders in their fields in China today", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("公司新闻稿脚注", "Analysys, by monthly interactions among PC-based AI-native office agents in China, June 2026", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("James Mitchell", "From an accounting perspective, the majority of the WorkBuddy spending by users is on subscriptions.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "But we are seeing a substantial ramp in the cash receipts today, and that will translate into reported revenue growth for Tencent Cloud as we move through the year.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "If you look at the gross margin for the paying users of WorkBuddy, or you look at the gross margin for our models of service, then the gross margins today are already comparable to the gross margins for Tencent Cloud overall.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "confirm": "暂无已公开表述的量化口径（工具只标注，不建议口径）：用户数（DAU/MAU）、付费用户数、ARPU、留存率、WorkBuddy收入金额及其对腾讯云收入的贡献、合同负债中预收订阅的规模、整体毛利率收敛的时间表，目前都没有披露。第三方的“2000万”是访问量、QuestMobile的“3,235.3万”是未去重月活，均非公司口径；被引用时是否回应、如何回应需确认。",
    "gap_ids": ["G13"],
    "v2_changes": ["删除目标价表述", "新增 QuestMobile 第三方月活（10-20 发布，标注未去重）"],
}

Q["Q08"] = {
    "rank": 9, "topics": ["AI_PRODUCTS", "SOCIAL", "ADS", "REG"],
    "evidence_add": [
        EV("HUXIU_XW", "2026-10-18", "媒体体验报道：小微可在16处入口唤起；点单停在付款页、“AI帮写”停在待发表，支付和发布类不可撤销动作仍需用户手动确认。未找到官方扩大灰度的公告。"),
        EV("TR_Q2_26", "2026-08-12", "瑞银Kenneth Fong明确问到小微会否只是把小程序交易转移到算力成本更高的智能体、并压缩高毛利广告曝光；刘炽平以“all the risks that you said would not be relevant”整体回应，并用QQ到微信作类比，未单独展开广告库存。"),
        EV("TR_Q3_25", "2025-11-13", "刘炽平（一年前）：微信智能体的“blue sky scenario”是在微信内帮用户完成大量任务，当时处于很早期、尚未上线垂直智能体。"),
    ],
    "psi": [
        S("公司新闻稿", "In recent weeks, we have begun a small-scale prototype test for Xiaowei, the agentic AI inside Weixin.", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("刘炽平（Martin Lau）", "Xiaowei will be rolled out to broader user base in a phased approach", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "we currently configure Xiaowei to require user intervention and multiple step confirmations as safety measures", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "Well, I think all the risks that you said would not be relevant", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "I think for Xiaowei, the envelope of investment on the cost side would be less than what we actually invested in Yuanbao on an ongoing basis in the past let us say year.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "confirm": "暂无已公开表述的五个方面（工具只标注，不建议口径）：(1) 灰度用户规模（券商说“数千万”，公司没有确认）和全量时间表。(2) 商业化方式：交易佣金、广告还是支付。(3) AI专属卡的使用数据。(4) 隐私合规的公司正式口径，目前只有微信员工的个人回应。(5) 广告库存挤出：Q2会上分析师明确问及，刘炽平整体回应“all the risks that you said would not be relevant”，未单独展开，是否需要更具体的口径需确认。",
    "gap_ids": ["G14"],
    "v2_changes": ["补入 10-18 媒体体验报道", "更正：刘炽平对广告库存问题是“整体回应”而非“未回应”（S004 原文）"],
}

Q["Q09"] = {
    "rank": 8, "topics": ["CLOUD", "COMPUTE"],
    "evidence_replace": {5: {"point": "券商观点：美银预计腾讯云收入在下半年和明年进一步提速，受益于算力增加和WorkBuddy推广。"}},
    "evidence_add": [
        EV("YB_SEARCH", "2026-10-20", "事实（媒体报道）：元宝搜索完成升级，并通过腾讯云向个人开发者和企业开放（Skill、MCP、API三种接入），内部日均调用数亿次。"),
        EV("CONF_CHINADAILY", "2026-09-16", "事实：10月29日腾讯全球数字生态大会设10余场AI产品专场，含模型与MaaS、算力与云基座、Agent Infra。"),
    ],
    "psi": [
        S("James Mitchell", "our cloud revenue growth rate accelerated from high teens percentage year-on-year in the first quarter to low 20s percentage in the second quarter", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("公司演示材料", "AI-related demand translated into increased revenue across GPU rental, Model-as-a-Service, and WorkBuddy & CodeBuddy, although we are still compute constrained", "PPT_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_ppt.txt")),
        S("James Mitchell", "We increased prices across the board in May for Tencent Cloud, and beyond those headline price increases, we have also been more substantially reducing discounts.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "Then toward the end of the year and into next year, we will also have sufficient GPU ASIC capacity to step up in terms of Tencent Cloud renting out bare metal GPU or providing Model-as-a-Service.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "we think that it is token production for WorkBuddy that carries the most enduring economic value to us, and that's why we're prioritizing it today.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "confirm": "暂无已公开表述的六个方面（工具只标注，不建议口径）：(1) 云收入绝对值、毛利率、AI云占比，还是继续只给增速区间。(2) WorkBuddy收入的分部归属（没有找到公开说明），以及合同负债中的预收订阅。(3) MaaS/TokenHub和外部GPU出租的签约与收入。(4) 年底之后对外出租的比例。(5) 价格竞争对Token定价影响的公司口径。(6) 新浪实录标题写“不准备出租算力”，与正文及英文稿（年底到明年将加大裸金属GPU租赁和MaaS）不一致，对外以哪一版为准需确认。",
    "gap_ids": ["G12", "G19"],
    "v2_changes": ["删除评级与目标价表述", "补入元宝搜索经腾讯云开放（10-20）"],
}

Q["Q10"] = {
    "rank": 12, "topics": ["MARGIN", "AI_CAPEX"],
    "evidence_add": [
        EV("TR_Q3_25", "2025-11-13", "James Mitchell：产品早期成本计入研发、在毛利线以下；商业化后成本转入营业成本、进入毛利线以上——毛利率与经营利润率的季度波动部分来自这一归类变化。"),
    ],
    "psi": [
        S("James Mitchell", "we could recover the depreciation almost immediately by renting the compute out to third parties as many neo cloud businesses are doing.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("Mitchell（新浪中文整理稿）", "要知道，如果我们把算力租给第三方，几乎立刻就能收回设备折旧成本，现在很多新兴云厂商都是这么操作的，我们也能在短期内拿到不错的收益。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("James Mitchell", "As we actually make the product more widely available, commercialize the product, we would move the costs from R&D expense into cost of service and therefore above the gross profit line.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
    ],
    "gap_ids": ["G10"],
    "v2_changes": ["补入 3Q25 实录成本归类表述（S001）"],
}

Q["Q11"] = {
    "rank": 13, "topics": ["ADS"],
    "evidence_add": [
        EV("META_8K", "2026-10-21", "同业事实：Meta三季度广告收入630.6亿美元，同比+26%。"),
    ],
    "psi": [
        S("James Mitchell", "our advertising revenue growth has ticked up and ticked down in the past, and it will continue to tick up and tick down in the future. I would not straight-line extrapolate anything.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "they did contribute about 2 percentage points to the advertising segment revenue growth this quarter.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "the China consumer, and therefore advertising market, remains choppy and there are some economic or consumption headwinds that may have an impact on advertising trends.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("米歇尔（新浪中文整理稿）", "我们广告收入增速过去存在波动，未来也会持续起伏，不能简单线性推演增长趋势，背后有多重原因。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("公司新闻稿（中文）", "大部分主要行业本季在我们平台的营销投入均有所增加", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
    ],
    "confirm": "暂无已公开表述的三个方面（工具只标注，不建议口径）：(1) Q3是否继续披露手游内广告对营销服务增速的贡献，以及具体数值。(2) “跑赢大盘”能不能量化，还是只做定性表述。(3) 宏观压力在Q3具体落在哪些行业的投放上。公司不提供季度指引，是否给方向性表述需确认。",
    "gap_ids": ["G20"],
    "v2_changes": ["补入 S004 英文原话", "补入 Meta 广告增速作同业参照"],
}

Q["Q12"] = {
    "rank": 11, "topics": ["MODELS"],
    "why_now_append": "截至2026-10-26，未检索到Hy4正式版发布的报道（未找到不代表未发生）。",
    "psi": [
        S("刘炽平（Martin Lau）", "we are training a larger parameter model, Hunyuan 4, which we expect to release later this year.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（Martin Lau）", "I think that's the path, and Hunyuan 4 is only another stop. Then we'll be upgrading to Hunyuan 5.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("马化腾（公司新闻稿）", "Hy3's production version provides users a widely used model with strong cost-performance metrics, and serves as a stepping-stone toward the Hy family of models attaining state-of-the-art capabilities in the future", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
    ],
    "gap_ids": ["G15"],
    "v2_changes": ["刷新至 10-26：未检索到正式版发布"],
}

Q["Q13"] = {
    "rank": 14, "topics": ["COMPUTE", "REG", "AI_CAPEX"],
    "evidence_add": [
        EV("TR_Q4_25", "2026-03-18", "James Mitchell：新增算力来自三条渠道——租赁、重新可得的高端进口GPU、数量递增的国产GPU，并将在下半年加速到位。"),
        EV("TR_Q3_25", "2025-11-13", "刘炽平：2025年资本开支低于指引，“indeed a change in terms of the AI chip availability”。"),
    ],
    "psi": [
        S("James Mitchell", "You know, that additional compute comes from leasing capacity. It comes from us purchasing, higher-end imported GPUs which are now becoming available again, and it comes from us purchasing, the increasing quantity of, domestically China-designed, GPUs.", "TR_Q4_25", "2026-03-18", TR("q4-2025")),
        S("James Mitchell", "that's now being addressed because the China designed ASICs are seeing, you know, more supply from fabs within China as well as more supply from fabs in neighboring countries.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("公司演示材料", "although we are still compute constrained", "PPT_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_ppt.txt")),
        S("刘炽平（Martin Lau）", "It is indeed a change in terms of the AI chip availability.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
    ],
    "confirm": "暂无已公开表述的六个方面（工具只标注，不建议口径）：(1) 新增算力的芯片结构，披露到什么程度还是完全不披露。(2) 对H200到货和甲骨文租赁报道是否回应、如何回应（目前未找到腾讯回应）。(3) 美国如果管制远程访问，有什么预案、合规怎么表述。(4) 芯片和内存涨价对单位算力成本的影响。(5) “年末储备充足”的判断是否不变（口径演变见 D07）。(6) 预付款里芯片采购和算力租赁怎么拆分。",
    "gap_ids": ["G16"],
    "v2_changes": ["补入 3Q25/4Q25/1Q26 三季实录中的算力供给表述", "删除代拟回应口径"],
}

Q["Q14"] = {
    "rank": 16, "topics": ["AI_CAPEX", "CAPITAL", "COMPUTE"],
    "evidence_add": [
        EV("TR_Q4_25", "2026-03-18", "James Mitchell：CPU、内存、存储等供应已提前数月、数季甚至数年被预订，供应商优先保障最大、最稳定的客户。"),
    ],
    "psi": [
        S("公司新闻稿", "Included in our operating cash flow were large AI-related prepayments to provide infrastructure to support our Hy model enhancements, WorkBuddy and CodeBuddy inference needs, Weixin AI initiatives, and development of AI capabilities across our products and services, as well as to meet growing external demand for our cloud services.", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("刘炽平（Martin Lau）", "As a matter of fact, for the prepayment and for some of the compute orders that we had made just a couple of months ago, today, we can actually sell that at more than 30% profit compared to the price that we paid just a few months ago.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "now, the supply is booked out months, quarters, in some cases, years in advance.", "TR_Q4_25", "2026-03-18", TR("q4-2025")),
    ],
    "gap_ids": ["G09"],
    "v2_changes": ["补入 4Q25 实录供应链预订表述（S002）"],
}

Q["Q15"] = {
    "rank": 17, "topics": ["GAMES_DOM"],
    "evidence_add": [
        EV("TR_Q1_26", "2026-05-13", "James Mitchell：一季度游戏递延收入跃升，将在随后三个季度为报表收入提供顺风。"),
    ],
    "psi": [
        S("公司新闻稿（中文）", "主要游戏大部分都实现了收入增长", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
        S("James Mitchell", "for our game business, the jump in deferred revenue in the quarter provides us with a sort of tailwind to the reported revenue over the coming three quarters.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("James Mitchell", "the objective at this point is really, you know, faster content creation and incremental revenue generation. We're not prioritizing margin expansion per se.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
    ],
    "confirm": "暂无已公开表述的四个方面（工具只标注，不建议口径）：(1) Q3新游的官方表现口径，目前只有第三方数据。(2) 《洛克王国：世界》的生命周期口径。(3) 递延收入余额的变化，以及高基数下增速放缓的定性表述。(4) 1Q26所说递延收入跃升对随后三个季度报表收入的支撑，Q3是否仍适用。",
    "gap_ids": ["G20"],
    "v2_changes": ["补入 1Q26 实录递延收入表述（S003）"],
}

Q["Q16"] = {
    "rank": 21, "topics": ["FINTECH"],
    "evidence_add": [
        EV("TR_Q3_25", "2025-11-13", "罗硕瀚（3Q25同期）：线上支付量稳步增长，此前受压的线下支付量开始恢复，线上线下增速差距收窄。"),
    ],
    "psi": [
        S("公司新闻稿（中文）", "金融科技服务收入增长主要因为商业支付、理财及消费贷款服务收入的增长", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
        S("罗硕瀚（John Lo）", "The offline payment volume, which had been very suppressed and under pressure for a period of time, has also started to recover.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
    ],
    "gap_ids": ["G20"],
    "v2_changes": ["补入 3Q25 同期表述作基数参照（S001）"],
}

Q["Q17"] = {
    "rank": 18, "topics": ["MARGIN"],
    "evidence_add": [
        EV("PPT_4Q25", "2026-03-18", "事实（官方演示材料第11页）：“Existing businesses are resilient and will benefit from AI”。"),
    ],
    "psi": [
        S("公司新闻稿", "Operating margin excluding new AI products contributions increased to 42% from 39% last year.", "REL_EN_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_release_en.txt")),
        S("公司演示材料", "Existing businesses are resilient and will benefit from AI", "PPT_4Q25", "2026-03-18", TXT("data/src/ir_official/4Q25_ppt.txt")),
        S("刘炽平（Martin Lau）", "One is actually the existing core franchises, which actually generates solid growth and also with quite a bit of operating leverage.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "我们已经完整阐述了对 AI 业务、相关投入的整体判断，投入规模会设置上限，延续腾讯一贯稳健、有纪律的经营管理风格。", "SINA_Q2", "2026-08-12", WEB, "zh"),
    ],
    "gap_ids": ["G04", "G20"],
    "v2_changes": ["补入 S004/S006 原话"],
}

Q["Q18"] = {
    "rank": 20, "topics": ["GAMES_INTL"],
    "evidence_add": [
        EV("TR_Q3_25", "2025-11-13", "James Mitchell（3Q25同期）：当季国际游戏增速显著快于趋势线，原因是新收购工作室并表及《Dying Light: The Beast》买断制收入的前置确认——构成Q3高基数。"),
    ],
    "psi": [
        S("James Mitchell", "Adjusted to include Arrows and other in-app advertising game revenue in the prior year and current periods, our international games year-on-year revenue growth would have been 4 percentage points faster than the disclosed figures.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "That is because during the quarter, we had the benefit of consolidation of newly acquired or recently acquired game studios, as well as the benefit of the upfront revenue recognition on copy sales for the game Dying Light: The Beast.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        S("公司新闻稿（中文）", "受汇率波动影响同比下降0.8%，按固定汇率计算则同比增长4%", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
    ],
    "gap_ids": ["G20"],
    "v2_changes": ["补入 3Q25 实录基数原因（S001）与 2Q26 口径调整原话（S004）"],
}

Q["Q19"] = {
    "rank": 15, "topics": ["AI_PRODUCTS", "FINTECH"],
    "why_now": "事实：六周内连续三次重大发布（9月2日开放平台、9月3日金融版、10月14日企业微信深度打通）。大摩10月13日研报认为WorkBuddy由单一产品转向生态（媒体转述/二手）。Q2电话会上，伯恩斯坦Robin Zhu已追问WorkBuddy如何与模型厂商自有harness竞争。10月29日腾讯全球数字生态大会预告发布100多项面向Agent的新产品和能力、展示500余个案例（官方通稿写10月29日，腾讯云开发者社区文章写10月29-30日），距Q3业绩会约三周。推断：大会发布内容会成为业绩会的新追问素材。",
    "evidence_add": [
        EV("CONF_DEVCLOUD", "2026-10-13", "事实：腾讯云开发者社区前瞻文章写作10月29-30日，与官方通稿（10月29日）不一致，以官方为准。"),
    ],
    "psi": [
        S("刘炽平（Martin Lau）", "I think it is indeed a new platform. It's a very flexible workspace for agentic AI.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "我认为 WorkBuddy 本质是一个全新平台，是适配通用人工智能、高度灵活的工作台，核心价值是落地执行任务，能解决职场办公人群、各类个体经营者、小微企业从业者的全部生产力需求。", "SINA_Q2", "2026-08-12", WEB, "zh",
          note="中文稿“适配通用人工智能”与英文稿“workspace for agentic AI”措辞不同，属整理稿差异。"),
        S("刘炽平（Martin Lau）", "Then, of course, we are the orchestrator, right?", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "confirm": "暂无已公开表述（工具只标注，不建议口径）：企业客户数和付费席位、金融版的签约和收费模式、开放平台的分成比例、企微打通后的转化数据，目前都没有披露。对“模型厂商自建harness”的竞争问题，是否准备比Q2更具体的表述需确认。10月29日生态大会如发布新数据，是否在11月18日前并入业绩口径需确认。",
    "gap_ids": ["G13", "G19"],
    "v2_changes": ["刷新 10-29 大会预告与日期差异"],
}

Q["Q20"] = {
    "rank": 22, "topics": ["ADS", "SOCIAL", "MARGIN"],
    "evidence_add": [
        EV("TR_Q1_26", "2026-05-13", "James Mitchell：视频号广告加载率约4%-5%，为行业最低，仍有明显提升空间（非官方逐字稿，待录音复核）。"),
        EV("TR_Q3_25", "2025-11-13", "罗硕瀚（3Q25同期）：广告增长约一半（约10个百分点）来自eCPM提升，主要归因于AI广告技术和闭环；另一半来自曝光量增长。"),
    ],
    "psi": [
        S("James Mitchell", "factually our ad load on Video Accounts is still the lowest in the industry, at 4%-5%.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("罗硕瀚（John Lo）", "roughly half of the growth, or about 10 percentage points, was due to higher ECPM, which we attribute primarily to AI-supported ad tech as well as to closed-loop benefits.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        S("James Mitchell", "given we are early in the evolution toward more closed-loop advertising that drives much higher ad pricing", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("公司新闻稿（中文）", "得益于AI驱动的广告推荐模型的优化", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
    ],
    "confirm": "暂无已公开表述的五个方面（工具只标注，不建议口径）：(1) 视频号加载率：1Q26文字稿中管理层称约4%-5%、为行业最低（非官方逐字稿，待录音复核），Q2公开材料只有定性表述；是否更新数字需确认。(2) eCPM和曝光量各自的增幅（3Q25同期曾给出“约一半来自eCPM”）。(3) 闭环广告（小店、小游戏、短剧）的占比。(4) 搜一搜广告收入的趋势，Q2公开材料里没有找到相关表述。(5) AI折旧上升下营销服务毛利率的展望。",
    "gap_ids": ["G20"],
    "v2_changes": ["更正 v1“只有定性表述”：1Q26 实录给出 4%-5%（S003）", "补入 3Q25 eCPM 拆分（S001）"],
}

Q["Q21"] = {
    "rank": 24, "topics": ["AI_PRODUCTS"],
    "evidence_add": [
        EV("YB_SEARCH", "2026-10-20", "事实（媒体报道）：元宝搜索能力通过腾讯云对外开放，支撑WorkBuddy、ima、腾讯视频等50多个内部业务——与“原子能力”定位一致（推断）。"),
    ],
    "psi": [
        S("刘炽平（Martin Lau）", "Over time, functionalities developed and honed by Yuanbao can become atomic capabilities for use in other Tencent products such as WorkBuddy, CodeBuddy, Weixin, and QQ Browser.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "小微持续运营的年度投入预算，低于往年元宝的常态化投入规模，整体成本完全可控。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("James Mitchell", "we aggressively prioritized WorkBuddy while deprioritizing some of the other products in that new AI product portfolio", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "gap_ids": ["G15"],
    "v2_changes": ["补入元宝搜索开放（10-20）"],
}

Q["Q22"] = {
    "rank": 23, "topics": ["MODELS", "AI_PRODUCTS", "CLOUD"],
    "evidence_add": [
        EV("TNW_DEEPSEEK", "2026-10-23", "媒体报道（公司未证实）：彭博称腾讯为DeepSeek新一轮融资的最大投资方之一，见Q28。", flags=["公司未证实"]),
    ],
    "psi": [
        S("刘炽平（Martin Lau）", "And Hunyuan will be one of the models that will be provided by WorkBuddy.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("刘炽平（新浪中文整理稿）", "混元会是 WorkBuddy 搭载的大模型之一。", "SINA_Q2", "2026-08-12", WEB, "zh"),
        S("James Mitchell", "But an important secondary use case is providing inference for the use of Hunyuan models as well as DeepSeek and other models behind WorkBuddy.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "gap_ids": ["G13", "G17"],
    "v2_changes": ["与新增 Q28（DeepSeek 融资报道）联动"],
}

Q["Q23"] = {
    "rank": 25, "topics": ["PORTFOLIO", "CAPITAL"],
    "question_cn": "6月末上市投资公允价值约4872亿元，较3月末5471亿元减少约600亿元，较2025年9月末约8010亿元下降约39%（计算）；7月公司出售约2.73亿股快手，持股降到9.37%。5月业绩会上管理层称正加快投资组合变现、以支撑全年回购。净现金下降、AI又需要资金，公司会不会继续加快投资组合变现（出售或实物分派）来支持资本开支或回购？对腾讯音乐等上市投资公司有什么规划？",
    "evidence_add": [
        EV("PPT_3Q25", "2025-11-13", "事实（3Q25演示材料第21页）：截至2025-09-30，上市投资公司（不含附属公司）权益公允价值约8010亿元人民币（1130亿美元）。"),
        EV("PPT_2Q26", "2026-08-12", "事实（2Q26演示材料第26页）：截至2026-06-30约4870亿元人民币（720亿美元）。【计算】较2025年9月末下降约39%。", label="计算"),
        EV("TR_Q1_26", "2026-05-13", "James Mitchell：正加快投资组合变现，以支撑全年回购。"),
        EV("TR_Q3_25", "2025-11-13", "James Mitchell（3Q25）：利用市场活跃更积极地循环投资组合，年初至今减持超过投资逾10亿美元；同时投资中国的AI初创公司。"),
    ],
    "psi": [
        S("James Mitchell", "We're accelerating the process of liquidizing some of that investment portfolio.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
        S("James Mitchell", "Overall, year to date, divestments have exceeded investments by over $1 billion.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        S("刘炽平（Martin Lau）", "how much investment portfolio we have on our balance sheet", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("公司演示材料", "As at 30 Sep 2025, the fair value of our shareholdings1 in listed investee companies (excluding subsidiaries) was ~RMB801 billion", "PPT_3Q25", "2025-11-13", TXT("data/src/ir_official/3Q25_ppt.txt")),
        S("公司演示材料", "As at 30 Jun 2026, the fair value of our shareholdings1 in listed investee companies (excluding subsidiaries) was ~RMB487", "PPT_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_ppt.txt")),
    ],
    "confirm": "暂无已公开表述的五个方面（工具只标注，不建议口径）：(1) 快手减持所得的用途，以及在Q3的会计处理和处置损益。(2) 投资组合变现有没有计划或原则，是出售还是实物分派。(3) 对腾讯音乐持股和战略定位的表述。(4) 快手持股下降、不再是主要股东之后，对“分占联营公司盈利”口径的影响。(5) 5月所称“accelerating the process of liquidizing”的进展。",
    "gap_ids": ["G21"],
    "v2_changes": ["补入 S001/S003/S005/S008 四处投资组合表述与数据"],
}

Q["Q24"] = {
    "rank": 26, "topics": ["SOCIAL"],
    "psi": [
        S("公司新闻稿（中文）", "社交网络收入同比增长0.8%至人民币325亿元", "REL_ZH_2Q26", "2026-08-12", PZH("data/src/ir_official/2Q26_release_zh.pdf"), "zh"),
        S("James Mitchell", "partially offset by decreased revenue from long-form video subscriptions, where revenue decreased 6% year-on-year.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        S("James Mitchell", "Audio subscription revenue increased 8%, driven by higher music ARPU and enriched content stemming from the inclusion of Ximalaya.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
    ],
    "gap_ids": ["G20"],
    "v2_changes": ["长视频 -6% 改为引用 S004 原话（v1 为纪要转述）"],
}

Q["Q25"] = {
    "rank": 27, "topics": ["REG", "GAMES_DOM", "AI_PRODUCTS"],
    "why_now_append": "10-19至10-26未检索到针对腾讯的新监管动作或10月版号批次（“未检索到”不代表未发生）。",
    "psi": [
        S("公司演示材料", "Moats arise from network effects, depth and value added along supply chain, IP, low take rates, regulatory requirements and private data.", "PPT_2Q26", "2026-08-12", TXT("data/src/ir_official/2Q26_ppt.txt"),
          note="仅说明管理层把监管要求列为护城河之一；未找到针对2026年AI监管新规、约谈或版号的公开表态。"),
    ],
    "gap_ids": ["G22"],
    "v2_changes": ["原 Investing.com 出处改为官方演示材料原文（S008）"],
}

Q["Q26"] = {
    "rank": 28, "topics": ["REG"],
    "evidence_add": [
        EV("FR_1260H", "2026-06-10", "事实（美国《联邦公报》原文，本地副本）：条目写明“Tencent is indirectly affiliated with the PLA (Section 1260H(g)(2)(B)(i)(I))”。仅陈述清单内容，不作判断。"),
    ],
    "psi": [
        S("腾讯自愿公告（经新浪财经报道）", "被列入1260H清单仅与美国国防采购事宜相关", "https://finance.sina.com.cn/jjxw/2025-01-07/doc-ineeeanv7990003.shtml", "2025-01-07", None, "zh"),
    ],
    "gap_ids": ["G16"],
    "v2_changes": ["补入联邦公报原文（一手）"],
}

# ---------------------------------------------------------------- 新增题目
NEW_QUESTIONS = [
    {
        "id": "Q27", "rank": 10, "theme": "AI投入与财务回报", "topics": ["AI_CAPEX", "AI_ROI", "CAPITAL", "ADS"],
        "sub_theme": "海外同业类比：Meta Q3（10-21）对腾讯的潜在追问",
        "question_cn": "Meta三季度广告收入同比增长26%，管理层称AI投资正在见效；同时单季资本开支349亿美元、自由现金流转负（-21亿美元）、当季没有回购，并宣布设立无投票权C类股（官方新闻稿列明用途包括融资、员工薪酬、潜在并购等）。腾讯同样处在“广告较快增长、资本开支大增、自由现金流承压”的阶段：管理层如何看待两者在投入强度（资本开支/收入、资本开支/经营现金流）、资金来源（发债还是股权）和股东回报取舍上的异同？腾讯广告增长中有多少可以归因于AI？",
        "question_en": "Meta grew ad revenue 26% in 3Q and says its AI investments are paying off, yet capex was US$34.9bn, FCF turned negative, it bought back no stock and is creating a non-voting Class C stock that it says can be used for capital raising, employee compensation and acquisitions. Tencent is in a similar phase — fast ad growth, surging capex, pressured FCF. How do you compare on capex intensity, funding (debt vs equity) and shareholder returns, and how much of your ad growth do you attribute to AI?",
        "why_now": {"text": "事实：Meta于10-21发布三季度业绩（官方新闻稿）：收入646.0亿美元（+26%），资本开支349.1亿美元，自由现金流-21.2亿美元，三季度未回购，2026年资本开支指引收窄为1350亿至1450亿美元，并宣布设立无投票权C类股（2027年1月生效）。【计算】腾讯2Q26资本开支/收入约25.8%，Meta 3Q26约54.0%。用户提供的1Q26实录显示，瑞银Kenneth Fong曾以“全球同业把80%到100%经营现金流投入AI资本开支、腾讯约35%”发问；2Q26实录中高盛Ronald Keung也以美国同业的策略变化提问。推断：10-28/29前后微软、谷歌、亚马逊相继发布后，海外同业类比追问概率上升（日期以 M1 模块核实为准）。",
                    "label": "推断", "src": ["META_8K", "FORTUNE_META", "PPT_2Q26", "TR_Q1_26", "TR_Q2_26"]},
        "evidence": [
            EV("META_8K", "2026-10-21", "同业事实：收入646.0亿美元（+26%），广告收入630.6亿美元（+26%）；资本开支（含融资租赁本金）349.1亿美元；自由现金流-21.2亿美元；三季度无股份回购；2026年资本开支指引1350亿至1450亿美元（原1300亿至1450亿美元）。"),
            EV("FORTUNE_META", "2026-10-21", "媒体报道：Meta计划设立无投票权C类股，用于AI建设、员工股权激励和并购；扎克伯格称“Our investments are paying off”。", flags=["媒体转述/二手"]),
            EV("PPT_2Q26", "2026-08-12", "事实：腾讯2Q26总资本开支528亿元，收入2048亿元（REL_EN_2Q26）。【计算】资本开支/收入约25.8%。", label="计算"),
            EV("TR_Q1_26", "2026-05-13", "瑞银Kenneth Fong提问：全球同业把80%到100%的经营现金流投入AI资本开支，腾讯上季度约35%，能否给更量化的AI资本开支指引。"),
            EV("TR_Q3_25", "2025-11-13", "罗硕瀚（3Q25）：广告增长约一半来自eCPM提升，主要归因于AI广告技术和闭环。"),
        ],
        "frequency": 3, "sensitivity": 4,
        "psi": [
            S("刘炽平（Martin Lau）", "We're comfortable in making significant investments in AI because not only there is a substantial upside potential, there is also clear downside protection.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
            S("James Mitchell", "You know, we have not got there by limiting each new product, each new service, to, you know, very, near term quantitative, you know, return on investment targets.", "TR_Q1_26", "2026-05-13", TR("q1-2026")),
            S("罗硕瀚（John Lo）", "roughly half of the growth, or about 10 percentage points, was due to higher ECPM, which we attribute primarily to AI-supported ad tech as well as to closed-loop benefits.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
        ],
        "confirm": "暂无已公开表述（工具只标注，不建议口径）：(1) 被要求与海外同业比较投入强度、融资方式和股东回报时，是否回应、如何回应。(2) 广告增长中AI贡献是否继续给出拆分（3Q25同期曾称约一半来自eCPM）。(3) 是否存在股权融资选项的任何表述需求（目前未找到相关公开表述）。",
        "gap_ids": ["G18", "G07"],
        "v2_changes": ["v2 新增（Meta 10-21 发布后）"],
    },
    {
        "id": "Q28", "rank": 19, "theme": "股东回报、资本结构与监管", "topics": ["PORTFOLIO", "MODELS", "REG"],
        "sub_theme": "DeepSeek 融资报道（公司未证实）",
        "question_cn": "据彭博10月22日报道（经TNW转述，公司未证实），DeepSeek完成约1000亿元人民币融资，腾讯为最大投资方之一。如果属实，这笔投资与自研混元、WorkBuddy接入DeepSeek模型之间是什么关系？投资金额、会计处理和对资本开支预算有没有影响？在美国国土安全部10月20日要求联邦机构停止采购DeepSeek产品的背景下，是否带来额外的地缘或合规考量？",
        "question_en": "Bloomberg reported on 22 October that DeepSeek raised about RMB100bn with Tencent among the largest investors; this has not been confirmed. If accurate, how does it fit with Hunyuan and with WorkBuddy already serving DeepSeek models, what is the size and accounting treatment, and does the US DHS procurement ban on DeepSeek products raise any additional considerations?",
        "why_now": {"text": "事实（媒体报道，公司未证实）：TNW 10-23转引彭博10-22报道，DeepSeek完成约1000亿元人民币（约150亿美元）融资，宁德时代与腾讯为最大投资方之一；DeepSeek未确认，报道未提及腾讯回应。两天前（10-20）美国国土安全部要求联邦机构停止采购DeepSeek产品。2Q26实录显示WorkBuddy的推理算力同时服务混元和DeepSeek等模型；3Q25实录中管理层称在积极投资中国AI初创公司。推断：如有分析师提问，会落在“投资与自研的关系”和地缘风险两点。",
                    "label": "推断", "src": ["TNW_DEEPSEEK", "TR_Q2_26", "TR_Q3_25"]},
        "evidence": [
            EV("TNW_DEEPSEEK", "2026-10-23", "媒体报道：DeepSeek据报完成约1000亿元人民币融资，宁德时代与腾讯为最大投资方之一；TNW未独立核实，DeepSeek未确认；同时提到美国国土安全部10-20要求联邦机构停止采购DeepSeek产品。", flags=["媒体转述/二手", "公司未证实"]),
            EV("TR_Q2_26", "2026-08-12", "James Mitchell：资本开支的重要次要用途是为WorkBuddy背后的混元、DeepSeek及其他模型提供推理。"),
            EV("TR_Q3_25", "2025-11-13", "James Mitchell（3Q25）：一直在积极投资一些有意思的AI初创公司，尤其在中国。"),
        ],
        "frequency": 2, "sensitivity": 5,
        "psi": [
            S("James Mitchell", "We have been actively investing in some interesting AI startups, particularly in China, where we can see a sort of new wave of value creation ahead.", "TR_Q3_25", "2025-11-13", TR("q3-2025")),
            S("James Mitchell", "But an important secondary use case is providing inference for the use of Hunyuan models as well as DeepSeek and other models behind WorkBuddy.", "TR_Q2_26", "2026-08-12", TR("q2-2026")),
        ],
        "no_statement_note": "未找到腾讯就 DeepSeek 融资报道的公开回应。",
        "confirm": "暂无已公开表述（工具只标注，不建议口径）：(1) 对未证实的投资报道是否回应、如何回应。(2) 如属实，金额、会计处理与披露时点。(3) 与混元自研和WorkBuddy多模型策略的关系。(4) 美国对DeepSeek的采购限制是否需要在合规层面准备表述。",
        "gap_ids": ["G17"],
        "v2_changes": ["v2 新增（彭博 10-22 报道）"],
    },
]

# ---------------------------------------------------------------- 口径漂移
DRIFT = [
    {"id": "D01", "type": "整理稿/翻译口径差异", "title": "“封顶” vs “回报好才继续投”", "topics": ["AI_CAPEX", "AI_ROI"],
     "sides": [
         {"side": "中文媒体整理稿", "speaker": "刘炽平", "text": "如果回报不及预期，现有投入规模就会封顶。", "src": "SINA_Q2", "date": "2026-08-12", "verify": WEB, "lang": "zh"},
         {"side": "英文第三方文字稿", "speaker": "Martin Lau", "text": "We will only keep on investing if it generates a great return. If not, then this is actually the amount that we are going to be investing, then the additional investment in CapEx would actually be tied to what kind of returns that we will be generating from that business.", "src": "TR_Q2_26", "date": "2026-08-12", "verify": TR("q2-2026"), "lang": "en"},
     ],
     "observation": "中文稿用“封顶”强调上限；英文稿强调“增量投入与回报挂钩”，全文未出现 cap/capped 一词（脚本计数见 computed）。两者都不是官方逐字稿。",
     "label": "推断", "related": ["Q01", "Q05"], "gap_id": "G08"},
    {"id": "D02", "type": "媒体转述与官方措辞差异", "title": "“至少翻倍” vs “effectively double”（官方为“more than double”）", "topics": ["AI_ROI", "AI_PRODUCTS"],
     "sides": [
         {"side": "中文媒体", "speaker": "刘炽平（媒体转述）", "text": "今年计划至少翻倍。", "src": "WSCN_FY25", "date": "2026-03-18", "verify": WEB, "lang": "zh"},
         {"side": "英文媒体", "speaker": "Martin Lau（媒体转述）", "text": "will effectively double its investment in AI in 2026", "src": "INV_FY25", "date": "2026-03-19", "verify": WEB, "lang": "en"},
         {"side": "官方演示材料", "speaker": "公司", "text": "We expect to more than double investments in New AI Products in 2026", "src": "PPT_4Q25", "date": "2026-03-18", "verify": TXT("data/src/ir_official/4Q25_ppt.txt"), "lang": "en"},
         {"side": "英文第三方文字稿", "speaker": "Martin Lau", "text": "We expect to more than double these investments in HunYuan, Yuanbao, and other new AI products in 2026", "src": "TR_Q4_25", "date": "2026-03-18", "verify": TR("q4-2025"), "lang": "en"},
     ],
     "observation": "官方措辞“more than double”与中文“至少翻倍”方向一致；英文媒体“effectively double”弱化了“超过”。另：基数180亿元在官方材料中是“成本及费用”（仅混元和元宝），媒体写作“投资/spent on the technology”，对象范围也被放大为“AI投入”。",
     "label": "推断", "related": ["Q02"], "gap_id": "G03"},
    {"id": "D03", "type": "公司公告与媒体转述差异", "title": "“一般企业用途” vs “主要用于AI资本开支”", "topics": ["CAPITAL", "AI_CAPEX"],
     "sides": [
         {"side": "港交所定价公告", "speaker": "公司", "text": "The Company intends to use the net proceeds for general corporate purposes.", "src": "PRICING", "date": "2026-10-14", "verify": TXT("data/src/ir_official/2026-10-14_E700_Pricing-Announcement.txt"), "lang": "en"},
         {"side": "中文媒体（转财联社）", "speaker": "媒体转述", "text": "另外，腾讯向投资者表示，债券资金主要用于人工智能 资本开支。", "src": "J21_BOND", "date": "2026-10-14", "verify": WEB, "lang": "zh"},
     ],
     "observation": "公告是法定口径；“主要用于AI资本开支”是媒体对路演沟通的转述，标题进一步写作“巨额资金投向AI资本开支”。10-22完成公告未见用途的新表述（仅核对标题）。",
     "label": "推断", "related": ["Q04"], "gap_id": "G06"},
    {"id": "D04", "type": "整理稿/翻译口径差异", "title": "“a prudent level of debt capacity” vs “维持稳健可控的投入规模”", "topics": ["CAPITAL"],
     "sides": [
         {"side": "英文第三方文字稿", "speaker": "Martin Lau", "text": "and then the operating cash flow, and then a prudent level of debt capacity", "src": "TR_Q2_26", "date": "2026-08-12", "verify": TR("q2-2026"), "lang": "en"},
         {"side": "中文媒体整理稿", "speaker": "刘炽平", "text": "这笔一次性算力投入的资金来源，不能只看经营性现金流，还要综合资产负债表现金储备、投资资产规模、新增经营现金流，维持稳健可控的投入规模，以上维度会共同决定前期算力投入的资金安排。", "src": "SINA_Q2", "date": "2026-08-12", "verify": WEB, "lang": "zh"},
     ],
     "observation": "英文稿明确把“债务能力”列为资金来源之一；中文稿没有出现“债务/举债”。10月发债后，这一差异更容易被引用。",
     "label": "推断", "related": ["Q04"], "gap_id": "G08"},
    {"id": "D05", "type": "口径范围变化", "title": "新AI产品口径：180亿元（2025成本及费用）vs 88亿/105亿元（2026剔除口径差额）", "topics": ["AI_ROI", "MARGIN"],
     "sides": [
         {"side": "4Q25官方演示材料", "speaker": "公司", "text": "Costs and expenses for our new AI products were RMB7 billion in 4Q25 and RMB18 billion in 2025", "src": "PPT_4Q25", "date": "2026-03-18", "verify": TXT("data/src/ir_official/4Q25_ppt.txt"), "lang": "en"},
         {"side": "1Q26官方新闻稿脚注", "speaker": "公司", "text": "Excludes revenues, costs and expenses for new AI products (Hy, Yuanbao, CodeBuddy, WorkBuddy, and QClaw)", "src": "REL_EN_1Q26", "date": "2026-05-13", "verify": TXT("data/src/ir_official/1Q26_release_en.txt"), "lang": "en"},
         {"side": "2Q26官方新闻稿脚注", "speaker": "公司", "text": "New AI products primarily consist of Hy, Yuanbao, CodeBuddy, WorkBuddy, and Xiaowei", "src": "REL_EN_2Q26", "date": "2026-08-12", "verify": TXT("data/src/ir_official/2Q26_release_en.txt"), "lang": "en"},
         {"side": "英文第三方文字稿", "speaker": "James Mitchell", "text": "If you look at where the RMB 8 billion in the first quarter flowed in terms of user acquisition spending and so forth, and which products it supported, versus where the RMB 10.5 billion in the second quarter flowed", "src": "TR_Q2_26", "date": "2026-08-12", "verify": TR("q2-2026"), "lang": "en"},
     ],
     "observation": "2025年180亿元是毛额“成本及费用”且仅含混元、元宝；2026年差额按1Q26定义是剔除“收入、成本及费用”后的净影响，产品范围逐季变化（QClaw→小微）。上半年两季差额合计约193亿元（推算）不能直接与180亿元比较。文字稿“RMB 8 billion”与推算的约88亿元不一致，待录音复核。",
     "label": "推断", "related": ["Q02", "Q17"], "gap_id": "G02"},
    {"id": "D06", "type": "表述与执行对照", "title": "回购：3月“少于2025” → 5月“支撑全年持续回购” → 8月“可能减少” → 10-15后无回购", "topics": ["CAPITAL"],
     "sides": [
         {"side": "4Q25官方演示材料", "speaker": "公司", "text": "we will likely buy back lower value of our shares versus 2025 to fund investment in AI, while increasing our dividends", "src": "PPT_4Q25", "date": "2026-03-18", "verify": TXT("data/src/ir_official/4Q25_ppt.txt"), "lang": "en"},
         {"side": "1Q26英文第三方文字稿", "speaker": "James Mitchell", "text": "That would enable us to sustain buybacks going through the rest of this year.", "src": "TR_Q1_26", "date": "2026-05-13", "verify": TR("q1-2026"), "lang": "en"},
         {"side": "2Q26英文第三方文字稿", "speaker": "James Mitchell", "text": "and therefore, potentially less cash toward buybacks. It will be a dynamic situation.", "src": "TR_Q2_26", "date": "2026-08-12", "verify": TR("q2-2026"), "lang": "en"},
     ],
     "execution_ref": "BUYBACK_COMPUTED",
     "observation": "三次表述侧重点不同（年度总量、年内持续性、边际资金分配），执行数据见 computed（按月金额、最后一笔日期）。是否矛盾不作判断，衔接方式由部门按既定流程决定。",
     "label": "推断", "related": ["Q06", "Q23"], "gap_id": "G07"},
    {"id": "D07", "type": "实质变化（非措辞漂移）", "title": "GPU：“内部够用”（3Q25）→“仍受算力约束”（2Q26）→“年底到明年充足”", "topics": ["COMPUTE", "CLOUD"],
     "sides": [
         {"side": "3Q25英文第三方文字稿", "speaker": "文字稿标注为 Pony Ma（归属待录音复核）", "text": "All our GPUs are actually sufficient for our internal use.", "src": "TR_Q3_25", "date": "2025-11-13", "verify": TR("q3-2025"), "lang": "en"},
         {"side": "1Q26英文第三方文字稿", "speaker": "James Mitchell", "text": "For Tencent Cloud, you know, where, until now we actually haven't had sufficient GPUs to begin to service the external demand", "src": "TR_Q1_26", "date": "2026-05-13", "verify": TR("q1-2026"), "lang": "en"},
         {"side": "2Q26官方演示材料", "speaker": "公司", "text": "although we are still compute constrained", "src": "PPT_2Q26", "date": "2026-08-12", "verify": TXT("data/src/ir_official/2Q26_ppt.txt"), "lang": "en"},
         {"side": "2Q26英文第三方文字稿", "speaker": "James Mitchell", "text": "toward the end of the year and into next year, we will also have sufficient GPU ASIC capacity", "src": "TR_Q2_26", "date": "2026-08-12", "verify": TR("q2-2026"), "lang": "en"},
     ],
     "observation": "3Q25所称“够用”限定为内部使用，同时承认对外云收入受限；此后需求上升（WorkBuddy、训练更大模型），表述转为“仍受约束、年底到明年充足”。属需求变化导致的实质变化，不是同一事实的措辞差异。Q3业绩会临近“年底”时点，可能被追问是否如期。",
     "label": "推断", "related": ["Q13", "Q09"], "gap_id": "G16"},
]

# ---------------------------------------------------------------- 暂无已公开表述事项（可导出）
GAPS = [
    {"id": "G01", "priority": "P0", "topics": ["AI_CAPEX"], "title": "资本开支量级与三套口径",
     "items": "2026、2027年资本开支是否给数字区间或量级；“今明两年集中投入”的时间边界与之后的常态水平；会计口径（上半年847亿元）、现金支付口径（发债文件：上半年963亿元、2025全年883亿元）、季度资本开支付款（Q2为593亿元）的对外解释。",
     "questions": ["Q01", "Q14"], "src": ["IR26", "LAUNCH", "REL_EN_2Q26"]},
    {"id": "G02", "priority": "P0", "topics": ["AI_ROI", "MARGIN"], "title": "“剔除新AI产品”口径的定义与可比性",
     "items": "1Q26定义为剔除新AI产品“收入、成本及费用”，2Q26脚注只列产品范围（QClaw→小微）：定义是否一致、有无同口径重述；共享算力折旧如何分摊；2025年180亿元（成本及费用，仅混元和元宝）与2026年差额（净影响）不可直接比较，对外如何说明；Q3是否继续披露、何时退出。",
     "questions": ["Q02", "Q17"], "src": ["PPT_4Q25", "REL_EN_1Q26", "REL_EN_2Q26"], "drift": ["D05"]},
    {"id": "G03", "priority": "P0", "topics": ["AI_ROI"], "title": "投入信封与全年AI预算",
     "items": "“集团利润一定比例”的具体比例或上限；全年投入是否超过3月“more than double”；中文“至少翻倍”、英文媒体“effectively double”与官方措辞不一，对外以官方措辞为准是否需要主动澄清。",
     "questions": ["Q02", "Q03"], "src": ["PPT_4Q25", "TR_Q2_26", "WSCN_FY25", "INV_FY25"], "drift": ["D02"]},
    {"id": "G04", "priority": "P0", "topics": ["MARGIN"], "title": "Q3利润同比下滑时的定性与是否回应券商预测",
     "items": "如Q3非IFRS利润同比下滑，是否、如何定性；3月“现有业务利润增长应能覆盖新AI产品增量投入”是否仍适用；是否回应券商（花旗-9.2%、瑞银-7%、大摩经营利润-3.1%，媒体转述/二手）或来源不明的一致预期683亿元。",
     "questions": ["Q03", "Q17"], "src": ["PPT_4Q25"]},
    {"id": "G05", "priority": "P0", "topics": ["CAPITAL"], "title": "自由现金流、净现金与杠杆边界",
     "items": "自由现金流转正的时间判断；下半年是否还有大额算力预付款；“a prudent level of debt capacity”能否量化（如净负债/EBITDA上限）、能否接受净负债；维持A级评级是否为约束；863亿元流动借款的再融资；Q3末净现金方向。",
     "questions": ["Q04"], "src": ["REL_EN_2Q26", "TR_Q2_26", "LAUNCH"], "drift": ["D04"]},
    {"id": "G06", "priority": "P0", "topics": ["CAPITAL", "AI_CAPEX"], "title": "发债用途口径",
     "items": "公告“一般企业用途”与媒体“主要用于人工智能资本开支”的关系是否需要澄清；10月票据（已于10-21完成）是期限匹配还是常态融资渠道；年内6月已发过债，10月不是首次。",
     "questions": ["Q04"], "src": ["PRICING", "J21_BOND", "HKEX_COMPLETION"], "drift": ["D03"]},
    {"id": "G07", "priority": "P0", "topics": ["CAPITAL"], "title": "回购与股息",
     "items": "全年回购金额区间或下限；3月“少于2025”、5月“支撑全年持续回购”、8月“可能减少回购资金”与执行数据（10-15后无回购，年内约324.44亿港元）如何衔接；停止原因未公开，业绩后何时恢复是否对外说明；2026财年“提高股息”的幅度。",
     "questions": ["Q06", "Q27"], "src": ["PPT_4Q25", "TR_Q1_26", "TR_Q2_26", "BB_JSON"], "drift": ["D06"]},
    {"id": "G08", "priority": "P0", "topics": ["AI_CAPEX", "CAPITAL"], "title": "引语复核与中英文整理稿差异（程序性）",
     "items": "本雷达引用的管理层原话多数来自第三方文字稿（StockAnalysis）或媒体整理稿（新浪），官方只提供webcast；凡拟在业绩材料或问答口径中引用的原话，需先以官方录音复核。已发现中英文整理稿差异：“封顶”（D01）、“债务能力”（D04）；文字稿发言人标注存在错误（如2Q26第39条“Speaker 12”实为大摩Gary）。",
     "questions": ["Q01", "Q04"], "src": ["SINA_Q2", "TR_Q2_26"], "drift": ["D01", "D04"]},
    {"id": "G09", "priority": "P1", "topics": ["AI_CAPEX", "COMPUTE"], "title": "预付款与表外承诺",
     "items": "二季度算力预付款确切金额（目前只能推算约514亿元）；转成固定资产与开始折旧的时间表；中期报告附注35“其他承诺”2801亿元的构成和期限；是否为锁定内存价格做过预付（仅有券商二手纪要）。",
     "questions": ["Q14"], "src": ["IR26", "REL_EN_2Q26"]},
    {"id": "G10", "priority": "P1", "topics": ["MARGIN"], "title": "折旧与成本",
     "items": "折旧增速方向；GPU和服务器折旧年限政策是否不变；技术基础设施运营成本（152亿元）中外租算力占比；成本在研发与营业成本之间的归类变化对毛利率的影响。",
     "questions": ["Q10"], "src": ["IR26", "TR_Q3_25"]},
    {"id": "G11", "priority": "P1", "topics": ["AI_ROI", "CLOUD"], "title": "AI投入回报框架",
     "items": "是否提供任何量化的回报或回本框架；“已预订算力转售溢价30%以上”现在是否仍成立、是否实际转售；“回报不达预期”时的判断标准与触发条件。",
     "questions": ["Q05"], "src": ["TR_Q2_26", "TR_Q1_26", "PPT_2Q26"]},
    {"id": "G12", "priority": "P1", "topics": ["CLOUD"], "title": "AI收入与云的披露",
     "items": "云收入绝对值与毛利率、AI云占比、MaaS/TokenHub与外部GPU出租收入、WorkBuddy收入的分部归属、合同负债中的预收订阅，是否披露、披露到什么程度；新浪实录标题“不准备出租算力”与正文及英文稿不一致，对外以哪一版为准。",
     "questions": ["Q09"], "src": ["TR_Q2_26", "PPT_2Q26", "SINA_Q2"]},
    {"id": "G13", "priority": "P1", "topics": ["AI_PRODUCTS"], "title": "WorkBuddy/CodeBuddy 量化指标与第三方数据",
     "items": "可披露哪些：DAU/MAU、付费用户、ARPU、留存、混元在Token中的占比、企业席位、开放平台分成、金融版收费模式；第三方“6月访问量超2000万”（访问量）与QuestMobile“9月月活3,235.3万”（未去重）可能被引用，是否回应、如何回应。",
     "questions": ["Q07", "Q19", "Q22"], "src": ["REL_EN_2Q26", "QM_SINA"]},
    {"id": "G14", "priority": "P1", "topics": ["AI_PRODUCTS", "SOCIAL", "REG"], "title": "小微",
     "items": "灰度用户规模（券商称“数千万”，公司未确认）与全量时间表；商业化路径（佣金、广告、支付）；隐私合规的公司正式口径；广告库存挤出问题是否需要比Q2“整体回应”更具体的表述。",
     "questions": ["Q08"], "src": ["REL_EN_2Q26", "TR_Q2_26", "HUXIU_XW"]},
    {"id": "G15", "priority": "P1", "topics": ["MODELS", "AI_PRODUCTS"], "title": "混元 Hy4 与元宝",
     "items": "Hy4正式版是否仍按“later this year”发布、是否支持多模态；OpenRouter排名从第一回落到第五如何看待；元宝官方用户数据停在2月，是否更新；对“元宝失宠”说法是否回应（管理层未点名元宝被降优先级）。",
     "questions": ["Q12", "Q21"], "src": ["TR_Q2_26"]},
    {"id": "G16", "priority": "P1", "topics": ["COMPUTE", "REG"], "title": "算力供给与地缘",
     "items": "新增算力中国产芯片、进口芯片、海外租赁的结构披露到什么程度；对H200到货和甲骨文租赁报道是否回应、如何回应；美国远程访问管制的预案；“年底到明年算力充足”是否如期；1260H复议进展与是否诉讼。",
     "questions": ["Q13", "Q26"], "src": ["TR_Q4_25", "TR_Q1_26", "PPT_2Q26", "FR_1260H"], "drift": ["D07"]},
    {"id": "G17", "priority": "P1", "topics": ["PORTFOLIO", "MODELS", "REG"], "title": "DeepSeek 融资报道（公司未证实）",
     "items": "对彭博10-22报道是否回应、如何回应；如属实，金额、会计处理与披露时点；与混元自研、WorkBuddy多模型策略的关系；美国国土安全部采购限制的合规表述需求。",
     "questions": ["Q28", "Q22"], "src": ["TNW_DEEPSEEK"]},
    {"id": "G18", "priority": "P1", "topics": ["AI_CAPEX", "CAPITAL", "ADS"], "title": "海外同业类比（Meta 等）",
     "items": "若被要求与Meta等比较投入强度（资本开支/收入、资本开支/经营现金流）、融资方式（Meta宣布设立可用于融资的无投票权C类股）、股东回报（Meta三季度无回购），是否回应、如何回应；10-28/29其他美国同业发布后需重跑 M1 模块再更新本条。",
     "questions": ["Q27"], "src": ["META_8K", "FORTUNE_META"]},
    {"id": "G19", "priority": "P1", "topics": ["AI_PRODUCTS", "CLOUD"], "title": "10-29 数字生态大会与业绩口径的衔接",
     "items": "大会（官方通稿10-29；部分文章写10-29至30）如发布WorkBuddy、混元、MaaS相关新数据，是否在11-18业绩前并入统一口径；两场活动相隔约三周，口径不一致的风险需提前排查。",
     "questions": ["Q19", "Q09"], "src": ["CONF_CHINADAILY", "CONF_DEVCLOUD"]},
    {"id": "G20", "priority": "P2", "topics": ["ADS", "GAMES_DOM", "GAMES_INTL", "FINTECH", "SOCIAL"], "title": "核心业务口径延续",
     "items": "是否继续披露手游内广告对营销服务的贡献（Q2约2个百分点）与应用内广告游戏口径调整（约4个百分点）；视频号加载率是否更新（1Q26文字稿约4%-5%）；eCPM与曝光量拆分；搜一搜趋势；国际游戏汇率影响与3Q25一次性买断收入的基数影响；金融科技单独增速；腾讯视频订阅下滑原因；游戏递延收入对Q3的支撑。",
     "questions": ["Q11", "Q15", "Q16", "Q18", "Q20", "Q24"], "src": ["TR_Q2_26", "TR_Q1_26", "TR_Q3_25"]},
    {"id": "G21", "priority": "P2", "topics": ["PORTFOLIO"], "title": "投资组合",
     "items": "5月所称“accelerating the process of liquidizing”的进展与用途；快手减持所得用途及Q3处置损益；投资组合变现原则（出售还是实物分派）；对腾讯音乐的定位；快手不再是主要股东后对“分占联营公司盈利”的影响。",
     "questions": ["Q23", "Q06"], "src": ["TR_Q1_26", "PPT_3Q25", "PPT_2Q26"]},
    {"id": "G22", "priority": "P2", "topics": ["REG"], "title": "国内监管",
     "items": "小微、元宝在拟人化互动办法、智能体实施意见、互联网信息服务管理办法修订草案下的备案与合规进展；市场监管总局约谈后AI产品营销推广的表述；游戏版号的公司口径。目前未找到任何公司公开表态。",
     "questions": ["Q25"], "src": ["PPT_2Q26"]},
]
PRIORITY_DEF = {"P0": "业绩前必须确定是否回应及口径", "P1": "建议业绩前确认", "P2": "备查，被问到时需要"}

# ---------------------------------------------------------------- 10-19 以来变化
CHANGES = [
    {"id": "C01", "date": "2026-10-22", "title": "10月票据发行完成",
     "detail": "18亿美元（13亿美元2036年到期6.10%、5亿美元2046年到期6.75%）及260亿元人民币（200亿元2036年到期2.40%、60亿元2056年到期3.00%）票据已于2026-10-21（纽约时间）完成发行；10-22发布完成公告、上市通告及定价补充文件。净所得款项约17.9亿美元及258.9亿元人民币，用途为一般企业用途（10-14定价公告）。",
     "src": ["HKEX_COMPLETION", "HKEX_TITLES", "PRICING"], "label": "公开披露", "tier": 1, "impact": ["Q04", "G06"]},
    {"id": "C02", "date": "2026-10-15", "title": "回购状态（复核）", "computed": "BUYBACK",
     "src": ["BB_JSON", "NDDR_1015", "HKEX_TITLES", "BOARD_MTG"], "label": "计算", "tier": 1, "impact": ["Q06", "G07"]},
    {"id": "C03", "date": "2026-10-23", "title": "南向持股最新",
     "detail": "截至2026-10-23，港股通合计持有腾讯1,089,863,992股，占已发行股份11.98%（10-22为12.02%，取样日中最高；年初至今+0.97个百分点）。【计算】10-21南向对腾讯净卖出约17.1亿港元，10-23净买入约13.0亿港元。业绩会上较少被直接问及，作背景。",
     "src": ["HKEX_SB", "HKEX_DAILY"], "label": "结构化数据", "tier": 1, "impact": ["Q06"]},
    {"id": "C04", "date": "2026-10-21", "title": "Meta 三季度业绩",
     "detail": "收入646.0亿美元（+26%）；资本开支349.1亿美元；自由现金流-21.2亿美元；三季度无回购；2026年资本开支指引1350亿至1450亿美元（收窄、上调下限）；宣布设立无投票权C类股，官方称用途包括融资、员工薪酬、潜在并购等。对腾讯的潜在追问见Q27（推断）。",
     "src": ["META_8K", "FORTUNE_META"], "label": "公开披露", "tier": 1, "impact": ["Q27", "Q01", "Q04", "Q06", "Q11", "G18"]},
    {"id": "C05", "date": "2026-10-29", "title": "腾讯全球数字生态大会（预告）",
     "detail": "官方通稿：10-29在深圳举行，主题“群智协同 数动飞轮：激发全场景生产力”，发布面向Agent的100多项新产品和能力、展示500余个案例，设40余个专场（含模型与MaaS、算力与云基座、Agent Infra）。部分文章写作10-29至30。预告未点名WorkBuddy或混元的具体新品。",
     "src": ["CONF_CHINADAILY", "CONF_DEVCLOUD"], "label": "公开披露", "tier": 4, "impact": ["Q19", "Q09", "Q12", "G19"]},
    {"id": "C06", "date": "2026-10-20", "title": "元宝搜索经腾讯云对外开放",
     "detail": "元宝搜索升级，并通过腾讯云向个人开发者和企业开放（Skill、MCP、API），内部日均调用数亿次、支撑50多个核心业务。",
     "src": ["YB_SEARCH"], "label": "公开披露", "tier": 4, "impact": ["Q21", "Q09"]},
    {"id": "C07", "date": "2026-10-20", "title": "QuestMobile 三季度AI应用报告",
     "detail": "9月WorkBuddy月活3,235.3万，为典型办公Agent第一；AI办公赛道合计1.42亿（第三方、未去重）。公司未披露用户数。",
     "src": ["QM_SINA"], "label": "公开披露", "tier": 4, "flags": ["第三方、未去重"], "impact": ["Q07", "G13"]},
    {"id": "C08", "date": "2026-10-22", "title": "DeepSeek 融资报道（公司未证实）",
     "detail": "彭博报道DeepSeek完成约1000亿元人民币融资，腾讯与宁德时代为最大投资方之一；DeepSeek未确认，未见腾讯回应。10-20美国国土安全部要求联邦机构停止采购DeepSeek产品。",
     "src": ["TNW_DEEPSEEK"], "label": "公开披露", "tier": 4, "flags": ["公司未证实", "媒体转述/二手"], "impact": ["Q28", "Q22", "G17"]},
    {"id": "C09", "date": "2026-10-26", "title": "Hy4 正式版：未检索到发布",
     "detail": "截至10-26未检索到Hy4正式版发布报道；10-12至10-18当周Hy4 preview在OpenRouter按调用量排第五（每经测算）。",
     "src": ["https://tech.ifeng.com/c/8xLU1ikuZ3g"], "label": "推断", "tier": 4, "impact": ["Q12"]},
    {"id": "C10", "date": "2026-10-18", "title": "小微：无官方扩大灰度公告",
     "detail": "媒体体验报道显示小微可在16处入口唤起，支付等不可撤销动作仍需用户确认；未检索到官方扩大灰度的公告。",
     "src": ["HUXIU_XW"], "label": "公开披露", "tier": 4, "impact": ["Q08"]},
    {"id": "C11", "date": "2026-10-26", "title": "国内监管/版号：未检索到新动作",
     "detail": "10-19至10-26未检索到针对腾讯的新监管动作或10月版号批次；“未检索到”不代表未发生。",
     "src": [], "label": "推断", "tier": None, "impact": ["Q25"]},
]

# ---------------------------------------------------------------- Q3 Top10 预注册（议题级）
TOP10 = [
    {"rank": 1, "id": "P01", "title": "AI资本开支规模、节奏与口径", "topics_primary": ["AI_CAPEX"], "topics_secondary": ["COMPUTE"],
     "scope": "2026/2027资本开支区间或量级、Q3是否继续提升、“今明两年集中投入”的边界、会计与现金口径差异。", "questions": ["Q01", "Q14"]},
    {"rank": 2, "id": "P02", "title": "新AI产品投入强度、投入信封与盈利时间表（含Q3利润同比）", "topics_primary": ["AI_ROI", "MARGIN"], "topics_secondary": ["AI_PRODUCTS"],
     "scope": "剔除新AI产品口径的差额与定义、信封比例、拖累峰值、含AI利润何时恢复增长、Q3利润同比。", "questions": ["Q02", "Q03", "Q17"]},
    {"rank": 3, "id": "P03", "title": "AI投入回报框架与回本路径（含海外同业类比）", "topics_primary": ["AI_ROI"], "topics_secondary": ["CLOUD", "AI_CAPEX"],
     "scope": "ROI/回本周期框架、算力转售或出租的下行保护、与阿里/Meta等同业的投入强度和回报比较。", "questions": ["Q05", "Q27"]},
    {"rank": 4, "id": "P04", "title": "WorkBuddy/CodeBuddy：用户、付费、收入确认与生态", "topics_primary": ["AI_PRODUCTS"], "topics_secondary": ["CLOUD"],
     "scope": "用户与付费指标、订阅收入确认进度、毛利、开放平台/金融版/企微、与模型厂商自建harness的竞争。", "questions": ["Q07", "Q19", "Q22"]},
    {"rank": 5, "id": "P05", "title": "腾讯云增速、对外算力出租与Token定价", "topics_primary": ["CLOUD"], "topics_secondary": ["COMPUTE"],
     "scope": "云收入增速与毛利、MaaS/GPU出租、算力自用与外租分配、Token价格竞争。", "questions": ["Q09"]},
    {"rank": 6, "id": "P06", "title": "资本配置：回购/股息与自由现金流、负债", "topics_primary": ["CAPITAL"], "topics_secondary": ["PORTFOLIO"],
     "scope": "全年回购金额与节奏、股息、自由现金流转正、净现金与发债、投资组合变现。", "questions": ["Q04", "Q06", "Q23"]},
    {"rank": 7, "id": "P07", "title": "小微/微信智能体进展与商业化（含元宝定位）", "topics_primary": ["AI_PRODUCTS"], "topics_secondary": ["SOCIAL", "ADS"],
     "scope": "小微灰度规模与全量时间表、交易闭环与商业化、对小程序交易和广告库存的影响、元宝定位。", "questions": ["Q08", "Q21"]},
    {"rank": 8, "id": "P08", "title": "混元Hy4正式版与模型竞争力", "topics_primary": ["MODELS"], "topics_secondary": ["AI_PRODUCTS"],
     "scope": "Hy4正式版时间、多模态、与DeepSeek/Qwen/Kimi的差异化、自研与第三方模型的关系。", "questions": ["Q12", "Q22"]},
    {"rank": 9, "id": "P09", "title": "营销服务增速可持续性与AI广告驱动", "topics_primary": ["ADS"], "topics_secondary": ["SOCIAL"],
     "scope": "广告增速区间与宏观、eCPM与曝光拆分、视频号加载率、闭环广告、AI对广告的贡献。", "questions": ["Q11", "Q20"]},
    {"rank": 10, "id": "P10", "title": "算力供给：芯片结构、国产化与采购约束", "topics_primary": ["COMPUTE"], "topics_secondary": ["REG", "AI_CAPEX"],
     "scope": "仍受算力约束的程度、年底到明年是否充足、国产/进口/租赁结构、出口管制与远程访问管制。", "questions": ["Q13"]},
]
TOP10_ALTERNATES = [
    {"title": "游戏：本土高基数与海外下滑", "topics": ["GAMES_DOM", "GAMES_INTL"], "questions": ["Q15", "Q18"],
     "why_not_top10": "券商预计Q3放缓，但近四季分析师提问中游戏话题出现在3/4场、2Q26为0（计算，M2a 人工编码），且AI话题挤占提问名额（推断）。"},
    {"title": "折旧与毛利率", "topics": ["MARGIN"], "questions": ["Q10"], "why_not_top10": "与P02高度重叠，预计以追问形式出现（推断）。"},
]

SCORING_PROTOCOL = [
    "数据：以 2026-11-18 业绩会官方 webcast 回放为准；如使用第三方文字稿，须标注并抽样对听核对发言人。",
    "切分：以主持人点名为界，切分每位分析师的提问单元（主问题与追问各算一个单元）；管理层主动陈述不计入。",
    "编码：两名编码员在不查看本清单的情况下，按 15 个话题 id 为每个单元标注 1 个主话题、至多 2 个次话题；分歧由第三人裁决。",
    "命中：某议题 P 的 topics_primary 中任一 id 与某单元的主话题相同，且该单元内容落在 scope 描述内，记该议题命中。",
    "指标：命中率 = 命中议题数 / 10；覆盖率 = 被任一议题命中的提问单元数 / 全部提问单元数；同时按相同方法报告朴素基线（以 2Q26 业绩会话题频次前 10 为预测）。",
    "完整性：评分前先重算本文件 SHA-256，与 m2_radar.json 中记录值一致后才评分；会后任何修改须另存新版本并保留本文件。",
]

# ---------------------------------------------------------------- v1 dropped 列表中需改写的条目（去掉估值相关字样）
DROPPED_REWRITE = {
    10: "radar-ai-products notes：“华尔街见闻8月13日汇总提到花旗的一项券商数字”。所引文章里没有这个数字。",
}
DROPPED_REPLACE = [["（估值部分并入Q06）", "（股东回报部分并入Q06）"]]
