# ADR 0139: 行回收站（删除统一软删 + 列表 / 恢复 / 彻底删除 / 保留期）

Status: Proposed（待评审）
Date: 2026-11-24
Related: `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/routers/bulk_crud.py`、`src/cndb/plugins/tables/services/core/lookup_sync.py`、`src/cndb/plugins/tables/services/core/links.py`、`src/cndb/plugins/tables/services/governance/merge.py`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/workspaces/services/storage.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/core/task_runner.py`、`frontend/src/api/records.ts`、`frontend/src/api/hooks.ts`、`frontend/src/pages/grid/GridPage.tsx`
需求卡片: `docs/requirements/0139-row-recycle-bin.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「删除统一软删」 | `bulk_delete` 改为软删（打 `_trashed` + `_trashed_at`），与 `trash_row` 同一实现；物理删除只保留给 `purge_row` / `purge_rows` / 保留期任务；治理合并（`governance/merge.py:136`）已是软删，不动 |
| C2 | 「回收站可列出」 | `GET /records?trashed=none\|only\|include`（`none` 默认，向后兼容 `include_trashed`）；行序列化对已删行附加 `_trashed_at`、`_trashed_by`（操作人取自 `tables_auditlog` 最近一条 `action='trash'`，不新增行内列） |
| C3 | 「可恢复」 | `restore_row` 保持 `_trashed=False` + `_trashed_at=NULL`；重复恢复幂等返回当前行（不 404） |
| C4 | 「彻底删除」 | 新增 `POST /records/{id}/purge`、`POST /records/purge`（`row_ids` ≤200）；只接受 `_trashed=1` 行，命中非已删行 → 400；成功后清理 link 关系并重算消费方 lookup 冗余列（复用 `delete_row` 现行逻辑） |
| C5 | 「保留期」 | 新增 `TRASH_RETENTION_DAYS`（默认 30，`0` 关闭）；`services/core/rows_retention.py::purge_expired_rows()` 按表分批（每批 ≤500）、幂等；后台入口 `cndb tables purge-trash --days N [--dry-run]`，生产挂 `deploy/` cron（与 `sync tick` 同范式） |
| C6 | 「软删后不失真」 | `trash_row` / `restore_row` 同事务调用 `sync_lookup_columns` + `resync_lookup_consumers_for_deleted_rows`（与硬删同口径），保证 `_lk_*` 下推过滤 / 排序 / COUNT 与实际可见行一致 |
| C7 | 「单一回收站口径」 | 删除 `_trash_table_name` / `DataTable.trash_table_name` 与 `storage.py` 对影子表的统计；回收站只有"原地标记"一种实现 |
| C8 | 「前端入口」 | 网格工具栏「回收站」抽屉（`RowRecycleBinDrawer`）：列表 / 恢复 / 彻底删除（Popconfirm）/ 批量恢复；无 `EDIT_RECORDS` 时隐藏入口 |
| C9 | （权限） | 列出按 `READ` + 读范围；恢复要求 `EDIT_RECORDS` + 写范围（越范围 404）；彻底删除同恢复；viewer 一律 403 |
| C10 | （备份） | 本期不改归档格式：只如实记录「已删行随字段列导出、恢复后成为活动行」这一现状（Context #10），随 P2 一起把软删状态纳入归档 |
| C11 | （兼容） | `include_trashed` 保留为 `trashed=include` 的别名；`DELETE /records/{id}?soft=false` 语义不变 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 单行删除是软删：写 `_trashed=True` + `_trashed_at=now()` | `records.py:951-985` | 单行删除可恢复 | 确认 C1 的一半 |
| 2 | **批量删除是物理 DELETE**，并同事务清 link | `records.py:1189-1226`（入口 `bulk_crud.py:108`） | 勾选多行删除即不可恢复，且与单行删除语义相反；用户以为"删了还能找回" | 确认 C1 的核心缺陷 |
| 3 | 治理合并已写 `_trashed=True/_trashed_at` | `governance/merge.py:136` | 与单行一致 | 确认（不改） |
| 4 | 行序列化剥掉 `_trashed` / `_trashed_at` | `records.py:1241` | 前端拿不到删除时间；`types/records.ts:191` 的 `_trashed_at?` 是死字段 | 新增 C2 |
| 5 | 无"只看回收站"筛选，只有 `include_trashed`（默认 false，含已删） | `routers/records.py:315,368` | 无法做回收站列表（含已删 = 混合展示） | 新增 C2 |
| 6 | 无 purge 端点、无保留期任务；`cndb` 已有运维子命令范式 | `cli/lookup.py`、`cli/views.py`、`cli/docs.py` | 已删行永久占库，只能连库手工删 | 新增 C4 / C5 |
| 7 | `trash_row` / `restore_row` 不重算 lookup 冗余列；硬删会重算 | `records.py:914-942`（硬删）、`lookup_sync.py:287` | 软删目标行后，消费方 `_lk_*` 仍是旧值 → 按 lookup 过滤 / 排序 / COUNT 与实际可见行不一致（ADR 0131 下推口径失真） | 新增 C6 |
| 8 | 预留"行回收站影子表"命名与用量统计，但**没有任何路径创建 / 写入该表** | `models.py:46,207`、`storage.py:126-127` | 两套回收站语义并存，读代码的人会以为行被搬到 `trash_*` | 新增 C7 |
| 9 | `ensure_link_targets_exist` 已排除软删目标 | `links.py:407-409` | 软删行不可被新关联；恢复后自动可用（不需迁移数据） | 确认（不改） |
| 10 | 归档备份**只导出字段列**（`colname_to_field` 过滤），`_trashed` / `_trashed_at` 不在载荷里；恢复按字段列 INSERT，软删列取默认值 | `workspace_backup.py:270-292`、`backup_io.py:290-315` | 已删行在备份里与活动行不可区分，恢复后**变成活动行**（回收站状态不随备份往返） | 新增 C10（已知限制 → P2） |

