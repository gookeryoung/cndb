# ADR 0009: 股市日线典型示例（数据源同步 + K 线等关键视图）

Status: Accepted（2026-10-20 评审通过）
Date: 2026-10-20
Related: `src/cndb/cli/seed/`、`src/cndb/plugins/datasource/`、`src/cndb/plugins/tables/routers/views.py`、`frontend/src/pages/grid/views/`；上游 ADR [0006](0006-periodic-datasource-sync.md)
需求卡片: `docs/requirements/0009-stock-kline-example.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 典型示例，股市日线 | 新增 seed 子模块 `cli/seed/datasource.py`，扫描 `<工作区>/datasource.json` 幂等注入同步任务；「数据源示例」工作区的 **股市日线** 表为其唯一目标表 |
| C2 | 应当配置数据源同步，允许多个源 URL 同步到表 | `datasource.json` 声明一个 `tencent_kline` 任务：`entrant_param=symbol` + `entrant_keys=[sh600519,sz000001,sz300750]`（每代码一个 URL）→ 全部 upsert 到 股市日线 表；`match_keys=[股票代码,交易日]`；`field_mapping` 将 provider 输出映射到表内中文列 |
| C3 | 增加多个视图 | 「数据源示例」工作区 `views.json` 的 股市日线 表新增 3 个图表视图：K线图 / 成交量图 / 量价散点图（保留既有网格视图）；复用既有 `_seed_views` |
| C4 | 实现 K 线等关键图的查看 | 图表视图（`view_type=chart`）新增 `chart_type=candlestick`：配置时间轴 + 开/高/低/收字段；前端注册 ECharts `CandlestickChart` 并装配 option；后端与 seed 视图字段校验白名单放行新字段键 |
| C5 | 派生图归位 | 涨跌幅/振幅不新增视图，沿用 `analytics.json` 既有窗口公式模板（本 ADR 不改分析模块） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号；ADR 新发现条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | seed 编排只注入 datasets/views/docs/analytics，无 datasource | `src/cndb/cli/seed/runner.py:109-140` | 无同步任务示例 | 确认 |
| 2 | seed 无 `datasource.json` 扫描入口 | `src/cndb/cli/seed/paths.py:41-76`（仅 views/analytics） | 需新增扫描 | 确认 |
| 3 | 图表视图仅 6 种 chart_type，无 candlestick | `frontend/src/pages/grid/views/chartBoard.ts:41`、`ChartView.tsx:19,37` | 无法看 K 线 | 确认 |
| 4 | 后端视图字段校验白名单 + charts[] 白名单 | `src/cndb/plugins/tables/routers/views.py:48-95` | 新字段键会被 400 | 确认 |
| 5 | seed 视图字段校验白名单 + charts[] 白名单 | `src/cndb/cli/seed/views.py:36-84` | 同上，口径需与后端一致 | 确认 |
| 6 | `tencent_kline` Provider 已具备（解析 + 默认归一） | `src/cndb/plugins/datasource/providers/tencent_kline.py` | 直接复用 | 确认 |
| 7 | 同步任务模型含 `entrant_param/entrant_keys` + `match_keys` + `field_mapping` | `src/cndb/plugins/datasource/models.py:100-106` | 多标的同源入同表已表达 | 确认 |
| 8 | 示例表 `股市日线` 为中文列，无派生列 | `examples/datasets/工作区-数据源示例/股市日线.csv` | 需字段映射；派生图归分析 | 确认 |
| 9 | 示例表 股票代码 为无前缀（`600519`），provider 标的为带前缀（`sh600519`） | `examples/.../股市日线.csv` vs `tencent_kline.py:28` | upsert 幂等键不匹配 → 重复行 | **新增（核心缺陷）** |
| 10 | `DataView.view_type` 为自由 `String(32)`；chart_type 存于 `view_options` JSON | `src/cndb/plugins/tables/models.py:253` | 新增图表类型无需迁移 | 确认 |
| 11 | 图表视图支持多图 `charts[]`（dashboard） | `frontend/src/pages/grid/views/chartBoard.ts`、`views.py:85-95` | 复用 | 确认 |
| 12 | 图表视图无公式/派生字段能力 | `frontend/.../chartBoard.ts`（仅对已存在列聚合） | 派生指标必须落到分析模块 | 确认 |

**核心缺陷（需求要补的）**：图表视图无法表达 OHLC 蜡烛图（`chart_type` 封闭枚举无 candlestick），且示例数据的同步标的格式与 CSV 幂等键不一致，导致「同步任务 + K 线视图」这条典型链路既跑不出图、也无法幂等落表。

设计目标（不变量）：

- **I1 存量零迁移**：不新增表/列/枚举，`view_type` / `view_options` 兼容结构不动；既有视图与同步任务行为不变。
- **I2 校验单一**：视图字段校验只有两处（后端 `routers/views.py` 与 seed `cli/seed/views.py`），新增 candlestick 字段键两处同口径。
- **I3 幂等**：seed 重复执行不重复建同步任务/视图；同步 upsert 依赖 `match_keys` 对齐，示例数据与同步标的格式一致。
- **I4 不联网副作用**：seed 只注入同步任务配置（`enabled=true`），不触发真实抓取。
- **I5 派生图归位**：视图只引用已存在列；涨跌幅/振幅等派生指标由分析模块（既有窗口公式）承载，不在视图层引入公式引擎。

## Decision

### 1. 数据模型

无 schema 变更。同步任务复用 `datasource_sync_job`（`workspace_id/name/provider/table_id/request_spec/entrant_param/entrant_keys/match_keys/field_mapping/cursor/schedule/enabled`）；K 线为 `view_options.chart_type=candlestick` 的一个取值，随 `charts[]` 或扁平键存储。`DataView.view_type` 仍为 `chart`。

#### 1.1 `datasource.json`（新种子配置契约）

位于 `examples/datasets/<工作区>/datasource.json`（并行 `views.json`/`analytics.json`），结构：

```json
{
  "jobs": [
    {
      "name": "股市日线同步",
      "provider": "tencent_kline",
      "table": "股市日线",
      "request_spec": { "url_template": "…{symbol},day,{start},{end},320,qfq", "time_window": { "mode": "range", "start_param": "start", "end_param": "end", "chunk_days": 320 } },
      "entrant_param": "symbol",
      "entrant_keys": ["sh600519", "sz000001", "sz300750"],
      "match_keys": ["股票代码", "交易日"],
      "field_mapping": {
        "symbol": { "name": "股票代码", "field_type": "text" },
        "trade_date": { "name": "交易日", "field_type": "date" },
        "open": { "name": "开盘价", "field_type": "float" },
        "close": { "name": "收盘价", "field_type": "float" },
        "high": { "name": "最高价", "field_type": "float" },
        "low": { "name": "最低价", "field_type": "float" },
        "volume": { "name": "成交量", "field_type": "number" }
      },
      "cursor": { "strategy": "date", "field": "交易日", "backfill_start": "2020-01-01" },
      "schedule": { "mode": "daily", "at": "17:30", "timezone": "Asia/Shanghai" },
      "enabled": true,
      "rate_limit_ms": 200
    }
  ]
}
```

`table` 名称由 seed 从 `tables_map` 解析为真实 `table_id`；未解析到则跳过并打印告警。

### 2. 判定算法（唯一入口）

无新判定入口。视图字段校验复用两端既有函数并扩展白名单键：

- 后端 `_validate_view_fields`（`routers/views.py:48`）：平铺键与 `charts[i]` 键均新增 `time_field`、`open_field`、`high_field`、`low_field`、`close_field`。
- seed `_validate_view_fields`（`cli/seed/views.py:13`）：同款新增，保持 I2。

seed 注入入口新增 `run_seed_datasource(db, user, ws_map, tables_map, datasets_dir)`（`cli/seed/datasource.py`），由 `runner.py` 在视图种子之后调用。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET/POST /api/v1/workspaces/{wid}/tables/{tid}/views` | 无结构变更；`view_options.chart_type=candlestick` 现可通过字段校验 |
| `/api/v1/workspaces/{wid}/datasource/*` | 无变更（示例任务由 seed 直写库，不经 HTTP） |

