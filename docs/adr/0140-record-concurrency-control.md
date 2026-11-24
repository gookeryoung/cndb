# ADR 0140: 直编并发冲突检测（行版本 `_rev` + 可选 `If-Match`）

Status: Proposed（待评审）
Date: 2026-11-24
Related: `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/routers/bulk_crud.py`、`src/cndb/plugins/tables/schemas/models.py`、`src/cndb/plugins/tables/services/governance/merge.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/transfer/exporting.py`、`src/cndb/core/errors.py`、`frontend/src/api/hooks.ts`、`frontend/src/api/records.ts`、`frontend/src/api/client.ts`、`frontend/src/pages/grid/GridPage.tsx`
需求卡片: `docs/requirements/0140-record-concurrency-control.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「可选乐观并发」 | `PATCH /records/{id}` 支持 `If-Match: v1-<id>-<rev>`；服务端解析 rev 后条件更新 `WHERE id=? AND _rev=?`，rowcount=0 时区分「不存在 / 超范围」（404）与「版本过期」（409 record_stale）；不带 `If-Match` 时走原无条件更新 |
| C2 | 「错误契约一致」 | 409 抛 `core/errors.py::ConflictError("该行已被他人修改，请刷新后重试", code="record_stale")`；响应体仍是 `{"detail","code"}` |
| C3 | 「所有写路径自增版本」 | 版本自增下沉到写入口：`update_row` / `bulk_update` / 导入 upsert（`records.py::upsert_rows`）/ 修改申请合并 / `matrix_upsert` / `restore_rows` 全部 `SET _rev=_rev+1`；插入默认 `0` |
| C4 | （兼容） | 行载荷只新增 `_etag`；`_rev` 不进 `_row_to_dict` 的键空间（显式排除）；字段 / 视图 / 表单配置不感知该列 |
| C5 | 「前端冲突提示」 | `useUpdateRowOptimistic` 从 cache 行读 `_etag` 并回传 `If-Match`；409 → 回滚乐观写入 + 行内提示 + 「载入最新值」；不自动重放写 |
| C6 | （迁移） | `ddl.py::ensure_row_version_column(engine/conn, table)`：幂等 `ALTER TABLE ADD COLUMN _rev INTEGER NOT NULL DEFAULT 0`，读 / 写 / 导出前按需补齐；新表由 `build_sa_table` 建出 |
| C7 | （数据出口） | `_rev` 永不出现在 CSV / XLSX / JSON 导出与备份字段快照中（这些路径按 `active_fields()` 取列，天然排除；补一条断言钉住） |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `PATCH /records/{id}` 只收 `values`，无基准 | `schemas/models.py:268`、`routers/records.py:588` | 两人同时改同一格：后写静默覆盖，双方都以为保存成功 | 确认 C1 的核心缺陷 |
| 2 | `update_row` 无条件 `UPDATE ... WHERE id=?` | `records.py:832-913` | 最后写入者胜，无任何痕迹 | 确认 C1 |
| 3 | 物理行无 `created_at/updated_at`，也无版本列 | `ddl.py:150-168` | 无法用时间戳做条件更新（也没有"值哈希"以外的替换方案） | 新增 C6 |
| 4 | 修改申请有 base_values 字段级漂移检测 | ADR 0005 | 只有 viewer / 关闭直编路径受保护；owner/editor 直编无保护 | 确认（范围不同，不重复实现） |
| 5 | 前端单元格写入唯一入口是乐观更新 hook | `frontend/src/api/hooks.ts:130-191` | 409 回滚与提示只需改一处 | 确认 C5 |
| 6 | 其它写路径（批量 / 矩阵 / 导入 / 合并 / 恢复）直接改行 | `bulk_crud.py`、`records.py:409`、`importing/importer.py`、`governance/merge.py` | 若不自增版本，编辑器带旧 etag 会覆盖导入刚写入的值（检测失效） | 新增 C3 |
| 7 | 前端错误归一化只保留 `detail`，丢弃 `code` | `frontend/src/api/client.ts:155-163` | 无法区分 409 冲突与其它错误 | 新增 C2 的前端侧 |
| 8 | 懒补列已有成熟范式（`_lk_*`） | `ddl.py:222-270` `ensure_lookup_columns` | 无需 alembic 迁移，旧库按需升级 | 确认 C6 |
| 9 | 导出按 `active_fields()` 取列 | `transfer/exporting.py` | `_rev` 天然不出现 | 确认 C7 |

**核心缺陷（需求要补的）**：直编写路径没有任何"我改的是我看到的那一版"的语义 —— 并发编辑静默互相覆盖，而协作侧（修改申请）早就用 `base_values` 做了同类保护，只有直编没有。

设计目标（不变量）：

- **I1 带基准的写入不得静默覆盖**：客户端提供 `If-Match` 时，版本不一致必须 409 且不落库。
- **I2 版本单调**：任何改变该行可见数据的写路径都必须让 `_rev` 严格递增；`_rev` 只增不减（恢复也不回退）。
- **I3 不带基准时零行为变化**：未升级客户端（无 `If-Match`）的写入结果与改造前逐条一致。
- **I4 版本列不外泄**：`_rev` 只用于并发控制与 `_etag` 计算，不进字段体系、筛选 / 排序、导出与备份。

> I1 已登记为硬约束 **H48**（2026-11-24 人工确认，H27 / ADR 0119）。

## Decision

### 1. 数据模型

- 物理表新增系统列 `_rev INTEGER NOT NULL DEFAULT 0`（与 `_trashed` / `_trashed_at` 同级，`build_sa_table` 建出）。
- 存量表按需懒补：`ensure_row_version_column(engine, table, *, conn=None)`，幂等（先 `inspect().get_columns()` 判断），失败按"该表暂不支持并发校验"降级并告警，不阻断读写。
- 无新表、无 alembic 迁移。

### 2. 判定算法（唯一入口）

| 入口 | 语义 |
|---|---|
| `row_etag(row_id: int, rev: int) -> str` | `v1-<id>-<rev>`，纯函数；读路径与写校验共用 |
| `parse_if_match(value: str \| None) -> tuple[int, int] \| None` | 解析 `v1-<id>-<rev>`；格式非法 → 400 `invalid_if_match`（不静默忽略） |
| `update_row(..., expected_rev: int \| None = None)` | `expected_rev` 非空时：`UPDATE ... WHERE id=? AND _rev=?` + `_rev=_rev+1`；`rowcount==0` 时再查一次，存在但 rev 不同 → `ConflictError(code="record_stale")`，不存在 / 超范围 → `None`（路由转 404） |
| `bump_rev(sa_table, row_ids)` | 内部写路径版本自增的唯一 SQL 片段（`SET _rev=_rev+1`），批量更新 / 导入 upsert / 合并 / 矩阵 / 恢复复用 |

判定顺序（路由层固定）：`get_table_or_404` → 写模式分派（直编 / 修改申请）→ 行写范围判定 → `If-Match` 解析 → `update_row`（含版本条件）→ 值校验（`ValueError` → 400）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/records` | 行载荷新增 `_etag`（删除时间等其它键不变） |
| `GET /{wid}/tables/{tid}/records/{id}` | 同上 |
| `PATCH /{wid}/tables/{tid}/records/{id}` | 新增可选请求头 `If-Match`；409 `record_stale` 且不落库；格式非法 400 `invalid_if_match` |
| `POST /{wid}/tables/{tid}/records` | 返回行同样带 `_etag`（rev=0），供紧随其后的编辑使用 |
| `POST /records/bulk-delete` / `bulk-update` / `matrix-upsert` / 导入 | 不校验 `If-Match`，但必须 `bump_rev`（C3）；响应不变 |

