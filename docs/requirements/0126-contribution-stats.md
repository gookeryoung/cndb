# 需求卡片：工作区统计「贡献统计」按编辑者展示贡献

- 编号：0126
- 来源 / 提出人：用户（会话 2026-11-08）
- 日期：2026-11-08
- 关联 ADR：无（S1，方案并入本卡片；统计页布局见需求 0093 C7）
- 分级：**S1**（跨后端聚合 + 前端统计页 + 数据行审计归属补记，无数据模型变更 / 无迁移）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 统计，贡献统计，按照项目编辑者显示贡献情况。需考虑曾经是编辑者的情况。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「按照项目编辑者」 | **范围 = 当前工作区**（`workspace_id`），不按模板项目上下文的项目行拆分；统计页 `?section=contribution` 分项展示。 | `workspaces` 插件、`frontend/src/pages/workspace/` | 接口只返回当前 `wid` 数据；前端分项渲染 |
| C2 | 「显示贡献情况」 | **纳入人员**：当前角色为 `owner` / `editor` 的成员（0 贡献也展示）+ 有直接写活动痕迹的曾为编辑者。按 `user_id` 去重；`owner` 与 `editor` 一并在「编辑者」口径内展示。 | `workspaces/models.py`、聚合服务 | 单测：当前 editor 0 贡献也出现；viewer 无活动不出现 |
| C3 | 「曾经是编辑者的情况」（判定） | **判定 = 历史活动推断**：当前已是 `viewer` 或已移出工作区（无 `WorkspaceMember` 行）的用户，只要存在 C4 任一直接写活动，即纳入并标记「曾为编辑者」；已移出另标「已移出」。不新增成员角色变更历史表。 | 聚合服务 | 单测：editor→viewer 仍出现且带标记；移出成员仍出现 |
| C4 | 「贡献情况」（活动口径） | 只统计**直接写入**（不含查看、不含 viewer 生成的修改申请）：① 数据行新建 `tables_auditlog.action=create`；② 数据行更新 `action=update`；③ 文档新建（`documents_document.created_by_id`）；④ 文档保存（`documents_documentversion.version_number > 1` 的 `created_by_id`）；⑤ 设计新建（`design_design.created_by_id`）；⑥ 设计保存（`design_designversion.version_number > 1` 的 `created_by_id`）。六项相加为 `total`。 | `tables` / `documents` / `design` 模型与审计 | 判定层单测逐项计数与合计 |
| C5 | 「需考虑曾经是编辑者」（存量数据） | 现有 `tables_auditlog.actor_id` 在行创建/更新时未写入，历史行无法归属；本期在写入路径补记 `actor_id`（`log_action` / `create_row` / `update_row` 透传当前用户），历史 NULL 行不计入，前端注明「数据行统计自本版本起」。 | `tables/services/core/audit.py`、`records.py`、`routers/records.py` | 接口层：新建/更新行后审计行 `actor_id` 正确；前端提示文案 |
| C6 | 「显示贡献情况」（接口） | 新增 `GET /api/v1/workspaces/{wid}/stats/contributions`，工作区成员可读（非成员按现有约定 404）；返回每人 6 项计数、`total`、`last_active_at`、当前角色 / 是否成员 / `is_former_editor`；按 `total` 降序、`last_active_at` 降序；**全部时间**，无时间参数、无分页。 | `workspaces/routers/`、`schemas/` | 接口层：排序、字段、非成员、空工作区 |
| C7 | 「显示贡献情况」（前端） | 替换贡献统计空态：加载 / 错误 / 空态 + 成员贡献表（成员、角色 / 曾为编辑者 / 已移出、数据行新建 / 更新、文档新建 / 保存、设计新建 / 保存、合计、最近活动）；按工作区已启用模块隐藏对应列；文案与操作提示遵循 ADR 0105。 | `frontend/src/pages/workspace/WorkspaceStatsPage.tsx`、`frontend/src/api/workspaces.ts` | 前端单测：有数据表格、模块列隐藏、空态 / 错误态；e2e 更新占位断言 |
| C8 | （性能 / 缓存） | 聚合按需实时计算（与文档 / 设计计数同口径），不引入新缓存；查询只走既有索引，按 `workspace_id` 限定；列表规模 = 工作区编辑者数量。 | 聚合服务 | 接口层：无缓存仍正确；查询计划人工核对 |
| C9 | （文档） | CHANGELOG 记录；CONTEXT「工作区统计」条目补充贡献统计口径；移除「贡献统计暂为空状态占位」表述。 | `CHANGELOG.md`、`CONTEXT.md` | `make check-docs` |
| C10 | 「类似 GITHUB 的图表曲线」（形态） | 贡献统计新增两段图表：① **GitHub 主页式日历热力图**：近 12 个月按天着色（0–4 五档），行 = 星期、列 = 周，单元格悬停显示「日期：N 次贡献」；② **按月折线趋势**：按自然月汇总所选范围贡献总量，平滑折线 + 面积。图表与成员贡献表同页展示。 | `frontend/src/pages/workspace/` | 前端单测：日历 / 趋势容器与按天着色数据渲染 |
| C11 | 「图表曲线表示数据」（维度 / 时间） | 趋势默认「工作区总量」，可切换单个成员；日历与趋势共用同一时间窗口 **近 12 个月（含今天共 365 天）**，不提供其他时间范围控件。 | 聚合服务、前端图表组件 | 单测：窗口外活动只进累计值、不进时序 |
| C12 | （接口） | `GET /api/v1/workspaces/{wid}/stats/contributions` 响应新增 `timeline_start` / `timeline_end`（日期）与 `daily`（仅窗口内、计数非零的 `{date, user_id, count}`），累计字段仍为全部时间；不新增接口、不引入缓存。 | `workspaces/services/contributions.py`、`schemas/` | 接口层：时序字段、同日合并、窗口过滤 |