### 4. 边界与例外

1. **多标的 K 线可读性**：同一时间轴上多标的蜡烛会重叠。candlestick 视图以**视图 `filters` 收窄到单一 `股票代码`**（示例 K 线视图过滤 `股票代码=sh600519`）；`group_field` 对 candlestick 不生效（schema 中 `visibleWhen` 不含 candlestick）。同表可另建按标的的 K 线视图。
2. **字段缺失空态**：candlestick 必填为 时间轴 + 开/高/低/收 五字段，缺任一即在卡片头显示缺失项标签（复用 `missingFieldLabels`）。
3. **统计面板**：candlestick 的描述统计基于 `close_field` 列（复用 `computeStats`）。
4. **字段映射未覆盖列**：`股票名称`/`成交额` provider 不产出，同步行这两列为空（允许，`field_mapping` 不含即不写）。
5. **成交量单位**：provider `volume` 为「手」，示例 CSV 既有值口径可能不同；示例以 provider 口径为准，不做事后换算。
6. **标的格式一致性（I3）**：示例 CSV 的 股票代码 统一为带市场前缀（`sh600519`/`sz000001`/`sz300750`），与 `entrant_keys` 对齐，使 CSV 预置行与同步行按 `match_keys` 幂等合并而非重复。

### 5. 迁移

