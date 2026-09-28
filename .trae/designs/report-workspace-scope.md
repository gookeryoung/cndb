# 报表归属工作区（report-workspace-scope）

## 背景与目标

报表 tab 已下沉到工作区分页导航（见 workspace-tab-nav.md），但报表页仍展示全量模板（`GET /v1/reports` 无工作区过滤），且「数据资产」「报表」tab 不显示数量。本轮目标：

1. 报表归属工作区：报表页只显示当前工作区拥有的模板。
2. tab 徽标：「数据资产」显示当前工作区表数量，「报表」显示当前工作区报表数量，「工作区设置」不显示。

## 归属语义

`ReportTemplate` 新增 `workspace_id` 列（显式归属，优先于 table_id 反推）：

- 创建时前端从路由上下文（`/w/:wid/reports`）显式传 `workspace_id`；
- 未传且 `table_id` 存在时从表反推（API 兼容存量调用与 seed）；
- 两者皆无 → `workspace_id` 为 NULL（不归属任何工作区，不出现在任何工作区报表页，仅全量 API 可见）；
- 归属工作区被删除 → `workspace_id` SET NULL（模板仍在全量列表可见，与 `table_id` 的 SET NULL 语义一致）。

## 数据模型

- `reports_template` 新增列 `workspace_id`：Integer，FK `workspaces_workspace.id`，ondelete SET NULL，nullable，索引。
- 迁移 `e5f6a7b8c9d0`（down_revision `d4e5f6a7b8c9`）：
  1. `_table_exists` 守卫复用 theme 迁移模式；
  2. `op.add_column` 加列；
  3. `op.create_foreign_key` + `op.create_index`；
  4. 回填：`UPDATE reports_template SET workspace_id = (SELECT t.workspace_id FROM tables_datatable t WHERE t.id = reports_template.table_id) WHERE table_id IS NOT NULL AND workspace_id IS NULL`（SQLite 关联子查询 UPDATE 语义）。
- downgrade：逆序删索引/外键/列。
- seed（cli/seed.py `_seed_report_templates`）：创建模板时显式写 `workspace_id`（取所属表的工作区）。

## 接口定义

### 后端

- `GET /v1/reports?workspace_id={id}`：可选过滤；缺省返回全量（API 兼容）；排序（id）与响应结构不变。
- `POST /v1/reports`：`TemplateCreate` 新增可选 `workspace_id`；显式传入时校验工作区存在（不存在 404）；未传且 table_id 存在时从表反推；两者皆无落 NULL。
- `TemplateResponse` / `TemplateListResponse` 新增 `workspace_id: int | None`。
- `GET /v1/workspaces` 列表响应（`WorkspaceWithPinnedResponse`）新增 `report_count: int`（与 table_count 同事务聚合）。

### 前端

- `reportApi.list(params?: { workspaceId?: number | string })` → `GET /v1/reports?workspace_id=X`。
- 类型 `ReportTemplate` / `ReportTemplateSummary` / `ReportTemplateCreate` 新增 `workspace_id?: number | null`；`Workspace`（列表类型）新增 `report_count: number`。
- ReportsPage：queryKey `['report-templates', wid]`、`list({ workspaceId: wid })`；create payload 注入 `workspace_id: Number(wid)`（编辑器表单不感知工作区）；create/remove/update 成功后追加 invalidate `['workspaces']`（tab 徽标刷新）。
- MainLayout：tab label 渲染数量——「数据资产」= `tables.length`（既有 `['workspaces', wid, 'tables']` 缓存，零新请求）；「报表」= `currentWs.report_count`（既有 `['workspaces']` 缓存，零新请求）。

## 算法与流程

- list 过滤：`workspace_id` 参数非空时 `stmt.where(ReportTemplate.workspace_id == workspace_id)`；其余逻辑不变。
- create 归属解析顺序：payload 显式 `workspace_id` → `table_id` 反推 → NULL；显式值需校验工作区存在。
- seed：模板创建时显式写 `workspace_id`（回填仅覆盖存量库，新建库依赖 seed 落值）。

## 异常处理

- create 传入不存在的工作区 id → 404「工作区不存在」。
- create 未传 workspace_id 且 table_id 不存在 → 既有 404「数据表不存在」语义不变。
- 工作区被删除 → 模板 `workspace_id` SET NULL，模板仍在全量列表可见，不出现在任何工作区报表页。
- badge 数量为 0（无报表）照常显示「报表 0」？——不：数量为 0 仍显示（语义一致），仅渲染条件为字段存在。

## 依赖项描述

- reports 路由依赖：`workspaces_workspace` 表（FK）、`tables_datatable` 表（回填与反推）。
- workspaces 列表聚合新增对 `reports_template` 的 count 查询（与 table_count 同一事务）。
- 文案联动：新手引导与帮助中心如描述「报表页显示全部模板」需同步为「当前工作区」口径（实现时核对 onboardingSteps / helpContent）。
- 测试联动：msw handlers 的 workspaces 响应需补 `report_count`；报表列表响应补 `workspace_id`。

## 验收清单

- [x] `GET /v1/reports?workspace_id=X` 只返回归属 X 的模板；缺省仍返回全量。
- [x] `POST /v1/reports` 带 workspace_id 正确落库；工作区不存在 404；未传时从 table_id 反推。
- [x] 迁移回填：存量带表模板 workspace_id = 表所在工作区；无表模板保持 NULL。
- [x] `GET /v1/workspaces` 列表含 `report_count`。
- [x] 报表页（/w/:wid/reports）只显示当前工作区报表；新建/删除后列表与徽标同步刷新。
- [x] MainLayout tab「数据资产」「报表」显示数量，数量为 0 也显示；「工作区设置」不显示；查询未就绪时不渲染数量（见 workspace-tab-nav.md）。
- [x] 新手引导/帮助中心文案与实际口径一致（onboardingSteps/helpContent 均按「当前工作区」表述，无需改动）。
- [x] 前后端测试全绿；make check 通过。
