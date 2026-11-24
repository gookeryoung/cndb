# 需求卡片：直编并发冲突检测（行版本 + 可选 If-Match）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0140（与 ADR `docs/adr/0140-record-concurrency-control.md` 同号）
- 来源 / 提出人：用户（会话 2026-11-24，数据表健壮性专项 P1-2）
- 日期：2026-11-24
- 关联 ADR：`docs/adr/0140-record-concurrency-control.md`（S2）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对数据表功能的健壮性和功能性增强，结合最佳实践给出后续计划

规划评审（2026-11-24）采纳顺序见 `docs/requirements/0141-table-robustness-roadmap.md`：

> 2026-11-24 用户确认「ok」——本期为路线图 **R2/F3 直编并发冲突检测**（P1-2），
> 与 0139（行回收站）同批评审。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「健壮性…最佳实践」 | **可选乐观并发**：`PATCH /records/{id}` 支持标准 `If-Match: <etag>`；etag 不匹配 → 409 且**不落库**；不带 `If-Match` 时行为与改造前逐条一致 | `routers/records.py`、`services/core/records.py` | 接口测试：匹配 → 200 且 `_rev` +1；不匹配 → 409 且行值不变；不带 → 现状 |
| C2 | 「健壮性」 | **错误契约一致**：409 走 `core/errors.py::ConflictError`，`code="record_stale"`，响应体仍是 `{"detail","code"}`，不新增顶层字段 | `core/errors.py`、`routers/records.py` | `tests/test_error_contract.py` 口径不破；新增 409 形状断言 |
| C3 | 「健壮性」 | **所有写路径自增版本**：用户直编、批量更新、修改申请合并、评分矩阵 upsert、导入 / 数据同步 upsert、回收站恢复，全部让该行 `_rev` +1（插入默认 0） | `services/core/records.py`、`importing/`、`governance/merge.py`、`services/core/row_*` | 单测：每条写路径后 `_rev` 严格递增；导入更新后旧 etag 立即失效 |
| C4 | （兼容） | 不带 `If-Match` 的客户端行为、`_rev` 不在字段列表 / 导出 / 公式中暴露、行载荷只多一个 `_etag` 字符串 | 全仓 | 存量 `tests/test_record*.py`、`tests/test_bulk_transfer.py` 全绿 |
| C5 | 「功能性」 | **前端冲突提示**：单元格提交带上缓存行的 `_etag`；409 回滚乐观写入并给行内提示「该行已被他人修改」+ 「载入最新值」动作，**不自动覆盖** | `frontend/src/api/hooks.ts`、`frontend/src/pages/grid/` | 前端单测（409 回滚 + 提示 + 重新载入）+ e2e `critical/record-conflict.spec.ts` |
| C6 | （迁移） | **无 alembic 迁移**：`_rev` 按需懒补（幂等 `ALTER TABLE ADD COLUMN _rev INTEGER NOT NULL DEFAULT 0`，复用 ADR 0131 `ensure_lookup_columns` 范式）；新表由 `build_sa_table` 直接建出 | `services/core/ddl.py` | 单测：旧表懒补后立即可用；重复调用幂等；`make test` 全绿 |
| C7 | （数据出口） | `_rev` / `_etag` 不进 CSV / XLSX / JSON 导出、不进备份字段快照、不作为可筛选 / 可排序列 | `transfer/exporting.py`、`workspaces/services/workspace_backup.py` | 导出测试：表头不含 `_rev`；备份载荷不含 `_rev` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 单行更新 | `services/core/records.py:832`、`routers/records.py:588` | 只有 `values`，无任何基准校验 |
| 2 | 物理行缺少版本 / 时间列 | `services/core/ddl.py:164-165` | 只有 `_trashed` / `_trashed_at`，无 `updated_at` / `_rev` |
| 3 | 前端唯一单元格写入入口 | `frontend/src/api/hooks.ts:130` | 乐观更新 + 失败回滚，冲突提示接入点 |
| 4 | 修改申请路径已有冲突检测 | ADR 0005 | 仅 viewer / 关闭直编路径，直编路径无 |
| 5 | 其它写路径 | `bulk_crud.py`、`routers/records.py:409`（matrix_upsert）、`importing/` | 都需要让 `_rev` 递增，否则冲突检测形同虚设 |

## 未决问题

- [x] ① 是否需要客户端参与：**是**，但为可选（带 `If-Match` 才校验），前端默认带。
- [x] ② 版本载体：**物理列 `_rev`（懒补）**，不用值哈希（避免 TOCTOU 与每次读成本）。
- [x] ③ 409 是否携带当前行：**不带**（统一错误体只有 `detail` / `code`），前端 409 后主动重取。
- [x] ④ 批量更新 / 矩阵 / 导入是否逐行校验基准：**不校验**，只负责自增版本（已知限制，记入 ADR）。
- [x] ⑤ 新增硬约束「带基准的直编冲突不得静默覆盖」→ **H48**（2026-11-24 人工确认，已入 `docs/CONSTRAINTS.md`）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题 ⑤（H 条目）已确认（H48）
