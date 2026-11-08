# ADR 0094: 工作区可配置模板与流程驱动（科研项目全生命周期示例）

Status: Implemented
Date: 2026-11-04
Related: `src/cndb/plugins/workspaces/`、`src/cndb/plugins/tables/`、`src/cndb/plugins/documents/`、ADR 0075、ADR 0080
需求卡片: `docs/requirements/0094-workspace-configurable-templates.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 增加可配置的模版 | 全局 `workspaces_template` + `workspaces_templaterevision`；模板中心 `/templates`；创建者 / 系统管理员可写，内置模板仅系统管理员可写 |
| C2 | 定义表单和文档规则 | `spec = {forms[], documents[], stages[]}`，`normalize_spec` 统一校验：key 唯一、阶段引用存在、无孤儿表单 / 文档、字段类型在注册表内、阶段顺序唯一 |
| C3 | 实现流程驱动 | 工作区新增模板引用与阶段列；`apply_spec_to_workspace` 建表 / 加字段 / 建占位文档；`lifecycle_state` 逐阶段门禁；`advance_stage` 门禁未过 409，force 写履历 |
| C4 | 科研项目全生命周期 | 内置「科研项目全生命周期管理」：立项申报 / 过程实施 / 结题验收，4 表单 + 5 文档规则，种子随 `cndb seed` 幂等注入 |
| C5 | 更新模板时的 diff | `diff_specs` 输出表单 / 文档 / 阶段 / 字段级变更与严重度；前端保存前必须经过预览 |
| C6 | 对已有数据影响预览 | `preview_impact` 逐工作区给出建表 / 加字段 / 建文档、存量行补值、阶段回落、保留的孤儿对象、类型冲突 |
| C7 | 避免模板变动导致无法使用 | 同步只增量补齐；移除的表 / 字段 / 文档一律保留；字段类型切换与当前阶段被删标记 breaking，需 `force=true`，force 不执行任何删除 |
| C8 | 工程口径 | 迁移 `134adcb233cb` 新增两表 + 工作区四列，幂等且 downgrade 可还原；模板为全局资源不进工作区备份 |

## Context

现状逐条核对：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区只有 `modules` 功能开关，没有可复用的结构 / 流程定义 | `src/cndb/plugins/workspaces/models.py` | 每个工作区的表结构、文档规则靠人工重复搭建 | 新增 C1/C3 |
| 2 | 数据表 / 文档已具备成熟创建入口（`create_table`、`create_document`） | `tables/services/core/ddl.py`、`documents/services/content.py` | 模板实例化只需复用这两个入口，不引入第二套建表 / 建文档逻辑 | 确认 C3 |
| 3 | 工作区创建只接受名称 / 模块 / 可见性 | `routers/workspaces.py::create_workspace` | 无法「按模板一键生成工作区」 | 新增 C3 |
| 4 | 已有 `workspace_modules` 决定派生功能开关 | `workspaces/modules.py` | 模板 modules 应与既有模块口径一致，不新建功能位 | 确认 C1 |
| 5 | 工作区备份只导出工作区自身数据 | `services/workspace_backup.py` | 模板是全局资源，恢复后工作区应为自由工作区（不携带失效 template_id） | 确认 C8 |
| 6 | 前端无全局模板入口 | `frontend/src/App.tsx`、`layouts/MainLayout.tsx` | 用户无法配置 / 预览模板 | 新增 C1/C5 |

核心缺陷（需求要补的）：**平台只有「一次建成」的工作区，没有可版本化、可流程化、可安全升级的「工作区定义」**。

设计目标（不变量）：

- **I1 非破坏同步**：模板更新永远不删除表 / 字段 / 文档，也不自动改物理列类型。
- **I2 映射稳定**：工作区用 `template_state` 记录 `form key → table id`、`doc key → doc id`，模板改名 / 改标题不破坏关联。
- **I3 先预览后保存**：任何 spec 变更都必须能产出 diff + 已有数据影响；破坏性变更需显式 force。
- **I4 门禁可解释**：阶段推进检查逐表单行数、逐文档存在性，未过时返回 409 明细，允许强制但写履历。

## Decision

### 1. 数据模型

- `workspaces_template`：`name`（唯一）、`description`、`category`、`modules`、`spec`（JSON）、`version`、`is_builtin`、创建者 / 更新者。
- `workspaces_templaterevision`：`(template_id, version)` 唯一，保存 `spec` 快照与变更说明；每次 spec 变化才递增版本。
- `workspaces_workspace` 新增：`template_id`、`template_version`、`template_stage`、`template_state`（JSON，`{form_tables, documents, history}`）。
- `spec` 结构：
  - `forms[]`：`key` / `name` / `description` / `fields[]`（`name` / `type` / `required` / `is_unique` / `config` / `hidden` / `default_value`）；
  - `documents[]`：`key` / `title` / `required` / `naming` / `content`；
  - `stages[]`：`key` / `name` / `description` / `order` / `forms[]` / `documents[]`。
- 表单的 `link` / `lookup` 字段支持 `config.target_form`，实例化时解析为 `target_table_id`。

### 2. 判定算法（唯一入口）

- `normalize_spec(raw)`：写路径唯一校验入口（创建 / 预览 / 更新 / 应用到工作区）。
- `apply_spec_to_workspace(...)`：唯一实例化 / 同步入口；先建 / 复用表，再补字段，再建占位文档，最后回填模板版本与阶段。
- `preview_impact(db, template, new_spec)`：唯一影响预览入口（只读）。
- `lifecycle_state(db, ws, template)`：唯一门禁计算入口；`advance_stage` 复用其结果。
- `diff_specs(old, new)`：唯一 diff 入口。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET/POST /api/v1/workspace-templates` | 列表 / 新建 |
| `GET/PUT/DELETE /api/v1/workspace-templates/{id}` | 详情 / 更新（含 diff + 影响返回）/ 删除（使用中拒绝） |
| `POST /api/v1/workspace-templates/{id}/preview` | 预览 diff + 已有数据影响 |
| `GET /api/v1/workspace-templates/{id}/revisions` | 历史版本 |
| `POST /api/v1/workspaces` | 新增 `template_id`，按模板实例化 |
| `GET /api/v1/workspaces/{wid}/lifecycle` | 生命周期状态与逐阶段门禁 |
| `POST /api/v1/workspaces/{wid}/lifecycle/advance` | 推进阶段（force 可选） |
| `POST /api/v1/workspaces/{wid}/lifecycle/apply` | 对已有工作区应用 / 切换模板（增量） |

