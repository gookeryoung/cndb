# 需求卡片：数据表健壮性与功能性增强路线图（P0–P3）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0141（本卡为**规划卡**：不含实现决策；各期立项时按号另出需求卡 + ADR）
- 来源 / 提出人：用户（会话 2026-11-24，要求「针对数据表功能的健壮性和功能性增强，结合最佳实践给出后续计划」）
- 日期：2026-11-24
- 关联 ADR：`docs/adr/0139-row-recycle-bin.md`（P1-1，已立卡 `docs/requirements/0139-row-recycle-bin.md`）、`docs/adr/0140-record-concurrency-control.md`（P1-2，已立卡 `docs/requirements/0140-record-concurrency-control.md`）

> 本卡是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对数据表功能的健壮性和功能性增强，结合最佳实践给出后续计划

评审结论（2026-11-24，用户确认「ok」）：按本文分期与顺序推进；先落地 P1-1 / P1-2 两个 S2 项，
P0 的运维与测试类小项（S1）可并行插入，不阻塞主线。

评审结论（2026-11-24，二次确认「合并到 main，评审通过」）：**P0 五项与 P1-1 / P1-2 全部验收通过**，
ADR 0139 / 0140 置 `Implemented`；P1 剩余的「行级历史与撤销」「写幂等键」与 P2 各项按需另行立项。

## 可实施约束（C1..C6：阶段级承诺）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「健壮性」 | **P0 止血期（1.5–2 周）**：① `cndb tables doctor [--fix]` 巡检孤儿 link / 失效 lookup 冗余列 / 排序索引漂移 / 回收站体积（已落地，见需求卡 0142；公式异常检测后移）；② 审计与事件流保留期（已落地，见需求卡 0143；查询端点沿用既有 `GET /tables/{id}/audit`）；③ 前端边界（未保存编辑离开拦截 + 行操作失败可重试；**大范围粘贴保护不适用** —— 网格没有多单元格粘贴入口，单元格是原生输入框）；④ 导入解析随机输入测试 + 行权限不变量矩阵（已落地，见 `tests/test_import_parsers_fuzz.py` / `tests/test_row_access_invariants.py`）；⑤ 翻页 / 内联编辑性能预算进 CI（`@perf` 旅程 + 硬上限；基线缺失只记录读数） | `cli/`、`services/core/`、`frontend/src/pages/grid/`、`tests/`、`frontend/scripts/perf-budget.mjs` | 每项独立需求卡 + 对应单测；`make check-fast` / `make test` / perf 预算全绿 |
| C2 | 「健壮性 + 功能性」 | **P1 协作可信期（3–4 周）**：行回收站（0139）、直编并发冲突检测（0140）、行级历史与撤销、写幂等键（`Idempotency-Key`） | `tables/`、`frontend/src/pages/grid/`、`core/` | 0139 / 0140 按各自 ADR 验收；历史与幂等各出 S2/S1 卡与 ADR |
| C3 | 「功能性」 | **P2 数据能力期（4–6 周）**：服务端聚合 / 分组端点、keyset 分页 + 可配导出上限、校验规则增强（条件必填 / 正则）、批量编辑增强（查找替换 / 粘贴校验预览 / 跨页全选）、大表 DDL dry-run | `tables/routers/`、`tables/services/`、`frontend/src/pages/grid/` | 每项独立卡；聚合计与前端本地口径对拍；深翻页纳入 perf 预算 |
| C4 | 「最佳实践」 | **P3 按触发条件启动**：实时协同（CRDT / 广播）、字段类型对外准入、表模板 —— 触发条件与取舍见下「暂不做」表 | `tables/` | 触发条件成立再立项，不预先落码 |
| C5 | （门禁） | 每个 S2 期先 ADR（`Proposed → Accepted` 人工评审）；新增 H 条目须人工确认后入 `docs/CONSTRAINTS.md`；每期收工按 H4 跑 `make check-fast` → `make test` → 文档回填 | 全仓 | `make adr-check` / `make constraint-check` 0 error |
| C6 | （度量） | 每期在 ADR「交接」记一行度量：409 `record_stale` 率、回收站行数与体积占比、`tables doctor` 脏数据条数、深翻页 p95、聚合扫描行数、导入失败率 | ADR 交接节 | 评审时可见趋势 |

## 缺口清单（分期依据）

编号是本路线图的稳定引用（R=健壮性，F=功能性）；立项时转成对应卡片的 C 行，不在此重复约束措辞。

