# 字段配置统一面板 Spec

> Status: ALIGNED
> Author: user
> Last updated: 2026-09-23

## Background

字段编辑弹窗 FieldEditor 目前把「必填/唯一/视图中隐藏」做成一行散落的内联 Checkbox，而标题为「字段配置」的 ConfigEditor（typeConfigPanel.tsx）只承载类型专属 config，通用属性与类型配置割裂在两个视觉区域。需要将其重构为通用、可复用的「字段配置」面板，并优化布局紧凑度。

## In scope

- 新增通用字段配置面板组件（FieldManager 目录内），聚合三类分区：
  1. 基础属性：必填、唯一、视图中隐藏（含 HelpTip）
  2. 默认值：现有 DefaultValueInput（按字段类型动态控件）
  3. 类型专属配置：现有 ConfigEditor
- FieldEditor 改为使用统一面板，删除原散落 Checkbox 行
- 分区卡片布局：两列网格、紧凑间距，复用 `fm-*` CSS 语言（index.css 已有字段管理紧凑样式区）
- 保持既有数据流不变：form 字段名 required / is_unique / hidden / default_value / config 均不变，index.tsx 的 handleSubmit 不改语义
- 相关单测同步更新

## Out of scope

- FieldList 行内快捷编辑（另立需求）
- 后端 schema / API 变更（required/is_unique/default_value 后端已支持）
- 其他视图（kanban/gantt 等）的字段配置入口

## Assumptions

- 「必选」即现有 `required`（必填）字段，仅 UI 文案沿用「必填」
- 面板为 FieldManager 专用复用单元，不强行抽到全局组件库（仅两处相似不提取）

## Solution

FieldEditor 内 `<Form>` 结构改为三个 `fm-section` 分区卡片：基础属性（三个 Checkbox 横排）、默认值（整行，label 复用现有 hidden Form.Item 注册模式）、类型专属（ConfigEditor 原样嵌入）。CSS 在 index.css 的字段管理区新增 `.fm-section / .fm-section-head / .fm-grid` 等紧凑样式，用 `var(--cn-*)` 语义色。

## Edge cases & risks

| Category | Notes |
|---|---|
| 边界 | link/attachment/timestamp 无默认值 → 面板显示禁用态说明 |
| 边界 | 未选类型 → 默认值控件占位「先选择字段类型」 |
| 兼容 | index.tsx 通过 getFieldsValue 读取，分区重构不得丢失 hidden Form.Item 注册 |
| 测试 | FieldManager.test.tsx 依赖 Checkbox 文案定位，需同步 |

## Acceptance criteria

- AC-1 编辑字段弹窗内存在「基础属性 / 默认值 / 类型专属配置」三个分区卡片，必填/唯一/隐藏开关与默认值控件均在面板内可操作并保存生效
- AC-2 新建与编辑两条路径保存后，payload 中 required/is_unique/hidden/default_value/config 与重构前语义一致（单测断言）
- AC-3 `pnpm check`、`pnpm test:coverage`、`pnpm build`、`pnpm bundle:budget` 本地全绿
