# Spec 0122：工作区项目上下文（多项目清单与单项目工作台）

- 需求卡片：`docs/requirements/0122-workspace-project-context.md`（C1-C12 唯一副本）
- 方案 ADR：`docs/adr/0122-workspace-project-context.md`（I1-I6 / D1-D10，已 Accepted）
- 硬约束：`docs/CONSTRAINTS.md` H39-H44
- 分级：S2 / L2；分期 P0 → P1 → P2

## 1. 目标与不变量

同一工作区既支持“多项目清单”，也支持“单项目工作台”：

- 单项目 = 模板根表单只有 1 行的退化形态，复用同一套模板、接口与页面（I4）。
- 项目身份 = 根表单 `project_application` 的行 ID（`project_row_id`），不新建项目主表。
- 项目阶段、门禁、文档均按项目隔离；工作区级表单不参与项目门禁（I1/I3）。
- 存量工作区默认 `project_mode=workspace`，显式启用才切换（I5）。
- 项目状态与文档映射必须可备份、可恢复（I6）。

## 2. 数据模型

### 2.1 `workspaces_workspace.project_mode`

- `varchar(16)`，非空，默认 `workspace`，取值 `workspace` / `project`。
- 新建工作区时：模板 spec 含 `project` 块 → `project`；否则 `workspace`。
- 存量零回填。

### 2.2 新表 `workspaces_workspace_project_state`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `workspace_id` | int FK CASCADE | |
| `project_row_id` | int 非空 | 根表单行 ID |
| `stage_key` | varchar(64) 非空 | 当前阶段 |
| `history` | JSON 默认 `[]` | 项目级推进履历 |
| `created_at` / `updated_at` | datetime | |

唯一键 `(workspace_id, project_row_id)`；索引 `(workspace_id, stage_key)`。

### 2.3 新表 `workspaces_workspace_project_document`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `workspace_id` | int FK CASCADE | |
| `project_row_id` | int 非空 | |
| `doc_key` | varchar(64) 非空 | 模板文档规则 key |
| `document_id` | int FK documents CASCADE | |

唯一键 `(workspace_id, project_row_id, doc_key)`；索引 `(workspace_id, document_id)`。

### 2.4 模板 spec

顶层新增可选 `project`：

```json
{"root_form": "project_application", "link_field": "所属项目", "title_field": "项目名称", "documents": "per_project"}
```

表单新增可选 `scope`（`project` / `workspace`）。校验规则（`normalize_spec`）：

1. `project` 出现时 `root_form` 必须存在；
2. `link_field` 必须是非根 `scope=project` 表单上的 link 字段，`target_form=root_form` 且 `multiple=false`；
3. `title_field` 必须是根表单文本字段；缺省 `项目名称`，再缺省根表单第一个文本字段；
4. 存在 `project` 时，非根表单必须显式声明 `scope`；
5. `documents` 取值 `workspace` / `per_project`，默认 `workspace`；
6. 无 `project` 的旧模板全部表单视为 `scope=workspace`，输出与现状一致。

## 3. 服务层

### 3.1 新模块 `services/templates/project_context.py`（无 engine 依赖）

- `project_config(spec) -> dict | None`：读取并补默认值。
- `form_scope(spec, form_key) -> str`：`project` / `workspace`，无 project 块返回 `workspace`。
- `resolve_project_row(db, ws, spec, project_row_id) -> int`：校验根表单行属于该工作区的根表且未软删，否则 `ProjectContextError`（路由层 404）。
- `count_project_rows(db, table, link_field, project_row_id) -> int`：按 link 关联表统计该项目行数（排除源表软删）。
- `root_form_table(db, ws, spec) -> DataTable | None`。
- `render_doc_title(rule, title_value) -> str`：`naming` 的 `{title_field}` 替换；无占位时 `项目名称-规则标题`。

### 3.2 `engine.py`

- `lifecycle_state(db, ws, template, project_row_id=None)`：
  - `project_mode=workspace` 或在 `project_mode=project` 且未启用项目行：沿用现有逻辑；
  - `project_mode=project`：读 `workspace_project_states`，无记录按第一阶段只读；门禁只统计 `scope=project` 表单且 `link_field = project_row_id`；`scope=workspace` 不计入；文档按 `per_project` 映射存活。
