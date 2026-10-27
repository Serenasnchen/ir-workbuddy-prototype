---
name: ir-number-gatekeeper
description: 披露数字守门员。在业绩材料定稿前使用，或当用户说“核对中英文公告和 PPT 的数字 / 检查这段讲稿有没有错数字或新数字 / 跑一遍勾稽”时使用。用确定性脚本抽取同一季度文件（英文新闻稿、中文新闻稿、港交所英文公告、港交所中文公告、业绩演示；五份齐全或任意子集，.txt 或 .pdf 均可）中的关键数字，统一单位后逐项勾稽，并检查草稿中与已披露冲突的数字和未见于已披露文件的新数字。不靠大模型判断数字对错。
---

# 披露数字守门员（ir-number-gatekeeper）

先加载 `ir-house-style`。**所有数字判断由脚本完成**，模型只负责组织结果、解释差异。

## 准备
1. Python 3.9+。输入全是 `.txt` 时只用标准库；**有 PDF 输入时才需要 PyMuPDF**：`pip install pymupdf`。
2. **输出目录**：加 `--out <可写目录>`，勾稽结果、草稿检查结果、注入草稿、从 PDF 抽出的文本都写进该目录，不写工作空间。工作空间只读（如沙箱）时必须加；给真实路径，不要用 `/tmp`（Windows 上的 Python 看不到 Git Bash 的 `/tmp`）。
3. **文件类型**：`release_en`（英文新闻稿）、`release_zh`（中文新闻稿）、`hkex_en` / `hkex_zh`（港交所英 / 中文业绩公告）、`ppt`（业绩演示）。每种类型只给一份；脚本会核对文件语言与类型是否相符（`*_zh` 应为中文，其余为英文），写反时直接报错。文本文件用 UTF-8；GBK（记事本 ANSI）也能读，会提示。
4. **季度**：默认 2Q26。用 `--doc` 时，其他季度加 `--quarter 3Q26`；完整模式下季度须已列在 `IR_QUARTERS` 中，再用 `--quarter` 或 `IR_TARGET` 选择。季度须与文件内容一致，否则正文段落会被当作其他期间跳过。
5. **出错时**：缺文件、工作空间只读、`--out` 指向已有文件等情况，脚本只打一行 `[错误] …` 说明原因，按提示改即可。

## 步骤：手头只有部分文件（常见情形）
用 `--doc 类型=路径` 逐个指定文件（可重复），不需要整理目录或 manifest。以中英文新闻稿两份文本为例：
1. **勾稽**：`python scripts/gatekeeper.py tieout --doc release_en=inputs/2Q26_release_en.txt --doc release_zh=inputs/2Q26_release_zh.txt --out <输出目录>` —— 指标 × 给定文件：一致 / 不一致 / 未出现；不一致项给出两边原文行，区分四舍五入差异与实质差异；只给两份时逐项列出只在一边出现的指标。结果写 `<输出目录>/m4_tieout_<季度>.json`。
2. **检查草稿**：`python scripts/gatekeeper.py check --draft inputs/draft_paragraph.txt --doc release_en=… --doc release_zh=… --out <输出目录>` —— 草稿每段一行，语言自动判断（可用 `--lang zh|en`）。红色为与已披露冲突，黄色为参照文件中没有的新数字（须人工判断是否构成新信息）。“已披露”基准 = 给定文件中的港交所公告与 PPT；只给了新闻稿时以新闻稿为基准，脚本会打印所用基准。结果写 `<输出目录>/m4_check_<草稿名>.json`。
3. **自测（可选）**：需同时给 `release_en` 与 `release_zh`。`python scripts/inject.py --seed 7 --n 30 --doc … --out <输出目录>` 在新闻稿上注入 7 类错误，生成模拟草稿与答案；`python scripts/gatekeeper.py check --eval --doc … --out <输出目录>` 报告分类召回率。
4. **出报告**：按严重程度排序的差异清单；重大异常注明“建议上报披露委员会”。

## 步骤：五份文件齐全、多季度（完整模式）
1. 在工作空间建 `data/src/ir_official/`，放入一个或多个季度的文件，命名 `<季度>_<类型>.pdf`（如 `2Q26_hkex_en.pdf`）；同目录放 `manifest.tsv`，每行四列（制表符分隔）：季度、类型、文件名、原始网址。
2. 用环境变量指定季度：`IR_QUARTERS=1Q26,2Q26`（全部可用季度，逗号分隔；每个季度五份文件都要有）、`IR_TARGET=2Q26`（要勾稽的季度，默认取最后一个）。
3. 在工作空间根目录运行（均可加 `--out`；不加时写工作空间 `demo/data/`，与以前一致）：
   - `python scripts/gatekeeper.py extract` —— 目标季度约 66 个关键指标的注册表，统一 RMB billion/million、亿元/百万元、%、个百分点，记录每个数字的文件与行号；
   - `python scripts/gatekeeper.py tieout` —— 五方勾稽；
   - `python scripts/gatekeeper.py check --draft <草稿.txt>` —— 以港交所中英文公告 + PPT 为基准检查草稿；
   - `python scripts/inject.py --seed 7 --n 30` / `python scripts/gatekeeper.py check --eval` —— 注入自测与其他季度干净段落误报率；
   - `python scripts/gatekeeper.py all` —— 依次执行以上全部，写 `m4_gatekeeper.json`（含随机抽查回原文的自检）。
4. 资本开支三口径对照（会计口径 / 发行文件现金口径 / 自由现金流口径）目前只针对 2Q26：需要目标季度为 2Q26、`IR_QUARTERS` 含 4Q25，且工作空间另有 `data/src/market_raw/dl/tc_ir26.txt`（2026 中报文本）与 `data/src/ir_official/2026-10-12_E700_Launch-Announcement.txt`（发债公告文本）。条件不全时自动跳过，并在结果的 `capex.reading` 里写明缺哪一项。同名的 pdftotext `.txt` 也是可选输入，只用于交叉核对行号。

`m4_checker.js` 是同一规则的浏览器简化版，可嵌入网页做“边写边查”。

## 已知局限
- 英文原文精度较粗时（如“2 million”），中文一侧在该精度内的改动无法识别。
- 图表中没有标签的数字、文字顺序错乱的表格不解析。
- “新数字”规则是启发式的，未达 100% 召回，必须保留人工复核。
- `--doc` 只处理单季度：没有上年同季、上一季文件，不能按规范值推算同比环比，也不能用上期数值确认表格列。首列与本季规范值不符的表格行会被忽略（计入“未锚定表格行”），不报不一致：例如 2Q26 PPT 经营开支 (50.6) 在完整模式下报“末位差异”，在 `--doc` 五份 PDF 下不报。需要这类核对时用完整模式。
- 只给新闻稿时，草稿“新数字”只与新闻稿比对，覆盖面比港交所公告 + PPT 窄。

## 部署要求
演示与测试只用已发布文件。**处理未公布业绩材料时，必须在私有化工作区运行，并关闭外部模型与外网访问。**

## 红线
- 不改写原文，只标注；定稿由人完成。
- 新数字是否构成内幕消息，由披露委员会或法务判断。