**核心缺陷（需求要补的）**：删除语义分裂 —— 单行是"可恢复的软删"，批量是"不可恢复的物理删"，且软删后下游派生数据（lookup 冗余列）不跟着失效；回收站既没有读路径也没有过期清理，行在库里只增不减。

设计目标（不变量）：

- **I1 行删除永不物理丢失**：用户可见的删除（单行 / 批量 / 治理合并）只打软删标记；物理删除只经 `purge` 或保留期任务，且必须显式传行 id。
- **I2 软删与硬删的下游一致**：任何"行消失"的路径（软删 / 硬删）都必须让消费方 lookup 冗余列与之一致；恢复必须回到一致状态。
- **I3 回收站单一实现**：行回收站只有"原地 `_trashed` 标记"一种口径，不存在影子表。
- **I4 权限不因回收站放宽**：回收站不扩大可见范围，恢复 / 彻底删除严格受写范围约束。

> I1 已登记为硬约束 **H47**（2026-11-24 人工确认，H27 / ADR 0119）。

## Decision

### 1. 数据模型

- **不新增列、不改物理表结构**：`_trashed` / `_trashed_at` 已由 `build_sa_table` 建出（`ddl.py:164-165`），存量表同样已有；`_trashed_by` 不落列，按需从 `tables_auditlog`（`action='trash'`, `target_id=row_id`）取最近一条的 `actor_id`。
- 回收站列表 = `_trashed=1` 的行；恢复 = 置回 `0` / `NULL`；彻底删除 = 物理 `DELETE`。
- 删除影子表预留命名（`models.py:46`、`models.py:207`）与 `storage.py:126-127` 的统计行。

### 2. 判定算法（唯一入口）

`services/core/records.py` 新增/收敛为三个入口，所有写路径必须复用：

