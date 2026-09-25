# Bug: link 字段修改必填/唯一属性时预检被跳过，数据不符合也能保存

> Status: FIXED
> Mode: default
> Severity: functional
> Author: user
> Last updated: 2026-09-25

## Symptom
表设置中把 link（关联）字段设为必填或启用唯一时，即使现有行数据不符合约束（存在未关联行 / 多行关联同一目标），保存也成功。

## Expected
与普通字段一致：保存前预检现有数据，不符合则返回 400 并列出违规行。

## Reproduction
- 步骤：建两张表 + link 字段 → 两行关联同一目标 → PATCH 字段 `is_unique: true` → 返回 200（应为 400）。
- 测试位置：`tests/test_field_edit_validation.py::TestLinkFieldPrecheck`
- 复现稳定性：修复前 4/4 用例稳定失败（stash fix 后仍 RED，test 真捕获 bug）。

## Hypotheses & diagnosis
| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | `find_null_rows`/`find_duplicate_values` 对 `has_physical_column=False` 的 link 字段直接返回空列表，预检静默放行 | confirmed (root cause) | ddl.py L279/L300 早退分支；失败测试显示 unique 启用返回 200 |
| H2 | link 字段 required False→True 误入 `_column_needs_rebuild` → `rebuild_column` 抛 ValueError → 500 | confirmed | 测试输出 `物理列重建失败: 旧字段 关联目标 无物理列，无法重建` |

## Root cause
字段更新预检与列重建判断都只面向"有物理列"的字段设计；link 字段值存在独立关联表（`link_table_name`），物理表无列，导致：
1. 必填/唯一预检返回空列表直接放行；
2. required 开启被误判为需要列重建，抛错 500。

## Fix
- `src/cndb/plugins/tables/services/core/links.py`：新增 `find_null_link_rows`（OUTER JOIN 关联表找未关联行）与 `find_duplicate_link_values`（按目标 id 集合分组判重，空关联不参与）。
- `src/cndb/plugins/tables/routers/fields.py`：预检按 `is_link_field` 分支调用 link 专属巡检函数。
- `src/cndb/plugins/tables/services/core/ddl.py`：`_column_needs_rebuild` 对任一侧无物理列的字段返回 False。

## Verification
- V-1: 修复后 `uv run pytest tests/test_field_edit_validation.py` → 19 passed ✓
- V-2: stash 源码修复 → 4 failed（RED，test 真捕获 bug）；pop 恢复 → GREEN ✓
- V-3: `uv run pytest tests/ -k "field or link or lookup or cov_query"` → 501 passed, 6 skipped ✓

## Regression test
- 路径：`tests/test_field_edit_validation.py::TestLinkFieldPrecheck`
- 名称：`test_enable_unique_blocked_by_duplicate_links` / `test_enable_required_blocked_by_unlinked_rows` / `test_enable_required_success_after_linking` / `test_enable_unique_success_after_distinct_links` / `test_required_toggle_off_no_precheck`

## Pattern analysis
| 搜索方式 | 命中数 | 是否本次同类隐患 |
|---|---|---|
| link 字段 required/unique 的写入时校验 | `records.py:146` 显式跳过 link 字段必填 | 是（见 Follow-ups） |

## Open questions / Follow-ups
- 写入路径（`records.py`）创建/更新行时对 link 字段的 required/unique 元数据不校验（本次范围外，属新行为变更，建议单独评估）。
- `lookup` 字段的 required/unique 语义（值经 JOIN 实时解析）同样未预检，待用户决定是否需要。
- 前端遗留失败：`FieldManager.test.tsx` 2 个 DefaultValueInput 用例在隔离运行下也失败，与本次改动无关（本次未触及前端），待单独排查。
