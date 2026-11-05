# 需求卡片：数据表修改申请页左右列表布局（按工作表分组 + 修改项展开显示行上下文）

- 编号：0107（与 ADR `docs/adr/0107-*.md` 同号；S1 项不写 ADR，方案见「口径」节）
- 来源 / 提出人：用户
- 日期：2026-11-06
- 关联 ADR：无（S1）

> 本卡片是**需求原文与约束编号的唯一副本**：如后续升级 S2 写 ADR，ADR 只引用 C1..Cn，不复制原文。

## 需求原句（逐字）

> 数据表，修改申请，采取左右列表布局，左侧列表为涉及的工作表，右侧列表为修改项。修改项的详情支持展开，能够显示修改行的上下文，便于用户理解。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 采取左右列表布局 | 工作区级「数据表修改申请」页（路由 `w/:wid/tables/change-requests`，`ChangeRequestsPage` workspaceMode）改为左右两栏：左栏为工作表清单，右栏为修改项清单，左右栏独立滚动 | `frontend/src/pages/changeRequests/` | 前端单测 + e2e |
| C2 | 左侧列表为涉及的工作表 | 左栏按 `table_id` 对当前 scope 的申请去重分组：每项显示表名与该表申请数（随 scope 联动）；默认选中申请数最多（并列取最新一条申请时间更近者）的表；选中态高亮，切换后右栏随之刷新 | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx` | 前端单测（分组/默认选中/计数） |
| C3 | 右侧列表为修改项 | 右栏展示选中表下的修改申请列表（复用工作区级列表响应按 `table_id` 过滤，不新增后端端点）；条目信息沿用现状：状态 Tag、标题、#id、提交人、时间、基准过期 / 冲突标记 | 同上 | 前端单测 |
| C4 | 修改项的详情支持展开 | 每条修改项支持展开 / 收起（Collapse）：展开后懒加载 `changeRequestsApi.get(wid, tableId, requestId)` 详情，展示变更项的字段级上下文——op 标签（新增/修改/删除）、行号、`base_values`（提交时基准）、`values`（申请值）、`current_values`（当前行值，即"修改行的上下文"）；行已删除 / 基准漂移时展示对应提示；同一申请只拉一次详情（缓存） | 同上 + `frontend/src/api/changeRequests.ts` | 前端单测（展开懒加载 / 上下文渲染 / 行缺失提示） |
| C5 | 便于用户理解 | 展开区为**只读**展示（不做逐项 apply/skip 决策，不合并）；点击申请标题仍跳转既有详情页（审批 / 评论 / 流转入口不变）；scope 筛选（待审核/已合并/全部/我的）保留并驱动左栏计数 | 同上 | 前端单测 + e2e |

## 口径（S1 方案，无 ADR）

- 改动面：仅前端（`ChangeRequestsPage.tsx` workspaceMode 分支 + 相关 API 类型 / 单测）；单表视图（`:tid` 路由）与同行合并视图（group_by=row）不改动。
- 数据来源：工作区级列表端点 `GET /{wid}/change-requests` 现有响应已含 `table_id/table_name/item_count/row_ids/conflicts_count`，左栏与右栏过滤纯前端派生；展开上下文懒加载既有详情端点，**零后端改动、零迁移**。
- 展开性能：详情响应按 requestId 内存缓存（组件级 state / react-query cache），重复展开不重复请求。
- 「上下文」口径：`current_values` 即当前整行字段值（含未修改字段），配合 `base_values/values` 形成三态对照；行不存在时降级展示「行已删除」提示（复用详情响应 `row_missing`）。
- 权限口径不变：列表仍走 `readable_tables` 可见表过滤；后端 403 兜底不变。

## 现状影响面（候选，已粗查）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区级修改申请扁平列表 | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx:138-385`（workspaceMode 分支） | 本次重构对象；单表分支保留 |
| 2 | 工作区级列表端点（附 table_name） | `src/cndb/plugins/change_requests/services.py:212-252`、`routers/change_requests.py:100-112` | 已含分组所需字段，不改 |
| 3 | 申请详情端点（items 三态 diff） | `src/cndb/plugins/change_requests/services.py:263-312` | 展开上下文数据源，不改 |
| 4 | 字段级 diff 表格组件 | `frontend/src/components/DiffView`（FieldDiffTable） | 展开区复用其展示形态 |
| 5 | 前端 API 封装 | `frontend/src/api/changeRequests.ts:25-28`（listWorkspace / get） | 已够用，不改 |

## 未决问题

- [x] Q1 窄屏（移动端）降级形态：左栏收为顶部横向滚动的胶囊标签，右栏占满宽度（2026-11-06 需求方确认）
- [x] Q2 展开能力在全部 scope 下可用（待审核 / 已合并 / 全部 / 我的），历史申请详情仍可查（2026-11-06 需求方确认）
- [x] Q3 「新建修改申请」按钮与写模式提示文案原位保留，行为不变（2026-11-06 需求方确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认
