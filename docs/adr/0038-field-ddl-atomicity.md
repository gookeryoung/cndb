# ADR 0038: 字段物理 DDL 的原子回退（新增必填字段 / 建表 / 类型切换）

Status: Proposed（待评审；全部阶段已落地）
Date: 2026-10-26
Related: `src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/tables/services/fields/field_import.py`、`src/cndb/plugins/tables/services/importing/importer.py`
需求卡片: `docs/requirements/0038-field-ddl-atomicity.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 已有数据时新增唯一非空字段报 `Cannot add a NOT NULL column` | 保存前预检：`required=True` 且有物理列 + 物理表已有任意行 → 400，文案给出「先建可空字段、补齐数据后再设必填」路径 |
| C2 | 报错后依然创建了字段 | 写序改为 **物理 DDL 先行、metadata 后提交**；加列或唯一索引任一步失败都逆向删除本次已建物理对象（先删索引再删列），不产生 DataField |
| C3 | 事后无法编辑，提示内部服务器错误 | 删除字段前检查物理列是否存在：历史孤儿字段（无物理列）按「已删除」直通，不再 `DROP COLUMN` 报 `no such column` |
| C4 | 原子回退处理 | 同类路径统一口径：建表/复制表 DDL 失败回滚 DataTable；link↔物理列互转改「先建后删」；字段导入非空表必填字段提前 400 |
| C5 | 分析还有无类似情况 | Context 表逐条核对全部「metadata + 物理 DDL」路径，缺口按 D2 口径补齐并回归 |

## Context

现状逐条核对（以代码为准，行号取本次修复前版本）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `create_field` 先 `db.commit()` 落 DataField、再 `add_column` 建物理列；DDL 异常只 `db.rollback()`（对已提交状态无效） | `routers/fields.py`（原 170-230 行） | 失败后 metadata 有字段、物理表无列 → 字段列表正常但行读写/字段编辑都 500，即用户上报现象 | C2 / C3 确认 |
| 2 | 新增必填字段直接交给 DDL；SQLite / PostgreSQL 的 `ADD COLUMN NOT NULL` 要求自带非 NULL 默认值 | `services/core/ddl.py:193-222` | 非空表必然 `OperationalError`，用户只看到底层 SQL 文案 | C1 确认 |
| 3 | `delete_field` 无条件 `DROP COLUMN` | `routers/fields.py`（原 507-530 行） | 对上述孤儿字段再删一次即 `no such column`，用户无自救路径 | C3 确认 |
| 4 | 新建表 / 复制表提交 metadata 后执行 `ddl_create`，失败无回退 | `routers/tables.py:205-214`、`routers/tables.py:593-601` | 残留「有 DataTable、无物理表」的孤儿表，列表可见但打开即报错 | C4 新增 |
| 5 | link 改物理列时先 `drop_link_table` 再 `add_column` | `routers/fields.py`（原 386-400 行） | 补列失败时 metadata 回退成 link，但关联表已被删 → 关联数据与结构同时丢失 | C4 新增 |
| 6 | 字段导入 / 导入自动加列已是「DDL 先行 + 逆向清理」，但必填字段进非空表仍抛原始 SQL 错 | `services/fields/field_import.py:256-288`、`services/importing/importer.py:829-905` | 原子性无问题，报错不可读、用户不知如何操作 | C4 部分确认 |
| 7 | 编辑字段改必填/唯一已有数据预检（空值 / 重复值），走 `rebuild_column` | `routers/fields.py:313-345` | 数据层违规已提前 400；物理重建失败回退 metadata，无需改动 | 排除 |

**核心缺陷**：物理 DDL 与 metadata 提交没有统一事务边界，失败路径只回滚 ORM 而不撤销已提交 metadata / 已建物理对象，任何一步失败都可能留下「一半结构」。

设计目标（不变量）：

- **I1 无孤儿字段**：请求返回非 2xx 时，DataField 与物理列要么都不存在，要么都保持请求前状态。
- **I2 无孤儿表**：建表/复制表返回非 2xx 时，DataTable 不落库。
- **I3 拒绝优于占位**：无法为存量行提供真实值的 `NOT NULL` 列一律在保存前拒绝，不用空串/0 等占位默认值污染必填语义。
- **I4 先建后删**：同一请求内的结构切换先建立目标结构，成功后再删旧结构，失败时旧结构仍在。

## Decision

### 1. 数据模型

无。不新增表 / 列 / 枚举；DataField、DataTable 字段不变。

### 2. 判定算法（唯一入口）

- 新增预检：`table_has_rows(engine, table.db_table_name)`（`services/core/ddl.py`）—— 物理表不存在或空表返回 False，任意行（含软删除行）返回 True。
- 物理列存在性：`column_exists(engine, table_name, column)`（同上），表或列缺失均返回 False。
- 删除字段的判定：`has_physical_column` 为真且 `column_exists` 为真才执行 `drop_column`；否则视为无物理列、直接完成软删除。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /{wid}/tables/{tid}/fields` | 非空表新增必填物理字段 → 400；DDL/唯一索引失败 → 500 且不落 metadata、不残留物理对象 |
| `PATCH /{wid}/tables/{tid}/fields/{fid}` | link → 必填物理列且表已有数据 → 400；类型切换改「先建后删」，失败回退 metadata 且旧结构保留 |
| `DELETE /{wid}/tables/{tid}/fields/{fid}` | 物理列不存在的孤儿字段可正常删除（204） |
| `POST /{wid}/tables`、`POST /{wid}/tables/{tid}/copy` | 物理建表失败 → 500 且回滚 DataTable |
| `POST /{wid}/tables/{tid}/fields/import` | 目标表已有数据且计划含必填物理字段 → 400（不再落到 DDL 异常） |

