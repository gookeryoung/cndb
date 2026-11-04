# ADR 0097: 数据流程支持多端到端流程与多流程展示

Status: Implemented
Date: 2026-11-04
Related: `src/cndb/plugins/workspaces/services/templates/`、`src/cndb/plugins/workspaces/routers/data_flow.py`、`frontend/src/pages/dataFlow/`、ADR 0095
需求卡片: `docs/requirements/0097-data-flow-multi-flows.md`

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 更多的端到端流程 | 顶层 `flows[]`：每条流程 = 有序 steps；step 可绑定一个表单与文档规则 |
| C2 | 多流程显示 | 接口返回 flows；页面顶部流程卡片并列展示，选中后进入步骤条 |
| C3 | 无表单步骤 | `step.form` 可空，表示审批 / 确认节点；页面只展示节点说明 |
| C4 | 数据 CRUD | 有表单的 step 复用 0095 的列表 / 搜索 / 新建 / 编辑 / 删除，写路径仍走 records API |
| C5 | 表单归属 | 表单可只被 flows 引用；孤儿校验按 stages ∪ flows；实例化仍建全部表单 |
| C6 | 版本与 diff | flows 纳入 spec 归一化、diff 与 counts |
| C7 | 示例 | 科研模板 4 条流程 + 3 张新表单 + 示例记录 |
| C8 | 旧模板兼容 | 无 flows 时按阶段派生 flows |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 0095 数据流程以「阶段 → 表单」组织，一条模板只有一条生命周期主线 | `routers/data_flow.py`、`DataFlowPage.tsx` | 经费报销 / 成果登记 / 变更等独立业务过程无处安放 | 新增 C1/C2 |
| 2 | 阶段承担生命周期门禁，不适合承载所有业务过程 | `services/templates/engine.py` | 若把新流程都塞进 stages，会改变生命周期推进顺序 | 确认 C1 解耦 |
| 3 | 表单 / 文档孤儿校验只认 stages | `spec.py::normalize_spec` | flow-only 表单会被判非法 | 新增 C5 |
| 4 | 0095 的 CRUD 已完整 | `DataFlowPage.tsx` | 多流程只需换入口编排，不重写写路径 | 确认 C4 |
| 5 | 科研模板已有 4 张表单 / 3 阶段 | `cli/seed/workspace_templates.py` | 需要更多业务过程与示例数据体现多流程 | 新增 C7 |

核心缺陷：**数据流程只有一条主生命周期，无法同时承载「立项 / 报销 / 成果 / 变更」等并列的端到端业务过程。**

设计目标（不变量）：

- **I1 流程与生命周期解耦**：flows 不改变 stages 门禁与推进顺序。
- **I2 表单唯一**：同一表单可在多条流程复用，数据只有一份。
- **I3 无表单步骤可展示**：审批 / 确认节点不建表、不伪造数据。
- **I4 兼容旧模板**：无 flows 时派生，不要求迁移。

## Decision

### 1. 数据模型

无数据库迁移。新增模板 `spec.flows[]`（JSON）：

```
flows: [
  {
    "key": "expense_reimbursement",
    "name": "经费报销",
    "description": "报销申请 → 审批确认 → 财务入账",
    "steps": [
      {"key": "claim", "name": "填报报销", "form": "expense_claim", "documents": []},
      {"key": "approve", "name": "审批确认", "description": "人工审批"},
      {"key": "post", "name": "财务入账", "form": "project_budget", "documents": ["budget_doc"]}
    ]
  }
]
```

### 2. 判定算法（唯一入口）

