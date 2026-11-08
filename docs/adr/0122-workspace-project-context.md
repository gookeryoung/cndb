# ADR 0122: 工作区项目上下文（多项目清单与单项目工作台）

Status: Proposed（待评审）
Date: 2026-11-08
Related: `src/cndb/plugins/workspaces/services/templates/engine.py`、`src/cndb/plugins/workspaces/services/templates/spec.py`、`src/cndb/plugins/workspaces/routers/data_flow.py`、`src/cndb/plugins/workspaces/routers/lifecycle.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/models.py`、`frontend/src/pages/dataFlow/DataFlowPage.tsx`、`docs/adr/0094-workspace-configurable-templates.md`
需求卡片: `docs/requirements/0122-workspace-project-context.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 一个工作区管多个项目的清单 | 根表单 `project_application` 一行一个项目；新增 `GET /workspaces/{wid}/projects` 返回项目行 + 阶段 + 门禁摘要；前端新增项目清单页 |
| C2 | 一个工作区又能管单个的项目 | 引入 `project_row_id` 上下文；数据流程、生命周期、文档树均按项目过滤；顶部项目切换器 + URL `?project=` 深链 |
| C3 | 一个工作区 | 不新增工作区类型 / 第二套模板；单项目是根表单 1 行的退化，走同一套模板、接口与页面 |
| C4 | 管单个的项目 | 新增 `workspace_project_states` 表；`lifecycle_state` / `advance` 增加可选 `project_row_id`，项目模式下按项目独立推进与记履历 |
| C5 | 管单个的项目 | 项目级门禁只统计 `scope=project` 且 `所属项目 = project_row_id` 的表单行；工作区级表单与别项目行不计入；文档按项目映射判断存活 |
| C6 | 管单个的项目 | 新增 `workspace_project_documents` 映射表；按文档规则为每个项目实例化占位文档，标题复用 `naming` 的 `{项目名称}` 占位，不覆盖已存在正文 |
| C7 | 项目 | `GET /data-flow` 增加可选 `project_id`；项目模式多项目时必填，单项目自动选中；新建记录默认写入 `所属项目` |
| C8 | 一个工作区 | 模板 spec 顶层新增 `project` 配置，表单新增 `scope`；`normalize_spec` 统一校验，旧模板缺省为工作区级 |
| C9 | （兼容口径） | 存量工作区默认 `project_mode=workspace`；显式启用项目级管理，幂等初始化；不自动拆分已有文档 |
| C10 | （权限口径） | 沿用工作区 owner / editor / viewer；推进编辑者及以上，应用/切换模板仅所有者；项目级成员权限不在本期 |
| C11 | （备份口径） | 新表纳入 `backup_io`，归档版本升到 v15；旧 v14 备份缺省还原为工作区模式 |
| C12 | （工程口径） | 单测 / 接口 / 迁移 / 备份 / 前端单测 / e2e 同轮补齐；更新 CONTEXT 与 ADR 交接 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 生命周期是工作区级单实例：`template_stage` + 阶段内整表行数 | `src/cndb/plugins/workspaces/services/templates/engine.py:524-596` | 同一工作区多个项目共享阶段，无法分别推进 | 确认 |
| 2 | 推进接口只按工作区推进，`force` 与履历也写在工作区 | `src/cndb/plugins/workspaces/routers/lifecycle.py:57-81`、`engine.py:599-651` | 无法表达项目级推进 | 确认 |
| 3 | 模板状态是单份映射：`template_state` 里 `form key → table id`、`doc key → doc id` | `src/cndb/plugins/workspaces/models.py:72-74`、`engine.py:41-47` | 缺项目级状态与项目级文档容器 | 确认 |
| 4 | 文档规则只创建一份占位文档，`naming` 已校验但实例化未使用 | `engine.py:266-285`、`src/cndb/plugins/workspaces/services/templates/spec.py:337` | 多项目无法各有一套立项 / 中期 / 结题文档 | 确认 |
| 5 | 数据流程接口无项目参数，计数与步骤按整表统计 | `src/cndb/plugins/workspaces/routers/data_flow.py:73-131` | 进入流程看到的是全部项目混在一起的数据 | 确认 |
| 6 | spec 顶层只允许 `forms` / `documents` / `stages` / `flows` | `spec.py:488` | 新增项目声明必须扩展校验，否则 422 | 确认 |
| 7 | 工作区备份元信息不含模板状态，新表需显式导出 | `src/cndb/plugins/workspaces/services/workspace_backup.py:157-165` | 不补导出会丢项目级状态与文档映射 | 确认 |
| 8 | 归档协议版本为 `BACKUP_VERSION = "14"` | `workspace_backup.py:51` | 需要 v15 与旧包兼容 | 新增 |
| 9 | 科研模板文档规则已声明 `{项目名称}` 命名 | `src/cndb/cli/seed/workspace_templates.py:541-575` | 可直接作为项目级文档命名入口 | 确认 |
| 10 | 数据流程前端只取前 500 行做快捷录入 | `frontend/src/pages/dataFlow/DataFlowPage.tsx:170-172` | 项目过滤后仍需保留上限，完整数据回数据表 | 确认 |
| 11 | 查看者写入仍走修改申请，记录 / 文档 202 逻辑与项目无关 | `src/cndb/plugins/tables/routers/records.py:82-116` | 项目上下文不得绕过既有权限与修改申请 | 新增 |
| 12 | 创建工作区可带 `template_id`，创建者登记为 OWNER | `src/cndb/plugins/workspaces/routers/workspaces.py:161-205` | 项目模式可在创建时按模板声明初始化 | 新增 |

**核心缺陷（需求要补的）**：现有模板只有“工作区级单实例阶段 + 单份文档占位”，无法表达同一工作区内多个项目各自的阶段、门禁与文档。

设计目标（不变量）：

- **I1 项目上下文边界**：`project_row_id` 必须属于当前工作区模板的根表单；跨工作区或跨表一律 404；所有项目级读写必须携带同一 `project_row_id`，不得回落到工作区级。
- **I2 生命周期唯一入口**：项目级阶段读取、门禁与推进只经 `lifecycle_state` / `advance_stage`；禁止业务代码直接改 `workspace_project_states`。
- **I3 门禁计数口径**：只统计 `scope=project` 且 `所属项目 = project_row_id` 的表单行；`scope=workspace` 的表单与其他项目行一律不计入；文档按项目映射且存活。
- **I4 单项目退化**：根表单只有 1 行时，项目模式与“单项目工作台”等价；前端自动选中并隐藏切换器，不产生第二套模板 / 路由。
- **I5 存量兼容**：未启用项目级管理的工作区保持工作区级阶段与共享文档；启用必须显式、幂等，且不自动拆分已有文档；旧备份恢复后为 `workspace` 模式。
- **I6 备份完整性**：项目状态与项目文档映射必须进 `backup_io`，往返一致；旧归档缺省还原为工作区模式（H12 / H14）。

> I1-I6 属跨需求不变量，按 H27 在 `Proposed → Accepted` 前登记入 `docs/CONSTRAINTS.md`，来源写 `ADR 0122 I#`。

