# 统一视图判定模型（Unified View Judgment）Spec

> Status: DRAFT
> Author: 用户（方案 B：统一判定模型并重构 done_flag）
> Last updated: 2026-09-23

## Background

看板完成标志（done_flag）目前采用「done_field + done_value 精确匹配」模型，与视图筛选（FilterRule）的「field + op + value」模型并行且能力不对齐：text/date 字段做完成标志时只能填具体匹配文本/日期，无法表达"非空即完成"。筛选体系（fieldOps.ts 的 FIELD_OPS_BY_TYPE）已有全类型 `is_empty`/`is_not_empty` 操作符并经后端 API 支持。本次将 done_flag 重构为该操作符模型的消费方，统一判定能力。

## In scope

- 新增统一判定模型：`{ field, op, value }`，op 复用 `getOpsForField(fieldType)` 的类型化操作符表（含别名解析）。
- done_flag 重构：`view_options` 存储 `done_field + done_op + done_value`（两键变三键）。
  - `DoneFlagFields.tsx`：选字段后按 `getOpsForField` 渲染操作符下拉；`is_empty`/`is_not_empty` 时隐藏值控件。
  - `kanbanBoard.ts` 判定纯函数：`resolveDoneCtx/isDoneRow/buildDoneToggleValue` 改为通用 `matchCondition(row, {field, op, value})`，与筛选执行逻辑对齐（优先复用现有筛选匹配函数，若可导入）。
  - text/longtext/date/datetime 类型获得"非空"判定能力（用户本次诉求的核心）。
- 兼容：无 `done_op` 的旧数据按 `=（等于）` 处理；后端无需迁移（view_options 为 JSON 透传）。
- 筛选侧无需新增操作符（is_empty/is_not_empty 已存在）。
- 测试：判定纯函数单测覆盖各字段类型 × 各操作符；DoneFlagFields 交互测试。

## Out of scope

- 日历/甘特/WBS 字段映射不改条件化（如"非空才上墙"）——留给后续方案 C。
- 后端 filters API 与 is_empty/is_not_empty 的服务端执行逻辑变更。
- 视图筛选 UI（FilterRule）重构。
- 拖拽到完成列时的反向 toggle 语义扩展（保持现行为）。

## Assumptions

- **待用户复核**：`done_op` 缺省语义为 `=`（等值），即旧数据 `done_value` 行为完全不变；`is_not_empty` 为新增可选值。不新增"反转"键。
- 判定函数与 ColumnFilterDropdown 的匹配实现若不可直接复用（执行侧在 row collection），则提取共享纯函数到 fieldOps.ts，两处消费——三处相似原则已满足（done 判定 / 列筛选 / 视图筛选）。
- multiselect + is_not_empty 语义 = 任一值存在即非空（与现筛选一致）。

## Solution sketch

1. `fieldOps.ts`：新增 `matchCondition(record, cond: {field, op, value}): boolean` 纯函数（内部按 valueKind 分派，is_empty/is_not_empty 无值直通）。
2. `viewOptionSchema.ts`：done_field 项 tooltip 更新，说明支持"非空"判定。
3. `DoneFlagFields.tsx`：字段下拉右侧加操作符 Select（`getOpsForField(ft)` 过滤掉带 valueKind 的重操作符可选，保留等值/非空/为空）；`is_empty`/`is_not_empty` 时不渲染值控件并 `onChange({ done_value: undefined })`。
4. `kanbanBoard.ts`：`isDoneRow` 改调 `matchCondition`；`buildDoneToggleValue` 增加 op 分支——is_not_empty/is_empty 勾选时清空该字段（写 null），取消时按类型写一个非空占位值（text→非空串不宜，改为清空回退旧值策略在实现期定，默认勾选=清空、取消=清空即不可逆时禁用 toggle）。
5. 视图设置 Tab 与创建表单共用 DoneFlagFields，无第二实现。

## Edge cases & risks

| Category | Notes |
|---|---|
| 边界 | boolean 字段无 is_not_empty 需求但操作符表已含——统一暴露，不特判 |
| 边界 | done_op=is_not_empty 时用户拖卡到完成列：value 语义未定义，v1 禁用该交互 |
| 兼容 | 旧视图无 done_op → 按 `=` 渲染，UI 保存后补写 done_op |
| 失败 | done_field 指向已删除字段 → 维持现行为（视为未完成） |
| 风险 | matchCondition 与筛选执行两处逻辑漂移 → 单测用同一参数表断言两入口结果一致 |

## Acceptance criteria

- AC-1 看板完成标志选 text/date 字段时，操作符下拉含"不为空"；选"不为空"且不填值后，该字段非空的行判定为完成（标题删除线+置底）。
- AC-2 旧数据（仅 done_field+done_value、无 done_op）判定结果与重构前逐例一致（现有 kanbanBoard 单测全部不改断言通过）。
- AC-3 `matchCondition` 单测覆盖 text/select/multiselect/date/boolean × (等值, is_empty, is_not_empty) ≥ 15 用例，全绿。
- AC-4 列头筛选、视图筛选、看板完成标志三入口对同一 `(field, op, value)` 返回一致结果（共享单测参数表）。
- AC-5 `pnpm check`、`pnpm test:coverage`、`pnpm build`、`pnpm bundle:budget` 全绿。

## Open questions

- `buildDoneToggleValue` 在 is_not_empty 判定下的勾选/取消语义（Assumption 中默认：不可逆时禁用）需在实现期以最小行为定稿，实现 PR 中标注。

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| 判定条件 Condition | 前端纯函数模型 | field, op, value | done_flag / FilterRule 共同消费 |
| 操作符 FieldOp | fieldOps.ts 静态表 | op, label, valueKind, needValue | 按 field_type 分组 |
| 完成标志 DoneFlag | view_options 三键 | done_field, done_op, done_value | Condition 的持久化形态 |

## Interview metadata

- Mode: default（2 wave）
- Waves: 2
- Final ambiguity: 28%
- Status: PASSED

### Clarity breakdown

| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.9 | 0.40 | 0.36 |
| Scope | 0.8 | 0.25 | 0.20 |
| AC | 0.8 | 0.25 | 0.20 |
| Context | 0.9 | 0.10 | 0.09 |

### Ontology convergence

Condition（新）、FieldOp（stable）、DoneFlag（renamed：done_field+done_value → 三键）
