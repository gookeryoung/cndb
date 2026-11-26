# 需求卡片：工作区多团队数据共享（团队授权扩展为 viewer / editor）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0163（与 ADR `docs/adr/0163-*.md` 同号，卡片存 `docs/requirements/0163-<topic>.md`）
- 来源 / 提出人：用户（会话 2026-11-26）
- 日期：2026-11-26
- 关联 ADR：0163（立项后回填；将修订 ADR 0154 D11）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对同一个工作区，加入多个团队的可行性，给出建议和方案

后续澄清（会话内确认，2026-11-26）：在方案 A（数据共享）/ 方案 B（多归属两档）/ 方案 C（平权多对多）三个选项中，用户拍板「**方案 A：数据共享（推荐）**」——工作区拥有团队保持唯一，其他团队通过 `WorkspaceTeamAccess` 团队授权加入，授权角色由固定 `viewer` 扩展为 `viewer / editor` 可选。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 同一个工作区加入多个团队 | 一个工作区可同时被多个团队访问：拥有团队唯一（`Workspace.team_id` 不动），其余团队经团队授权（`WorkspaceTeamAccess`，可多条，每团队一条）获得数据面 | `workspaces`（models / permissions / routers/team_access） | 判定层单测：用户分属 3 团队 + 工作区对 2 团队授权 → 取最高命中角色 |
| C2 | 方案 A：数据共享（用户拍板） | 授权角色从固定 `viewer` 扩展为 `viewer / editor` 二选一（`POST /team-access` 请求体新增 `role`，默认 `viewer`）；仍**只产数据面、不产任何管理面能力位**（H49 / H65 不动） | `workspaces/services/links.py`（`grant_team_access`）、`routers/team_access.py`、schemas | 接口测试：editor 授权生效；`capabilities` 无管理面位 |
| C3 | 加入多个团队的可行性 | 判定语义：`data_role = max(显式成员角色, 团队授权最高命中, 拥有团队来源)`，多来源取角色最高；`sources` 逐条归因，403 文案补「来自团队授权 editor」分支 | `workspaces/permissions.py`（`active_team_access` / `resolve_capabilities`） | 判定层单测 + ADR 0047 文案断言 |
| C4 | （隐含）既有口径不变 | `private` 工作区团队授权仍不放宽数据面（H66）；授权仍仅工作区 owner 可授 / 撤（`MANAGE_ACCESS`）；链接创建的团队授权维持 viewer；到期惰性失效语义不变 | 同上 + `services/links.py` | 回归 `tests/test_workspace_team_capabilities.py`、`tests/test_teams_api.py` |
| C5 | （隐含）管理面一致 | 授权管理 UI（工作区设置「团队授权」卡）支持选角色 viewer / editor，展示生效状态与到期；前端门控沿用 `MANAGE_ACCESS` | `frontend/src/pages/settings/*`、`frontend/src/api/workspaces.ts` | 前端单测 + 真窗验收 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 判定层已支持多团队命中 + 取最高角色，且已放行 editor 值 | `src/cndb/plugins/workspaces/permissions.py:155-188` | 授予侧放开后判定层几乎零改动，仅归因/文案补分支 |
| 2 | 授予侧写死 `role="viewer"` | `src/cndb/plugins/workspaces/services/links.py:171-200`（`grant_team_access`） | C2 主落点；链接创建路径（`revoke_link_team_access` 上下游）维持 viewer |
| 3 | 团队授权 API 无 `role` 字段 | `src/cndb/plugins/workspaces/routers/team_access.py:68-115`、`schemas`（`TeamAccessCreate`） | C2 |
| 4 | 事件摘要写死「只读」 | `routers/team_access.py:103,134` | editor 授权时文案需跟随 |
| 5 | ADR 0154 D11「不允许 editor」决策将推翻 | `docs/adr/0154-*.md`、`docs/adr/README.md` 承接关系 | S2 依据；需新 ADR 修订，不直接改 0154 决策表 |
| 6 | 前端团队授权卡 | `frontend/src/pages/settings/`（团队授权卡）、`frontend/src/api/workspaces.ts` | C5 |

## 未决问题

- [x] 归属模型选型：方案 A（数据共享）/ B（多归属两档）/ C（平权多对多）→ 用户拍板方案 A（2026-11-26）
- [x] editor 是否产管理面 → 不产，仅数据面（沿用 H49 / H65，写入 ADR）
- [x] 链接创建的团队授权是否跟随 editor → 不跟随，维持 viewer（授权入口语义独立，写入 ADR）
- [ ] editor 授权是否需要默认有效期（沿用链接默认 TTL 还是允许长期 NULL）→ 待 ADR 评审拍板

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（仅 1 项默认有效期口径留给 ADR 评审拍板）