## Decision

### 1. 数据模型

**新增表 `workspace_project_states`**

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | int | PK |
| `workspace_id` | int | FK `workspaces.id`，`ON DELETE CASCADE` |
| `project_row_id` | int | 根表单行 ID，非空；不建跨动态表 FK，由服务层校验归属 |
| `stage_key` | varchar(64) | 非空 |
| `history` | JSON | 默认 `[]`；项目级推进履历 |
| `created_at` / `updated_at` | datetime | 时间戳 |

唯一键 `(workspace_id, project_row_id)`；索引 `(workspace_id, stage_key)`。

**新增表 `workspace_project_documents`**

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | int | PK |
| `workspace_id` | int | FK `workspaces.id`，`ON DELETE CASCADE` |
| `project_row_id` | int | 根表单行 ID，非空 |
| `doc_key` | varchar(64) | 模板文档规则 key |
| `document_id` | int | FK `documents.id`，`ON DELETE CASCADE` |

唯一键 `(workspace_id, project_row_id, doc_key)`；索引 `(workspace_id, document_id)`。

**`Workspace` 新增列**

- `project_mode`：varchar(16)，非空，默认 `workspace`；取值 `workspace` / `project`。
- `workspace` 表示沿用现有工作区级生命周期；`project` 表示项目级生命周期。单项目不需要独立取值。

