# Bug: 工作区备份导入与自动默认视图「全部」重名冲突导致 IntegrityError

> Status: FIXED
> Mode: (default)
> Severity: functional（真实导出文件导入必现失败）
> Author: user
> Last updated: 2026-09-24

## Symptom

导入工作区备份 JSON 返回 400「导入失败: (sqlite3.IntegrityError) UNIQUE constraint failed: tables_dataview.table_id, tables_dataview.name」。

## Expected

备份导入成功，视图按备份内容恢复。

## Reproduction

- 命令 / 步骤：`POST /api/v1/workspaces/{id}/import`，备份中某表 `views` 含名为「全部」的视图（导出端会把所有视图含默认视图写入备份，因此真实导出文件必现）。
- 测试位置：`tests/test_workspaces_plugin.py::TestWorkspaceExportImport::test_import_workspace_all_view_name_collision`
- 复现稳定性：3/3 reliably fails（stash fix 后）。

## Hypotheses & diagnosis

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | `ensure_default_view` 先建「全部」，视图导入循环再插入备份中同名「全部」，commit 时违反 `uniq_table_view_name` | confirmed (root cause) | failing test 3/3 稳定报同一 IntegrityError；错误参数中 INSERT 的 sortings 为备份视图内容，证明是第二次同名插入 |
| H2 | 备份文件自身同表内重名视图 | eliminated | 导出端查询数据库视图，DB 唯一约束保证不会产出重名文件 |

## Root cause

`_import_backup_into_workspace` 中 `ensure_default_view(commit=False)` 无条件创建默认视图「全部」并挂在 session 中，随后视图导入循环把备份里的「全部」再次插入，`db.commit()` flush 时第二次同名 INSERT 违反 `uniq_table_view_name (table_id, name)`。代码注释声称"若导入的 views 里已存在同名则跳过"，但实现未做该判断。

## Fix

- 改动文件：`src/cndb/plugins/workspaces/routers/workspaces.py:593-597,622-623`
- 提取 `views_data` 后，仅当备份视图不含名为「全部」的视图时才调用 `ensure_default_view`；视图循环复用 `views_data`。

## Verification

- V-1: failing test → GREEN ✓
- V-2: 仅 stash 源码修复 → test 重新 RED ✓（证明 test 真捕获 bug）；pop 恢复 → GREEN ✓
- V-3: `uv run pytest tests/test_workspaces_plugin.py` → 47 passed ✓

## Regression test

- 路径：`tests/test_workspaces_plugin.py:760`
- 名称：`test_import_workspace_all_view_name_collision`（备份含「全部」视图时导入成功且视图不重复、sortings 保留）

## Pattern analysis

`ensure_default_view` 其余 6 处调用（tables.py:130、tables.py:447、table_create.py:265/423/585 及 CLI seed）均为新建空表场景，后续不插入用户视图，无同类隐患。`git grep ensure_default_view` 共 7 处调用，唯一会与用户视图冲突的路径即本次修复的工作区导入。

## Open questions / Follow-ups

无。如未来允许导入端点接受手工构造的备份（含同表重名视图），可在视图循环加名字去重（当前该输入会被 400 拒绝，行为可接受）。