- `normalize_spec`：校验 flows / steps / 引用；孤儿校验改为 stages ∪ flows。
- `get_data_flow`：构建 flows；无显式 flows 时按 stages 派生。
- CRUD：仍走 records API，不新增写端点。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/data-flow` | 响应新增 `flows[]`（steps / form / form_count / step_count / record_count）；`stages` 保留 |

### 4. 边界与例外

- step.form 为空：展示审批 / 确认节点，不提供 CRUD。
- 同一表单被多条流程引用：共享记录与计数。
- 表单只在 flows 中出现：仍由模板同步建表；不被 stages ∪ flows 引用才报孤儿。
- 旧模板无 flows：按阶段派生（一阶段一流程），前端无需特判。
- 流程仅改变展示编排，不改变生命周期门禁 / 推进。

### 5. 迁移

无（spec JSON 内扩展；旧模板读时派生 flows）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/dataFlow/DataFlowPage.tsx` | 流程卡片并列展示 + 步骤条 + 步骤表单 CRUD / 审批节点空态 |
| 类型 | `frontend/src/api/types/templates.ts` | `TemplateSpecFlow`、`DataFlowFlow`、`DataFlowStep`、counts / diff 扩展 |
| 模板编辑 | `frontend/src/pages/templates/` | JSON 规格新增 `flows` 配置（沿用现有编辑器） |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_workspace_templates.py`：多流程校验 / flow-only 表单建表与 CRUD / 审批节点 / 科研模板 4 流程与示例记录 / 旧模板派生 flows。
- `frontend/src/pages/dataFlow/DataFlowPage.test.tsx`：多流程卡片、切审批节点无 CRUD、表单 CRUD、搜索。

**接口层**：`GET /workspaces/{wid}/data-flow` 多流程响应 / 旧模板派生。

**迁移 / 备份**：无迁移；模板 spec 随版本快照，工作区备份口径不变。

**e2e（前端）**：本期未新增（组件测试覆盖主路径）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | spec flows 校验 + 数据流程接口 flows | 低 |
| **P1** | 多流程页面（卡片 / 步骤 / CRUD / 审批节点） | 中 |
| **P2** | 科研模板 4 流程 + 3 张表单 + 示例数据 | 低 |

## 决策记录

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 流程与生命周期 | flows 独立于 stages | 不改变既有门禁 / 推进顺序；一条模板可承载多条业务过程 | 把流程塞进 stages（生命周期错乱） | `spec.py` |
| D2 | step 的表单 | 一个 step 最多绑定一个表单，可空 | 页面按步骤聚焦单一表单；审批节点无需建表 | 一步多表单（UI 复杂、CRUD 入口不明确） | `_normalize_data_flows` |
| D3 | 表单复用 | 同一表单可被多条流程引用 | 数据只有一份，流程只是入口编排 | 每流程复制表单 / 表（数据分叉） | `data_flow.py` |
| D4 | 旧模板 | 无 flows 时按阶段派生 | 0095 模板零迁移，前端始终多流程视图 | 要求旧模板补 flows（迁移成本） | `resolveFlows` / `data_flow.py` |
| D5 | 孤儿校验 | stages ∪ flows 引用 | flow-only 表单合法；真正未引用仍拦截 | 只认 stages（新功能不可用） | `normalize_spec` |
| D6 | 示例数据 | 科研模板新增 3 张流程专用表单 + 4 条流程 | 覆盖报销 / 成果 / 变更等常见端到端过程 | 只复用原有 4 张表（流程演示不完整） | `workspace_templates.py` |

## Consequences

- **正向**：数据流程从单主线升级为多业务流程工作台；页面并列展示流程；审批节点与表单 CRUD 统一。
- **负向**：模板 spec 更复杂；流程卡片数量多时需要横向/网格浏览。
- **风险与缓解**：流程配置字段写错 → 保存时校验；旧模板无 flows → 自动派生。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板 spec / 生命周期 | `WorkspaceTemplate.spec`、stages | flows 不改变 stages 门禁与推进；模板同步建全部表单 | ADR 0094 |
| 数据流程 CRUD | records API | 有表单的 step 复用 0095 的 CRUD 与权限口径 | ADR 0095 |
| 表权限 / 修改申请 | records 写路径 | 多流程不新增写路径，权限仍以表为边界 | ADR 0003 / 0004 / 0005 |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/templates/spec.py`、`src/cndb/plugins/workspaces/routers/data_flow.py` | `tests/test_workspace_templates.py` | 本次 |
| P1 | 已落地 | `frontend/src/pages/dataFlow/DataFlowPage.tsx`、`frontend/src/api/types/templates.ts` | `frontend/src/pages/dataFlow/DataFlowPage.test.tsx` | 本次 |
| P2 | 已落地 | `src/cndb/cli/seed/workspace_templates.py` | `tests/test_workspace_templates.py` | 本次 |

## 交接

- 当前阶段：全期已落地（P0 / P1 / P2）。
- 已完成：flows 规格、多流程接口、流程卡片 / 步骤 / 审批节点、科研模板 4 流程与示例数据。
- 下一步：可补流程可视化编辑器（流程 / 步骤拖拽）与数据流程 e2e。
- 已知坑：旧模板派生 flows 的 key 为 `stage-<阶段 key>`，前端不要依赖固定 key；流程专用表单不进 stages，生命周期门禁不检查它们。
- 最近一次全绿：`make flow`（本次提交前，2026-11-04）。