### 4. 边界与例外

- 模板删除：仍有工作区使用 → 409；无工作区使用才允许硬删（版本一并级联）。
- 切换模板：仅工作区所有者；已使用其他模板时需 `force=true`。
- 文档占位：已有映射且未删除时永不覆盖正文；被用户删除后再次同步会重建占位。
- 表单 / 字段移除：只从模板管理范围移除，不删除物理列与数据。
- 新增必填字段：非空表的物理列按可空加（SQLite / PostgreSQL 无法为存量行补 NOT NULL），元数据仍为必填；存量行待补值计入影响预览，不阻塞模板保存。
- 字段类型变更：不自动 DDL，只报 breaking；由用户自行迁移。
- 当前阶段被删：回落到新模板第一阶段，写 `history` 且需 force。
- 备份 / 恢复：模板不随工作区导出；恢复后的工作区为自由工作区，不保留旧 template 引用。

### 5. 迁移

单条迁移 `134adcb233cb_add_workspace_templates.py`（`down_revision=f1a2b3c4d5e6`）：

- 新建两表 + 索引；
- 工作区补 4 列（`template_state` 默认 `{}`），SQLite 用 `add_column`，不补外键；
- 全部步骤幂等（表 / 列存在则跳过），downgrade 按依赖序删除。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/templates/TemplatesPage.tsx` | 模板中心：左右双栏（左清单按内置 / 自定义分组，右详情）/ 复制 / 导出 / 删除 |
| 组件 | `frontend/src/pages/templates/TemplateEditorModal.tsx` | JSON 规格编辑，保存前强制预览 |
| 组件 | `frontend/src/pages/templates/TemplatePreviewPanel.tsx` | diff + 影响分组展示，breaking 确认 |
| 工具 | `frontend/src/pages/templates/templateSpec.ts` | JSON 解析 / 影响摘要纯函数 |
| 设置 | `frontend/src/pages/settings/WorkspaceLifecyclePanel.tsx` | 生命周期 Tab：阶段时间线 / 门禁 / 推进 / 应用模板 |
| 列表 | `frontend/src/pages/workspace/WorkspaceList.tsx` | 新建工作区可选模板（模块由模板接管） |
| API | `frontend/src/api/workspaceTemplates.ts`、`frontend/src/api/types/templates.ts` | 模板 / 生命周期类型与调用 |
| 导航 | `frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx` | `/templates` 路由与顶栏 / 用户菜单入口 |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_workspace_templates.py`：spec 非法引用 / 孤儿表单、按模板实例化、门禁拦截与补齐推进、强制推进履历、diff / 影响预览、breaking 需 force、非破坏同步（表 / 文档保留）、字段类型冲突。
- `frontend/src/pages/templates/templateSpec.test.ts`：JSON 解析 / 影响摘要 / 严重度文案。
- `frontend/src/pages/templates/TemplatesPage.test.tsx`：模板详情与新建流程。
- `frontend/src/pages/settings/WorkspaceLifecyclePanel.test.tsx`：阶段门禁展示、强制推进、无模板空态。