**模板 spec 扩展**

```json
{
  "project": {
    "root_form": "project_application",
    "link_field": "所属项目",
    "title_field": "项目名称",
    "documents": "per_project"
  },
  "forms": [
    {"key": "project_application", "scope": "project", "...": "..."},
    {"key": "project_progress", "scope": "project", "...": "..."},
    {"key": "project_owner", "scope": "workspace", "...": "..."}
  ]
}
```

校验口径（写入 `normalize_spec`）：

1. `project` 为可选顶层对象；出现时 `root_form` 必须存在于 `forms`。
2. `link_field` 必须是所有非根 `scope=project` 表单上的字段名，类型为 link / lookup，`target_form = root_form`，`multiple = false`。
3. `title_field` 必须是根表单上的文本字段；缺省取 `项目名称`，再缺省取根表单第一个文本字段。
4. 存在 `project` 时，非根表单必须显式声明 `scope`（`project` / `workspace`），避免静默默认造成门禁漏算。
5. `documents` 取 `workspace` / `per_project`，默认 `workspace`；`per_project` 时文档规则按项目实例化。
6. 无 `project` 的旧模板：全部表单视为 `scope=workspace`，行为与现状完全一致；导入 / 导出格式保持向后兼容，导出时按归一化结果落 `project`（若存在）。

### 2. 判定算法（唯一入口）

```python
lifecycle_state(db, workspace, template, project_row_id: int | None = None) -> dict
advance_stage(db, workspace, template, user, project_row_id: int | None = None, force: bool = False) -> dict
```

`lifecycle_state` 判定顺序：

1. `project_mode=workspace`：忽略 `project_row_id`，走现有工作区级逻辑，保证存量零变化。
2. `project_mode=project`：解析根表单对应表；校验 `project_row_id` 属于该表且属于当前工作区，否则 404。
3. 读取 `workspace_project_states`；无记录时按第一阶段只读呈现（不写库），首次推进时插入。
4. 逐阶段计算门禁：
   - 根表单：该项目行存在即满足。
   - `scope=project` 表单：统计 `link_field = project_row_id` 的行数，至少 1 行。
   - `scope=workspace` 表单：不计入项目门禁。
   - 文档：`project.documents=per_project` 时查 `workspace_project_documents` 且文档存活；否则沿用现有工作区级文档。
5. 返回阶段、`gate_satisfied`、缺失项（表单 / 文档）、`is_current`、`is_completed`。

`advance_stage`：

1. 权限：编辑者及以上；模板应用 / 切换仍仅所有者。
2. 校验当前阶段；未过门禁且 `force=false` → 409，返回缺失项；`force=true` 记 `forced: true` 履历。
3. 项目模式：`INSERT ... ON CONFLICT (workspace_id, project_row_id) DO UPDATE` 更新 `stage_key` 与 `history`；工作区模式沿用现有 `template_stage` / `template_state.history`。

