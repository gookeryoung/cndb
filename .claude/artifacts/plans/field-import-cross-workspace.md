# 字段引入跨工作区增强 Implementation Plan

> Status: APPROVED
> Source: .claude/artifacts/designs/field-import-cross-workspace.md
> Mode: (default)
> Iterations: 1 / 3
> Author: 用户
> Last updated: 2026-09-23

## Requirements summary

字段管理"从其他表引入字段"升级：源表选择器支持跨工作区（级联工作区→表），后端收紧为源表需 READ 权限（含 preview_only），并增强映射分组、仅引入已匹配、全选/反选、字段搜索等操作体验。建表入口 `import_from_table_id` 不动。

## Acceptance criteria

- AC-1 用户对源表无 READ 权限时，`POST .../fields/import`（含 preview_only=true）返回 400，detail 含源工作区名称。
- AC-2 有 READ 权限即可跨工作区预览并成功引入多字段。
- AC-3 前端源表选择器：工作区下拉仅含 `workspaceApi.list()` 返回项；表下拉排除目标表自身；源字段拉取使用源表所在 wid。
- AC-4 勾选区支持全选/反选与名称过滤，过滤不清空勾选。
- AC-5 映射面板按"推荐/低置信度"分组，"仅引入已匹配"一键把低置信度项置为跳过。
- AC-6 `make check` 全绿。

## RALPLAN-DR

### Principles
- 最小代码：只动引入对话框与 import_fields 权限校验，不动建表链路。
- 复用既有抽象：权限用 `check_action`，工作区列表用 `workspaceApi.list`，字段拉取用 `fieldApi.list`。
- 权限拒绝不泄露源字段信息（400 而非 403，detail 只含工作区名）。

### Decision drivers
- 安全正确性（权限收紧是本次核心）
- 前后端权限口径一致（fields list 已要求源表 READ）
- 改动面小、测试易写

### Viable options
**Option A（选定）：级联双 Select + check_action READ 校验**
- 前端在引入对话框内加工作区 Select（workspaceApi.list）+ 源表 Select（tableApi.list(sourceWid)）；后端 import_fields 对 src 表 `check_action(..., TableAction.READ)`。
- Pros: 零新后端接口；口径与 fields list 一致；改动集中两个文件。
- Cons: 工作区多时需搜索（Select showSearch 解决）。

**Option B：后端新增"可引入源表汇总"接口**
- 后端一次性返回所有可读工作区+表树，前端单 Select 分组渲染。
- Pros: 前端一次请求。
- Cons: 新增 API + schema + 测试，违背最小代码；表多时响应大；被否。

### ADR
- **Decision**: 采用 Option A，前端级联选择 + 后端 check_action(READ) 收紧。
- **Alternatives**: Option B rejected（新增接口不必要，违背最小代码）。
- **Consequences**: 原先可跨工作区无权限探测字段定义的路径被堵；fields list 权限口径（READ）即引入口径，无新规则。
- **Follow-ups**: 建表入口 `import_from_table_id` 若将来要跨工作区，复用同一校验（记录于 spec Out of scope）。

## Implementation steps

1. 后端权限收紧 — `src/cndb/plugins/tables/routers/fields.py:311-318`：取到 `src` 后，`db.get(Workspace, src.workspace_id)` 取源工作区，`check_action(db, src, current_user, TableAction.READ)` 为 False 时 `raise HTTPException(400, detail=f"没有源工作区「{ws.name}」的读取权限，无法引入其字段")`；顶部补 `Workspace` 与 `check_action`/`TableAction` 导入（`TableAction` 已导入）。
2. 后端测试 — `tests/test_fields_import.py`：新增 3 用例：无源工作区权限（含 preview_only=true）→ 400 且 detail 含工作区名；有 READ（viewer 角色）跨工作区 preview+执行成功；源工作区不存在（防御分支沿既有 404/400 路径不动，仅必要时补）。
3. 前端类型 — `frontend/src/api/types.ts` 无需新字段（Workspace/TableSummary/FieldImportResponse 已有）。
4. 前端级联选择 — `frontend/src/pages/fields/FieldManager/index.tsx`：
   - 新增 `sourceWid` state；新增 workspaceApi.list 的 useQuery（enabled: importOpen）。
   - 源表 query 的 queryKey/queryFn 改用 `sourceWid`（`['tables', sourceWid]`），enabled 依赖 sourceWid；源字段 query 同理（`['fields', sourceWid, sourceTableId]`）。
   - 源表 Select 前加工作区 Select（showSearch，选项过滤掉目标工作区可选保留——保留但标记"当前"）；切换工作区时清空 sourceTableId/勾选/预览；表 Select options 过滤目标表自身，label 对跨工作区表显示 `表名`（工作区已在上一步体现）。
   - `runPreview`/`importMutation` 不变（仍传 `wid,tid` 目标 + source_table_id）。
5. 体验增强 — 同文件：
   - 勾选区头部加"全选/反选"按钮（基于过滤后列表）与名称搜索 Input（本地 state，过滤 `sourceFieldsWithConflict`，不动勾选值）。
   - 映射面板：suggestions 先按 `will_map` 分组渲染（推荐组在前），组头 Tag 计数；推荐组头右侧"仅引入已匹配"按钮 → 把 `!will_map` 项在 importMapping 置 null。
6. 前端测试 — 查找现有 FieldManager 相关测试（glob frontend/src/pages/fields/**/*.test.tsx）更新/新增：级联渲染、过滤+全选、仅引入已匹配逻辑（提取纯函数到 `kanbanBoard.ts` 式工具文件如 `fieldImport.ts` 便于单测，若现有结构允许则内联+组件测试）。

## Workspace setup

- `git status --short` / `git branch --show-current`：若干净且在 main，建议 `git worktree add -b codex/field-import-cross-ws ../cndb-field-import`；dirty 时保护现有改动，不混提交。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| 权限收紧破坏既有测试（测试账号对源表无显式 READ） | 既有测试多为同工作区/owner，check_action 天然放行；跑全量 pytest 验证 |
| 前端 query 缓存键变化导致旧数据残留 | queryKey 含 sourceWid，切换即隔离；closeImportDialog 重置全部 state |
| "仅引入已匹配"与用户手工调整冲突 | 按当前 suggestions 的 will_map 即时计算，不缓存 |

## Verification steps

- AC-1/AC-2：`uv run pytest tests/test_fields_import.py -q`（新增用例全绿）。
- AC-3/4/5：`cd frontend && pnpm test -- pages/fields` + `pnpm check`。
- AC-6：仓库根 `make check`。
- 手工：`make dev` 起服务，两个工作区各建表，验证级联选择、预览、引入、权限拒绝提示。

## Review trail

- Planner draft v1: Option A/B 对比，选定 A。
- Architect challenge v1: steelman——400 vs 403 语义；tension——安全一致性 vs API 语义惯例；综合：沿用模块内既有 400 惯例（源表不存在也是 400），避免前端特判，保持一致。
- Critic verdict v1: APPROVED，reservation——源工作区已删除时 `db.get(Workspace)` 为 None，detail 生成需判空；已并入 step 1（ws 为 None 时 detail 不含名称）。