约束编号在实现中原样引用；不重编号、不合并。

## S1 方案（并入卡片）

### 聚合服务

新增 `workspaces/services/contributions.py::compute_workspace_contributions(db, workspace_id)`：

1. 取工作区内未回收站数据表 `DataTable.id` 集合，按 `tables_auditlog.actor_id` + `action in (create, update)` 分组计数；`actor_id IS NULL` 跳过。
2. 文档：`documents_document` 按 `created_by_id` 计新建；`documents_documentversion` join `documents_document`（同工作区）且 `version_number > 1` 按 `created_by_id` 计保存。
3. 设计：`design_design` 按 `created_by_id` 计新建；`design_designversion` 按 `workspace_id` + `version_number > 1` 的 `created_by_id` 计保存。
4. 汇总当前成员角色（`WorkspaceMember` join `User`）；并集 = 当前 `owner/editor` + 所有有活动计数的 `user_id`。
5. 用户已删除时仍以 `user_id + actor_name 快照` 展示；无 User 行显示「已删除用户」。
6. `is_former_editor` = 当前角色不是 `owner/editor`（含非成员）且存在活动；`is_member` = 是否有当前成员行。

### 接口契约

```
GET /api/v1/workspaces/{wid}/stats/contributions
200 {
  "generated_at": "2026-11-08T12:00:00Z",
  "timeline_start": "2025-11-09",
  "timeline_end": "2026-11-08",
  "daily": [
    {"date": "2026-01-03", "user_id": 12, "count": 2}
  ],
  "items": [{
    "user_id": 12, "username": "alice", "nickname": "Alice",
    "role": "editor" | "viewer" | "owner" | null,
    "is_member": true, "is_former_editor": false,
    "rows_created": 10, "rows_updated": 4,
    "documents_created": 2, "documents_edited": 3,
    "designs_created": 1, "designs_edited": 1,
    "total": 21, "last_active_at": "2026-11-08T11:00:00Z"
  }]
}
```

权限与 `GET /workspaces/{wid}` 同口径：`_require_member`，非成员按现有约定返回 404（工作区不存在同为 404）。

### 数据行操作人补记

