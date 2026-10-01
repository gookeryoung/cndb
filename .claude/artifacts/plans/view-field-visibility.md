# 视图字段显示/隐藏配置 Implementation Plan

> Status: APPROVED
> Source: user request（无既有 spec）
> Mode: default（Planner → Architect → Critic 完整 loop）
> Iterations: 1 / 3
> Author: user
> Last updated: 2026-10-01

## Requirements summary

为表格视图提供**视图级**的字段显示/隐藏配置：每个视图可独立指定哪些字段不显示（以 grid 视图的列为核心消费场景）。现状只有两层隐藏——字段级（`DataField.hidden`，全局生效，字段管理器配置）与权限级（`TablePermission.hidden_fields`，按角色在后端剔除数据）——缺少「同一张表不同视图看不同列」的能力。

## Acceptance criteria

- AC-1 视图 A 隐藏字段 X 后，grid 表格不渲染 X 列；同表视图 B 不受影响（各自 `view_options` 独立）。
- AC-2 默认全部字段显示：未配置过 `hidden_fields` 的视图行为与改动前完全一致（回归）。
- AC-3 视图隐藏的字段仍可参与筛选/排序规则（`ViewConfigDialog` 的筛选/排序 tab 候选不含视图隐藏概念，仅沿用字段级 `!f.hidden` 过滤）。
- AC-4 行详情抽屉（RowDetailDrawer）不受视图隐藏影响——视图隐藏是列布局，不是数据访问控制。
- AC-5 「重置列宽与列序」一并清理 `hidden_fields`（三键同族语义：column_widths / field_order / hidden_fields）。
- AC-6 字段级 hidden 的字段在「字段显示」tab 中呈禁用态并标注「字段已隐藏」，不参与勾选。
- AC-7 保存语义复用现有链路：ViewConfigDialog「保存」→ `onSaveOptions` → `setViewOptionsDraft` → 防抖持久化到后端 `view_options`（零后端代码改动、零迁移）。
- AC-8 隐藏列不参与选中行聚合栏（gridAggregationBar）的数字聚合展示。

## RALPLAN-DR

### Principles

1. 跟随既有模式：`hidden_fields` 与 `column_widths` / `field_order` 同属 grid 列布局族，同存 `view_options`、同用 `String(field.id)` 标识、同走防抖保存链路。
2. 最小代码：后端 `view_options` 是自由 dict，列布局族键不进 `_validate_view_fields` 白名单，后端与 seed 均零改动。
3. 三层隐藏语义不混淆：字段级（全局显示开关）/ 权限级（角色数据访问）/ 视图级（本视图列布局）。
4. 公共函数配套测试（buildColumns 过滤逻辑为纯函数，可单测）。

### Decision drivers

1. **一致性**（与既有列布局键的存储/标识/链路完全一致）—— 决定性
2. **改动面**（后端零改动、零迁移）—— 决定性
3. **可测试性**（纯函数过滤 + 既有测试基建直接复用）

### Viable options

**Option A: `view_options.hidden_fields` 黑名单（`String(field.id)` 数组）** — favored
- 实现思路：视图默认全显；被勾选隐藏的字段 id 记入数组；`buildColumns` 过滤链叠加。
- 改动文件：`buildColumns.tsx`、`GridPage.tsx`、`ViewConfigDialog.tsx` + 3 个测试文件。
- Pros: 新增字段自动显示（符合直觉）；黑名单通常远小于全字段集；与 column_widths/field_order 同族同标识；后端零改动。
- Cons: 「隐藏几乎所有列」场景数组较长（无实际影响）。

**Option B: `view_options.visible_fields` 白名单** — rejected
- 实现思路：视图只显示白名单内字段。
- Rejected rationale: 新增字段默认不可见，用户困惑（「我新建的字段去哪了」）；空数组的语义歧义（全部隐藏 vs 全部显示）必须特判；语义与「隐藏」相反映射负担大。

**Option C: 启用闲置的 `field_options` 列（Baserow 模式：每字段 `{visible, width, order}`）** — rejected
- 实现思路：把列布局三件套统一迁入 `field_options`。
- Rejected rationale: 需迁移既有 column_widths/field_order 并做双读兼容，改动面数倍扩大，属于架构重构而非本需求；违反最小代码原则。作为长期演进方向记入 Follow-ups。

## Implementation steps

