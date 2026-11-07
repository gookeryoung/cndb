# 需求卡片：工作区数据流程二级模块（模板驱动的表单式增删查改）

- 编号：0095
- 来源 / 提出人：用户（会话 2026-11-04）
- 日期：2026-11-04
- 关联 ADR：0095（S2：新增模块边界与模板 spec 契约；无数据库迁移）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 针对工作区模板，需要增加数据流程二级模块，以更适应用户体验的模式处理数据的增删查改。请设计数据流程的可配置设计，并结合科研项目管理模板配置典型示例数据。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「增加数据流程二级模块」 | 模板工作区在数据表域新增「数据流程」二级入口（路由 `/w/:wid/data-flow`），无模板工作区不显示；页面按「阶段 → 表单」组织记录收发 | `frontend/src/App.tsx`、`layouts/MainLayout.tsx`、`pages/dataFlow/` | 前端：模板工作区显示入口并进入页面；自由工作区不显示、直落链接给使用模板提示 |
| C2 | 「可配置设计」 | 模板 spec 的表单增加 `flow` 配置：列表字段 / 搜索字段 / 创建编辑分组 / 字段提示 / 默认值 / 增删改开关 / 默认排序 / 空态文案；未配置时派生默认值 | `services/templates/spec.py` | 单测：默认 flow 派生；非法字段引用 / 重复分组 / 未知 key 抛 `TemplateSpecError`；未分组字段自动补「其他信息」 |
| C3 | （数据流程元数据） | 新增只读端点 `GET /workspaces/{wid}/data-flow`：返回阶段 / 当前阶段 / 门禁状态 / 表单映射（table_id）/ 字段 / flow / 记录数 / 操作开关；操作开关 = 模板开关 ∩ 表级 `EDIT_RECORDS` | `routers/data_flow.py`、`schemas/templates.py` | 接口层：阶段与表单结构、记录数、权限开关；无模板 404 |
| C4 | 「处理数据的增删查改」 | 写操作复用既有 records API（create / list / update / delete），不另建写路径；保留字段校验、修改申请、行级权限、附件归属等口径 | `frontend/src/pages/dataFlow/DataFlowPage.tsx` | 前端：列表 / 搜索 / 新建 / 编辑 / 删除；查看者按既有双轨制转修改申请 |
| C5 | 「科研项目管理模板配置典型示例数据」 | 科研模板的四张表单配置数据流程；种子额外创建「科研项目管理（模板示例）」工作区，典型数据外置在 `examples/templates/科研项目全生命周期管理/`：6 个项目 / 10 条进展 / 10 条经费 / 3 条结题 / 6 条报销 / 6 项成果 / 5 条变更与 5 份阶段文档正文 | `cli/seed/workspace_templates.py`、`cli/seed/runner.py`、`examples/templates/` | 单测：种子幂等；示例工作区有 6 条项目申报记录；结题文档写入示例正文；流程配置可读取 |
| C6 | （版本与 diff） | `flow` 属于模板 spec：保存时参与 diff（`form_flow_changed`），不触发数据迁移 / 不需要 force | `services/templates/diff.py` | 单测：flow 变更出现在 diff；已有数据零影响 |
| C7 | （工程口径） | 更新 CHANGELOG / CONTEXT / ADR 索引；`make check-docs`、`make flow` 通过 | 文档 | 门禁 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 模板规格校验 | `workspaces/services/templates/spec.py` | 表单新增 `flow`，默认派生 |
| 2 | 模板 diff | `workspaces/services/templates/diff.py` | flow 变更计入表单修改 |
| 3 | 模板数据接口 | `workspaces/routers/data_flow.py` | 新增只读元数据端点 |
| 4 | 工作区二级导航 | `frontend/src/layouts/MainLayout.tsx` | 按 `template_id` 显示「数据流程」 |
| 5 | 科研模板种子 | `cli/seed/workspace_templates.py` | flow 配置 + 示例工作区 / 记录 / 文档 |
| 6 | CRUD 写路径 | 既有 `tables/routers/records.py` | 不新增写端点，完全复用 |

## 未决问题（已确认）

- [x] ① flow 配置位置：**结论**放在表单 spec 内（阶段已引用表单，不再复制阶段关系）。
- [x] ② CRUD 后端：**结论**只提供元数据接口，写操作复用 records API，避免第二套权限 / 校验。
- [x] ③ 默认配置：**结论**未配置 flow 时派生（列表前 6 字段 / 前 3 个可搜索字段 / 全部字段一组）。
- [x] ④ 示例数据：**结论**新建独立示例工作区，不污染原有「科研项目管理」数据集工作区。
- [x] ⑤ 方案分级：**结论**S2（模块边界 + 对外 spec 契约），但无数据库迁移。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-04 用户口述）
