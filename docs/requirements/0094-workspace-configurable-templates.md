# 需求卡片：工作区可配置模板与流程驱动（科研项目全生命周期示例）

- 编号：0094
- 来源 / 提出人：用户（会话 2026-11-04）
- 日期：2026-11-04
- 关联 ADR：0094（S2：新增数据模型 / 迁移 / 前端页面，方案存在实质分叉）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 工作区功能增强：增加可配置的模版，以科研项目全生命周期管理为例，定义模板所需的表单和文档规则，实现流程驱动。支持更新模板时的 diff 和对已有数据影响预览，避免模板变动导致无法使用。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「增加可配置的模版」 | 新增全局模板资源：`workspaces_template`（名称 / 分类 / 模块 / spec / version / 内置标记）+ `workspaces_templaterevision`（每次保存的规格快照）；提供列表 / 详情 / 新建 / 更新 / 删除 / 历史版本 API 与前端模板中心 `/templates` | `workspaces/models.py`、`routers/templates.py`、`schemas/templates.py`、`frontend/src/pages/templates/` | 接口层：CRUD 与版本递增；前端：模板中心可查看 / 新建 / 编辑 |
| C2 | 「定义模板所需的表单和文档规则」 | 模板 spec 为 JSON：`forms[]`（表单名 + 字段：名称 / 类型 / 必填 / 配置）、`documents[]`（标题 / 是否必需 / 命名规则 / 初始正文）、`stages[]`（阶段 + 引用表单 / 文档 key）；保存前统一校验 key 唯一、引用存在、无孤儿表单 / 文档、字段类型合法 | `services/templates/spec.py` | 单测：非法引用 / 孤儿 / 未知字段类型 422；合法 spec 归一化 |
| C3 | 「实现流程驱动」 | 工作区持有 `template_id / template_version / template_stage / template_state`；按模板创建时增量建表、建字段、建阶段文件夹与文档占位；生命周期接口返回逐阶段门禁（必需表单至少 1 行、必需文档存在），推进阶段时门禁未过 409，`force` 可强制并写履历 | `services/templates/engine.py`、`routers/lifecycle.py`、前端 `WorkspaceLifecyclePanel` | 单测：按模板建工作区、门禁拦截、补齐后推进、强制推进记录 forced |
| C4 | 「以科研项目全生命周期管理为例」 | 内置种子模板「科研项目全生命周期管理」：立项申报 → 过程实施 → 结题验收；4 张表单（项目申报 / 项目进展 / 经费使用 / 结题验收）+ 5 条文档规则（立项申请书 / 中期检查报告 / 经费决算表 / 结题报告 / 成果归档清单） | `cli/seed/workspace_templates.py`、`cli/seed/runner.py` | `cndb seed` 幂等创建内置模板；单测校验 spec 可通过 `normalize_spec` |
| C5 | 「支持更新模板时的 diff」 | 更新前对比当前 spec 与新 spec：表单 / 文档规则 / 阶段的新增、移除、修改，字段级新增 / 移除 / 类型 / 必填 / 配置变化；输出严重度与计数，前端模板编辑器保存前强制预览 | `services/templates/diff.py`、`frontend/src/pages/templates/TemplateEditorModal.tsx` | 单测：删除表单 / 文档 / 阶段、新增必填字段、字段类型变更均出现在 diff |
| C6 | 「对已有数据影响预览」 | 预览使用该模板的工作区：将建表 / 加字段 / 建文档计数、存量行待补值、当前阶段回落、保留的孤儿表 / 字段 / 文档、字段类型冲突；按工作区给出变更明细 | `services/templates/engine.py::preview_impact` | 单测：新增必填字段给出 backfill 行数；删除表单 / 文档给出保留提示 |
| C7 | 「避免模板变动导致无法使用」 | 模板更新**只做增量同步**：缺表建表、缺字段加列、缺文档建占位；移除的表 / 字段 / 文档一律保留且不被删除或改类型。非空表新增必填字段时物理列按可空加、元数据保持必填（存量行补值见预览），不阻塞保存；字段类型切换与当前阶段被删标记 breaking，需 `force=true`；`force` 仅确认影响，不执行任何删除 | `services/templates/engine.py::apply_spec_to_workspace`、`routers/templates.py` | 单测：更新后被移除的表 / 文档仍在、新字段已补；breaking 变更无 force 返回 409，带 force 成功 |
| C8 | （工程口径） | 迁移 `134adcb233cb` 新增两表与工作区四列（幂等、downgrade 可还原）；CHANGELOG / CONTEXT / ADR 索引同步 | `src/cndb/alembic/versions/`、`CHANGELOG.md`、`CONTEXT.md`、`docs/adr/README.md` | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区表 / schema | `workspaces/models.py`、`workspaces/schemas/models.py` | 新增 4 列与模板引用 |
| 2 | 工作区创建 | `routers/workspaces.py::create_workspace` | 支持 `template_id` 并实例化 |
| 3 | 工作区列表 / 详情缓存 | `routers/workspaces.py` | 模板字段透传，不改变原统计口径 |
| 4 | 工作区设置 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | 新增「生命周期」Tab |
| 5 | 全局导航 | `frontend/src/layouts/MainLayout.tsx`、`App.tsx` | 新增模板中心入口 / 路由 |
| 6 | 种子 | `cli/seed/runner.py` | 内置科研模板先于数据集注入 |
| 7 | 备份 | `workspaces/services/workspace_backup.py` | 模板为全局资源，不随工作区导出；恢复后为自由工作区 |

## 未决问题（已确认）

- [x] ① 模板作用域：**结论**全局资源（工作区只引用），便于复用与统一升级。
- [x] ② 表单载体：**结论**模板表单映射为工作区数据表（字段即表单字段），不另建表单引擎。
- [x] ③ 文档规则：**结论**按阶段创建占位文档；已有正文永不覆盖。
- [x] ④ 更新策略：**结论**非破坏增量同步，breaking 只提示确认、不执行删除 / 改列。
- [x] ⑤ 方案分级：**结论**S2（新表 + 迁移 + 前端页面 + 生命周期口径）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-04 用户口述）
