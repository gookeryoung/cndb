# 需求卡片：股市日线典型示例（数据源同步 + K 线等关键视图）

- 编号：0009（与 ADR `docs/adr/0009-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-20
- 关联 ADR：`docs/adr/0009-stock-daily-datasource-example.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 典型示例，股市日线，应当配置数据源同步，允许从多个源URL同步到数据表。为股市日线数据表增加多个视图，实现K线等关键图的查看。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 典型示例，股市日线 | 「数据源示例」工作区的 **股市日线** 表作为典型示例：随 `cndb seed` **幂等**注入一个数据源同步任务与新增视图 | `src/cndb/cli/seed/`、`examples/datasets/工作区-数据源示例/` | `cndb seed` 后该表存在同步任务与新增视图；重复 seed 不重复建 |
| C2 | 应当配置数据源同步，允许从多个源URL同步到数据表 | 为 **股市日线** 表注入一个 `tencent_kline` 同步任务：`entrant_param=symbol`、`entrant_keys` 含多个股票代码（每个代码生成一个 URL），多 URL 全部 upsert 到同一张表；`match_keys=[股票代码, 交易日]`；`field_mapping` 将 symbol/trade_date/open/close/high/low/volume 映射到表内中文列 | `plugins/datasource/providers/tencent_kline.py`（已存在）、seed 新增注入 | datasource.json 注入成功并打印；任务绑定到 股市日线 表 |
| C3 | 为股市日线数据表增加多个视图 | 为 **股市日线** 表注入 ≥3 个新增图表视图：**K线图**、**成交量图**、**量价散点图**（保留既有「全部」「放量日」网格视图）；视图经 `views.json` 声明并复用后端字段校验 | `examples/.../views.json`、`src/cndb/cli/seed/views.py`、`src/cndb/plugins/tables/routers/views.py` | seed 打印新增视图；视图配置引用字段全部存在 |
| C4 | 实现K线等关键图的查看 | 图表视图（`view_type=chart`）新增 `chart_type=candlestick`：可配置开/高/低/收四个数值字段（+ 可选按标的 `group_field`），前端用 ECharts CandlestickChart 渲染；后端与 seed 的视图字段校验白名单放行 candlestick 所用的键 | `frontend/src/pages/grid/views/`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`tables/routers/views.py`、`cli/seed/views.py` | 前端单测（chartBoard + 组件）+ e2e 打开 K 线视图可见蜡烛图 |
| C5（派生图归位） | （澄清追加）「涨跌幅/振幅」等派生图 | 派生指标（涨跌幅/振幅）**不新增视图**，由既有「数据分析」模板承载（`analytics.json` 已配 `pct_change`/`amplitude` 窗口公式） | `examples/.../analytics.json`（已配置） | 分析模板可见涨跌幅/振幅图，不新增视图 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | seed 不注入任何 datasource 任务 | `src/cndb/cli/seed/runner.py:21`、`src/cndb/cli/seed/`（无 datasource 模块） | 需新增 datasource 种子扫描（对齐 views.json/analytics.json 模式） |
| 2 | 图表视图无 candlestick 类型 | `frontend/src/pages/grid/views/chartBoard.ts:41`、`ChartView.tsx:19`、`view-config/viewOptionSchema.ts:285` | 需扩展 ChartType/CHART_OPTIONS/option 装配 |
| 3 | 后端视图字段校验白名单（含 charts[]） | `src/cndb/plugins/tables/routers/views.py:58-95` | 需为 candlestick 新增字段键（open/high/low/close 等）放行 |
| 4 | seed 视图字段校验白名单（含 charts[]） | `src/cndb/cli/seed/views.py:36-84` | 同上，与后端口径保持一致 |
| 5 | tencent_kline Provider 已具备 | `src/cndb/plugins/datasource/providers/tencent_kline.py` | 复用，无需新增 provider |
| 6 | 已有 datasource 示例仅天气 | `examples/datasource/weather-open-meteo.json` | 可补一份股票日线示例（可选） |
| 7 | 示例表字段命名 | `examples/datasets/工作区-数据源示例/股市日线.csv` | 中文列：股票代码/股票名称/交易日/开盘价/最高价/最低价/收盘价/成交量/成交额；同步无「股票名称」需允许为空 |
| 8 | 同步标的格式不一致 | `股市日线.csv`（`600519`） vs tencent_kline（`sh600519`） | 潜在演示数据不一致点，ADR 需给口径 |
| 9 | DataView.view_type 为自由 String(32) | `src/cndb/plugins/tables/models.py:253` | 新增视图类型无需迁移 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 「多个源URL」语义：**多标的同源** —— 同一 `tencent_kline` 模板 + `entrant_keys` 多个股票代码，每代码一个 URL，写同一张表（用户 2026-10-20 确认）。
- [x] K 线实现方式：**在图表视图新增 candlestick 类型**（复用多图/筛选/保存/权限既有机制），不新建独立 kline 视图（用户确认）。
- [x] 种子注入方式：**新增 `datasource.json` 配置化**（并行 views.json/analytics.json），seed 新增 datasource 种子模块（用户确认）。
- [x] 派生图（涨跌幅/振幅）承载：**用已有数据分析模板**，不新增视图（用户确认）。
- [x] 视图范围：K线图 + 成交量图 + 量价散点图（涨跌幅/振幅归数据分析）。
- [x] `entrant_keys` 取值：`sh600519`、`sz000001` 两个标的；示例任务 `enabled=true`，seed 只注入配置、**不联网抓取**（用户确认）。
- [x] K 线视图仅烛身，成交量单独成视图（不做同图双轴副图）（用户确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-20）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
