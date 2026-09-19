# 计划：表设置 Modal 布局美化（左侧竖向导航）+ 功能健壮性增强

## Summary

对「表设置」Modal（`TableSettingsModal`，4 Tab：基本信息/字段/视图/权限）做两类改造：

1. **布局美化紧凑化**：Modal 改为左侧竖向 Tab 导航（类 Notion 设置面板），基本信息 Tab 的 bordered Descriptions 换成紧凑统计条，视图 Tab 卡片化，字段 Tab 列表紧凑化。
2. **健壮性修复**：权限隐藏字段从 `document.querySelectorAll` DOM 采集改为受控 state；修复 `initialTab='permissions'` 直接打开时权限数据永不加载；`row_filters: null` 不再随权限保存误发；修正前端 `View` 类型与后端不符（`is_default` vs `default`）；消除 `any`。

范围：仅表设置 Modal 及其内嵌的 FieldManager 字段列表、PermissionEditor 隐藏字段区。**不含**「显示模式」Dialog（TableSettingsDialog）。

## Current State Analysis

- [TableSettingsModal.tsx](file:///f:/Dev/cndb/frontend/src/pages/modals/TableSettingsModal.tsx)：780 宽 Modal + 顶部 Tabs；Tab1 用 `Descriptions bordered`（6 项 2 行）占空间大；Tab3 视图列表为朴素 div 行，`views.map((v: any)`；Tab4 权限的隐藏字段勾选在 [PermissionEditor.tsx L263-281](file:///f:/Dev/cndb/frontend/src/pages/grid/components/PermissionEditor.tsx#L263-L281) 用原生 `<input type=checkbox data-perm-hidden>`，而保存按钮在 TableSettingsModal L361-371 用 `document.querySelectorAll('input[data-perm-hidden]:checked')` 采集 —— 跨组件 DOM 耦合，且保存固定携带 `row_filters: null`（PATCH `exclude_unset` 语义下会清空已有行级过滤）。
- 权限查询 `enabled: false`，仅 `handleTabChange` 切到 permissions 时 `refetchPerm()` —— `initialTab='permissions'` 打开时 `permData` 永不加载。
- [api/types.ts L280-291](file:///f:/Dev/cndb/frontend/src/api/types.ts#L280-L291)：前端 `View` 接口声明 `default?: boolean`；后端 [ViewResponse](file:///f:/Dev/cndb/src/cndb/plugins/tables/schemas/models.py#L261-L277) 实际返回 `is_default: bool`。GridPage L119/L371 读 `view.default` 恒为 undefined —— 视图页签"默认"标记与默认视图匹配失效（存量 bug）。
- [FieldManager.tsx L253-286](file:///f:/Dev/cndb/frontend/src/pages/modals/FieldManager.tsx#L253-L286)：字段表类型列显示英文原始值，必填/隐藏列"是/否"文本，操作列为文字按钮。
- 样式约定：组件内 inline style + CSS 变量 `--cn-*`；全局深浅色主题靠 CSS 变量与兜底规则（index.css）。硬编码色值（#999 等）已有深色模式兜底，但新代码统一用 `var(--cn-*)`。
- 测试：vitest + testing-library + MSW，参照 `WorkspaceSettingsContent.test.tsx` / `CreateEditViewForm.test.tsx` 的 mock 模式。`TableSettingsModal` 目前无测试。
- 门禁：`make check` = gitkeep-check + lint(frontend-check+ruff) + typecheck(pyrefly) + frontend-check(ft+fl+ftest) + cov(pytest)。

## Proposed Changes

### 1. [TableSettingsModal.tsx](file:///f:/Dev/cndb/frontend/src/pages/modals/TableSettingsModal.tsx) — 布局重构 + 健壮性（主文件）

**布局：左侧竖向导航**
- `Tabs` 加 `tabPosition="left"`、`className="table-settings-tabs"`；Tab label 保持 图标+文字。
- Modal：`width={720}`、`className="table-settings-modal"`；title 保持 `表设置 + 表名 Tag`。

**Tab1 基本信息紧凑化**
- 删除 `Descriptions bordered`，换成一行 4 个统计块（字段数 / 记录数 / 视图数 / 创建日期），数字加粗 + 下方小字标签；第二行 muted meta 文本：`表 ID {id} · 工作区 {workspace_id}`。
- Form 保持 vertical（表名/描述），间距收紧；底部操作行：保存 + 删除表（含权限提示 Tag），保持现有 mutation 逻辑。
- 脏检查：`Form.useWatch` 对比 `table.name/description`，无变化时保存按钮禁用。

**Tab3 视图卡片化**
- 新增本地 `VIEW_MODE_META` 映射（icon + 中文标签，与 GridPage MODE_BUTTONS 一致）：grid→表格 `ColumnHeightOutlined`、kanban→看板 `AppstoreOutlined`、gallery→画廊 `EyeOutlined`、calendar→日历 `CalendarOutlined`、gantt→甘特图 `LineChartOutlined`、wbs→工作分解 `PartitionOutlined`；未知类型 fallback 显示原始值。
- 视图行：类型图标 + 名称 + 中文类型 Tag + 默认 Tag（读 `v.is_default`）+ hover 背景 + 编辑/删除 icon 按钮（现有 Popconfirm 保留）。
- `(v: any)` → `View` 类型。

**Tab4 权限健壮性（核心修复）**
- 新增 `const [hiddenNames, setHiddenNames] = useState<string[]>([])`；`useEffect` 在 `permData?.hidden_fields` 变化时用 `buildHiddenSet` 展平重置。
- 保存 payload：`{ hidden_fields: { admin: hiddenNames } }`（空数组也发，保证可清空），**删除 `row_filters: null`**（PATCH exclude_unset 语义下不再误清空）。
- `permData as any` → `TablePermission | undefined`。
- `initialTab='permissions'` 修复：`handleTabChange` 中的 `refetchPerm()` 移入 `useEffect(() => { if (isActive && activeTab === 'permissions') refetchPerm() }, [isActive, activeTab])`，覆盖直接打开场景。

### 2. [PermissionEditor.tsx](file:///f:/Dev/cndb/frontend/src/pages/grid/components/PermissionEditor.tsx) — 隐藏字段区受控化

- 导出 `buildHiddenSet`（现 L38-51，加 `export`）。
- Props 新增 `hiddenNames: string[]`、`onHiddenNamesChange: (v: string[]) => void`；L267-281 原生 `<input type=checkbox data-perm-hidden>` + `<Form>` 区块替换为 antd `Checkbox.Group`（受控绑定上述 props，flex wrap 布局，字段类型小字保留）。仅 TableSettingsModal 一处使用方，安全。

### 3. [FieldManager.tsx](file:///f:/Dev/cndb/frontend/src/pages/modals/FieldManager.tsx) — 字段列表紧凑化（仅 `fieldListContent` L253-286）

- 工具栏：左移除空占位，左侧加 `共 {sorted.length} 个字段` caption，右侧按钮不变。
- 类型列：`FIELD_TYPES.find(t => t.value === v)?.label ?? v` 中文 Tag。
- 必填/隐藏列：`v ? <Tag color="orange">必填</Tag> : '-'`（隐藏同理用默认 Tag），保持 70 宽。
- 操作列：icon-only + `Tooltip`（编辑/删除），宽 160→90。
- 该内容为 embedded/独立 Modal 两模式共用，纯渲染改动无逻辑回归面。

### 4. [api/types.ts](file:///f:/Dev/cndb/frontend/src/api/types.ts) — View 类型修正

- `View` 接口：`default?: boolean` → `is_default: boolean`，`view_type?: string` → `view_type: string`（对齐后端 ViewResponse）。
- 同步更新引用：[GridPage.tsx L119](file:///f:/Dev/cndb/frontend/src/pages/grid/GridPage.tsx#L119) `view.default` → `view.is_default`、[L371](file:///f:/Dev/cndb/frontend/src/pages/grid/GridPage.tsx#L371) `views.find(v => v.default)` → `v.is_default`。此修复同时让 GridPage 视图页签"默认"标记与默认视图匹配恢复生效。

### 5. [index.css](file:///f:/Dev/cndb/frontend/src/index.css) — 表设置 Modal 紧凑化样式

在 `.table-settings-dialog` 规则块附近新增：

```css
/* ─── 表设置 Modal — 左侧导航 + 紧凑化 ─── */
.table-settings-modal .ant-modal-body { padding: 8px 16px 16px 8px; }
.table-settings-tabs .ant-tabs-nav { min-width: 116px; padding: 8px 0; }
.table-settings-tabs .ant-tabs-tab { padding: 7px 12px; margin: 2px 0; justify-content: flex-start; }
.table-settings-tabs .ant-tabs-content-holder {
  max-height: min(600px, calc(100vh - 240px));
  overflow-y: auto;
  padding: 8px 4px 8px 12px;
}
/* 统计块 / 视图行卡片 hover 等 .ts-* 小类 */
```

新增少量 `.ts-stat` / `.ts-view-row` 等类（色值一律 `var(--cn-*)`），替代散落的 inline style；具体数值实现时微调。

### 6. 新增 [TableSettingsModal.test.tsx](file:///f:/Dev/cndb/frontend/src/pages/modals/TableSettingsModal.test.tsx)

参照 `WorkspaceSettingsContent.test.tsx` 的 mock 模式（vi.mock('@/api') + QueryClientProvider 包裹）。用例：

1. `initialTab='permissions'` 挂载后触发 `permissionApi.get`（回归修复 1）。
2. 勾选/取消隐藏字段后点保存 → `permissionApi.patch` 收到 `{ hidden_fields: { admin: [...] } }` 且 payload 不含 `row_filters`（回归修复 2/3）。
3. 基本信息无改动时保存按钮禁用，修改表名后启用（脏检查）。

## Assumptions & Decisions

- 左侧竖向导航用 antd `Tabs tabPosition="left"` 实现，不引入自定义导航组件。
- 隐藏字段保存桶固定写 `admin`（与现有行为一致，展平展示模型不变）；`row_filters` 一律不发送。
- `View` 类型改为 `is_default` 属存量类型 bug 修复，连带 GridPage 两处引用，属本次健壮性范围。
- 权限 Tab 中 PermissionEditor 的 Owner Card / 成员表结构不动，仅隐藏字段区受控化。
- CreateEditViewForm 提交失败即关弹窗的现状保留（有 message.error 提示），不在本次扩大。

## Verification

1. `cd frontend && pnpm test -- TableSettingsModal` — 新增用例通过。
2. `cd frontend && pnpm typecheck && pnpm lint` — 无 any 残留、无类型错误。
3. 手工冒烟（`pnpm dev`）：表设置 4 个 Tab 布局正常（浅色/深色主题各看一次）；直接以"权限"Tab 打开能加载权限数据；勾选隐藏字段保存后重新打开回显正确；无改动时保存禁用；视图"默认"Tag 在设置页与 GridPage 视图页签均显示。
4. 收尾运行全套 `make check` 确认 lint/typecheck/cov 全绿。
