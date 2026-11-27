# ADR 0163: 工作区多团队数据共享（团队授权扩展为 viewer / editor）

Status: Implemented（2026-11-26 人工确认，含 H57 修订放行）
Date: 2026-11-26
Related: ADR 0153（团队层）、ADR 0154（工作区链接与团队数据授权，D11 被本 ADR 修订）、ADR 0161（权限边界）、ADR 0047（403 文案）、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/services/links.py`、`src/cndb/plugins/workspaces/routers/team_access.py`、`src/cndb/plugins/workspaces/schemas/models.py`
需求卡片: `docs/requirements/0163-workspace-multi-team-data-sharing.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。选型：卡片未决问题已拍板方案 A（数据共享），方案 B（多归属两档）与方案 C（平权多对多）被否决，见 D1。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 同一个工作区加入多个团队 | 拥有团队唯一（`Workspace.team_id` 不动）；其他团队经 `WorkspaceTeamAccess` 多条授权行加入，判定层多团队命中取最高角色（机制现成，见 Context #1） |
| C2 | 方案 A：数据共享（用户拍板） | `WorkspaceTeamAccess.role` 值域扩为 `viewer / editor`；`POST /team-access` 请求体新增 `role`（默认 `viewer`）；只产 `data_role`，不产任何管理面能力位（H49 / H65 不动） |
| C3 | 加入多个团队的可行性 | 判定语义：`data_role = max(显式成员角色, 团队授权最高命中, 拥有团队来源)`；`sources` 逐条归因，403 文案补「来自团队授权 editor」分支 |
| C4 | （隐含）既有口径不变 | `private` 团队授权仍不放宽数据面（H66）；授权仅工作区 owner 可授 / 撤（`MANAGE_ACCESS`）；链接创建的团队授权维持 viewer；TTL 语义不变 |
| C5 | （隐含）管理面一致 | 工作区设置「团队授权」卡支持选角色 viewer / editor，展示角色 / 生效状态 / 到期；前端门控沿用 `MANAGE_ACCESS` |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 判定层已支持多团队命中：按用户全部 `TeamMember` 匹配授权行，过滤过期后取 `ROLE_RANK` 最高一条，且已放行 `editor` 值（预留扩展口） | `src/cndb/plugins/workspaces/permissions.py:155-188`（`active_team_access`） | C1 / C3 的判定机制**现成**，判定层几乎零改动 | 确认（C1 / C3） |
| 2 | 授予侧写死 `role="viewer"`：`grant_team_access` 新建行硬编码 viewer，覆盖已有行时不改 role | `src/cndb/plugins/workspaces/services/links.py:171-200` | editor 授权无法产生（C2 主缺口） | 确认（C2） |
| 3 | API 无 `role` 字段：`TeamAccessCreate` 只有 `team_id` / `ttl_days` / `note`；`TeamAccessResponse.role` 已存在 | `src/cndb/plugins/workspaces/schemas/models.py:336-341` | C2 | 确认（C2） |
| 4 | 事件摘要写死「只读」 | `src/cndb/plugins/workspaces/routers/team_access.py:103,134` | editor 授权时审计文案失真 | 新增 |
| 5 | 链接创建的团队授权（`revoke_link_team_access` 上下游）均走 `grant_team_access(role 固定 viewer)` | `src/cndb/plugins/workspaces/services/links.py:203-219` | 链接路径维持 viewer 不受影响（D3） | 确认（C4） |
| 6 | ADR 0154 D11 规定「`role` 固定 `viewer`」并登记为 H57 | `docs/adr/0154-workspace-link.md:205`、`docs/CONSTRAINTS.md`（H57） | 本需求**推翻该决策**，H57 须人工确认修订 | 新增（C2） |
| 7 | 前端团队授权卡无角色选择 | `frontend/src/pages/settings/`（团队授权卡）、`frontend/src/api/workspaces.ts` | C5 | 确认（C5） |

**核心缺陷（需求要补的）**：判定与数据结构已天然支持「一个工作区 × 多个团队 × 多档角色」，唯独**授予面**把角色锁死在 viewer——用户要的「多团队加入同一工作区（含可编辑协作）」没有入口。