1. **ColumnOptions 扩展与过滤叠加** — `frontend/src/pages/grid/cells/buildColumns.tsx:67-77`（`ColumnOptions` 接口新增 `hiddenFieldIds?: ReadonlySet<string>`，注释注明 key 为字段 id 字符串）；`buildColumns.tsx:133-136` 过滤链由 `fields.filter(f => !f.hidden)` 叠加 `!options?.hiddenFieldIds?.has(String(f.id))`（注意保持既有 sort + applyFieldOrder 顺序不变，过滤在 sort 之前或之后均可——建议与 `!f.hidden` 同位置合并为一个 filter 谓词）。
2. **GridPage 解析与传参** — `frontend/src/pages/grid/GridPage.tsx:828-836` 旁新增 `hiddenFieldIds` 解析 memo（`viewOptionsDraft.hidden_fields` → `Set<string>`，非数组时为空 Set）；`GridPage.tsx:884-891` 传入 `buildColumns` 的 options。
3. **重置链路纳入** — `GridPage.tsx:871-882`：`hasColumnLayoutOverride` 增加 `hidden_fields` 非空判断；`handleResetColumnLayout` 三键一并 delete。
4. **骨架屏列数** — `GridPage.tsx:491-499`：`lastVisibleFieldsCountRef` 的计算叠加视图隐藏字段（`!f.hidden && !hiddenFieldIds.has(String(f.id))`）。
5. **聚合过滤** — `GridPage.tsx:896-913`：`aggregates` memo 的 `numericFields` 过滤叠加视图隐藏；memo 依赖数组加 `hiddenFieldIds`。rationale：聚合栏以字段名展示 count/sum/avg，隐藏列的数字悬空无上下文（用户会困惑「这字段在哪」）。
6. **ViewConfigDialog 新增「字段显示」tab** — `frontend/src/pages/grid/view-config/ViewConfigDialog.tsx`：仅 `viewType === 'grid'` 时 push 一个 `key: 'fields'` 的 tab（插在 sort 之后、view 之前），内容为全字段 Checkbox 列表：
   - draft 状态存组件内（`useState<Set<string>>`），open effect 时从 `viewOptions.hidden_fields` 初始化；
   - 字段级 `f.hidden` 的字段渲染禁用 Checkbox + 「字段已隐藏」标注（AC-6）；
   - 保存按钮统一收口：全显时从 `draftOpt` delete `hidden_fields`（与现有 `cleanOpt` 空值清洗语义一致），否则写入 id 数组——即在现有 footer 保存 onClick 里追加，最终仍走 `onSaveOptions`；
   - 代码注释说明：不进 viewOptionSchema.ts 的原因是交互形态不同（全字段 checkbox + 禁用态 vs 按类型过滤的有限选择），避免后人误统一。
7. **测试** —
   - `frontend/src/pages/grid/cells/buildColumns.test.tsx`：新增用例「hiddenFieldIds 叠加过滤：隐藏字段不出列、字段级 hidden 与视图级 hidden 同时生效、空 Set 行为不变」；
   - `frontend/src/pages/grid/view-config/ViewConfigDialog.test.tsx`：新增用例（复用 `renderDialog` helper 与 `makeField` fixture）——grid 出现「字段显示」tab 且非 grid（如 kanban）不出现、勾选隐藏后保存回调 `onSaveOptions` 收到 `hidden_fields` 数组、全显时 `onSaveOptions` 收到的对象不含 `hidden_fields` 键、字段级 hidden 字段为禁用态；
   - `frontend/src/pages/grid/GridPage.tableSkeleton.test.tsx`：扩展一例「视图隐藏字段不计入骨架列数」。

## Workspace setup

- Run `git status --short` and `git branch --show-current` before implementation.（当前已确认：main 分支，working tree 干净）
- 本 plan 会修改代码与测试；当前在 main 分支，推荐先创建分支或 worktree：`git worktree add -b codex/view-field-visibility ../cndb-view-field-visibility`（或征得用户同意后直接在 main 上建普通分支）。
- 实施期间每步编辑后用 `git diff` 核对落盘（项目 memory 有「Edit/Write 显示污染」教训，git 是唯一事实通道）。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| 失效 id 残留：字段被删除后 `hidden_fields` 残留旧 id | 前端过滤幂等（Set 查不到自然无影响），与 column_widths/field_order 既有行为一致；不做清理钩子（违反外科手术原则），记入 ADR Consequences |
| 必填字段被视图隐藏后，grid 内联新增行缺少该字段输入 | 与字段级 hidden 同边界同行为（既有语义：隐藏即不出现于新增行列），RowDetailDrawer 始终显示全部字段兜底；记入 Open questions 待用户复核 |
| `hidden_fields` 与 `field_order` 交互：隐藏字段仍占据 field_order 位次 | `applyFieldOrder` 对不存在的 id 天然忽略（`buildColumns.tsx:84-98`），取消隐藏后字段按原位次恢复——预期行为，写入 ViewConfigDialog 测试断言 |
| 聚合 memo 新增依赖导致防抖保存期间聚合闪变 | 影响可忽略（O(数字字段×选中行)），且防抖窗口仅 800ms 级；不做额外处理 |

