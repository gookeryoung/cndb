# 需求卡片：行回收站（单行 / 批量删除统一软删 + 可恢复 + 保留期）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0139（与 ADR `docs/adr/0139-row-recycle-bin.md` 同号）
- 来源 / 提出人：用户（会话 2026-11-24，数据表健壮性专项 P1-1）
- 日期：2026-11-24
- 关联 ADR：`docs/adr/0139-row-recycle-bin.md`（S2）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对数据表功能的健壮性和功能性增强，结合最佳实践给出后续计划

规划评审（2026-11-24）采纳的缺口条目与顺序见 `docs/requirements/0141-table-robustness-roadmap.md`：

> 2026-11-24 用户确认「ok」——按计划启动本期：**R1/F1 行回收站**（P1-1），
> 与 **R2/F3 直编并发冲突检测**（P1-2，见 0140）同批评审。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「健壮性…最佳实践」 | **删除统一软删**：单行删除、批量删除、治理合并/去重路径的「删除语义」一律只打 `_trashed=True` + `_trashed_at`，不物理删除；物理删除只发生在「彻底删除（purge）」与「保留期到期」两条显式入口 | `tables/services/core/records.py`、`routers/bulk_crud.py`、`services/governance/merge.py` | 单测：`bulk_delete` 后行仍在物理表且 `_trashed=1`；`links` 关系仍在 |
| C2 | 「健壮性」 | **回收站可列出**：`GET /records` 支持 `trashed=only`，返回 `_trashed_at` 与删除操作人；默认列表（`trashed=none`）行为与改造前逐条一致 | `routers/records.py`、`services/core/records.py` | 接口测试：默认列表不含已删行；`trashed=only` 只返回已删行且带 `_trashed_at` / `_trashed_by` |
| C3 | 「功能性」 | **可恢复**：`POST /records/{id}/restore` 恢复后行重新出现在默认列表；恢复不重置 `id` / 字段值 / link 关系；重复恢复幂等（第二次 404 或 200 幂等二选一，取幂等） | `services/core/records.py::restore_row` | 接口测试：恢复后读得到原值、link 可解析；二次恢复 200 且不报错 |
| C4 | 「功能性」 | **可彻底删除**：`POST /records/{id}/purge`、`POST /records/purge`（按 ids 批量）要求 `EDIT_RECORDS`，只对 `_trashed=1` 的行生效；非已删行 → 400（不静默物理删除） | `routers/records.py`、`services/core/records.py` | 接口测试：已删行 purge 成功并清理 link；未删行 purge 400；viewer 403 |
| C5 | 「健壮性…最佳实践」 | **保留期**：`TRASH_RETENTION_DAYS`（默认 30，`0` = 永不清理）到期行由后台任务物理清理；任务幂等、按表分批、单批上限固定，超时不影响主服务 | `core/task_runner.py`、`services/core/rows_retention.py`、`cli/tables.py` | 单测：过期=清理、未过期=保留、`0`=不清理、分批与幂等 |
| C6 | 「健壮性」 | **软删后不产生失真数据**：软删目标行时同事务重算消费方 lookup 冗余列（`_lk_*`），恢复时重算回来；口径与硬删（`resync_lookup_consumers_for_deleted_rows`）一致 | `services/core/lookup_sync.py`、`records.py::trash_row` / `restore_row` | 单测：软删后消费方 `_lk_*` 变空、按 lookup 过滤不再命中；恢复后回填 |
| C7 | 「健壮性」 | **单一回收站口径**：清理"预留但未使用"的影子表命名与用量统计（`_trash_table_name` / `trash_table_name` / `storage.py` 计入），避免两套回收站语义并存；存量数据库无迁移（列已存在） | `tables/models.py`、`workspaces/services/storage.py`、`tests/test_tables_plugin.py` | 单测：`workspace_table_bytes` 只统计活动物理表；`make test` 全绿 |
| C8 | 「功能性」 | **前端入口**：网格工具栏/表详情提供「回收站」抽屉（已删行列表：删除时间、操作人、恢复、彻底删除、批量恢复）；非 owner/editor 只读或不可见（与 `EDIT_RECORDS` 一致）；窄屏按 0123 口径 | `frontend/src/pages/grid/`、`frontend/src/api/records.ts` | 前端单测（列表/恢复/purge 二次确认）+ e2e `critical/row-recycle-bin.spec.ts` |
| C9 | （权限） | 列出回收站按 `READ` 且沿用行级权限读范围；恢复 / 彻底删除要求 `EDIT_RECORDS` 且写范围命中，否则 403/404（不泄露存在性） | `services/core/access.py`、`row_access.py` | 接口测试：viewer 恢复 403、越行范围 404 |
| C10 | （备份） | 本期先**如实记录**现状：归档只导出字段列（`_trashed` / `_trashed_at` 不在其中），恢复后已删行以**活动行**回来 —— 属已知限制，P2 修（归档携带软删状态，旧备份缺键按活动行还原） | `workspaces/services/workspace_backup.py`、`backup_io.py` | P2 备份测试：归档往返后已删行仍为已删；旧包缺键按活动行 |
| C11 | （兼容） | 默认读路径、`include_trashed` 参数、`soft=false` 硬删参数的行为保持向后兼容（前端未升级时不出现新行为） | `routers/records.py` | 存量 `tests/test_record*.py` 全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 单行删除 / 恢复 | `services/core/records.py:951`、`routers/records.py:617,646` | 已软删 + 可恢复，但无时间/操作人对外 |
| 2 | 批量删除 | `routers/bulk_crud.py:108` → `records.py:1189` | **物理 DELETE**，与单行删除语义相反 |
| 3 | 回收站影子表 | `tables/models.py:46,207`、`workspaces/services/storage.py:126` | 只有命名与用量统计，无任何写入路径 |
| 4 | lookup 冗余列（ADR 0131） | `lookup_sync.py:287`、`records.py:883-893` | 硬删会重算，软删不会 |
| 5 | 行序列化 | `records.py:1241` | 剥掉 `_trashed` / `_trashed_at`，前端无法展示删除时间 |
| 6 | 前端回收站 | `frontend/src/api/types/records.ts:191` | 类型预留 `_trashed_at?`，无任何页面引用 `restore` |

## 未决问题

- [x] ① 回收站实现口径：**原地 `_trashed` 标记**（列已存在），不引入影子表。
- [x] ② 保留期默认值：**30 天**，`0` 关闭；由运维任务清理（不随请求触发）。
- [x] ③ 批量删除语义：改为软删（与单行一致），彻底删除只走显式 purge。
- [x] ④ 备份口径：保持现状（含已删行），恢复后仍在回收站。
- [x] ⑤ 新增硬约束「行删除永不物理丢失」→ **H47**（2026-11-24 人工确认，已入 `docs/CONSTRAINTS.md`）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题 ⑤（H 条目）已确认（H47）
