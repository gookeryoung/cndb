# ADR 0095: 工作区数据流程二级模块（模板驱动的表单式 CRUD）

Status: Implemented
Date: 2026-11-04
Related: `src/cndb/plugins/workspaces/`、`src/cndb/plugins/tables/routers/records.py`、`frontend/src/pages/dataFlow/`、ADR 0094
需求卡片: `docs/requirements/0095-workspace-data-flow-module.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 增加数据流程二级模块 | 模板工作区在数据表域新增 `/w/:wid/data-flow`；入口按 `Workspace.template_id` 门控 |
| C2 | 可配置设计 | 表单 spec 增 `flow`：`list_fields` / `search_fields` / `form_groups` / `detail_groups` / `hints` / `default_values` / `allow_create/edit/delete` / `default_sort` / `empty_text` |
| C3 | 数据流程元数据 | `GET /workspaces/{wid}/data-flow` 返回阶段 → 表单（table_id / 字段 / flow / 记录数 / 操作开关） |
| C4 | 增删查改 | 写操作复用 records API；数据流程只负责 UX 编排 |
| C5 | 科研模板示例数据 | 科研模板四表单写 flow 配置；种子新建示例工作区并写典型记录 / 文档 |
| C6 | 版本与 diff | flow 参与 spec diff（`form_flow_changed`），无迁移、无 force |
| C7 | 工程口径 | 文档 / 索引 / CHANGELOG / CONTEXT 同步 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 模板已定义阶段 / 表单 / 文档规则，但工作区只能进数据表原始网格 | `workspaces/services/templates/`、`frontend/src/pages/grid/` | 业务用户需要理解表结构、自己找字段，流程感弱 | 新增 C1/C4 |
| 2 | 表单字段已具备类型 / 必填 / 选项 / link 配置 | `tables/models.py`、`tables/field_types/` | 可直接用于动态表单渲染，无需第二套字段系统 | 确认 C2 |
| 3 | records API 已有权限、校验、修改申请、行级权限、附件归属 | `tables/routers/records.py` | 数据流程若自建写路径会复制并分叉这些规则 | 确认 C4 |
| 4 | 模板 diff / 影响预览已有统一入口 | `services/templates/diff.py` | flow 属于模板配置，应进入 diff 但不影响数据 | 新增 C6 |
| 5 | 科研模板已有四张表单与文档规则 | `cli/seed/workspace_templates.py` | 缺少可直接体验的数据流程示例工作区 | 新增 C5 |

核心缺陷：**模板解决「结构从哪来」，但用户进入工作区后仍面对通用数据表，没有按阶段收口的录入 / 查看体验。**

设计目标（不变量）：

- **I1 单一写路径**：数据流程不新增写端点，CRUD 全部走 records API。
- **I2 配置向后兼容**：旧模板 / 旧 spec 无 `flow` 时派生默认值，不要求迁移。
- **I3 权限交集**：页面操作开关 = 模板 `flow` 开关 ∩ 表级 `EDIT_RECORDS`；读仍走表 `READ`。
- **I4 不丢字段**：flow 分组未覆盖的字段自动补进「其他信息」，避免配置遗漏导致字段不可见。

## Decision

### 1. 数据模型

无数据库迁移。`flow` 存于模板 `spec.forms[].flow`（JSON），随模板版本快照保存。

### 2. 判定算法（唯一入口）

- `normalize_spec` 内的 `_normalize_flow`：唯一 flow 校验 / 默认派生入口。
- `GET /workspaces/{wid}/data-flow`：唯一数据流程元数据出口；表单映射读 `Workspace.template_state`。
- 记录 CRUD：不新增判定入口，直接复用 records API。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/data-flow` | 新增：阶段 / 表单 / 字段 / flow / 记录数 / 操作开关 |

### 4. 边界与例外

- 无模板 / 模板失效：404，前端展示「使用模板后可用」引导。
- 表单对应表被删 / 进回收站：该表单不在数据流程中展示（避免死入口）。
- 用户无表 `READ`：该表单不展示；无 `EDIT_RECORDS`：只读，不显示增删改按钮。
- 查看者 / 关闭直编：新建 / 编辑 / 删除沿用 records API 的双轨制，转修改申请。
- 数据流程只取前 500 行用于快捷录入；完整数据仍在数据表页。
- flow 变更只影响展示与操作开关，不触发模板同步的建表 / 加字段，也不需要 force。

### 5. 迁移