- `log_action(..., actor_id=...)` 已有形参，补齐调用方：`create_row` 增加可选 `user`，`update_row` 已接收 `user`；`routers/records.py` 的创建 / 更新调用传入 `current_user`。
- 批量导入 / 数据同步等无用户上下文的写入保持 `actor_id=NULL`（不计入个人贡献），不伪造归属。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 贡献统计占位空态 | `frontend/src/pages/workspace/WorkspaceStatsPage.tsx:66-79` | C7 替换为真实表格 |
| 2 | 统计分项定义 | `frontend/src/pages/workspace/workspaceStatsSections.tsx:14-18` | 无需改动 |
| 3 | 前端统计页单测 | `frontend/src/pages/workspace/WorkspaceStatsPage.test.tsx:86-93` | 占位断言改为真实数据 |
| 4 | e2e 统计分项 | `frontend/tests/e2e/critical/navigation.spec.ts:222-229` | 保留切换断言，补充表格可见 |
| 5 | 工作区详情统计 | `src/cndb/plugins/workspaces/routers/workspaces.py:213-264` | 新增独立统计端点，不改详情响应 |
| 6 | 工作区统计缓存 | `src/cndb/plugins/workspaces/services/stats_cache.py:38-96` | C8 不进缓存 |
| 7 | 成员角色 / 移除无历史 | `src/cndb/plugins/workspaces/routers/member_routes.py:125-204` | C3 用活动推断，不新增历史表 |
| 8 | 行审计写入 | `src/cndb/plugins/tables/services/core/audit.py:27-61` | C5 补 `actor_id` 调用方 |
| 9 | 行创建 / 更新 | `src/cndb/plugins/tables/services/core/records.py:375-415`、`:737-794` | C5 透传用户 |
| 10 | 行接口调用 | `src/cndb/plugins/tables/routers/records.py:281`、`:460` | C5 传入 `current_user` |
| 11 | 行审计模型 | `src/cndb/plugins/tables/models.py:555-566` | 已有 `actor_id`，无需迁移 |
| 12 | 文档作者字段 | `src/cndb/plugins/documents/models.py:125-130`、`:165-167` | C4 直接使用 |
| 13 | 设计作者字段 | `src/cndb/plugins/design/models.py:75-80`、`:114-116` | C4 直接使用 |
| 14 | 前端 API 封装 / 类型 | `frontend/src/api/workspaces.ts:9-31`、`frontend/src/api/types/workspaces.ts` | C6 新增方法与类型 |

## 未决问题（已确认）

- [x] ① 「项目」范围：**结论**当前工作区，不按项目上下文拆分（2026-11-08 用户确认）。
- [x] ② 贡献活动：**结论**数据表记录创建 / 编辑 + 文档创建 / 保存 + 设计保存；不含查看与 viewer 修改申请（2026-11-08 用户确认）。
- [x] ③ 曾经是编辑者：**结论**历史活动推断，不新增成员角色变更历史表（2026-11-08 用户确认）。
- [x] ④ 时间窗口：**结论**全部时间（2026-11-08 用户确认）。
- [x] ⑤ 历史数据表行无操作人：**结论**本期起补记操作人，历史 NULL 不计入并在页面标注（2026-11-08 用户确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-08 用户确认）
- [x] 需求确认（S1，人工拍板后进入实现）— 2026-11-08 用户确认

## 落地状态（2026-11-08）

- C1-C9 已实现：`workspaces/services/contributions.py`（新增）、`GET /workspaces/{wid}/stats/contributions`、数据行审计 `actor_id` 透传、前端贡献表与模块列隐藏。
- C10-C12 已实现：贡献统计页新增 GitHub 风格日历热力图与按月折线趋势（`frontend/src/pages/workspace/ContributionCharts.tsx`），趋势默认工作区总量、可切换单个成员；接口新增 `timeline_start` / `timeline_end` / `daily`（近 365 天、仅非零日），累计值仍为全部时间。
- 测试：`tests/test_workspace_contributions.py` 7 例（含同日合并与窗口外过滤）、`WorkspaceStatsPage.test.tsx` 8 例；`make check-fast` 绿。
- 边界：历史数据行无 `actor_id` 不计入；成员角色变更史未新增，曾为编辑者按历史活动推断；按天时序只覆盖近 12 个月，更早活动只体现在累计值。