| 入口 | 语义 | 复用方 |
|---|---|---|
| `trash_rows(engine, table, row_ids, db, *, user, enforce_row_rules)` | 批量软删（单行 = 长度为 1），同事务重算 lookup 冗余列，逐行写审计 `trash` | `DELETE /records/{id}`、`POST /records/bulk-delete`、治理合并（改调本入口） |
| `restore_rows(engine, table, row_ids, db, *, user)` | 幂等恢复（已恢复视为成功），重算 lookup 冗余列，写审计 `restore` | `POST /records/{id}/restore`、回收站批量恢复 |
| `purge_rows(engine, table, row_ids, db, *, user)` | 物理删除，**只处理 `_trashed=1` 的行**，清 link + 重算消费方 lookup，写审计 `purge` | `POST /records/{id}/purge`、`POST /records/purge`、保留期任务 |

保留期判定唯一入口：`services/core/rows_retention.py::purge_expired_rows(db, *, days=None, dry_run=False)` —— `days` 缺省取 `settings.TRASH_RETENTION_DAYS`；`days<=0` 直接返回 0（关闭）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/records` | 新增 `trashed=none\|only\|include`（默认 `none`）；`include_trashed=true` 映射为 `include`（兼容）；`trashed=only` 时行内附 `_trashed_at`、`_trashed_by` |
| `DELETE /{wid}/tables/{tid}/records/{id}` | 行为不变（默认软删）；`soft=false` 保留为内部/超管硬删路径，文档标注"不推荐，优先 purge" |
| `POST /{wid}/tables/{tid}/records/{id}/restore` | 幂等：已恢复返回 200（原为 404） |
| `POST /{wid}/tables/{tid}/records/{id}/purge` | **新增**：仅接受已删行，否则 400 |
| `POST /{wid}/tables/{tid}/records/purge` | **新增**：`{"row_ids": [...]}`，≤200 行，返回 `{"purged": n}` |
| `POST /{wid}/tables/{tid}/records/bulk-delete` | 语义改为软删；返回 `{"deleted": n}` 不变（字段名兼容） |
| `POST /{wid}/tables/{tid}/records/restore` | **新增**：批量恢复 `{"row_ids": [...]}` |

### 4. 边界与例外

1. 已删行不能被直接 `PATCH`（现状为 404，保持）；恢复后才能改。
2. `purge` 传入非已删行 → 整批 400，不做部分成功（避免"以为彻底删了其实还在"）；返回中列出越界 id，按 404 口径只给"不存在"，不泄露他人行。
3. 行级权限：`trashed=only` 列表受读范围过滤；恢复 / purge 受写范围过滤，越界视为不存在（404）。
4. 保留期任务只清理 `_trashed_at < now - days`；`_trashed_at` 为 `NULL` 的历史已删行（本 ADR 之前产生）视为"时间未知"，**不自动清理**，只在 `--dry-run` 报告中列出，由人工决定（避免上线即删数据）。
5. link：软删不动关系表；`purge` 清关系。lookup：软删 / 恢复 / purge 三者都重算消费方冗余列（I2）。
6. 公式 / lookup 字段无物理列，不进回收站快照（沿用现状）。

### 5. 迁移

- **无 alembic 迁移**：所需列已存在（`ddl.py:164-165`，存量表在建表时已带）。历史物理表若缺 `_trashed_at`（早期库），由 `build_sa_table` 之外的巡检命令 `cndb tables purge-trash --dry-run` 报告，不自动 ALTER。
- 无数据回填；`_trashed_at IS NULL` 的历史已删行按「边界 4」处理。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/records.ts` | `list({ trashed })`、`restoreMany`、`purge`、`purgeMany`；`RowResponse` 补 `_trashed_by?` |
| 页面 | `frontend/src/pages/grid/GridPage.tsx` | 工具栏「回收站」入口（`canEditRecords` 门控）+ 抽屉开关（lazy） |
| 组件 | `frontend/src/pages/grid/RowRecycleBinDrawer.tsx`（新增） | 已删行列表（字段摘要 / 删除时间 / 操作人）、恢复、彻底删除（Popconfirm 二次确认，文案含"不可恢复"）、批量恢复；空态 `.cn-state` |
| 样式 | `frontend/src/index.css` | 只新增 `--cn-*` token 驱动的回收站行样式（H29） |