| # | 缺口 | 现状证据 | 计划期 |
|---|---|---|---|
| R1 / F1 | 行回收站不可用（批量删除是物理删、无列表 / 无保留期） | `records.py::bulk_delete`、`routers/records.py` | P1（0139） |
| R2 / F3 | 直编无并发冲突检测 | `records.py::update_row`、`hooks.ts::useUpdateRowOptimistic` | P1（0140） |
| R3 / F2 | 审计无字段级 diff、无保留期、无行历史与撤销 | `services/core/audit.py`、`tables_auditlog` | P0（保留期）/ P1（历史） |
| R4 | 批量 / 直编写路径无幂等键 | `bulk_crud.py`、`routers/records.py` | P1 |
| R5 | 无数据一致性体检 / 修复 | 无 `cndb tables` 子命令 | P0 |
| R6 | 大表 DDL 无 dry-run（耗时 / 影响行数预估） | ADR 0038 仅保证原子回退 | P2 |
| R7 | 前端边界（未保存编辑丢弃、粘贴无保护） | `GridPage.tsx`、`cells/` | P0 |
| R8 | 解析器无 fuzz、行权限无属性测试 | `tests/` 现状 | P0 |
| F4 | 无服务端聚合 / 分组（`gridAggregationBar` 只统计选中行） | `gridAggregationBar.tsx`、`routers/records.py` | P2 |
| F5 | 深翻页 offset 全扫、导出 10000 行上限、非 grid 视图 2000 行上限 | `records.py::list_rows`、`transfer/exporting.py` | P2 |
| F6 | 校验规则表达力（无条件必填 / 正则 / 跨字段） | `field_types/`、`schemas/` | P2 |
| F7 | 批量编辑能力（查找替换 / 粘贴预览 / 跨页全选） | `bulk_crud.py`、`cells/` | P2 |
| F8 | 协作可见性（谁在看 / 刚改了什么） | 无 | P3（触发条件） |

## 暂不做（触发条件）

| 候选 | 为什么暂不做 | 触发条件 |
|---|---|---|
| 实时协同（CRDT / WebSocket / 多人光标） | 0139 + 0140 已覆盖 90% 场景；引入协同需要重写写路径与冲突模型 | 「同表 5 分钟内 ≥3 人编辑」占比 > 5% 且有明确用户投诉 |
| 字段级权限（按单元格授权） | 现有「字段隐藏」+ 行级权限已覆盖主要诉求；爆炸半径大 | 出现必须"同表不同人看不同列"的付费级需求 |
| 跨表事务 / 表间公式依赖图 | 与"轻量表格"定位冲突，复杂度接近自研数据库 | 有 ≥3 个真实业务流需要原子跨表写入 |
| 字段类型对外插件化 | `field_types/registry.py` 已内部可扩展，对外开放要先有沙箱与版本协议 | 内部准入清单跑满 3 个季度无事故 |

## 未决问题

- [x] ① 分期顺序：先 P1（协作可信）还是先 P0（止血）：**两条并行**，P0 为 S1 小项、不占主线。
- [x] ② 0139 / 0140 是否同批：**同批**（都动行表列与写路径，合并一次评审窗口）。
- [x] ③ 新增 H 条目：**H47**（行删除永不物理丢失）、**H48**（带基准的直编冲突不得静默覆盖）已入台账；审计写入不静默失败待 P0-2 立项时再确认。
- [x] ④ 保留期默认值：行回收站 **30 天**、审计 **180 天**（2026-11-24 确认）。
- [x] ⑨ P0-3 前端边界已落地：`useUnsavedGuard`（脏草稿时 `beforeunload` 拦截 + 切视图 / 切模式前确认）、`GridErrorBar`（行操作失败保留最近一次并提供显式重试，成功自动收起）；大范围粘贴保护经核实不适用（网格无多单元格粘贴入口）。**已知限制**：侧栏直接切到另一张表属于跨页面 Link 跳转，`BrowserRouter`（非 data router）下没有全局 `useBlocker`，未纳入拦截；如需覆盖须切到 react-router data router。
- [x] ⑩ P0-5 性能预算已落地：`@perf` 旅程新增「表格翻页」「表格内联编辑」两条，只断言「交互响应 <600ms / 单次长任务 <400ms」硬上限，基线缺失时只记录读数（`baselines.json` 目前为空，回填方式：同环境连续 3 次取中位数）。
- [x] ⑦ P0-2 审计 / 事件流保留期已落地（需求卡 0143）：`AUDIT_RETENTION_DAYS`（默认 180，0 关闭）+ `cndb tables purge-audit`（默认 dry-run，分批 1000）；审计读接口沿用既有端点。
- [x] ⑧ P0-4 随机输入 / 不变量测试已落地：导入解析器（CSV / TSV / 分号、XLSX、JSON）与行级权限矩阵（H15 / H17 / 并集语义 / 单调性）。未引入 hypothesis（避免新增依赖），用固定种子的 `random.Random` 保证可复现。
- [x] ⑥ P0-1 `cndb tables doctor` 已落地（需求卡 0142）：孤儿关联关系 / 失效 lookup 冗余列 / 孤儿排序索引 / 回收站体积四项，`--fix` 幂等且不删业务行；公式异常检测按成本后移。
- [x] ⑤ 0139 P2（保留期任务 + CLI + 回收站抽屉 + 备份携带软删状态）与 0140 P2（前端 If-Match + 409 提示 + 双上下文 e2e）已落地。

## 卡点

- [x] 每条需求句都有 C 编号约束（C1..C6 覆盖阶段承诺）
- [x] 未决 ③ / ④ 已确认（H47 / H48、30 天 / 180 天）