无 alembic 迁移（无 schema 变更）。示例 CSV 的 股票代码 取值调整属数据文件改动，随 `make seed` 全量重建生效。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 图表纯逻辑 | `frontend/src/pages/grid/views/chartBoard.ts` | `ChartType` 增 `candlestick`；`ChartConfig` 增 `time_field`/`open_field`/`high_field`/`low_field`/`close_field`；新增 `buildCandlestickData`（按时间轴取 `[open,close,low,high]`，无效行剔除）并接入 `buildChartData` |
| 图表组件 | `frontend/src/pages/grid/views/ChartView.tsx` | 注册 `CandlestickChart`；`buildOption` 增 candlestick 分支（xAxis 类目=时间轴、series.type=candlestick）；`missingFieldLabels`/`chartKeyFieldLabel` 增 candlestick 分支 |
| 视图配置 schema | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | `CHART_OPTIONS` 增 `chart_type.candlestick` 选项 + `time_field`/四个 OHLC 字段项（`visibleWhen` 限 candlestick）；`normalizeChartList`/`serializeChartList` 自动兼容新键 |
| 种子视图 | `examples/datasets/工作区-数据源示例/views.json` | 股市日线 新增 K线图 / 成交量图 / 量价散点图 三视图 |

### 7. 测试清单

**判定层（单测）**：`chartBoard` 的 `buildCandlestickData`（类目排序、`[open,close,low,high]` 取值、空/非数值剔除、缺字段）；`CHART_OPTIONS` 的 candlestick `visibleWhen`；`normalizeChartList`/`serializeChartList` 对 candlestick 条目往返。

**接口层**：视图创建携带 `chart_type=candlestick` + 五个字段键通过校验；引用不存在字段返回 400；`charts[]` 各条目 OHLC 键越界返回 400（定位到 `charts[i].<key>`）。

**seed**：`datasource.json` 注入幂等（重复 seed 不新增任务）；`table` 名解析失败打印并跳过；candlestick 视图字段校验通过并落库。

**迁移 / 备份**：无迁移；`make seed` 全量重建后 股市日线 表含同步任务与 3 个新视图。