### 4. 边界与例外

1. 空表新增必填字段不受限（SQLite 空表 `ADD COLUMN NOT NULL` 合法），保持原行为。
2. 非必填（nullable）字段不受预检影响；存量行以 NULL 填充，唯一索引对 NULL 不判重。
3. `link` / `lookup` 无物理列，不参与必填物理列预检；其必填约束仍由行级校验（`find_null_link_rows`）负责。
4. 已存在的历史孤儿字段不自动批量修复：用户从字段列表删除该字段即可清理（C3）；不启动期扫描，避免启动耗时与误删风险。
5. 采用占位默认值（空串 / 0）让 DDL 通过被否决：会静默改变必填语义并污染存量数据。

### 5. 迁移

无。属于运行时 DDL 行为修正，不涉及 Alembic；历史孤儿字段由用户按字段删除清理。

### 6. 前端

无。仍复用既有错误提示通道（400 detail 直接展示）。

### 7. 测试清单

**判定层（单测）**：`ddl.table_has_rows` 对不存在表 / 空表 / 有行三种结果。

**接口层**：
- 非空表新增唯一非空字段 → 400，无 metadata、物理列不变、行编辑仍 200
- 非空表新增可空唯一字段 → 201 且物理唯一索引存在
- 加列失败 / 唯一索引失败 → 500 且无孤儿字段、物理列回缩
- 删除无物理列的孤儿字段 → 204
- link → 物理列时补列失败 → 500，字段仍为 link 且关联表仍在
- link → 必填物理列且表有数据 → 400，字段仍为 link
- 建表 / 复制表 `ddl_create` 失败 → 500 且无孤儿表
- 字段导入必填字段进非空表 → 400 且目标字段集合不变

**迁移 / 备份**：不涉及。

**e2e（前端）**：不涉及（后端错误语义，现有错误提示已覆盖）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 新增字段 DDL 先行 + 逆向清理、必填预检、孤儿字段可删除、`ddl.table_has_rows` / `column_exists` | 低 |
| **P1** | 建表 / 复制表失败回滚 metadata、link↔物理列先建后删、link→必填预检 | 低 |
| **P2** | 字段导入必填字段 400 预检与文案 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 非空表新增必填字段如何处置 | 保存前 400 拒绝，提示先建可空字段再补齐数据后设必填 | SQLite/PostgreSQL `ADD COLUMN NOT NULL` 均要求非 NULL 默认值；新字段无法为存量行提供真实值 | ① 用空串/0 占位默认值：污染必填语义与数据；② 允许 DDL 失败让用户看 SQL 错：不可操作 | `routers/fields.py` |
| D2 | metadata 与物理 DDL 的提交顺序 | 物理 DDL 先行，全部成功后再提交 metadata；失败逆向撤销本次物理对象 | I1 无孤儿字段；与 `field_import` / `importer._auto_add_fields` 既有事务策略一致 | 先提交 metadata 再 DDL（本次缺陷根因） | `routers/fields.py`、`routers/tables.py` |
| D3 | 历史孤儿字段的恢复 | 不启动期扫描；删除字段时物理列缺失按已删除处理 | 用户上报场景已产生孤儿字段，必须能自助清理；启动扫描有误删与耗时风险 | 自动批量修复（修复需猜测数据/结构意图，风险高） | `routers/fields.py`、`services/core/ddl.py` |
| D4 | 结构切换的建立顺序 | 先建目标结构、成功后再删旧结构 | I4；link→物理列失败不得丢关联表，物理列→link 失败不得丢列数据 | 先删后建（失败即不可逆丢失） | `routers/fields.py` |
| D5 | 字段导入遇必填字段进非空表 | 计划阶段 400 拒绝，不自动降级为可空 | 静默降级会改变源字段约束语义；已有 DDL 逆向清理保证原子性，缺的只是可读报错 | 自动转可空（静默改变约束） | `services/fields/field_import.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：物理结构与 metadata 不再出现半成品；用户对「非空表加必填字段」有明确可操作提示；历史坏表可自助恢复。
- **负向**：新增字段成功路径多一次探测 SQL（`SELECT 1 … LIMIT 1`）；`required=True` 在非空表上被明确拒绝，需要「先可空、后必填」两步操作。
- **风险与缓解**：历史孤儿字段需用户手动删除，帮助文案已在错误提示中给出（先可空路径）；后续如需批量体检可另立 ADR。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/tables/services/core/ddl.py` | `tests/test_field_edit_validation.py`、`tests/test_cov_links_ddl.py` | 4d9456f8 |
| P1 | 已落地 | `src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/routers/fields.py` | `tests/test_tables_coverage.py`、`tests/test_field_edit_validation.py` | 4d9456f8 |
| P2 | 已落地 | `src/cndb/plugins/tables/services/fields/field_import.py` | `tests/test_fields_import.py` | 4d9456f8 |

## 交接（会话结束更新）

- 当前阶段：全部期已落地，待人工评审 Status
- 已完成：P0 / P1 / P2
- 下一步：人工评审后把 Status 改为 Accepted；提交后回填落地表 sha
- 已知坑：SQLite 空表 `ADD COLUMN NOT NULL` 合法、非空表不合法；物理 DDL 事务与 ORM Session 事务相互独立，`db.rollback()` 撤销不了已提交的 metadata；测试须用真实非空物理表复现
- 最近一次全绿：`make cov`（5449 passed / 3 skipped，覆盖率 96.98%）@ 2026-10-26
