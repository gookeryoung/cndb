# 需求卡片：权限不足错误提示增强

- 编号：0047（与 ADR `docs/adr/0047-permission-denied-message.md` 同号，卡片存 `docs/requirements/0047-permission-denied-message.md`）
- 来源 / 提出人：用户（口语需求，2026-10-27）
- 日期：2026-10-27
- 关联 ADR：待立项后回填（建议 `docs/adr/0047-permission-denied-message.md`）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 针对权限不足等情况，请给出更详细的说明，以便于初级用户处理。如【当前用户在此工作区【查看者】角色，权限不足，如需提升权限请向工作区拥有者【...】申请权限】。请分析并处理此类问题，提升用户体验。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「权限不足等情况……给出更详细的说明」 | 后端所有 403 权限类错误响应的 `detail` 必须包含结构化说明：当前用户在该工作区的角色（中文标签：所有者/编辑者/查看者）+ 被拒原因（工作区级 / 表级 / 视图级），不允许再裸返回「权限不足」「无权限」这类无上下文文案 | `src/cndb/plugins/tables/services/core/access.py`、`src/cndb/core/errors.py` | 后端单测断言 403 响应体含角色文案 |
| C2 | 「向工作区拥有者【...】申请权限」 | 403 响应需携带工作区拥有者的展示名（昵称，缺省回退用户名），detail 文案形如「当前用户在此工作区的角色为【查看者】，权限不足；如需提升权限，请联系工作区拥有者【xxx】」；拥有者不可得时降级为不含联系人的文案（不报错） | `src/cndb/plugins/workspaces/permissions.py`、403 构造点 | 单测覆盖含/缺拥有者两种分支 |
| C3 | 「如【...查看者...】」 | 角色中文标签与现有口径一致：owner=所有者、editor=编辑者、viewer=查看者（对齐 `help/services/figures/builders.py:44` 与 `row_access.py:49` 的既有标签），不新造术语 | 403 构造点 | 单测断言标签文案 |
| C4 | 「提升用户体验」 | 前端对 403 响应原样展示后端 `detail`（后端已带上下文），且不因新增文案破坏现有错误提取逻辑（`frontend/src/api/client.ts` 的 detail 归一化）；公开分享页等无登录态场景不展示「联系拥有者」提示 | `frontend/src/api/client.ts` | 前端单测 + 现有 e2e 不回归 |
| C5 | 「分析并处理此类问题」 | 404「表/视图不存在」与 403 的现有区分语义保持不变（无权限看到的表仍按 404 处理，不因本需求泄露存在性）；本需求只增强 403 文案，不改变任何权限判定逻辑 | `access.py`、`view_access.py` | 现有权限测试全量回归 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区级权限门槛 403（detail=「权限不足」） | `src/cndb/plugins/tables/services/core/access.py:232` | check_workspace_permission，此处能拿到 user_role，最适合注入角色+拥有者文案 |
| 2 | 表级动作 403（detail=「表级权限不足」） | `access.py:268`、`src/cndb/plugins/tables/routers/records.py:65,303,332`、`bulk_crud.py:97` | 文案重复散落多处，需收敛为统一构造函数 |
| 3 | 视图权限 403（detail=「视图权限不足」） | `src/cndb/plugins/tables/services/core/view_access.py:56` | FORBIDDEN_DETAIL 常量 |
| 4 | 文档编辑权校验（viewer 拒写） | `src/cndb/plugins/documents/services/content.py:133` | viewer 已有「修改申请」双轨路径，需确认拒绝点文案是否也在范围 |
| 5 | 统一异常体系 PermissionDeniedError | `src/cndb/core/errors.py:74` | 服务层抛出的 permission_denied 错误码路径 |
| 6 | 前端错误归一化 | `frontend/src/api/client.ts:159-168` | detail 透出逻辑，需确认能展示更长文案 |
| 7 | 角色中文标签既有口径 | `src/cndb/plugins/help/services/figures/builders.py:44`、`src/cndb/plugins/tables/services/core/row_access.py:49` | 所有者/编辑者/查看者(/查看者=member_read) 标签可复用 |
| 8 | 拥有者信息获取 | `src/cndb/plugins/workspaces/routers/workspaces.py:241-242`（owner_member.user.nickname 模式）、`workspaces/permissions.py:15` | 已有现成查询模式 |

## 未决问题

- [x] Q1：403 响应体采用**纯文案**——保持 `{detail, code}` 形状不变，角色与拥有者信息拼接进 detail 中文文案，前端零改造。（需求方 2026-10-27 确认）
- [x] Q2：非工作区成员（角色为空）被拒时文案为「你不是该工作区成员，请联系工作区拥有者【xxx】申请加入」，与成员场景区分。（需求方 2026-10-27 确认）
- [x] Q3：超管正常路径下被 `row_filters_bypass` / owner 放行，不设特殊文案分支；如有特殊拒绝点按同一模板输出（角色按实际判定结果标注）。
- [x] Q4：文档「修改申请」双轨路径中 viewer 触发 202 是正常业务流，**排除**在本需求外；仅覆盖文档侧真正的拒绝点（如 require editor 失败的 403）。
- [x] 覆盖范围：**全部 403 点位**（工作区级、表级、视图级、文档侧拒绝点）统一收敛。（需求方 2026-10-27 确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-27）