### 4. 边界与例外

1. `If-Match: *` 按"行存在即视为匹配"处理（RFC 9110 语义），仍要求权限 / 范围通过。
2. 修改申请路径（202）不参与 `If-Match`：其冲突检测由 ADR 0005 的 `base_values` 负责，避免两套口径叠加。
3. 导入 / 数据同步 / 合并 / 矩阵 upsert 不逐行校验基准（拿不到 per-row etag），只保证 `bump_rev`；已知后果：编辑器持有的旧 etag 在这些路径之后再提交会 409（这正是期望行为）。
4. `_rev` 表列缺失（懒补失败）时：读路径不返回 `_etag`，写路径忽略 `If-Match` 并记 warning（降级而非拒绝服务）。
5. 恢复（`restore_rows`）也 `bump_rev`（I2：只增不减）。
6. 恢复 / purge / 修改申请合并等内部路径不受 409 影响（它们不接收外部 etag）。

### 5. 迁移

- 无 alembic 迁移；`_rev` 懒补（`ensure_row_version_column`），由 `GET /records`、`PATCH`、导出、`cndb tables doctor` 触发。
- 无数据回填（`DEFAULT 0` 即合法初始版本）。
- 备份 v16 不受影响（备份按字段导出，`_rev` 不在其中）；恢复后行 `_rev` 从 0 起，客户端持有的旧 etag 会 409 → 期望行为（恢复即换库）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 类型 | `frontend/src/api/types/records.ts` | `RowResponse` 增 `_etag?: string` |
| API 封装 | `frontend/src/api/records.ts` | `update(..., { ifMatch })` → `If-Match` 请求头 |
| 错误归一化 | `frontend/src/api/client.ts` | 保留后端 `code` 到 `err.code`（向后兼容，仅新增字段） |
| 写入口 | `frontend/src/api/hooks.ts` | `useUpdateRowOptimistic` 取缓存行 `_etag` 作 `If-Match`；409 回滚乐观写入、不自动重试，暴露 `conflict` 状态给页面 |
| 页面 | `frontend/src/pages/grid/GridPage.tsx` | 冲突时该单元格显示警示图标 + 行内提示条「该行已被他人修改」+「载入最新值」（重新拉单行） |

