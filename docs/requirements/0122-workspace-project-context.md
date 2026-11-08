# 需求卡片：工作区项目上下文（多项目清单与单项目工作台）

- 编号：0122
- 来源 / 提出人：用户（会话 2026-11-08）
- 日期：2026-11-08
- 关联 ADR：0122（S2：模板契约、数据模型、迁移与备份变更）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 如何能够实现，一个工作区管多个项目的清单，一个工作区又能管单个的项目

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「一个工作区管多个项目的清单」 | 同一工作区以模板根表单 `project_application` 承载项目清单，一行一个项目；新增项目清单页，返回项目行 + 当前阶段 + 门禁摘要 | `workspaces`、`frontend` | 接口返回多行；e2e 清单可见 |
| C2 | 「又能管单个的项目」 | 引入项目上下文 `project_row_id`；数据流程、项目文档、生命周期均按项目过滤；工作区顶部提供项目切换 | `workspaces`、`documents`、`frontend` | 切换项目后三处数据一致 |
| C3 | 「一个工作区」 | 不新增工作区类型、不新增第二套模板；单项目是“根表单 1 行”的退化，同一套页面与接口 | `workspaces`、`frontend` | 单项目/多项目走同一模板与同一路由 |
| C4 | 「管单个的项目」 | 项目级生命周期：每个项目独立 `stage_key` 与推进履历；`lifecycle_state` / `advance` 支持 `project_row_id` | `workspaces` | 推进项目 A 不影响项目 B |
| C5 | 「管单个的项目」 | 项目级门禁：只统计 `scope=project` 且 `所属项目 = project_row_id` 的表单行；工作区级表单不计入；必需文档按项目映射判断存活 | `workspaces` | 单测覆盖跨项目行不计入 |
| C6 | 「管单个的项目」 | 项目级文档：按文档规则为每个项目实例化占位文档，标题使用现有 `naming` 的 `{项目名称}` 占位；不覆盖已有正文 | `documents`、`workspaces` | 两个项目各自生成一套文档 |
| C7 | 「项目」 | 数据流程接口新增可选 `project_id`：项目模式多项目时必须显式；单项目自动选中；新建记录默认带 `所属项目` | `workspaces`、`frontend` | 接口 200 / 422；前端自动聚焦 |
| C8 | 「一个工作区」 | 模板 spec 顶层新增 `project` 配置（`root_form` / `link_field` / `title_field` / `documents`），表单新增 `scope`；`normalize_spec` 统一校验 | `workspaces` | 合法/非法 spec 单测 |
| C9 | （兼容口径） | 存量工作区默认保持工作区级旧行为；启用项目级管理必须显式、幂等；不自动拆分已有文档 | `workspaces`、`documents` | 迁移与启用接口测试 |
| C10 | （权限口径） | 沿用工作区 owner / editor / viewer；推进仍要求编辑者及以上；模板应用/切换仍仅所有者；项目级成员权限不在本期 | `workspaces` | 权限接口测试 |
| C11 | （备份口径） | 新表纳入 `backup_io`；旧备份缺省还原为工作区模式；归档版本按需升版 | `workspaces` | 备份往返 + 旧备份兼容 |
| C12 | （工程口径） | 分层测试同轮：判定单测 / 接口 / 迁移 / 备份 / 前端单测 / e2e；更新 CONTEXT、ADR 交接 | 全链路 | `make flow` 全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 生命周期为工作区级单实例 | `src/cndb/plugins/workspaces/services/templates/engine.py:524-596` | `template_stage` + 整表行数 |
| 2 | 推进接口不接收项目 | `src/cndb/plugins/workspaces/routers/lifecycle.py:57-81`、`engine.py:599-651` | 需加可选 `project_id` |
| 3 | 模板状态为单份映射 | `src/cndb/plugins/workspaces/models.py:72-74`、`engine.py:41-47` | 缺项目级状态容器 |
| 4 | 文档规则一份占位 | `engine.py:266-285` | `naming` 已存在于 spec 但实例化未使用 |
| 5 | 数据流程无项目参数 | `src/cndb/plugins/workspaces/routers/data_flow.py:73-131` | 计数与步骤均按全表 |
| 6 | spec 顶层只允许四个键 | `src/cndb/plugins/workspaces/services/templates/spec.py:488` | 新增 `project` 需扩展校验 |
| 7 | 备份工作区元信息不含模板/项目状态 | `src/cndb/plugins/workspaces/services/workspace_backup.py:157-165` | 新表需单独导出 |
| 8 | 备份版本常量 | `workspace_backup.py:51` | 升版与旧包兼容 |
| 9 | 科研模板文档命名声明 | `src/cndb/cli/seed/workspace_templates.py:541-575` | `{项目名称}` 可直接用于项目实例化 |
| 10 | 数据流程前端只取前 500 行 | `frontend/src/pages/dataFlow/DataFlowPage.tsx:170-172` | 项目过滤后仍保留上限 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已收敛，待 ADR 评审）

- [x] 单项目是否单独做模板：否，单项目 = 清单只有 1 行（ADR D1）。
- [x] 项目身份：复用根表单 `project_application` 的行 ID，不新建项目主表（ADR D2）。
- [x] 存量工作区：默认旧行为，显式启用项目级管理（ADR D8）。
- [x] 项目级文档：复用现有 `naming`，不自动拆分旧文档（ADR D4 / D8）。
- [x] 项目级成员权限：不在本期（ADR D10）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论；用户 2026-11-08 确认按该方向起草，具体设计以 ADR 评审为准