### 7. 测试清单

**判定层（单测）**：`trash_rows` 批量软删 / 单行软删等价、`restore_rows` 幂等、`purge_rows` 只收已删行、`purge_expired_rows` 的 过期 / 未过期 / `days=0` / dry-run / 分批 / `_trashed_at IS NULL` 不清理。

**接口层**：`trashed=only|include|none` 三态；viewer 恢复 403、越行范围 404；`bulk-delete` 后行仍在物理表且 link 关系保留；`purge` 清理 link + 重算 `_lk_*`；软删后消费方 lookup 过滤不再命中、恢复后回填（C6）。

**迁移 / 备份**：归档往返后已删行仍为已删、`_trashed_at` 不变；旧归档（无 `_trashed_at` 值）恢复不报错。

**e2e（前端）**：`frontend/tests/e2e/critical/row-recycle-bin.spec.ts` —— 删除 3 行 → 打开回收站看到 3 行 → 恢复 1 行回网格 → 彻底删除其余 2 行 → 网格仍剩 1 行。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 语义统一 + 不变量：`trash_rows` / `restore_rows` / `purge_rows` 三入口 + `bulk-delete` 改软删 + 软删/恢复重算 lookup 冗余列 + 删影子表口径（C1 / C6 / C7） | 中（触及既有批量删除语义与派生列，需回归 link / lookup / 治理） |
| **P1** | API：`trashed` 三态、`_trashed_at` / `_trashed_by` 输出、`purge` / 批量恢复端点（C2 / C3 / C4） | 低 |
| **P2** | 保留期任务 + CLI + 前端回收站抽屉 + e2e（C5 / C8）+ 备份携带软删状态（C10） | 中（后台清理涉数据删除，必须 dry-run 先行；归档新增可选键需兼容旧包） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 回收站存储形态 | **原地 `_trashed` 标记** | 列已存在（`ddl.py:164`），恢复不需要跨表搬迁，行 id 稳定、link 关系天然保留 | 影子表 `trash_*`（现状只有命名无实现；搬迁要重写全部读路径与 link 解析，id 会变） | `records.py::trash_rows` |
| D2 | 批量删除语义 | **改为软删** | 与单行一致，符合 I1；前端不需要两套确认文案 | 保留物理删并加二次确认（用户仍无法找回，且与单行体验割裂） | `records.py::bulk_delete` → `trash_rows` |
| D3 | 删除操作人存储 | **读 `tables_auditlog`**，不新增行内列 | 审计已在写 `action='trash'` + `actor_id`；加列要改每张物理表 DDL | 行内加 `_trashed_by`（每表 ALTER + 回填，收益低） | `records.py` 序列化辅助 |
| D4 | 保留期默认与执行者 | **默认 30 天，`0` 关闭；CLI / cron 执行** | 与 `cndb sync tick`、`cndb views` 同一运维范式；不给请求路径加后台删除负担 | 应用内定时器（多进程重复执行、无租约） | `cli/tables.py`、`deploy/` |
| D5 | 历史 `_trashed_at IS NULL` 已删行 | **不自动清理**，仅 dry-run 报告 | 上线即批量物理删除存量数据不可逆 | 按"最早时间"推定清理（错误删除风险） | `rows_retention.py` |
| D6 | `purge` 部分失败处理 | **整批 400，不做部分成功** | 用户预期是"彻底删掉这些"，部分成功无法表述 | 逐行忽略失败（静默残留） | `routers/records.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：误删可自助恢复；批量删除不再不可逆；lookup 下推与实际可见行一致（顺带修掉一个数据失真）；库内不再无限积累不可见行。
- **负向**：批量删除改为软删后，物理行保留至保留期到期，短期库体积上升；`bulk-delete` 的处理成本从一次 DELETE 变为 UPDATE + 派生列重算（大批量需分批）；备份暂不保留回收站状态（P2 收口）。
- **风险与缓解**：保留期任务误删 → 强制 `--dry-run` 报告 + `TRASH_RETENTION_DAYS=0` 可一键关闭 + 备份兜底（C10）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 行级权限 | 行读 / 写范围 | 回收站不扩大可见范围，恢复与 purge 受写范围约束 | ADR 0004（I1 / I6 口径沿用） |
| lookup 冗余列 | `_lk_*` 物理列 | 软删 / 恢复必须与硬删同样重算冗余列 | ADR 0131 |
| 修改申请 | 删除申请（202） | 修改申请 merge 后的删除同样走 `trash_rows`（不物理删） | ADR 0005 |
| 工作区备份 | 归档载荷 | 已删行随备份往返，语义不变 | ADR 0075 |
| 存储用量 | `workspace_table_bytes` | 只统计活动物理表，去掉影子表统计 | ADR 0024 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/bulk_crud.py`、`src/cndb/plugins/tables/services/core/lookups.py`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/workspaces/services/storage.py` | `tests/test_row_recycle_bin.py` | `ff4be4c7` |
| P1 | 已落地 | `src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/schemas/models.py`、`src/cndb/plugins/tables/services/core/audit.py` | `tests/test_row_recycle_bin.py` | `ff4be4c7` |
| P2 | 已落地 | `src/cndb/plugins/tables/services/core/rows_retention.py`、`src/cndb/cli/tables.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/grid/RowRecycleBinDrawer.tsx` | `tests/test_rows_retention.py`、`frontend/src/pages/grid/RowRecycleBinDrawer.test.tsx`、`frontend/tests/e2e/critical/row-recycle-bin.spec.ts` | `91e78f8b` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已实现；e2e `row-recycle-bin.spec.ts` 待本地/CI 实跑验证。
- 已完成：`trash_rows` / `restore_rows` / `purge_rows` 三入口；`bulk_delete` 改软删；软删 / 恢复重算 lookup 冗余列；读路径（`_read_source_values`）排除软删目标行；`trashed=none|only|include` 三态 + 删除时间 / 操作人；`purge` / 批量恢复端点；删除影子表命名与用量统计；`rows_retention.purge_expired_rows` + `cndb tables purge-trash`（30 天 / dry-run / `days=0` 关闭 / 时间未知不清理）；前端工具栏「回收站」+ `RowRecycleBinDrawer`（恢复 / 彻底删除二次确认）；归档携带软删状态并在恢复时还原。
- 下一步：跑 `make e2e`（`critical/row-recycle-bin.spec.ts`）；观察回收站体积与保留期任务执行情况后回填本表。
- 已知坑：
  - `_trashed_at` 在早期库可能缺失列，本 ADR 不做自动 ALTER（只报告）。
  - 软删后 link 关系仍在，但 `attach_links` / lookup 解析都排除软删目标（`links.py:407`、`lookups.py::_read_source_values`），因此回收站行对外表现为"已删除"；恢复即恢复显示。
  - **已知限制（P2 修）**：工作区备份只导出字段列，`_trashed` / `_trashed_at` 不随归档往返 —— 恢复到新库后，原回收站里的行会以活动行出现（数据不丢，但状态丢失）。
  - `bulk_delete` 现有调用方（前端 `recordsApi.bulkDelete`、治理、测试）必须同批更新，否则会出现"以为硬删了其实软删"的断言失败。
  - 删除影子表命名会改动 `tests/test_tables_plugin.py:236,299` 的既有断言。
- 最近一次全绿：`make flow` @ `1d523b4b`（2026-11-23）
