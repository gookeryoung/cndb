# 需求卡片：股市日线数据同步到本地（参照 stockmaster）

- 编号：0033（与 ADR `docs/adr/0033-*.md` 同号，卡片存 `docs/requirements/0033-stock-daily-sync-to-local.md`）
- 来源 / 提出人：用户（会话提出）
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0033-stock-daily-dual-source-sync.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请参照~/stock-strategy项目功能，实现【数据校核】的数据同步到本地功能。把相关配置完善到【数据源示例】当中，移除现有的【股市日线-新浪】等已有内容。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | "参照~/stock-strategy项目功能" | 参照 `/root/stockmaster`（`~/stock-strategy` 为空仓库，实际代码在 stockmaster）的日线同步链路：公开行情接口 → 增量拉取 → 本地表幂等 upsert（标的 + 日期去重，可重复运行不产生重复行） | datasource plugin | 同步运行测试（假源桩） |
| C2 | "实现【数据校核】的数据同步到本地功能" | 在 cndb 数据源同步机制上落地股市日线「同步到本地」：拉取日线 OHLCV 写入本地数据表，支持增量（`cursor.strategy=date`）与手动/定时调度 | datasource plugin（http_json provider / pipeline / runner） | 后端单测 + 集成测试 |
| C3 | "把相关配置完善到【数据源示例】当中" | 同步任务配置进入 `examples/datasets/工作区-数据源示例/datasource.json`，配套示例表 / CSV / 视图；`cndb seed` 开箱注入（只注入配置不联网），演示时点「立即运行」即可拉取 | cli/seed + examples/datasets | `test_seed_datasource` 断言 |
| C4 | "移除现有的【股市日线-新浪】等已有内容" | 新方案不保留旧的按源分表静态示例结构（「股市日线」「股市日线-新浪」「自选股」）；仓库侧该内容已随 `299f4e6a` 移除，本需求的「移除」落点见未决问题 3 | examples/datasets | seed 测试 + grep 复验 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 通用 http_json provider | `src/cndb/plugins/datasource/providers/http_json.py:53` | 新浪日线接口（`CN_MarketDataService.getKLineData`）返回纯 JSON 数组，可直接配置；腾讯日线（`web.ifzq.gtimg.cn/appstock/app/fqkline/get`）为嵌套数组（`data.<symbol>.qfqday`），当前 parse 不支持 |
| 2 | 行内补齐标的列 `fill_entrant` | `src/cndb/plugins/datasource/services/pipeline.py:123` | 新浪日线响应不带 symbol，靠请求维度补齐——注释即为本场景预留 |
| 3 | 腾讯专用响应处理器 | `src/cndb/core/http.py:463`（`tencent_stock` 注册于 :521） | 仅覆盖腾讯**实时快照**（`v_xxx="a~b~c"` 格式），不含日线 |
| 4 | seed 注入逻辑 | `src/cndb/cli/seed/datasource.py:40` | 按 `(workspace_id, name)` 幂等跳过，**无删除能力**（存量库中的废弃任务不会被清理） |
| 5 | candlestick 图表类型与行内 KlineView | `frontend/src/pages/grid/views/`（`299f4e6a` 删除 `KlineView.tsx` / `klineBoard.ts` 并收敛 `viewOptionSchema.ts`） | 仅 `ChartView.test.tsx:31` 残留 echarts mock 引用；如需 K 线可视化须恢复前端代码 |
| 6 | 旧股市示例内容 | `examples/datasets/工作区-数据源示例/` | `299f4e6a` 已删除 `股市日线.csv` / `股市日线-新浪.csv` / `自选股.json` 及相关 views/fields 配置；现存任务仅两条 llm_prompt |
| 7 | datasource_sync_job 模型与运行链路 | `src/cndb/plugins/datasource/models.py:73`、`services/runner.py:257` | `entrant_keys`（多标的）+ `match_keys`（幂等键）+ `cursor`（增量）+ `schedule`（manual/daily/cron）均已具备 |
| 8 | 参照项目同步与校核实现 | `/root/stockmaster/backend/app/sync/{sync_service,repository,quality}.py`、`providers/{sina,tencent}_provider.py` | 日线增量 upsert 按 `code/trade_date/adjust` 幂等；`data-quality` 体检项：缺失历史/缺口/陈旧/OHLC 异常/极端涨跌/qfq 不连续等 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已确认，2026-10-25 需求方拍板）

- [x] 1. 「数据校核」的口径：**仅实现其前置的「数据同步到本地」**，校核语义由视图（筛选/图表）表达，不移植 stockmaster 的质量检查引擎。
- [x] 2. 数据源选择：**新浪 + 腾讯双源**（对齐 stockmaster 多源思路，支持来源交叉比对）；腾讯日线的嵌套数组格式需小幅扩展 http_json 解析能力。
- [x] 3. 「移除」的落点：**新方案不回退旧的按源分表静态示例结构即可**；仓库侧已随 `299f4e6a` 移除，不给 seed 增加删除逻辑，存量库残留由需求方在界面自行清理或重种。
- [x] 4. K 线可视化：**不恢复** candlestick 图表类型与行内 Kline 视图，表格 + 现有图表视图演示。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-25 会话逐项拍板）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
