# 视图级字段显示/隐藏设计

## 需求来源

- 用户请求：视图字段可独立配置隐藏与显示（制定开发与测试计划，实施计划见 `.claude/artifacts/plans/view-field-visibility.md`）。
- 与既有两层隐藏的边界：字段级 `DataField.hidden`（全局显示开关，字段管理器配置）、权限级 `TablePermission.hidden_fields`（按角色，后端在 records 返回时剔除数据）——本设计为**视图级**，仅控制本视图的列布局，不改变数据可见性。

## 数据模型

- 持久化载体：grid 视图的 `view_options`（既有 JSON dict，零迁移）。新增一个键：
  - `hidden_fields`: `string[]` — 被隐藏字段的 id 字符串（`String(f.id)`）数组，黑名单语义；缺省 = 全部显示。
- 与 `column_widths` / `field_order`（见 `grid-column-width-order.md`）同族：同用字段 id 字符串标识、同走 GridPage 的 viewOptionsDraft 防抖保存链路。
- 不进后端 `_validate_view_fields` 校验白名单（该白名单只校验单值字段名键，列布局族键均不校验）；后端零改动。
- 失效 id（字段已删除）允许残留：前端过滤幂等（Set 查不到不影响渲染），与 column_widths/field_order 既有行为一致。
- 新增字段不进黑名单，自动显示（黑名单语义的回归保证：未配置 = 行为不变）。

## 接口定义

### buildColumns.tsx

- `ColumnOptions` 新增 `hiddenFieldIds?: ReadonlySet<string>`（key 为字段 id 字符串）。
- 过滤链：`fields.filter(f => !f.hidden)` 叠加 `!hiddenFieldIds.has(String(f.id))`（与字段级 hidden 合并为同一 filter 谓词，置于 sort + applyFieldOrder 之前）。

### GridPage.tsx

- `hiddenFieldIds` 解析 memo：`viewOptionsDraft.hidden_fields`（非数组时为空 Set）。
- `hasColumnLayoutOverride` 纳入 `hidden_fields` 非空；`handleResetColumnLayout` 三键（column_widths / field_order / hidden_fields）一并 delete——「重置列宽与列序」菜单语义扩展为整个列布局。
- 骨架屏列数（`lastVisibleFieldsCountRef`）：`!f.hidden && !hiddenFieldIds.has(String(f.id))`。
- 选中行聚合（`aggregates`）：过滤视图隐藏字段——聚合栏以字段名展示，隐藏列的数字无上下文。

### ViewConfigDialog.tsx

- 仅 `viewType === 'grid'` 时新增「字段显示」tab（key: `fields`，插在 sort 之后、view 之前）：
  - 全字段 Checkbox 列表；字段级 `f.hidden` 的字段渲染禁用态 + 「字段已隐藏」标注，不参与勾选。
  - draft 为组件内 `useState<Set<string>>`，open effect 从 `viewOptions.hidden_fields` 初始化。
  - 保存统一走 footer「保存」：全显时从 `draftOpt` delete `hidden_fields`（与 cleanOpt 空值清洗语义一致），否则写入 id 数组，最终经 `onSaveOptions` → viewOptionsDraft → 防抖持久化。
  - 不进 viewOptionSchema.ts 的原因：交互形态不同（全字段 checkbox + 禁用态 vs 按类型过滤的有限选择）。

## 语义约束

- 视图隐藏不改变数据访问：筛选/排序规则的字段候选不含视图隐藏概念（仅沿用 `!f.hidden`）；行详情抽屉（RowDetailDrawer）显示全部字段。
- 视图隐藏与 `field_order` 交互：隐藏字段仍可占 field_order 位次，`applyFieldOrder` 对未渲染字段天然忽略；取消隐藏后按原位次恢复。
- 各视图 `view_options` 独立，互不影响。
- 视图内联新增行走 grid 列布局，被隐藏字段不出现在新增行（与字段级 hidden 同边界同行为）。

## 验收标准

- [x] 视图 A 隐藏字段 X 后 grid 不渲染 X 列；同表视图 B 不受影响（各视图 view_options 独立）
- [x] 未配置 hidden_fields 的视图行为与改动前完全一致（回归：buildColumns 空 Set 用例 + 既有全量测试通过）
- [x] 被隐藏字段仍可用于筛选/排序（ViewConfigDialog 候选仅按 `!f.hidden` 过滤，未引入视图隐藏概念）；行详情抽屉不受影响（RowDetailDrawer 未改动）
- [x] 「重置列宽与列序」一并清理 hidden_fields（hasColumnLayoutOverride 纳入 hidden_fields 非空）
- [x] 字段级 hidden 字段在「字段显示」tab 呈禁用态并标注「字段已隐藏」
- [x] 保存走既有 onSaveOptions → viewOptionsDraft → 防抖链路，后端零改动（hidden_fields 空数组经 cleanOpt 空值清洗自动剔除）
- [x] 隐藏列不参与选中行聚合栏（aggregates memo 叠加 hiddenFieldIds 过滤）