## Verification steps

- 验证 AC-1/AC-2/AC-6/AC-8：`pnpm --dir frontend vitest run src/pages/grid/cells/buildColumns.test.tsx src/pages/grid/view-config/ViewConfigDialog.test.tsx`
- 验证 AC-2（回归）+ AC-5：`pnpm --dir frontend vitest run src/pages/grid/GridPage.tableSkeleton.test.tsx`；新增「重置清理三键」断言（步骤 3 对应，可在现有 gridTableSection 或 GridPage 相关测试中补）
- 全量门禁：`make check`（lint/typecheck/cov，收尾必须注明已本地通过）
- 手工冒烟（可选）：两个视图分别隐藏不同字段，切换验证互不影响；重置列宽与列序后字段全显

## ADR

- **Decision**: 视图级字段显示/隐藏采用 `view_options.hidden_fields` 黑名单（`String(field.id)` 数组），前端过滤、后端零改动。
- **Drivers**: 一致性（与 column_widths/field_order 同族同标识同链路）与改动面（零迁移、零后端代码）起决定作用。
- **Alternatives considered**: Option A（chosen——默认全显直觉、黑名单小、后端零改动）；Option B 白名单（rejected——新增字段默认不可见 + 空值歧义）；Option C field_options 重构（rejected——超范围架构重构）。
- **Why chosen**: 既有 grid 列布局族（column_widths/field_order）已验证该存储与保存模式可行，hidden_fields 是该族的自然第三成员；黑名单语义让「未配置 = 行为不变」的回归保证成立。
- **Consequences**: 正——各视图列布局独立、零迁移、导入导出随 view_options 自动携带。负——失效 id 会残留（与同族键一致的已知 limitation）；视图隐藏与字段级/权限级隐藏三层叠加的语义需在文档中向用户说明。
- **Follow-ups**: 表头右键快捷「隐藏此字段」（UI 增强，不在本次范围）；field_options 统一模型（长期演进，需专项 spec）；字段删除时的 view_options 清理钩子（若残留问题实际恶化再做）。

## Review trail

- Planner draft v1: Option A（hidden_fields 黑名单）+ 8 个实施步骤，含后端校验两步骤。
- Architect challenge v1: steelman「零校验是双刃剑」——评估后维持不校验（与同族键一致，垃圾残留记 limitation）；指出 tab 归属需注释说明不进 schema 系统的原因；确认聚合栏（gridAggregationBar）与列布局的 UI 关联支持过滤决策；提供 tradeoff tensions 三条（一致性 vs 防御性 / 聚合一致性 vs 信息完整 / 复用链路 vs 独立保存），均给出取舍依据。
- Critic verdict v1: APPROVED with reservations。Reservations: ① 聚合过滤的性能与消费位置——已通过实读 gridAggregationBar.tsx 确认为选中行摘要底栏，过滤决策成立；② 必填字段被视图隐藏的新增行边界——记入 Open questions 待用户复核；③ ViewConfigDialog.test.tsx 基建——已确认 renderDialog helper + makeField fixture 可直接复用。
- Planner 修订（同轮）: 移除后端 views.py / seed.py 校验步骤（零改动）、明确 tab 注释要求、补齐测试文件级细节。
- Final iterations: 1 / 3

## Open questions

- [ ] 必填字段被视图隐藏时，grid 内联新增行缺该字段输入（与字段级 hidden 同边界）。默认沿用既有行为，**待用户复核**是否需要「隐藏必填字段时提示」的防护。
- [ ] CreateEditViewForm（创建视图对话框）是否需要字段显示配置入口——默认不做（创建后默认全显，再用 ViewConfigDialog 调整）。