**e2e（前端）**：打开 股市日线 的 K 线视图 → 渲染 candlestick（存在 canvas/svg 容器）；数据源同步页可见该任务。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端/seed 视图字段校验白名单扩展 + 前端 chartBoard/ChartView/schema 的 candlestick 支持 + 前端单测 | 中 |
| **P1** | seed `datasource.py` + `datasource.json` + 示例 CSV 标的格式对齐 + seed 测试 | 中 |
| **P2** | 示例 `views.json` 三视图 + e2e + 文档/CONTEXT/CHANGELOG + 落地回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 「多个源 URL」语义 | 多标的同源：单任务 `entrant_keys` 多代码 → 多 URL → 同表 | 复用 `entrant_param`/`entrant_keys`，零框架改动 | 多源站多 Provider（如需另建 job，示例更复杂）；单任务多 url_template（框架扩展，非必要） | `datasource_sync_job.entrant_keys` |
| D2 | K 线实现方式 | 图表视图新增 `chart_type=candlestick` | 复用多图/筛选/保存/权限既有机制，改动面最小 | 新建独立 `view_type=kline`（需新组件/schema/校验，重复造轮子） | `viewOptionSchema.ts`、`chartBoard.ts` |
| D3 | 种子注入方式 | 新增 `datasource.json` + `cli/seed/datasource.py` | 与 views.json/analytics.json 同构，可扩展、幂等 | 硬编码在 seed（不可配置、难扩展） | `cli/seed/datasource.py` |
| D4 | 派生图承载 | 涨跌幅/振幅归分析模块既有窗口公式模板，不进视图 | 视图层无公式引擎（I5）；`analytics.json` 已配好 | 图表视图支持公式字段（改动最大）；seed 补派生列（同步行会缺列，口径不一） | `examples/.../analytics.json`（不改） |
| D5 | 标的格式一致性 | 示例 CSV 股票代码统一为带前缀格式，与 `entrant_keys` 对齐 | 保证 `match_keys` upsert 幂等（I3），避免重复行 | 保留无前缀 CSV（upsert 永不命中，产生重复行） | `examples/.../股市日线.csv`、`datasource.json` |
| D6 | 校验口径 | 后端与 seed 两处校验函数同步扩展 candlestick 字段键 | 保持 I2 单一口径，避免前后/种子漂移 | 仅改后端（seed 播种视图会被自身校验拦下） | `routers/views.py`、`cli/seed/views.py` |
| D7 | K 线多标的呈现 | 视图用 `filters` 收窄到单一标的；`group_field` 对 candlestick 不生效 | 同轴多蜡烛重叠不可读 | 多 series 同行轴渲染（视觉不可辨） | `views.json`（K线视图 filters） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：典型示例端到端可用（同步配置 + K 线/成交量/量价视图）；图表视图能力增强且零迁移；`datasource.json` 让同类示例可配置化扩展。
- **负向**：图表 `chart_type` 枚举、schema `visibleWhen`、`missingFieldLabels`、`chartKeyFieldLabel`、两端校验白名单需同步维护（新增类型时的一致性成本）。
- **风险与缓解**：candlestick 在多标的场景可读性差 → 以视图过滤单标的规避（D7）；示例 CSV 格式变更需同步 e2e 断言中的代码取值。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 同步任务定义 | `datasource_sync_job` | 示例任务字段与幂等键 | ADR 0006（框架） → 本 ADR（示例实例） |
| 视图配置 | `view_options.chart_type` | 新增 candlestick 取值 | 本 ADR |
| 派生指标 | 分析模板 | 涨跌幅/振幅由窗口公式承载 | ADR 0006 M4/M5 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/grid/views/chartBoard.ts`、`frontend/src/pages/grid/views/ChartView.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | `frontend/src/pages/grid/views/chartBoard.test.ts`、`frontend/src/pages/grid/views/ChartView.test.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.test.ts`、`tests/test_views_api.py` | — |
| P1 | 已落地 | `src/cndb/cli/seed/datasource.py`、`examples/datasets/工作区-数据源示例/datasource.json`、`examples/datasets/工作区-数据源示例/股市日线.csv`、`src/cndb/cli/seed/paths.py`、`src/cndb/cli/seed/runner.py` | `tests/test_seed_datasource.py` | — |
| P2 | 已落地 | `examples/datasets/工作区-数据源示例/views.json` | `frontend/tests/e2e/critical/view-mode-switch.spec.ts` | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地（含文档 / CONTEXT / CHANGELOG 回填）
- 已完成：需求卡片、ADR（Accepted）、P0 前端 candlestick + 两端校验白名单、P1 seed 数据源种子 + 示例配置/CSV 口径对齐、P2 三视图 + e2e
- 下一步：无（本 ADR 范围内交付完毕）；如需扩展「多源站 / 多 Provider 写同表」按 D1 否决项另立 ADR
- 已知坑：candlestick 多标的重叠（D7 用视图 `filters` 收窄单标的规避）；示例 CSV 股票代码改为带前缀（`sh/sz`）后，若下游断言依赖旧的无前缀取值需同步更新；seed 只注入 `datasource.json` 中的同步任务配置，**不会联网抓取**，示例表数据仍来自 CSV
- 最近一次全绿：`make check-fast`（2026-10-20）；待收尾跑 `make flow`