设计目标（不变量）：

- **I1 只产数据面**：团队授权（无论 viewer / editor）只写 `data_role`，不产任何管理面能力位，不并 `TEAM_MANAGE_CAPABILITIES`（H49 / H65 不动）。
- **I2 private 不放宽**：`visibility=private` 时团队授权不放宽数据面（H66 沿用 ADR 0161 口径）。
- **I3 授予天花板**：授 / 撤 / 改角色仍仅工作区 owner（`MANAGE_ACCESS`）；不得通过授权行获得管理面或 owner 专有能力位。
- **I4 存量不变**：无数据迁移；存量授权行 role 均为 viewer，行为与升级前逐条一致。
- **I5 可归因**：`sources["data"]` 标注命中授权的角色与来源，403 文案可解释（ADR 0047 单一出口）。

> 本 ADR 修订 ADR 0154 D11 / H57：`H57` 口径由「团队数据授权 role 固定 viewer」修订为「团队数据授权只产数据面（viewer / editor），不产管理面」。**H 条目修订须人工确认**（H 条目不得自行放宽），随本 ADR `Proposed → Accepted` 一并评审；不新增其他 H 条目。

## Decision

### 1. 数据模型

无新表、无新列、无迁移。`workspaces_teamaccess.role` 已是 `String(16)`，值域由代码约束（`TEAM_ACCESS_ROLE` 常量与 schema 校验）扩为 `{viewer, editor}`；存量行均为 viewer，I4 天然成立。`models.py` 的 `TEAM_ACCESS_ROLE = "viewer"` 保留（默认值与链接路径语义）。

### 2. 判定算法（唯一入口）

`resolve_capabilities` 判定顺序**不变**（显式 > 团队授权 > 拥有团队来源 > 无）。仅两处补齐：

1. `active_team_access` 已按 `ROLE_RANK` 取最高命中并放行 editor（Context #1），不改逻辑；`sources["data"]` 已写 `team_grant:{role}`，随 role 值自动归因。
2. `permission_denied_detail`（ADR 0047 单一出口）增加团队授权分支：来源为 `team_grant:editor` 时文案写明「来自团队【X】的编辑授权」，避免「非成员」误导（对齐 ADR 0161 已知坑②）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /workspaces/{wid}/team-access` | 请求体 `TeamAccessCreate` 新增 `role: Literal["viewer","editor"] = "viewer"`；事件摘要按角色写「只读 / 编辑」 |
| `GET /workspaces/{wid}/team-access` | 响应不变（`role` 字段已存在） |
| `DELETE /workspaces/{wid}/team-access/{id}` | 不变；撤销事件摘要按行内 role 写「只读 / 编辑」 |
| 其他端点 | 无变更 |

`grant_team_access` 增加关键字参数 `role: str = TEAM_ACCESS_ROLE`，新建与覆盖两分支均写入该值；**覆盖已有行时不降级**（调用方显式传 role，路由层校验）。

### 4. 边界与例外

1. **链接创建的团队授权维持 viewer**：`grant_team_access` 的链接调用点不传 role（沿用默认），链接语义「只读引用」不变（ADR 0154 A / B′ 口径）。
2. **TTL 语义不变**：viewer / editor 统一沿用现有口径——默认 `LINK_DEFAULT_TTL_DAYS`，须在 1–`LINK_MAX_TTL_DAYS` 天内；不开放长期 `NULL`（卡片未决问题的结论，D4）。
3. **同 (工作区, 团队) 唯一行**：UNIQUE 约束不变；换角色 = 覆盖该行 role（以最后一次 owner 操作为准）。
4. **`private` 工作区**：团队授权不放宽数据面（I2，沿用 `resolve_capabilities` 现有分支）。
5. **editor 授权不等于成员**：被授权用户不出现在工作区成员列表、不产 `WorkspaceMember` 行、管理面为零（I1）。
6. **行级 / 视图 / 文档权限天花板不变**：editor 数据面仍受 ADR 0003 / 0004 细粒度规则约束，团队授权不新增绕过通路。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/workspaces.ts` | `createTeamAccess` 请求体增 `role` |
| 设置页 | `frontend/src/pages/settings/`（团队授权卡） | 授予表单增角色选择（只读 / 可编辑，默认只读）；列表增角色列；编辑授权仅 `MANAGE_ACCESS` 可见（沿用现有门控） |
| 测试 | 团队授权卡对应 `.test.tsx` | 角色选择 / 默认值 / 展示断言 |

