# 需求卡片：数据流程支持多端到端流程与多流程展示

- 编号：0097
- 来源 / 提出人：用户（会话 2026-11-04）
- 日期：2026-11-04
- 关联 ADR：0097（S2：模板 spec 契约扩展 + 数据流程页面重构；无数据库迁移）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 数据流程需要支持更多的端到端流程，请完善设计和示例，支持多流程显示和数据 CRUD。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「支持更多的端到端流程」 | 模板 spec 新增顶层 `flows[]`：每条流程有 key / name / description / steps[]；step 有 key / name / description / form（可空）/ documents[]；与生命周期 `stages` 解耦 | `services/templates/spec.py` | 单测：多流程 / 步骤校验；未知表单 / 文档引用、重复 key、空步骤 422 |
| C2 | 「支持多流程显示」 | `GET /workspaces/{wid}/data-flow` 返回 `flows[]`（含步骤、表单、统计）；前端顶部以流程卡片同时展示全部流程，选中后展示步骤条与步骤内容 | `routers/data_flow.py`、`schemas/templates.py`、`frontend/src/pages/dataFlow/DataFlowPage.tsx` | 接口层：flows 数量 / 步骤 / form_count / record_count；前端：多卡片渲染、切换流程 |
| C3 | （无表单步骤） | flow step 的 `form` 可为空，表示审批 / 确认节点；页面展示为空态信息，不显示 CRUD 按钮 | 同上 | 单测：审批步骤 form=null、description 正确；前端：切到审批步骤无新建按钮 |
| C4 | 「数据 CRUD」 | 绑定表单的步骤继续复用 records API：列表 / 搜索 / 新建 / 编辑 / 删除；多流程可共用同一表单（如经费入账复用经费使用表） | `DataFlowPage.tsx` | 前端单测：多流程下新建记录；接口层：流程专用表单可 CRUD 并计数 |
| C5 | （表单归属放宽） | 表单 / 文档可只被 flows 引用（不必出现在 stages）；孤儿校验改为「stages ∪ flows 引用」；实例化仍创建全部 flows 用到的表单 | `spec.py`、`services/templates/engine.py` | 单测：flow-only 表单建表成功；未被任何阶段 / 流程引用仍 422 |
| C6 | （版本与 diff） | `flows` 参与模板 spec 归一化与 diff（`flow_added/removed/modified`）；`spec_counts` 增加 `flow_count` / `step_count` | `spec.py`、`diff.py` | 单测：流程变化出现在 diff；模板计数含流程数 |
| C7 | 「完善示例」 | 科研模板配置 4 条端到端流程：项目全生命周期 / 经费报销 / 成果登记 / 项目变更；新增经费报销、成果登记、项目变更 3 张表单；示例工作区写入 2 条报销、2 条成果、1 条变更 | `cli/seed/workspace_templates.py` | 单测：4 条流程 / 3 张新表单 / 示例记录数量；seed 幂等 |
| C8 | （兼容） | 旧模板没有 `flows` 时，数据流程接口按阶段派生「一阶段一流程」，前端始终有多流程视图 | `routers/data_flow.py`、`DataFlowPage.tsx` | 单测：无 flows 的模板返回派生 flows；既有 0095 用例保持通过 |
| C9 | （工程口径） | 更新 CHANGELOG / CONTEXT / ADR 索引；`make flow`、前端全量测试通过 | 文档 | 门禁 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 模板 spec | `workspaces/services/templates/spec.py` | 新增 `flows`，放宽表单 / 文档孤儿校验 |
| 2 | 模板 diff / 计数 | `diff.py`、`spec_counts` | flows 纳入变更与统计 |
| 3 | 数据流程接口 | `routers/data_flow.py`、`schemas/templates.py` | 返回 flows 与步骤；旧模板派生 |
| 4 | 数据流程页面 | `frontend/src/pages/dataFlow/DataFlowPage.tsx` | 流程卡片 + 步骤 + CRUD |
| 5 | 科研模板 / 示例 | `cli/seed/workspace_templates.py` | 4 条流程、3 张新表单、示例数据 |
| 6 | 既有 0095 行为 | 阶段门禁 / 生命周期 | 不变；数据流程页面不再以阶段为主视图 |

## 未决问题（已确认）

- [x] ① 流程与阶段关系：**结论**flows 与 stages 解耦；stages 保留生命周期门禁，flows 负责业务过程展示。
- [x] ② 同一表单能否被多条流程使用：**结论**可以；记录与表单是同一份数据，流程只做入口编排。
- [x] ③ 审批节点是否建表：**结论**不建表，step.form=null 仅展示节点说明。
- [x] ④ 旧模板兼容：**结论**后端按阶段派生 flows，前端无需兼容分支。
- [x] ⑤ 方案分级：**结论**S2（模板 spec 对外契约 + 页面重构），无数据库迁移。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-04 用户口述）
