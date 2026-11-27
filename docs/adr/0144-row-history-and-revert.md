# ADR 0144: 行级历史与撤销（只存 diff + 撤销生成新版本）

Status: Accepted（2026-11-24 需求方指示「P1+P2」实施，范围沿用已评审的路线图 0141 P1）
Date: 2026-11-24
Related: `src/cndb/plugins/tables/models.py`、`src/cndb/alembic/versions/ea1b2c3d4e5f_add_row_revision_and_idempotency.py`、`src/cndb/plugins/tables/services/core/row_history.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/records.py`
需求卡片: `docs/requirements/0144-row-history-and-revert.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「一次写操作 = 一条版本」 | `record_revision()` 在 create / update / trash / restore / revert 后追加；`version = max(version)+1`，`(row_id, version)` 唯一 |
| C2 | 「只记变化」 | `build_diff()` 只保留变化字段，剔除 `_` 前缀系统键；update 无变化 → 不记版本 |
| C3 | 「撤销生成新版本」 | `revert_revision()` 取目标版本 diff 的 `old` 作为写回值，调用 `update_row(history_op="revert")` |
| C4 | 「写放大可控」 | 批量链路（`bulk_update` / `bulk_update_rows`）不写历史；`update_row(record_history=False)` 可关 |
| C5 | 「可审计」 | 存 `actor_id` + `actor_name` 快照；`row_id` 不设外键，purge 后历史保留 |
| C6 | （接口） | `GET /records/{id}/history`、`POST /records/{id}/revert/{version}`；读口径 404、写口径复用双轨分派 |
| C7 | （前端） | 本期不做 UI（见「已知限制」） |
| C8 | （兼容） | 新表 + 迁移，存量零迁移；历史写入尽力而为 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 审计 `tables_auditlog` 只存「谁在何时做了什么」+ 整行快照 `detail` | `services/core/audit.py` | 能看到某个时刻的行快照，但拿不到"某字段从 A 改成 B"，也无法按版本撤销 | 新增 C1/C2 |
| 2 | 行写入路径已有统一入口 `update_row` / `trash_rows` / `restore_rows` / `create_row` | `records.py` | 历史只需挂在这四处，不需逐路由改造 | 确认 C1 |
| 3 | 导入 / 同步走高吞吐批量链路 | `bulk_update` / `bulk_update_rows` | 逐行写历史会造成写放大 | 新增 C4 |
| 4 | 行物理删除（purge）后行本身消失 | `records.py::purge_rows` | 历史若加 `row_id` 外键会被级联清理，失去审计价值 | 新增 C5 |
| 5 | 修改申请轨道已有 `base_values` 冲突检测 | ADR 0005 | 撤销在申请轨道上也要给差量 | 确认 C6 |

**核心缺陷（需求要补的）**：行改动只有「审计快照 + 当前值」，没有版本链 —— 用户误改后无法自助回退，排查"这个字段被谁改成这样"只能靠翻审计快照人工比对。

设计目标（不变量）：

- **I1 版本单调**：同一行的 `version` 严格递增且唯一；撤销不回退版本号。
- **I2 diff 最小化**：只存变化字段，系统 / 派生键（`_etag` / `_rev` / 软删元数据）永不进入 diff。
- **I3 历史只增不改**：任何入口不得修改或删除已写入的版本（表级清理仅随数据表删除级联）。
- **I4 历史不阻塞主路径**：历史写入失败只记日志，主写操作照常成功。

> I2 / I3 属数据口径，已由单测钉住；如需登记为硬约束（H 条目）须人工确认后补入 `docs/CONSTRAINTS.md`（H27）。

## Decision

### 1. 数据模型

- 新表 `tables_recordrevision`：`id`、`table_id`（FK CASCADE）、`row_id`（**无外键**）、`version`、`op`、`actor_id`（FK SET NULL）、`actor_name`（快照）、`diff`（JSON）、时间戳；唯一键 `(row_id, version)`，索引 `table_id` / `row_id` / `actor_id`。
- 与 `tables_idempotencykey` 同一条迁移 `ea1b2c3d4e5f`，可重入，downgrade 可还原。

### 2. 判定与写入口（唯一入口）

| 入口 | 语义 |
|---|---|
| `build_diff(before, after)` | 变化字段集合（剔除 `_` 前缀键；最多 200 字段，超出截断并告警） |
| `record_revision(db, table, row_id, op, before=, after=, user=)` | 追加版本（尽力而为；update 无 diff 时不写） |
| `list_revisions(db, table, row_id, limit=50)` | 版本倒序 |
| `revert_revision(db, table, row_id, version, user=)` | 按目标版本 `old` 写回，生成新版本 |
| `revert_values(revision)` | 把版本折算成写回值（修改申请轨道复用） |

调用点固定四处：`create_row`（create）、`update_row`（update / revert）、`trash_rows`（trash）、`restore_rows`（restore）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/records/{rid}/history` | **新增**：`limit` 默认 50（1..200），返回 `version` / `op` / `actor_id` / `actor_name` / `diff` / `created_at` |
| `POST /{wid}/tables/{tid}/records/{rid}/revert/{version}` | **新增**：恢复该版本之前的值；版本不存在 404；写范围外 / 不可直编按既有双轨（202 修改申请 / 403 / 404） |

### 4. 边界与例外