### 7. 测试清单

**判定层（单测，`tests/test_workspace_team_capabilities.py` 扩展）**

- 用户分属 3 团队 + 工作区对 2 团队分别授 viewer / editor → 取最高命中 `editor`，`sources["data"]="team_grant:editor"`。
- editor 授权 → `capabilities` 无任何管理面位（I1）；`/capabilities` 的 `can_manage=false`。
- `private` 工作区 editor 授权 → `data_role=None`（I2）。
- 显式成员 viewer + 团队授权 editor → 仍 viewer（显式优先，C3 max 语义不越级：显式角色优先于授权，维持现判定顺序）。
- 403 文案含「来自团队授权 editor」分支（ADR 0047）。

**接口层（`tests/test_teams_api.py` / 新增 `tests/test_team_access_editor.py`）**

- owner 授 editor → 201，`role=editor`；同团队覆盖换角色 → 行数不变、role 更新。
- 非 owner 授 / 撤 → 403；`role` 传非法值 → 422。
- editor 授权用户读表 / 文档可读（受 0003 / 0004 规则约束）、写表可写、进设置页 403。
- 链接创建的团队授权仍为 viewer（回归 `tests/test_workspace_link*`）。
- 事件摘要含「编辑」字样。

**迁移 / 备份**：无迁移；回归备份往返（授权行 role 序列化不变）与 `tests/test_teams_migration.py`。

