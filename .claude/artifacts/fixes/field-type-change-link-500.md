# Bug: 物理列字段改为 link 后编辑行报 500

> Status: FIXED
> Mode: default
> Severity: functional
> Author: user
> Last updated: 2026-09-25

## Symptom
员工表将「部门」字段改为单选（link 关联，multiple=False）并引入部门表「负责人」lookup 字段后，编辑行修改「部门」关联值报 Request failed with status code 500。

## Expected
编辑 link 字段关联值返回 200，并输出目标行摘要；lookup「负责人」实时解析。

## Reproduction
- 步骤：select 字段 → PATCH 字段类型为 link → PATCH 行写入关联值 [目标行 id]
- 测试位置：`tests/test_field_edit_validation.py::TestTypeChangeLinkTransition`
- 复现稳定性：3/3 reliably fails（stash fix 后仍 RED）

## Hypotheses & diagnosis
| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | 字段类型改为 link 时未创建关联物理表，行写入 set_links 反射失败抛 RuntimeError → 500 | confirmed (root cause) | RED 错误信息 `Could not reflect: link_f8961c1717a2`；`_column_needs_rebuild` 在任一侧无物理列时直接返回 False，update_field 无任何 DDL |
| H2 | lookup 解析路径抛错 | eliminated | attach_lookup_values 全程容错回退 None，不抛错 |

## Root cause
`routers/fields.py update_field` 的物理变更检测只覆盖「新旧类型均有物理列」的 rebuild 场景。物理列 → link 互转时（`_column_needs_rebuild` 返回 False）：改为 link 既不删旧物理列也不建关联表；link 改回物理列既不删关联表也不加列。后续行写入因反射不到关联表/物理列抛 RuntimeError，路由层仅捕获 ValueError → 500。

## Fix
- 改动文件：`src/cndb/plugins/tables/routers/fields.py`（update_field 新增 1b 分支）
- 改为 link：drop_column(旧物理列) + create_link_table；改回物理列：drop_link_table + add_column；DDL 失败走既有 `_revert_metadata` 并返回 500。

## Verification
- V-1: 新增 3 个测试 → GREEN ✓（32 passed）
- V-2: stash fix → 3 个测试重新 RED ✓；pop 恢复 → GREEN ✓
- V-3: 字段/关联相关 7 个测试文件 167 passed ✓；全仓 2343 passed ✓
- V-4: 已本地通过 `make check`（exit=0）

## Regression test
- 路径：`tests/test_field_edit_validation.py::TestTypeChangeLinkTransition`
- 名称：test_select_to_link_then_edit_record / test_select_to_link_import_lookup_still_resolves / test_link_to_select_creates_physical_column

## Pattern analysis
| 搜索方式 | 命中数 | 是否本次同类隐患 |
|---|---|---|
| `git grep -n "_column_needs_rebuild"` | 仅 ddl.py 定义 + fields.py 调用 | 否 |
| create_field 路径 | add_column 已含 link 建关联表分支 | 否 |

## Open questions / Follow-ups
- 物理列改为 link 时旧列文本值无法自动映射为目标行 id，旧值随旧列删除而丢弃（与 rebuild 路径「数据转换失败即丢失」语义一致）；如需保留可后续提供「值 → 目标行」迁移向导。
