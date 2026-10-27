# Q3 业绩准备台：IR 个人智能体原型

用公开数据搭建的投资者关系（IR）工作原型，配套 5 个按 SKILL.md 标准编写的 WorkBuddy 技能。数据截至 2026-10-26。

- 在线演示：https://ir-q3-prep-desk.vercel.app （中国内地网络可能需要代理）
- 离线演示：`site/index.html`，下载后用浏览器直接打开，不需要联网

演示页有 6 个页签：今日简报、同业矩阵、问题雷达、股东·资金·回购、数字守门员、评测与回放。页面里带下划线的数字都可以点开，查看出处、证据标签和核查状态。

## 目录

| 路径 | 内容 |
|---|---|
| `skills/` | 5 个 WorkBuddy 技能：ir-house-style、ir-number-gatekeeper、ir-peer-flash、ir-qa-radar、ir-holder-watch。用法见 `docs/技能包使用说明.md` |
| `demo/pipeline/` | 各模块的数据处理脚本、模块说明（`*_NOTES.md`）和回归测试 |
| `demo/web/` | 演示页的样式与脚本，无外部依赖 |
| `demo/data/` | 各模块的输出（JSON），每个数字都带来源编号和证据标签 |
| `report/` | 报告图表与 Word 文档的生成脚本 |
| `tools/` | 打包与部署脚本 |
| `资料来源清单.csv` | 用到的 197 条公开来源 |

## 重新生成演示页

需要 Python 3.9 及以上，在仓库根目录运行：

```
python -I demo/pipeline/wording.py --check
python -I demo/pipeline/build.py
```

`build.py` 把 `demo/data/` 下的模块输出和 `demo/web/` 下的页面打包成一个离线 HTML，输出到 `deliverables/Q3业绩准备台.html`。如果模块输出里有邮箱、本机路径，或不符合 IR 用语规范的措辞（例如替管理层拟定口径、引用券商盈利预测），构建会直接失败。

## 数据说明

- 只使用公开信息：腾讯投资者关系网站的业绩材料、港交所披露易、同业公司的业绩新闻稿，以及 StockAnalysis 公开的业绩会文字稿。
- 业绩会文字稿是第三方整理稿，不是官方逐字稿，引用前应以官方录音复核。
- 原始下载文件（文字稿网页、PDF 等）不随仓库分发，可按各模块 `*_NOTES.md` 中的网址重新获取；因此重跑各模块脚本和部分测试需要先下载这些文件。
- 本项目不构成投资意见，也不代表腾讯公司口径。