1. 行不在调用者读范围 → 历史 404（不泄露存在性）。
2. `record_history=False` 的写路径（批量 / 导入 / 同步 / 运维脚本）不产生版本。
3. 已 purge 的行：历史仍在，但接口按「行不存在」404（行已不可见）。
4. 撤销只回写 diff 中出现的字段；期间被他人改过的其他字段保持不变（不做整行覆盖）。
5. diff 最多 200 字段，超出截断并 `logger.warning`（不静默丢且不阻塞写入）。

### 5. 迁移

- 单条 alembic `ea1b2c3d4e5f`（`down_revision=d1e2f3a4b5c6`），可重入：表 / 唯一约束已存在则跳过；downgrade 完整删除两表。
- 无数据回填；存量行没有历史（首次修改起才有 v1 之后的版本）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 本期 | 无 | 只交付后端 + 接口；行详情「历史」时间线与撤销入口列为后续（C7） |

### 7. 测试清单

**判定层**：`build_diff`（只变化 / 增删键 / 相同）、`record_revision`（create v1、update 只含变化字段、无变化不写、trash/restore 各一版、`record_history=False` 跳过、actor_name 快照、版本单调）。

**接口层**：历史列表形状与倒序、撤销后值回退且版本 +1、行不存在 404、版本不存在 404。

**迁移**：`HEAD_REVISION` 更新为 `ea1b2c3d4e5f`，head 校验与既有迁移用例全绿；两表在元数据中可查（防"只加模型忘迁移"）。

**前端**：本期无（C7）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 + 迁移 + `row_history` 服务 + 四处写入口接入 | 中（触及核心写路径） |
| **P1** | 历史 / 撤销接口 + 权限与双轨分派 | 低 |
| **P2** | 前端时间线 UI + 撤销入口（**未开始**） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 存什么 | **只存 diff** | 整行快照会把大字段重复落库；审计已有快照 | 整行快照每版（存储放大 N 倍） | `row_history.build_diff` |
| D2 | 撤销语义 | **生成新版本** | 可反复撤销、可审计；历史只增不改（I3） | 删除目标版本之后的所有版本（审计断链、不可恢复） | `revert_revision` |
| D3 | 行 id 外键 | **不加外键** | purge 后历史仍有审计价值 | 外键级联（行一删历史就没了） | `models.py::RecordRevision` |
| D4 | 批量链路 | **不记历史** | 导入 / 同步是万行级写入，逐行版本会拖垮库 | 全部记录（写放大） | `records.py` 调用点 |
| D5 | 系统键处理 | **`_` 前缀一律不进 diff** | `_etag` / `_rev` 的变化是并发控制副产物，不是用户改动 | 全字段记录（每次编辑都多噪声字段） | `build_diff` |

门禁：`Proposed → Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：行改动有版本链，可逐版本查看前后值并自助撤销；与审计（谁做）互补；为前端时间线提供数据。
- **负向**：每次用户写多一条元数据行 + 一次 commit（`record_revision` 独立提交）；批量链路不记历史意味着导入无法逐行回退（符合预期）。
- **风险与缓解**：历史表随时间增长 —— 已提供 `purge-old-audit` 之外，历史清理未做（见「已知限制」，后续可加保留期）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 审计 | `tables_auditlog` | 审计=谁做了什么（整行快照），历史=字段级前后值；两者并存互不替代 | ADR 0004 / 本次 |
| 修改申请 | `base_values` | 撤销在申请轨道上提交差量，不绕过冲突检测 | ADR 0005 |
| 行回收站 | `_trashed` | trash / restore 也记版本（可见性变化可追溯） | ADR 0139 |
| 备份 | 归档 | 历史是流水，不进备份（与审计同口径） | ADR 0075 |
| 并发控制 | `_rev` / `_etag` | `_rev` 不进 diff；撤销与直编共用 `update_row` | ADR 0140 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/models.py`、`src/cndb/alembic/versions/ea1b2c3d4e5f_add_row_revision_and_idempotency.py`、`src/cndb/plugins/tables/services/core/row_history.py`、`src/cndb/plugins/tables/services/core/records.py` | `tests/test_row_history_idempotency.py` | `58a363f8` |
| P1 | 已落地 | `src/cndb/plugins/tables/routers/records.py` | `tests/test_row_history_idempotency.py` | `58a363f8` |
| P2 | 已落地 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx`（时间线 + 逐版本「恢复到此版本前」）、`frontend/src/api/records.ts`（history / revert 两个 API） | `frontend/src/pages/grid/gridPolish.test.tsx`（op 文案映射与 diff 摘要两个纯函数 + 抽屉渲染历史、仅非首版提供撤销入口） | `9a287b7a` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部已落地。
- 已完成：模型 + 迁移 + diff 最小化 + 四处写入口 + 历史/撤销接口 + 权限与双轨分派；前端行详情「字段变更历史」时间线（版本 / 操作人 / 时间 + 「字段：旧 → 新」摘要，>5 折叠）与逐版本「恢复到此版本前」（Popconfirm；无直编权限走修改申请轨道）。
- 下一步：历史表保留期清理（可复用 `purge-audit` 范式）——属独立事项，不在本 ADR 分期内。
- 已知坑：
  - `record_revision` 独立 `commit`，因此它出现在主写事务之后；主写回滚时不会留下历史（顺序保证）。
  - diff 只回写出现过的字段：撤销不会覆盖期间别人改的其他字段（这是有意的）。
  - 历史表无保留期，长期运行需清理（未做，记在 Consequences）。
- 最近一次全绿：`make flow` @ `58a363f8`（2026-11-24，P0-P1）；P2 @ `9a287b7a`（2026-11-25）；2026-11-27 复核 `gridPolish.test.tsx` 9 例全绿。