### 7. 测试清单

**判定层（单测）**：`row_etag` / `parse_if_match`（合法 / 非法 / `*`）；`update_row(expected_rev=...)` 命中、未命中、行不存在、超范围四分支；`bump_rev` 幂等性。

**接口层**：`If-Match` 命中 → 200 且 `_rev` +1；未命中 → 409 `record_stale` 且行值不变；不带 → 与改造前一致（用改造前的断言直接跑）；`If-Match: v1-x` 非法 → 400；导入完成后旧 etag 提交 → 409（C3 联合用例）。

**迁移 / 备份**：旧表懒补 `_rev` 后读写正常、重复调用幂等；备份导出不含 `_rev`；导出 CSV / XLSX 表头不含 `_rev`。

**e2e（前端）**：`frontend/tests/e2e/critical/record-conflict.spec.ts` —— 两个浏览器上下文打开同一行 → A 改字段并保存 → B 基于旧值改另一字段保存 → B 看到冲突提示、行内未静默覆盖 → B 点「载入最新值」后可见 A 的改动。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 列 + 判定入口：`_rev` 懒补、`row_etag` / `parse_if_match`、`update_row(expected_rev)`、行载荷 `_etag`（C1 / C2 / C6） | 中（触及核心写路径与 DDL 懒补） |
| **P1** | 全路径 `bump_rev` + 导出 / 备份排除断言（C3 / C4 / C7） | 中（导入 / 合并 / 矩阵路径较多，需逐条回归） |
| **P2** | 前端冲突提示与「载入最新值」+ e2e（C5） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 版本载体 | **物理列 `_rev`（懒补）** | 条件更新可在一条 SQL 内完成，无 TOCTOU；复用 `ensure_lookup_columns` 的懒补范式，无 alembic | 值哈希 ETag（先 SELECT 算哈希再 UPDATE，中间存在竞态；每次读都要算整行哈希；隐藏字段参与哈希会让"同一行不同用户 etag 不同"） | `ddl.py::ensure_row_version_column` |
| D2 | 校验是否默认开启 | **可选**（客户端带 `If-Match` 才校验） | I3 兼容性；第三方脚本 / 老前端不受影响 | 强制校验（升级即让未升级客户端全线 409） | `routers/records.py` |
| D3 | 409 载荷 | **只 `{"detail","code"}`，不带当前行** | 统一错误契约（`core/errors.py`）已固定形状；前端 409 后重取单行即可 | 409 内嵌 current 行（要扩契约、且与全局 handler 冲突） | `core/errors.py` |
| D4 | 批量 / 矩阵 / 导入是否逐行校验基准 | **不校验，只自增 `_rev`** | 这些路径本就没有 per-row 基准语义；自增足以让编辑器下一次提交 409 | 逐行校验（每个 upsert 都要额外 SELECT，导入吞吐明显下降） | `records.py::bump_rev` |
| D5 | 版本自增在哪些路径 | **一切改变行可见数据的写路径**（含恢复） | I2 单调性；漏一条就等于给静默覆盖留后门 | 只在用户直编自增（导入后旧 etag 仍有效 → 覆盖导入结果） | `records.py`、`importing/`、`merge.py` |
| D6 | 懒补失败时的降级 | **不返回 `_etag` + 忽略 `If-Match` + warning** | 避免"某个旧表解锁即不可编辑"；可编辑性优先 | 直接 500 / 拒绝写入（可用性代价过高） | `ddl.py`、`records.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：直编并发冲突从"静默覆盖"变成"明确提示 + 用户裁决"；与修改申请路径的冲突保护对齐；为后续行历史（P1-3）提供天然的版本锚点。
- **负向**：每张物理表多一列（8 字节量级）；每条写路径多一次 `_rev=_rev+1` 赋值；前端需处理 409 分支与一次单行重取。
- **风险与缓解**：懒补 DDL 在 SQLite 上为 `ALTER TABLE ADD COLUMN`（O(1)）；大批量 upsert 的 `_rev` 自增与既有 `UPDATE` 同一语句，无额外往返；`_rev` 溢出按 SQLite INTEGER 上限忽略（不可能达到）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 并发冲突检测（申请态） | `change_requests.base_values` | 保持现状，不与 `If-Match` 叠加 | ADR 0005 |
| 行级权限 | 行写范围 | 版本校验在范围判定之后，越范围仍 404（不泄露） | ADR 0004 |
| lookup 冗余列 | `_lk_*` 懒补列 | `_rev` 复用同一套懒补 / 幂等范式 | ADR 0131 |
| 行回收站 | `_trashed` / `_trashed_at` | 恢复也 `bump_rev`；purge 物理删除无需版本 | ADR 0139 |
| 评分矩阵 | `matrix_upsert` | 写入后 `bump_rev`，不做 per-cell 基准 | ADR 0136 |
| 数据同步 / 导入 | upsert 写路径 | 写入后 `bump_rev`，不做 per-row 基准 | ADR 0006 / ADR 0035 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/schemas/models.py` | `tests/test_record_concurrency.py` | `ff4be4c7` |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/governance/merge.py`、`src/cndb/plugins/tables/services/transfer/exporting.py` | `tests/test_record_concurrency.py`、`tests/test_bulk_transfer.py` | `ff4be4c7` |
| P2 | 已落地 | `frontend/src/api/hooks.ts`、`frontend/src/api/records.ts`、`frontend/src/api/client.ts` | `frontend/src/api/hooks.test.tsx`、`frontend/tests/e2e/critical/record-conflict.spec.ts` | `708ed4e1` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已全部落地（含双上下文 e2e `critical/record-conflict.spec.ts`，本地待 `make e2e` 实跑）。
- 已完成：`_rev` 列（新表 `build_sa_table` 建出 + 旧表 `ensure_row_version_column` 懒补）；`row_etag` / `parse_if_match`；`update_row(expected_rev=…)` 条件更新 + 409 `record_stale`；行载荷 `_etag`；各写路径 `_rev=_rev+1`（直编 / 批量 / 批量逐行 / 软删 / 恢复 / 治理合并）；导出与备份剔出 `_etag` / `_rev`；前端 `client.ts` 保留 `code`、`hooks.ts` 带 `If-Match` 且 409 时回滚 + 明确提示（不自动重放）。
- 下一步：`make e2e` 实跑两条新 spec（record-conflict / row-recycle-bin）；观察 `record_stale` 发生率后由人确认 Status 是否改 `Implemented`。
- 已知坑：
  - `_rev` 已从 `_row_to_dict` 键空间排除（只露 `_etag`）；业务字段若叫 `id` 会覆盖行 id，ETag 用单独留存的主键计算。
  - 导入 upsert 的 `_rev` 自增已合进现有 `UPDATE ... SET`（`bulk_update_rows` 两个分支），无额外往返。
  - 前端尚未接 `If-Match`（P2）：当前所有直编仍是"最后写入者胜"，只有显式带头的客户端受保护。
  - 懒补列对 `cndb seed` / 备份恢复建出的新表同样生效（新表由 `build_sa_table` 直接带列）。
- 最近一次全绿：`make flow` @ `1d523b4b`（2026-11-23）