**接口层**：模板 CRUD / 预览 / 更新 / 生命周期 / 推进 / 应用均经 `TestClient` 覆盖。

**迁移 / 备份**：迁移幂等由 `test_migration_missing_model_columns.py` 的 head 链间接覆盖；备份不导出模板，恢复为自由工作区。

**e2e（前端）**：本期未新增 e2e（模板编辑为低频管理操作，接口 + 组件测试覆盖主路径）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 / 迁移 / spec 校验 / 实例化 / 生命周期门禁 | 低 |
| **P1** | diff / 影响预览 / 非破坏更新与 force | 中 |
| **P2** | 模板中心 / 生命周期面板 / 新建工作区选模板 / 内置科研模板 | 中 |

## 决策记录

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 模板作用域 | 全局资源（工作区只引用） | 同一模板可复用到多个工作区，升级一次全部生效；便于内置模板 | 工作区私有模板（升级需逐工作区处理，无法统一内置） | `workspaces_template` |
| D2 | 表单载体 | 模板表单映射为工作区数据表，不另建表单引擎 | 复用既有字段 / 视图 / 权限 / 导入能力 | 新建表单运行时（与数据表能力重复，成本高） | `services/templates/engine.py` |
| D3 | 更新策略 | 只增量同步；移除的表 / 字段 / 文档保留 | 「模板变动不得导致无法使用」：删除是唯一不可逆操作，直接禁止 | 与模板强一致（删表删字段，破坏存量数据） | `apply_spec_to_workspace` |
| D4 | 破坏性判定 | 字段类型切换、当前阶段被删需 force；force 只确认影响 | 类型切换需人工迁移；阶段回落会改变流程口径 | 无 force 直接拒绝（用户无法完成必要调整） / 自动按新类型 DDL（SQLite 风险高） | `diff_specs`、`preview_impact` |
| D5 | 映射存储 | `template_state` JSON 保存 key → id | 模板改名 / 文档改标题不影响关联；不加表结构 | 按名称匹配（改名即断链） | `Workspace.template_state` |
| D6 | 文档占位 | 按阶段文件夹 + 初始正文创建；已有正文永不覆盖 | 阶段即文档目录，降低用户整理成本 | 同步覆盖正文（会丢用户内容） | `_ensure_stage_folder` |
| D7 | 门禁口径 | 阶段内表单至少 1 行、必需文档存在；推进 409 可 force | 可解释、可预览；不引入审批流引擎 | 表单逐字段必填校验（与数据表校验重复，且存量数据会阻塞） | `lifecycle_state` |
| D8 | 备份口径 | 模板不随工作区导出，恢复为自由工作区 | 模板为全局资源，跨部署 id 不可映射 | 按模板名重建（名字冲突 / 版本不一致） | `workspace_backup.py` |