无（不用 alembic）。旧模板 spec 在读取时经 `normalize_spec` 补默认 flow。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/dataFlow/DataFlowPage.tsx` | 阶段 Steps + 表单切换 + 列表 / 搜索 / 新建 / 编辑 / 删除 / 分组动态表单 |
| 复用 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx` | 导出 `FieldEditor`，数据流程复用字段控件 |
| 导航 | `frontend/src/layouts/MainLayout.tsx`、`App.tsx` | 模板工作区显示「数据流程」二级入口与路由 |
| API | `frontend/src/api/workspaceDataFlow.ts`、`types/templates.ts` | 元数据类型与调用 |
| 模板编辑 | `frontend/src/pages/templates/` | JSON 规格可配置 `flow`（无需额外表单） |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_workspace_templates.py`：flow 默认 / 非法引用 / 重复分组 / 未分组补全；数据流程接口阶段 / 表单 / 记录数 / 无模板 404；科研模板 flow + 示例工作区种子幂等。
- `frontend/src/pages/dataFlow/DataFlowPage.test.tsx`：阶段 / 表单渲染、按配置搜索、新建记录、无模板空态。

**接口层**：`GET /workspaces/{wid}/data-flow` 正常 / 404。

**迁移 / 备份**：无迁移；模板 flow 随 spec 版本快照，工作区备份口径不变。

**e2e（前端）**：本期未新增（组件测试覆盖主路径）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | flow 规格校验 + 数据流程元数据端点 | 低 |
| **P1** | 数据流程页面 + 二级导航 + CRUD 复用 | 中 |
| **P2** | 科研模板 flow 配置 + 示例工作区 / 典型数据 | 低 |

## 决策记录

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 模块定位 | 数据表域的二级模块，仅模板工作区显示 | 与数据分析 / 数据同步同层，不改变一级模块；自由工作区没有流程可依 | 新一级模块（对无模板工作区无意义，导航膨胀） | `MainLayout.tsx` |
| D2 | flow 配置位置 | 放在表单 spec 内 | 阶段已引用表单，避免重复维护阶段关系 | 顶层 `flows[]`（需要二次校验阶段 / 表单引用，复杂） | `spec.py` |
| D3 | 写路径 | 复用 records API | 权限 / 修改申请 / 校验 / 行级权限 / 附件只有一套实现 | 新增 data-flow 写端点（口径分叉） | `DataFlowPage.tsx` |
| D4 | 默认配置 | 未配置时派生，且未分组字段自动补全 | 旧模板无需迁移；新增字段不会在页面消失 | 强制要求配置完整 flow（旧模板全不可用） | `_normalize_flow` |
| D5 | 操作开关 | 模板开关 ∩ 表级 `EDIT_RECORDS` | 模板只决定 UX，权限仍以表权限为硬边界 | 只看模板开关（越权风险） | `data_flow.py` |
| D6 | 示例数据 | 独立示例工作区 | 不污染既有「科研项目管理」数据集；可重复 seed 幂等 | 直接写进模板定义（模板不应携带业务数据） | `workspace_templates.py` |
| D7 | 列表规模 | 前端取前 500 行 + 客户端搜索 | 数据流程是快捷录入视图，完整检索仍属数据表 | 服务端分页 + 复杂筛选（本期收益低） | `DataFlowPage.tsx` |

## Consequences

- **正向**：模板工作区获得业务友好的阶段化录入体验；flow 可配置又向后兼容；CRUD 无第二套权限 / 校验。
- **负向**：flow 只能通过模板 JSON 配置（暂无可视化分组编辑器）；列表仅取前 500 行。
- **风险与缓解**：flow 配置字段名写错 → 保存时报错并指出字段；新增字段未分组 → 自动补「其他信息」。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板 spec / 生命周期 | `WorkspaceTemplate.spec`、`template_state` | 数据流程只读模板配置与映射，不改变模板同步 / 门禁口径 | ADR 0094 |
| 表级权限 / 行级权限 | `tables/services/core/access.py`、records API | 数据流程沿用表权限与行级权限，不自建 | ADR 0003 / 0004 |
| 修改申请双轨制 | records 写路径 | 查看者 / 关闭直编仍转修改申请 | ADR 0005 |
| 工作区模块 | `Workspace.modules` | 「数据流程」不进入模块勾选，是模板工作区的数据表派生入口 | ADR 0080 |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/templates/spec.py`、`src/cndb/plugins/workspaces/routers/data_flow.py` | `tests/test_workspace_templates.py` | 本次 |
| P1 | 已落地 | `frontend/src/pages/dataFlow/DataFlowPage.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/App.tsx` | `frontend/src/pages/dataFlow/DataFlowPage.test.tsx` | 本次 |
| P2 | 已落地 | `src/cndb/cli/seed/workspace_templates.py`、`src/cndb/cli/seed/runner.py` | `tests/test_workspace_templates.py` | 本次 |

## 交接

- 当前阶段：全期已落地（P0 / P1 / P2）。
- 已完成：flow 规格、数据流程元数据接口、阶段化 CRUD 页面、科研模板 flow 配置与示例工作区数据。
- 下一步：可补 flow 可视化编辑器（分组拖拽 / 字段勾选）与数据流程 e2e。
- 已知坑：数据流程页面依赖模板工作区列表里的 `template_id` 才显示入口；列表缓存 10s，应用模板后需失效工作区列表（现有逻辑已失效）。
- 最近一次全绿：`make flow`（本次提交前，2026-11-04）。
