# 需求卡片：网页性能瓶颈识别与提升方案（数据源示例工作区 · 股市日线海量数据 · 页面切换卡滞）

- 编号：0046（与 ADR `docs/adr/0046-web-performance-bottlenecks.md` 同号）
- 来源 / 提出人：用户（口语需求）
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0046-web-performance-bottlenecks.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 本地数据库，数据源示例工作区，股市日线，拥有海量的数据，平台各页面切换卡滞，是否和它过大存在关系。请对网页的性能提升进行瓶颈识别和方案制定。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「平台各页面切换卡滞」 | 产出可复现的瓶颈清单：每条含实测耗时、触发路径与 `文件:行号`，覆盖「进入数据表目录页 / 打开表网格 / 翻页与筛选 / 非 grid 视图」四类切换路径 | tables / workspaces / datasource 插件 + frontend | ADR Context 表逐条列实测数据与代码落点 |
| C2 | 「是否和它（股市日线数据量）过大存在关系」 | 用测量数据回答因果：量化「股市日线 4,286,980 行」对每条路径耗时的贡献占比，区分「与行数线性相关（确认）」与「与行数无关（排除）」两类瓶颈 | 同 C1 | ADR Context 表每条标「确认 / 排除 / 新增」 |
| C3 | 「对网页的性能提升进行瓶颈识别和方案制定」 | 产出分期修复方案（ADR 0046），每期给出可验收的性能指标（本地实测口径），P0 先治后端读路径热区，P1 治前端载荷，P2 治分页与渲染 | ADR 0046 | 每期落地后按指标复测（`tests/` + e2e 性能回归） |
| C4 | （隐含）修复不得改变现有功能口径 | 分页 total 语义、select 选项颜色、视图渲染、行级权限过滤、缓存失效行为保持不变（颜色口径的预期变化须在 ADR 决策行声明） | tables 插件 + frontend | 既有单测 / e2e 全绿，不新增失败 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 网格行数据走 GET 端点，无缓存（POST /list 才有 5s 缓存） | `frontend/src/api/records.ts:7-13`、`src/cndb/plugins/tables/routers/records.py:173-217` | 最热读路径每次全量执行 |
| 2 | 行列表每次执行 COUNT(*)（带 `_trashed=0`）+ 全表排序 | `src/cndb/plugins/tables/services/core/records.py:527-546` | 大表上数百 ms ~ 秒级 |
| 3 | 默认视图排序（股票代码 ASC, 日期 DESC）无法命中 match 索引（全 ASC） | `src/cndb/plugins/datasource/services/write.py:143-170`、`tables_dataview` 视图 21 | 排序溢出到临时 B-tree |
| 4 | 工作区详情逐表反射 + COUNT + 懒算存储快照，无缓存；数据表目录页每次进入调用 | `src/cndb/plugins/workspaces/routers/workspaces.py:211-226,255`、`frontend/src/pages/workspace/TablesList.tsx:228-232` | 实测 ~240ms/次 |
| 5 | 表详情与字段列表携带 select 字段全量 options（7289 个，约 450KB） | `src/cndb/plugins/tables/routers/tables.py:427-498`、`routers/fields.py:244-255` | 表详情实测 414KB |
| 6 | 非 grid 视图一次性拉 2000 行（839KB 载荷） | `frontend/src/pages/grid/useGridData.ts:22,37` | 大表上后端 0.31s + 前端渲染 |
| 7 | 深分页 offset 线性扫描（4,000,000 偏移实测 4.44s） | `src/cndb/plugins/tables/services/core/records.py:538-544` | 翻到后段页面卡死感 |
| 8 | 关键词 contains 走全字段 LIKE '%x%'（实测 1.13s） | `src/cndb/plugins/tables/services/core/query.py`（compile_filters） | 搜索与 `__query__` 路径 |
| 9 | MainLayout 内容区按 pathname 整体重挂载（Suspense 骨架重放 + 页面进入动画） | `frontend/src/layouts/MainLayout.tsx:589-597` | 跨页切换的前端固定成本 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [ ] 性能验收阈值取值确认：P0 目标拟定为「网格默认视图冷请求 ≤ 600ms、5s 内复访 ≤ 50ms、数据表目录页 ≤ 350ms」（本地 SQLite 实测口径），是否认可？
- [ ] select 字段超大 options（> 500 项）在表详情 / 字段列表默认截断、字段编辑器再拉全量，是否可接受（含 Tag 颜色从「选项位置」改为「值稳定哈希」的口径变化）？
- [ ] 是否允许为大表追加「视图排序专用索引」（同步写入时有索引维护写放大代价）？

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
