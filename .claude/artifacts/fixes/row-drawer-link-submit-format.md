# Bug: 行详情抽屉编辑提交时 link 字段携带 [{id,value}] 摘要导致后端校验报错

> Status: FIXED
> Mode: (default)
> Severity: functional
> Author: user
> Last updated: 2026-09-25

## Symptom
员工表行编辑（行详情抽屉）保存时提示「link 字段的值必须是目标行 id 列表」。

## Expected
编辑保存正常，link 字段提交目标行 id 列表。

## Reproduction
- 步骤：打开行详情抽屉 → 保存（即使不触碰 link 字段）
- 测试位置：`frontend/src/pages/grid/layout/RowDetailDrawer.test.tsx:123`
- 复现稳定性：3/3 稳定失败（stash 修复后仍 RED）

## Hypotheses & diagnosis
| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | 抽屉编辑回填未把 attach_links 输出的 `[{id,value}]` 摘要转成 id 列表，保存原样提交 | confirmed (root cause) | failing test 显示 PATCH body 中 `部门 = [{id:7,...},{id:8,...}]`；GridCell 内联编辑路径有 extractLinkIds 转换而抽屉没有 |

## Root cause
后端读取（attach_links）将 link 值输出为 `[{id,value}]` 摘要；GridCell 网格内联编辑在编辑态做了 `extractLinkIds` 归一化，但 RowDetailDrawer 直接 `form.setFieldsValue(row)` 回填、保存时 `getFieldsValue()` 原样提交，触发 relation.py `validate_value` 的非 list[int] 校验报错。

## Fix
- 改动文件：`frontend/src/pages/grid/layout/RowDetailDrawer.tsx`
  - 新增 `extractLinkTargetIds()`：摘要对象 / id 数组 / 单个 id / 字符串数字统一归一化为正整数 id 列表
  - `handleSubmit`：保存前对所有 link 字段值归一化
  - FieldEditor link 分支：回显转 id；单选（multiple=false）value 取 `ids[0]`
- 顺带修复（阻塞门禁）：`src/cndb/plugins/tables/services/core/links.py` 两个新增预检函数 `engine: Engine` → `engine: Any`（对齐同文件 `find_null_rows` 惯例，路由层 `db.get_bind()` 返回 `Connection | Engine`）；`tests/test_field_edit_validation.py` 未使用变量 `rows` → `_rows`

## Verification
- V-1: 新增回归测试 RED（修复前）→ GREEN（修复后）✓
- V-2: stash 修复 → 测试重新 RED ✓（证明测试真捕获 bug）
- V-3: grid 目录 25 个测试文件全 GREEN；frontend tsc --noEmit 通过 ✓
- V-4: make check 后端 lint/typecheck/2330 passed/覆盖率 97.96% 全绿；前端 868 passed ✓（另有 2 个存量失败，见下）

## Regression test
- 路径：`frontend/src/pages/grid/layout/RowDetailDrawer.test.tsx:123`
- 名称：`编辑保存：link 字段的 [{id,value}] 摘要归一化为目标行 id 列表再提交`

## Pattern analysis
| 搜索方式 | 命中数 | 是否同类隐患 |
|---|---|---|
| grep 前端 `setFieldsValue(row)` 直接回填 | 仅本抽屉 | 否（GridCell 已正确转换） |

## Open questions / Follow-ups
- 存量失败（与本次无关，无本次改动时同样失败）：`frontend/src/pages/fields/FieldManager/FieldManager.test.tsx`「select 设置默认值后提交包含 default_value」「text 类型输入默认值后提交正确」— 查询选择器 `/创\s*建/` 命中「创建日期」删除按钮 aria-label 导致歧义，建议单独修复（收窄正则或改用 testId）
- 工作区另有未提交后端改动（fields.py / ddl.py / links.py 预检功能），非本次引入，仅做了类型注解与 lint 对齐