**前端 / e2e**：团队授权卡角色选择与展示单测；e2e 补「授 editor → 对方团队用户可编辑」关键路径（沿用现有 workspace-permissions e2e 文件或独立 spec）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | schema + `grant_team_access(role)` + 路由 `role` 字段 + 事件文案 + 判定层 / 接口层测试（判定层改动近零） | 低 |
| **P1** | 403 文案团队授权分支 + `private` / 显式优先回归测试 + 前端授权卡角色选择与单测 | 中 |
| **P2** | e2e 关键路径 + 文档回填（0154 D11 修订指针、CONTEXT.md 术语、CHANGELOG） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 归属模型选型 | 方案 A：拥有团队唯一 + `WorkspaceTeamAccess` 多条授权（卡片未决问题，用户拍板 2026-11-26） | C1；判定与数据结构现成，改动集中在授予面 | 方案 B 多归属两档（推翻 0153 D3 / H52，含 SQLite 重建迁移，收益仅多管理面归属）；方案 C 平权多对多（权限并集不可解释，测试矩阵爆炸） | 本 ADR 全文 |
| D2 | 授权角色值域 | `role` 扩为 `viewer / editor`，仅产 `data_role`，不产管理面；**修订 ADR 0154 D11 与 H57**（人工确认随评审） | C2；判定层已预留 editor 值 | 维持 viewer-only（无法满足「多团队加入同一工作区」的可编辑协作）；editor 加管理面（违反 I1 / H49） | `schemas/models.py`、`services/links.py`、`routers/team_access.py` |
| D3 | 链接创建的团队授权 | 维持 viewer，不跟随 role 扩展 | C4；链接语义是「只读引用」（0154 A 期口径） | 链接也可授 editor：改变链接产品语义，超出本需求范围 | `services/links.py` |
| D4 | editor 授权有效期 | 与 viewer 统一：默认 `LINK_DEFAULT_TTL_DAYS`，1–`LINK_MAX_TTL_DAYS` 天，不开放长期 `NULL` | 可写授权长期挂起风险高于只读；卡片未决问题收口 | editor 允许长期授权（写权限无期限暴露，撤销依赖人工巡检）；viewer 也开放长期（本期不动存量语义） | `routers/team_access.py`、`schemas/models.py` |
| D5 | 判定合并语义 | 维持现判定顺序：显式成员角色优先（团队授权永不覆盖显式角色），无显式成员时多团队授权取 `ROLE_RANK` 最高 | C3；与 ADR 0153「显式 > 策略默认 > 无」一致 | 显式角色与授权取 max（同一用户两种来源竞争时口径变模糊，403 归因困难） | `permissions.py`（不改逻辑，仅测试锁定） |
| D6 | 事件与文案 | 事件摘要按角色写「只读 / 编辑」；403 文案补「来自团队授权 editor」分支 | I5 / ADR 0047 | 沿用「只读」写死（editor 授权审计失真） | `routers/team_access.py`、`permissions.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：「多团队加入同一工作区（含可编辑协作）」有正式入口；授予面与判定面能力对齐（判定层 editor 通道终于被消费）；跨团队协作不再需要逐用户批量加成员（0154 A 期场景）。
- **负向**：editor 团队授权 = 跨工作区写入口，审计与撤销依赖 owner 自律（TTL 强制缓解，D4）；H57 口径修订需评审确认。
- **风险与缓解**：editor 授权滥用 → 事件 `workspace.team_access_grant` 带角色、TTL 强制、撤销即时生效 + 缓存失效（现有 `_invalidate` 路径不变）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 团队数据授权边界 | `workspaces_teamaccess.role` | viewer → viewer / editor（仍只产数据面）；0154 D11 由本 ADR D2 修订 | ADR 0154，本 ADR 修订 |
| 管理面天花板 | 能力位 | 不变：团队授权不产管理面（H49 / H65） | ADR 0153 D4 / 0161 |
| `private` | `Workspace.visibility` | 不变：团队授权不放宽数据面（H66） | ADR 0161 I3 |
| 判定顺序 | `resolve_capabilities` | 不变：显式 > 团队授权 > 拥有团队来源 > 无 | ADR 0153 D5 |
| 403 文案 | `permission_denied_detail` | 单一出口不变，补团队授权分支 | ADR 0047 |
| 工作区链接 | `workspace_link` | 不变：链接授权维持 viewer | ADR 0154 A 期 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/schemas/models.py`、`src/cndb/plugins/workspaces/services/links.py`、`src/cndb/plugins/workspaces/routers/team_access.py` | `tests/test_team_access_editor.py`、`tests/test_workspace_team_access.py` | `bc505abb` |
| P1 | 已落地 | `src/cndb/plugins/workspaces/permissions.py`、`frontend/src/api/types/links.ts`、`frontend/src/pages/settings/TeamAccessCard.tsx` | `tests/test_team_access_editor.py`、`frontend/src/pages/settings/TeamAccessCard.test.tsx` | `bc505abb` |
| P2 | 已落地 | `frontend/tests/e2e/critical/workspace-team-access-editor.spec.ts`、`CHANGELOG.md`、`docs/adr/README.md`、`docs/adr/0154-workspace-link.md` | `frontend/tests/e2e/critical/workspace-team-access-editor.spec.ts` | `bc505abb` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部已落地并提交（`bc505abb`，2026-11-26）
- 已完成：需求卡片 0163（C1-C5）；ADR Accepted（含 H57 修订，2026-11-26 人工确认）；P0 授予面 role 扩展；P1 403 归因文案 + 前端授权卡；P2 e2e + CHANGELOG 回填
- 下一步：无未落地分期。已提交（`bc505abb`，`feat: 团队数据授权扩展 viewer/editor 支撑工作区多团队共享 (ADR 0163)`）；e2e `critical/workspace-team-access-editor.spec.ts` 实跑结果待回填。
- 已知坑：① `grant_team_access` 覆盖分支显式传 role 才会改角色——链接路径不传，owner 手工 editor 授权不会被链接批准降级；② e2e 授权前置放 beforeAll（用例相互独立，重试不依赖其它用例）；③ 设置页团队授权卡在 `?section=permissions` 分区
- 最近一次全绿：`make check-fast` + 单跑 e2e `workspace-team-access-editor.spec.ts`（2 例通过）@ 本轮（2026-11-26）