## Consequences

- **正向**：工作区从「一次性搭建」升级为「可版本化定义 + 流程驱动」；科研项目模板可作为领域示例；更新路径有 diff / 影响预览与非破坏保障。
- **负向**：模板 spec 为 JSON，前端编辑门槛偏高；模板同步会给大工作区带来一次性建表 / 加列成本。
- **风险与缓解**：JSON 手改易错 → 保存前强制 `normalize_spec` + 预览；大工作区同步慢 → 仅增量、幂等，多次保存不会重复建表。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 工作区模块 | `Workspace.modules` / `resolve_features` | 模板 modules 只决定新工作区默认模块，不改变既有模块推导 | ADR 0080 |
| 工作区备份 | 备份协议 v13 | 模板全局资源不导出，恢复后为自由工作区 | ADR 0075 |
| 字段 DDL 原子性 | `ddl.add_column` / `create_table` | 模板同步复用既有 DDL 幂等入口，不新增 DDL 路径 | ADR 0038 |
| 文档创建 | `documents.services.content.create_document` | 占位文档复用既有版本 / FTS 逻辑 | ADR 0010 / 0049 |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/templates/spec.py`、`src/cndb/plugins/workspaces/services/templates/engine.py`、`src/cndb/alembic/versions/134adcb233cb_add_workspace_templates.py` | `tests/test_workspace_templates.py` | 687e4a9d |
| P1 | 已落地 | `src/cndb/plugins/workspaces/services/templates/diff.py`、`src/cndb/plugins/workspaces/routers/templates.py` | `tests/test_workspace_templates.py` | 687e4a9d |
| P2 | 已落地 | `frontend/src/pages/templates/`、`frontend/src/pages/settings/WorkspaceLifecyclePanel.tsx`、`src/cndb/cli/seed/workspace_templates.py` | `frontend/src/pages/templates/*.test.ts*`、`frontend/src/pages/settings/WorkspaceLifecyclePanel.test.tsx` | 687e4a9d |

## 交接

- 当前阶段：全期已落地（P0 / P1 / P2）。
- 已完成：模板模型与迁移、spec 校验、实例化 / 生命周期、diff / 影响预览、非破坏更新、模板中心 / 生命周期面板、内置科研模板。
- 示例资源：内置科研模板的「科研项目管理（模板示例）」典型数据（13 张表单记录 + 技术体系 tree / 任务 WBS 视图 + 5 份阶段文档正文）外置在 `examples/templates/科研项目全生命周期管理/`，seed 读取后按 link 依赖建表并写入视图与文档；旧独立「科研项目管理」示例工作区已整体并入并移除；资源缺失时只建空模板工作区。
- 下一步：可按需补 e2e（模板编辑 → 预览 → 保存）与模板导入 / 导出（跨部署迁移模板）。
- 已知坑：模板同步内会 commit（SQLite 下 DDL 前必须释放事务）；`template_state` 读取必须复制 `history` 列表，否则 SQLAlchemy 判等导致 UPDATE 丢失。
- 最近一次全绿：`make flow`（本次提交前，2026-11-04）。