所有读路径（数据流程、生命周期面板、项目清单、推进）必须复用该入口，不得另写计数 SQL。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/projects` | 新增：分页返回根表单项目行 ID + 阶段 + 门禁摘要 + 文档缺失数；行数据由前端复用 records API 合并 |
| `GET /api/v1/workspaces/{wid}/data-flow` | 新增可选 `project_id`；项目模式多项目缺失 → 422 `project_required`；单项目自动选中并返回 `auto_selected=true`；无项目 → 409 `project_empty` |
| `GET /api/v1/workspaces/{wid}/lifecycle` | 新增可选 `project_id`；项目模式下未传且多项目 → 422 |
| `POST /api/v1/workspaces/{wid}/lifecycle/advance` | body 新增可选 `project_id`；项目模式下必填；权限与 409 口径不变 |
| `POST /api/v1/workspaces/{wid}/project-mode/enable` | 新增：仅所有者；幂等；为现有根表单行初始化项目状态；可选 `generate_documents` 为每个项目补文档占位 |
| `POST /api/v1/workspaces/{wid}/projects/{project_row_id}/documents` | 新增：编辑者及以上；按规则补建缺失的项目文档，已存在则不覆盖 |
| `GET /api/v1/workspaces/{wid}/documents` | 新增可选 `project_id`：按 `workspace_project_documents` 过滤文档树；不传时保持现状 |

### 4. 边界与例外

1. 跨工作区或跨根表的 `project_row_id` 一律 404，不泄露存在性。
2. `project_mode=project` 且根表单 0 行：数据流程返回 409 `project_empty`，前端引导先建项目；项目清单显示空态。
3. 多项目且未选择项目：数据流程 / 生命周期返回 422 `project_required`，前端停留在项目清单。
4. 项目作用域表单缺少 `所属项目` 值：该行不计入任何项目门禁；不做自动回填，项目清单显示门禁缺失。
5. `scope=workspace` 表单（负责人、技术体系等）不参与项目门禁；其共享文档也不拆分。
6. 删除根表单项目行：`workspace_project_states` 与 `workspace_project_documents` 映射级联删除；**文档本身保留**，变为普通文档，避免误删正文；对该行推进返回 404。
7. 文档已删除 / 归档：与现有门禁口径一致，不计为存活；项目文档补建只补缺失映射，不覆盖正文。
8. 在数据表 / 数据流程之外直接创建根表单行：项目状态按第一阶段只读呈现，文档在显式调用“生成项目文档”时创建；项目清单标记“未初始化”。
9. “全部项目”只做只读汇总（清单、分析），不提供跨项目写入；写操作必须落到某个 `project_row_id`。
10. P0 / P1 不支持从 `project` 回退到 `workspace`；需要回退时用升级前备份恢复，避免两套状态并存。
11. 数据流程仍只取前 500 行；项目过滤不改变该上限，完整数据回数据表。

### 5. 迁移

- 单条 alembic 迁移：新增 `workspaces_workspace.project_mode`（非空默认 `workspace`）+ 两张新表与索引 / 唯一键；`downgrade` 反向删除。
- 存量工作区零回填：`project_mode=workspace`，不创建项目状态与项目文档映射；现有阶段、共享文档、备份行为不变。
- 启用接口：按当前 `template_stage` 为每个现有项目行插入一条状态；已有文档保留为共享文档，不拆分；`generate_documents=true` 时只为缺失规则补占位。
- 模板同步：模板新增 `project` 块不自动切换存量工作区模式；新建工作区时若模板含 `project` 块，`project_mode=project`。
- 备份：`BACKUP_VERSION` 升到 `"15"`，新增 `project_states[]` / `project_documents[]`；恢复时先导入文档，再导入映射；v14 旧包缺省 `project_mode=workspace`、两张表为空。
- 内置科研模板升版：补 `project` 块、表单 `scope` 与 `documents=per_project`；已使用旧版模板的工作区需显式启用后才生效。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 工作区布局 | `frontend/src/layouts/MainLayout.tsx`、工作区上下文 Provider | 顶部项目切换器；当前项目写 URL `?project=`；单项目自动选中并隐藏切换器 |
| 项目清单页 | `frontend/src/pages/projects/`（新增） | 列表：项目名称 / 负责人 / 状态 / 当前阶段 / 门禁 / 文档缺失 / 更新时间；点击进入项目上下文 |
| 数据流程 | `frontend/src/pages/dataFlow/DataFlowPage.tsx` | 读取 `project_id`；422 / 409 空态；新建记录默认带 `所属项目`；切换项目重载步骤计数 |
| 生命周期面板 | `frontend/src/pages/settings/WorkspaceLifecyclePanel.tsx` | 按当前项目展示时间线与门禁；无项目时展示项目清单入口 |
| 文档区 | `frontend/src/pages/documents/` | 按 `project_id` 过滤目录树；项目文件夹 `阶段 / 项目`；未启用时保持现状 |
| 模板编辑器 | `frontend/src/pages/templates/`（ADR 0121） | 增加 `project` 配置区与表单 `scope` 选择；校验由 `normalize_spec` 与服务端返回 path 驱动 |
| API 封装 | `frontend/src/api/` | 新增 projects / project-mode / documents 项目参数 |

### 7. 测试清单

**判定层（单测）**

- `normalize_spec`：合法 `project` 块；缺 `root_form`；`link_field` 不存在 / 类型不符 / `multiple=true`；非根表单缺 `scope`；旧模板无 `project` 仍归一化通过。
- `lifecycle_state`：项目 A 的行不计入项目 B；`scope=workspace` 表单不计入；无状态记录按第一阶段；跨工作区行 404。
- `advance_stage`：门禁未过 409；`force` 记 `forced`；项目 A 推进不影响 B；最终阶段不可再推进。
- 文档命名：`{项目名称}` 替换；无占位时按 `项目名称-规则标题`。
- 启用接口：幂等；现有项目全部初始化；不拆分旧文档。

**接口层**

- `GET /projects` 分页与空态；`GET /data-flow` 单项目自动选中、多项目 422、零项目 409；`project_id` 跨工作区 404。
- `POST /lifecycle/advance` 项目模式必填、权限 403、409 缺失项；`POST /project-mode/enable` 仅所有者。
- `POST /projects/{row}/documents` 编辑者可用、重复调用不覆盖正文。
- 查看者写入仍返回 202，不因项目上下文绕过修改申请。

**迁移 / 备份**

- `upgrade` / `downgrade` 可逆；存量工作区默认 `workspace` 且零回填。
- v15 备份往返：项目状态、项目文档映射、项目模式一致；v14 旧包恢复为 `workspace` 模式。

**前端单测 / e2e**

- 单项目自动选中、隐藏切换器；多项目切换后数据流程 / 文档 / 生命周期一致。
- 项目清单进入项目；门禁缺失项可见；空态引导。
- e2e：科研模板建 2 个项目，推进 A 不影响 B；单项目工作区直接进入项目；查看者提交修改申请。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 数据模型（`project_mode` + 项目状态表）、项目级生命周期 / 门禁、项目清单接口与页面、数据流程 `project_id`、项目切换器 | 中：迁移与存量兼容 |
| **P1** | 项目级文档映射表、`naming` 实例化、文档树项目过滤、存量工作区启用流程 | 中高：跨 documents 插件与备份 |
| **P2** | 项目清单统计（预算 / 完成度 / 延期）、批量补文档、未初始化项目修复工具、提醒 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体模型：双模式还是统一模型 | 统一“项目上下文”，单项目 = 根表单 1 行的退化；不做双模板 / 双工作区类型 | 避免两套页面与两套门禁口径；单项目无需特判 | 双模板（维护两份 spec）；双工作区类型（迁移与入口分叉）；每项目一个工作区（项目多时工作区膨胀） | `Workspace.project_mode`、项目上下文 Provider |
| D2 | 项目身份 | 复用根表单 `project_application` 的行 ID | 现有模板已一行一个项目，链接字段已指向它 | 新建 `projects` 主表（与动态表双写、迁移大） | `project_row_id` |
| D3 | 项目阶段存储 | 新表 `workspace_project_states`，唯一键 `(workspace_id, project_row_id)` | 原子 upsert、可查询、可备份、并发不互相覆盖 | 塞进 `template_state` JSON map（并发丢更新、无法索引） | 新表 + `advance_stage` |
| D4 | 项目文档映射 | 新表 `workspace_project_documents`，文档表不加项目列 | 避免跨插件改文档模型；映射可独立备份与清理 | 文档表加 `project_row_id`（跨插件迁移、历史文档语义混杂） | 新表 + 文档树过滤 |
| D5 | 模式开关 | `Workspace.project_mode` 新列，默认 `workspace` | 显式、可查询、备份可见；存量零变化 | 从 `template_state` 推断（隐式、查询差） | 迁移 + 创建/启用接口 |
| D6 | 模板契约 | 顶层 `project` + 表单 `scope`，旧模板缺省工作区级 | 显式声明避免门禁漏算；导入导出可向后兼容 | 自动推断关联字段（不可靠）；按表单名硬编码（模板不可配置） | `spec.py` |
| D7 | 数据流程项目参数 | `project_id` 可选；多项目必填，单项目自动；不提供跨项目写入 | 避免误写别项目；单项目零选择成本 | 默认“全部项目”并提供写入（串项目风险） | `data_flow.py` |
| D8 | 存量启用 | 显式 `project-mode/enable`，按当前阶段初始化；旧文档不拆分 | 自动拆分无法判断正文归属，易复制错内容 | 模板同步时自动切换（不可控）；自动复制文档（正文可能错位） | 启用接口 |
| D9 | 删除项目行 | 状态与文档映射级联删除；文档保留 | 防止误删正文；文档可在文档区继续管理 | 级联删文档（数据丢失风险） | 记录删除路径 / 映射 FK |
| D10 | 权限 | 工作区三级角色不变；项目级成员权限不做 | 本期需求是项目清单与单项目聚焦，不是项目级授权 | 项目级成员表（扩大范围、需新权限入口） | 复用 `permissions.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：一个工作区同时支持项目清单与单项目工作台；每个项目有独立阶段、门禁与文档；单项目无需额外模板；存量工作区可平滑选择启用。
- **负向**：新增两张表、一个模式列与一套项目上下文；模板编辑器、数据流程、文档树、备份均需同步改动；项目清单与记录数据需要两次读取合并。
- **风险与缓解**：存量兼容风险由“默认 workspace + 显式启用 + 备份回退”控制；项目行直接创建导致未初始化，由项目清单标记与修复工具兜底；文档拆分风险由“不自动拆分”控制。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板 spec 与生命周期 | `spec.py` / `lifecycle_state` | 0122 在 0094 的工作区级生命周期上增加项目级可选参数；工作区级行为不变 | ADR 0094 |
| 数据流程 | `data_flow.py` / `flows[]` | 0122 只增加项目过滤，不改变 flows / steps 结构 | ADR 0095 / 0097 |
| 备份 | `workspace_backup.py` / `backup_io.py` | 0122 将归档版本升到 v15，新增项目状态与文档映射 | ADR 0075 |
| 模板结构化编辑 | 模板编辑器 | 0122 要求编辑器补 `project` 与 `scope` 配置，仍复用 0121 的草稿与校验链路 | ADR 0121 |
| 科研模板 | `workspace_templates.py` | 0122 为内置科研模板补 `project` 块与表单作用域 | ADR 0027 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 未开始（ADR 待评审）
- 已完成：需求卡片与 ADR 初稿、索引与术语登记
- 下一步：人工评审 ADR 0122；确认 I1-I6 是否登记入 CONSTRAINTS；通过后按 P0 实现
- 已知坑：根表单是动态表，`project_row_id` 无跨表 FK；项目行删除与文档保留需按 D9；旧备份必须回落到 `workspace` 模式
- 最近一次全绿：`make check-docs`（2026-11-08，0 error；3 warning 来自 0121）
