# 字段引入跨工作区增强 Spec

> Status: ALIGNED
> Author: 用户
> Last updated: 2026-09-23

## Background

字段管理已有"从其他表引入字段"对话框（前端 `frontend/src/pages/fields/FieldManager/index.tsx`，后端 `POST /workspaces/{wid}/tables/{tid}/fields/import`），支持多字段勾选、preview_only 预览、suggest_field_mapping 智能映射、field_mapping 重命名/跳过、gap_analysis 缺口分析。但源表选择器只列当前工作区，跨工作区实际不可用；后端对源表不校验任何源工作区权限（安全缺口）。

## In scope

- 后端权限收紧：`import_fields` 校验当前用户对源表所在工作区有读取权限，否则 400（含提示源工作区名）。
- 前端源表选择器升级为跨工作区级联选择：先选工作区（仅用户有权限的，来自工作区列表 API），再选该工作区下的表（排除目标表自身）。
- 拉取跨工作区源表字段时使用源表所在工作区 wid 调 `fieldApi.list`。
- 映射面板增强：按"推荐/低置信度"分组展示；提供"仅引入已匹配字段"快捷操作（一键把低置信度项置为跳过）。
- 勾选区体验：全选/反选、按字段名搜索过滤。
- 后端权限收紧与 preview_only 组合的测试；前端组件测试更新。

## Out of scope

- 建表时 `create_table` 的 `import_from_table_id` 不改动（保持本工作区）。
- 引入字段的数据同步（维持 schema-only，独立副本）。
- link 字段目标表跨工作区的进一步处理（后端已天然支持保留 target_table_id）。
- 拷贝字段数据、建立持续同步关系。

## Assumptions

- 源工作区读权限复用现有 workspace 权限模型（READ 级即可，目标表仍需 EDIT_SCHEMA）。
- 工作区列表 API 已存在且返回当前用户可访问的工作区（若无专门 API，用现有登录后工作区列表接口）。
- 引入后字段为独立副本，不随源表变化，此交互文案维持不变。

## Solution

后端：在 `import_fields`（src/cndb/plugins/tables/routers/fields.py L293 起）取到 `src` 后，调用现有工作区权限依赖/服务校验 `current_user` 对 `src.workspace_id` 有 READ 权限；无权限返回 400，detail 指明源工作区名称。preview_only 同样受限（防止枚举探测字段名）。

前端（FieldManager/index.tsx 引入对话框）：
1. 新增状态 `sourceWid`；源表 Select 改为两步级联（工作区 Select + 表 Select），工作区选项来自工作区列表 query，表选项 `tableApi.list(sourceWid)`，过滤目标表自身。
2. 源字段 query 的 queryKey 与 queryFn 改用 `sourceWid`。
3. 勾选区顶部加"全选/反选"与名称搜索 Input（前端过滤）。
4. 映射面板：suggestions 按 `will_map` 分两组渲染，组头提供"仅引入已匹配"按钮（把 `!will_map` 的项在 importMapping 中置 null）。

## Edge cases & risks

| Category | Notes |
|---|---|
| Boundary conditions | 源表在回收站 / 源表不存在 → 沿用现有 400；源工作区被删 → 400 |
| Failure modes | 用户仅有源工作区读权限但字段列表接口要求更高权限 → 需核实 fields list 权限级别，若高于 READ 需对齐或降级校验口径 |
| Risks | 权限收紧属行为变更：原先能用的匿名跨工作区路径会被拒 |
| Mitigation | 400 detail 返回源工作区名，前端 message 展示；测试覆盖 preview 与执行两路径的拒绝分支 |

## Acceptance criteria

- AC-1 用户 A 对源工作区无任何权限时，`POST .../fields/import`（含 preview_only=true）返回 400，detail 含源工作区名称；不返回源字段任何信息。
- AC-2 用户 A 对源工作区有 READ 权限时，选择该工作区源表可预览并成功引入多字段。
- AC-3 前端源表选择器工作区下拉仅含用户可访问的工作区，且不包含权限不足项；选择后表下拉排除目标表自身。
- AC-4 勾选区提供全选/反选与按名称过滤，过滤后勾选状态保持。
- AC-5 映射面板按推荐/低置信度分组，点击"仅引入已匹配"后所有低置信度项映射为跳过，确认引入结果与映射一致。
- AC-6 `make check` 全绿（后端新权限测试 + 前端组件测试通过）。

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| Workspace | 既有 | id, name | 拥有 DataTable |
| DataTable | 既有 | id, workspace_id, trashed | 拥有 DataField |
| DataField | 既有 | name, field_type, config | 引入后为目标表独立副本 |
| FieldImportRequest | 既有 | source_table_id, field_ids, field_mapping, preview_only | 本次收紧权限校验 |

## Interview metadata

- Mode: default
- Waves: 2
- Final ambiguity: ~22%
- Status: PASSED
- 决策 1：源工作区需读权限（用户选定"收紧为需源工作区读权限"）。
- 决策 2：仅字段设置入口升级，建表入口不动（用户选定）。