- `advance_stage(..., project_row_id=None)`：项目模式 upsert 项目状态；工作区模式沿用 `template_stage`。
- `apply_spec_to_workspace`：仅当文档规则为工作区级（无 project 或 `documents=workspace`）时创建共享占位；项目文档由启用/补建接口处理。
- `project_list(db, ws, template)`：返回 `[{project_row_id, title, stage_key, stage_name, gate_satisfied, missing_forms, missing_documents, initialized}]`。
- `enable_project_mode(db, ws, template, user, generate_documents=False)`：所有者、幂等；按当前阶段为所有根表单行初始化状态；可选补项目文档。
- `ensure_project_documents(db, ws, template, user, project_row_id)`：仅补缺失映射；标题按 `naming` 渲染；不覆盖正文。

### 3.3 API

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/projects` | 新增：项目清单 + 阶段 + 门禁摘要 |
| `GET /api/v1/workspaces/{wid}/data-flow?project_id=` | 新增可选参数；多项目必填 422 `project_required`；零项目 409 `project_empty`；单项目自动 |
| `GET /api/v1/workspaces/{wid}/lifecycle?project_id=` | 同上 |
| `POST /api/v1/workspaces/{wid}/lifecycle/advance` | body 新增可选 `project_id`；项目模式必填 |
| `POST /api/v1/workspaces/{wid}/project-mode/enable` | 新增：仅所有者；幂等；`generate_documents` |
| `POST /api/v1/workspaces/{wid}/projects/{row}/documents` | 新增：编辑者+；补缺失项目文档 |
| `GET /api/v1/workspaces/{wid}/documents?project_id=`（list / tree） | 新增可选过滤；不传保持现状 |

## 4. 备份

- `BACKUP_VERSION = "15"`；workspace 元信息新增 `project_mode`；新增顶层 `project_states[]` / `project_documents[]`。
- 恢复：先文档后映射；v14 及更早缺省 `project_mode=workspace`、两张表为空；`clear_workspace_content` 清理两表。

## 5. 前端

- 工作区级项目上下文 hook：读取 `?project=`，拉取 `/projects`；单项目自动选中；多项目渲染顶部项目切换器。
- 新增项目清单页 `/w/:wid/projects`：项目名称 / 负责人 / 阶段 / 门禁 / 文档缺失；点击进入 `?project=`。
- `DataFlowPage` / 生命周期面板 / 文档树读取 `project` 参数；422 / 409 空态。
- 模板编辑器：`project` 配置区与表单 `scope` 选择；服务端 422 path 直接展示。

## 6. 验收与门禁

- 后端单测：spec 校验、项目门禁隔离、推进互不影响、文档命名、启用幂等、跨工作区 404。
- 接口层：projects 列表、data-flow 200/422/409、lifecycle advance、project-mode/enable、项目文档补建、documents 过滤。
- 迁移：upgrade / downgrade 可逆；存量 `workspace` 零回填。
- 备份：v15 往返一致；v14 旧包回落 `workspace`。
- 前端单测 + e2e：单项目自动选中、多项目切换、推进 A 不影响 B。
- 门禁：`make check-fast`（每期）→ `make flow`；收尾 `make check`（覆盖率口径变化时）。

## 7. 分期与交付顺序

- P0：模型 + 迁移、spec 扩展、项目级生命周期 / 门禁、projects / data-flow / lifecycle API、project-mode enable、备份 v15、前端上下文 / 切换器 / 清单页 / data-flow 项目参数。
- P1：项目文档映射与实例化、文档树过滤、存量启用流程。
- P2：清单统计列、批量补文档、未初始化项目修复；删除不可落地的“提醒”项。

## 8. 需人工确认事项

- 本规格与 ADR 0122 一致；用户已于 2026-11-08 确认按此推进到结束。
- H39-H44 台账条目已登记（来源 ADR 0122 I1-I6）。
