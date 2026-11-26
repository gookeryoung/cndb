# ADR 0161: 工作区 / 团队权限边界收紧（私有可见性统一判定 + 管理面不得提权到 owner）

Status: Accepted（2026-11-26 人工确认）
Date: 2026-11-26
Related: ADR 0153（团队层与两平面分离）、ADR 0154（链接与团队数据授权）、ADR 0047（403 文案）、ADR 0075（覆盖恢复）、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/routers/member_routes.py`、`src/cndb/plugins/tables/services/core/access.py`
需求卡片: 无卡片（由权限审计直接立项；口径 C1..C6 就地定义）

## 口径（需求 → 设计落点）

需求原句（逐字）：

> 请分析当前团队和工作区的管理权限是否存在漏洞，是不是严格按照工作区配置权限进行设计的，避免无权限人员可访问。
>
> 好的，整理成 ADR

审计结论作为本 ADR 的输入，约束就地编号 C1..C6：

| 约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 管理权限不得被低权限角色提权 | `team_admin` 不得通过成员端点把任何人（含自己）升为 `owner`，也不得转让 / 移除 owner（D1） |
| C2 | 管理动作不得让操作者本人获得数据面 | 禁止团队管理员把自己加入所管理工作区；放宽可见性与 `allow_edit`、变更 `team_id` 改为 owner 专属（D2 / D3） |
| C3 | 严格按工作区配置权限执行 | 资源层（表 / 文档 / 设计 / 文件 / 议题 / 修改申请 / 分析 / 数据源 / 搜索）统一走 `resolve_capabilities`，不再直查原始成员角色（D4） |
| C4 | 无权限人员不可访问 | `private` 工作区非 owner 的数据面恒为 `None`，任何来源不得放宽（D4 / I3） |
| C5 | 团队内部不得出现下级操作上级 | 团队成员移除 / 降级增加角色等级校验（D5） |
| C6 | 管理面可见性要与真实能力一致 | `/capabilities` 对「有管理面、无数据面」的调用者返回 200 载荷而非 404（D6） |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 对应约束 |
|---|---|---|---|---|
| 1 | `MANAGE_MEMBERS` 同时授予团队 owner / admin，但成员端点没有「owner 角色上限」 | `workspaces/permissions.py:65-74`、`routers/member_routes.py:199-237` | 团队管理员可把自己或任意成员改为 `owner`，拿到全部能力位 | C1 |
| 2 | 所有权转让只校验 `MANAGE_MEMBERS`，可绕过现任 owner | `routers/member_routes.py:279-323` | 团队管理员可把 owner 降级、把任意成员升为 owner | C1 |
| 3 | 单加成员的门控是 `EDIT_SETTINGS`（`_require_owner` 的真实语义），团队管理员持有 | `routers/deps.py:61-75`、`routers/member_routes.py:82-109` | 团队管理员可把自己加入任意所辖工作区（响应体回传 `member_id`），I1 被击穿 | C2 |
| 4 | 修改工作区属性的门控也是 `EDIT_SETTINGS`，含 `visibility` / `allow_edit` / `team_id` | `routers/workspaces.py:407-434`、`permissions.py:222-231` | 团队管理员把工作区改成 `public` 后，作为团队成员按 D6 获得 `viewer` 数据面；也可把工作区迁出团队 | C2 |
| 5 | `private` 只在 `resolve_capabilities` 生效；资源层用 `get_member_role` / `check_workspace_permission` | `permissions.py:209-212`；`tables/services/core/access.py:121-142,234-254`；`documents/routers/documents.py:110-119`；`design/routers.py:122-129`；`files/services.py:139-147`；`workspaces/routers/search.py:49-78` | 私有工作区的 editor / viewer 可经资源接口读到数据；同一用户不同端点结论相反 | C3 / C4 |
| 6 | `check_workspace_permission` 与 `preload_table_access` 只认原始成员角色 | 同上；`workspaces/services/search.py:36-50` | 团队策略默认角色、`public`、`team_grant` 这些合法数据面在资源层被丢弃（授权了却读不到），权限未按配置统一执行 | C3 |
| 7 | `remove_team_member` 只要求 `ADMIN`，仅保护「最后一个 owner」，不做角色等级比较 | `routers/teams.py:335-371` | 团队存在 ≥2 个 owner 时，团队管理员可移除 owner | C5 |
| 8 | `/capabilities` 在 `data_role is None` 时直接 404 | `routers/workspaces.py:314-328` | 团队管理员有管理面但前端 `useCapabilities` fail-closed，管理入口不可见（能力与展示不一致） | C6 |
| 9 | `resolve_capabilities` 未处理 `is_superuser`，而其它判定（如文档可见性）允许 | `permissions.py:191-245`；`documents/services/visibility.py:49` | 超级管理员在统一入口被当作普通非成员，行为与 ADR 0153 §4.7 不一致 | C3 |

**核心缺陷**：ADR 0153 把「管理面」与「数据面」分离，但只收紧了**读取路径的入口函数**，没有收紧**管理面能授予什么**，也没有把资源层纳入唯一判定；于是管理面可以生产数据面（自授权、提权），且 `private` 在资源层失效。

设计目标（不变量）：

- **I1 单一判定**：工作区级数据面判定（含资源层读写门槛）必须来自 `resolve_capabilities`，禁止路由 / 服务直接以 `WorkspaceMember.role` 作为最终数据面结论。
- **I2 管理面天花板**：`MANAGE_MEMBERS` / `EDIT_SETTINGS` 不得授予 owner 专有能力位（所有权转移、删除工作区、放宽数据暴露、跨工作区授权、链接审批）。
- **I3 私有可见性**：`visibility=private` 时非 owner 的 `data_role` 恒为 `None`，任何来源（显式角色、`team_grant`、`public`、策略默认）不得放宽。
- **I4 无隐式自授权**：任何管理动作不得使操作者本人获得其此前不具备的数据面权限。
- **I5 存量不变**：无数据迁移；存量 `team_id=NULL`、存量 `private` 已归一为 `member` 的口径不变（ADR 0153 I3）。

> 跨需求长期生效的不变量已在 `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)：I1 → H64、I2 → H65、I3 → H66、I4 → H67（H27，ADR 0119）。I5 为「无数据迁移」的一次性事实，不入台账。

## Decision

### 1. 数据模型

无新表、无新列。仅扩展能力位枚举：

```python
class WorkspaceCapability(enum.StrEnum):
    ...
    TRANSFER_OWNERSHIP = "TRANSFER_OWNERSHIP"   # 新增：owner 授予 / 转让 / 移除 owner
    WIDEN_ACCESS = "WIDEN_ACCESS"               # 新增：放宽数据暴露（visibility 放宽、allow_edit 由关到开）
```

`ROLE_CAPABILITIES[OWNER]` 已包含全部能力位（`frozenset(WorkspaceCapability)`），新增两项自动归 owner；`TEAM_MANAGE_CAPABILITIES` 保持 `{EDIT_SETTINGS, MANAGE_MEMBERS, RESTORE}` 不新增。

### 2. 判定算法（唯一入口）

`resolve_capabilities` 判定顺序不变（显式 > 团队授权 / 策略 > 无），只补两处：

1. `user.is_superuser` 为真时视为该工作区 `owner`（全能力位），`sources["manage"] = "superuser"`（落实 ADR 0153 §4.7；不改任何资源级判定）。
2. `private` 判定保持现状，并新增「任何来源都不得放宽」的断言：`data_role = None` 的分支不得再被后续逻辑覆盖。

资源层统一入口新增薄封装（`workspaces/permissions.py`）：

```python
def workspace_data_role(user, workspace, db) -> WorkspaceRole | None:
    """数据面角色（含 private / public / 策略 / team_grant），供资源层替代 get_member_role。"""
    return resolve_capabilities(user, workspace, db).data_role

def require_workspace_read(user, workspace, db) -> Capabilities: ...
def require_workspace_write(user, workspace, db) -> Capabilities: ...
```

`tables/services/core/access.py`：

- `preload_table_access` / `readable_tables` / `check_action` 的 `member_role` 参数改由 `workspace_data_role(...)` 提供；
- `check_workspace_permission(db, workspace_id, user, min_role)` 签名不变，内部先把 `min_role` 映射为能力位（`VIEWER→READ`、`EDITOR→WRITE`、`OWNER→` 管理面），再走 `resolve_capabilities`；失败维持 403 + ADR 0047 文案；
- `OWNER` 等价判断（如 `_is_workspace_owner`）改为 `capabilities.allows(DELETE_WORKSPACE)`，避免把「团队管理员」误判为数据 owner。

以下路径必须改为复用上述入口（清单一）：`documents/routers/{documents,vault,charts,templates,tags}.py`、`documents/services/{content,change_requests,issues}.py`、`design/routers.py`、`files/services.py`、`issues/services.py`、`change_requests/services.py`、`workspaces/routers/search.py`、`analytics/routers/*`、`datasource/routers/*`、`tables/routers/*`、`pipeline/routers/workflows.py`。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /workspaces/{wid}/members` | 门控改为 `MANAGE_MEMBERS`；`payload.username == current_user.username` 时 403（禁止自加入）；角色上限保持「不得 owner」 |
| `POST /workspaces/{wid}/members/batch` | 同上：过滤操作者本人并计入 `errors`；其余行为不变 |
| `PATCH /workspaces/{wid}/members/{mid}` | 门控改 `TRANSFER_OWNERSHIP` 才能写入 `role=owner`；`MANAGE_MEMBERS` 只能操作 `editor/viewer`，且目标不得是 owner |
| `POST /workspaces/{wid}/owner` | 门控改为 `TRANSFER_OWNERSHIP`（仅工作区 owner） |
| `DELETE /workspaces/{wid}/members/{mid}` | 目标为 owner 时要求 `TRANSFER_OWNERSHIP`；`MANAGE_MEMBERS` 不可移除 owner |
| `PATCH /workspaces/{wid}` | `visibility` 放宽、`allow_edit` 由关到开要求 `WIDEN_ACCESS`；`team_id` 的挂载 / 解绑要求 `DELETE_WORKSPACE`（owner-only） |
| `GET /workspaces/{wid}/capabilities` | 有任一管理面能力位时返回 200（`data_role` 可为 `null`）；无管理面且 `data_role is None` 仍 404 |
| `DELETE /teams/{tid}/members/{mid}` | 增加角色等级校验：目标角色等级 > 操作者 → 403（owner 不可被 admin 移除） |
| `PATCH /teams/{tid}/members/{mid}` | 增加同一等级校验（现为 owner-only，作为兜底） |

### 4. 边界与例外

1. **团队管理员仍可管理成员**（ADR 0153 D4 不推翻）：可以添加他人、调整 editor/viewer、移除 editor/viewer；只是不能触碰 owner 层、不能添加自己。
2. **`private` 与成员角色**：owner 仍可添加 editor / viewer，但按其访问资源时 `data_role=None`（404 / 403 由各入口语义决定），只有 owner 能读写。
3. **团队数据授权的写权限**：`WorkspaceTeamAccess` 仍固定 `viewer`（ADR 0154 D11），本 ADR 不放宽。
4. **`public` 的授予仍然按 D6**：只对团队成员生效；未挂团队等价 `member`。团队管理员若要启用，需要工作区 owner（`WIDEN_ACCESS`）。
5. **系统管理员**：按 owner 处理，但需写审计事件（`workspace.superuser_access`），403 文案标注「系统管理员」。
6. **链接审批 / 团队授权**：继续沿用 `MANAGE_LINKS` / `MANAGE_ACCESS`（owner-only），本 ADR 不改。

### 5. 迁移

无。判定层与路由门控改动均为代码行为变更，不涉及数据库结构与存量数据。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 能力位 Hook | `frontend/src/hooks/useCapabilities.ts` | 无需改逻辑；确认 `data_role=null` 且 `capabilities` 非空时可正常渲染管理入口 |
| 工作区设置 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | 可见性放宽 / 成员角色下拉按 `WIDEN_ACCESS` / `TRANSFER_OWNERSHIP` 门控；团队管理员不显示 owner 选项与转让入口 |
| 成员管理 | `frontend/src/pages/settings/*Member*`（现有组件） | 隐藏「添加自己」入口；owner 行对团队管理员只读 |
| 团队页 | `frontend/src/pages/team/TeamPage.tsx` | 成员列表对 admin 隐藏 owner 行的移除 / 改角色操作 |

### 7. 测试清单

**判定层（单测，`tests/test_workspace_team_capabilities.py` 扩展）**：

- 团队管理员对 `private` / `member` / `public` 工作区的 `data_role` 与能力位矩阵；
- 团队管理员改 `visibility=public` 不改变其自身数据面（改由 owner 执行后才生效）；
- `team_grant` / 策略默认 / `public` 在 `workspace_data_role` 与 `check_workspace_permission` 下结果一致。

**接口层（新增 `tests/test_workspace_permission_hardening.py`）**：

- 团队管理员 `POST /members` 加自己 → 403；加他人 → 201；
- 团队管理员 `PATCH /members/{id}` 设 `owner` → 403；
- 团队管理员 `POST /owner` → 403；`DELETE /members/{owner_id}` → 403；
- 团队管理员 `PATCH /workspaces/{wid}` 改 `visibility=public` / 解绑 `team_id` → 403；
- `private` 工作区 viewer/editor 访问表、文档、设计、文件、搜索 → 404 / 403（与详情页一致）；
- `private` 工作区 owner 全量可用；
- 团队管理员 `DELETE /teams/{tid}/members/{owner_mid}`（存在 2 个 owner）→ 403；
- `/capabilities` 对团队管理员返回 200 且 `capabilities` 含管理面、`data_role=null`。

**迁移 / 备份**：无迁移；回归 `tests/test_workspace_backup_v9.py` 与 `tests/test_teams_migration.py`，确认备份往返与存量口径不受影响。

**e2e（前端）**：`frontend/tests/e2e/critical/workspace-permissions.spec.ts`（新增）——团队管理员视角不见 owner 选项 / 转让入口 / 可见性放宽控件。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 新增两个能力位；收紧成员角色 / 所有权端点；禁止自加入；补判定层与接口层单测 | 低（只收紧写入口） |
| **P1** | 资源层统一到 `workspace_data_role`（表 / 文档 / 设计 / 文件 / 搜索优先），修复 `private` 泄漏与授权少给 | 中（58 + 27 处调用点，需逐模块回归） |
| **P2** | 剩余模块（分析 / 数据源 / 议题 / 修改申请 / 流水线）接入；前端门控与 e2e；审计事件与文档回填 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | owner 层的变更权限归属 | 新增 `TRANSFER_OWNERSHIP`，仅工作区 owner；`MANAGE_MEMBERS` 不得授予 / 转移 / 移除 owner | C1；破坏 D4 与 D9 的利用链最短 | 让团队管理员也能转让：等于管理面可生产数据面，直接违反 I1/I2 | `permissions.py`、`routers/member_routes.py` |
| D2 | 团队管理员能否把自己加入所辖工作区 | 禁止；单端点 403，批量端点计入 `errors` | I4；自加入是最短的自授权路径 | 允许自加入但限制角色：仍可读到数据，只是把提权路径变长 | `routers/member_routes.py` |
| D3 | 放宽数据暴露与团队归属的权限 | `visibility` 放宽、`allow_edit` 由关到开需 `WIDEN_ACCESS`；`team_id` 挂载 / 解绑需 `DELETE_WORKSPACE` | C2；管理动作不得产生数据面或改变治理边界 | 沿用 `EDIT_SETTINGS`：团队管理员可自授权读数据、可把工作区迁出团队 | `routers/workspaces.py`、`permissions.py` |
| D4 | 资源层判定来源 | 统一走 `resolve_capabilities`（经 `workspace_data_role` 薄封装），不再以原始成员角色作最终结论 | C3 / C4；同一用户不同端点结论必须一致 | 只在资源层补 `visibility` 判断：会继续丢弃 `team_grant` / 策略 / `public`，欠授权仍在 | `tables/services/core/access.py`、文档 / 设计 / 文件 / 搜索等 |
| D5 | 团队成员等级校验 | 操作者角色等级必须 ≥ 目标；owner 不可被 admin 移除 | C5；消除下级操作上级 | 仅保护最后一个 owner：≥2 owner 时仍可被 admin 移除 | `routers/teams.py` |
| D6 | `/capabilities` 对「有管理面无数据面」的返回 | 返回 200，`data_role=null`；完全无能力仍 404 | C6；前端门控与真实能力一致 | 保持 404：前端 fail-closed，团队管理员无法进入其本应可管理的设置页 | `routers/workspaces.py` |
| D7 | 系统管理员在统一入口的口径 | 视为该工作区 owner（全能力位），写审计事件，403 文案标注 | ADR 0153 §4.7；消除两套判定 | 维持现状（不识别 superuser）：与 ADR 0153 不一致，且管理台跨工作区操作会 404 | `permissions.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：消除「团队管理员 → 工作区 owner → 删除工作区」提权链；`private` 在资源层真正生效；权限判定从「两套并存」收敛为一套；团队数据授权 / 策略默认 / `public` 的合法读取不再被资源层吞掉。
- **负向**：P1 需迁移 22 个文件、37 处调用点，回归面大；`check_workspace_permission` 改为能力位后，403 / 404 文案与状态码可能有细微变化，需要逐模块对齐 ADR 0047。
- **风险与缓解**：资源层统一期间若某模块漏改，会继续保留旧行为——用「同一用户 × 工作区 × 端点结论一致」的契约测试兜底，并在 P1 / P2 分批提交、每批跑完整门禁。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 管理面 / 数据面分离 | 能力位 | 保持分离，并补「管理面不得生产数据面 / 不得授 owner」 | ADR 0153 D4，本 ADR D1-D3 收紧 |
| `private` 可见性 | `Workspace.visibility` | 语义不变（仅 owner 有数据面），扩大到资源层生效 | ADR 0153 D6，本 ADR D4 |
| 团队数据授权 | `WorkspaceTeamAccess` | 仍只产 `viewer`，资源层开始正确消费 | ADR 0154 D11，本 ADR D4 |
| 403 文案 | `permission_denied_detail` | 模板不变，调用点迁移后统一走该出口 | ADR 0047，不改 |
| 覆盖恢复 | `POST /workspaces/{wid}/restore` | 维持仅 owner（`DELETE_WORKSPACE`），`RESTORE` 能力位不再对团队管理员承诺 | ADR 0075 D3，本 ADR D1 对齐 |
| 系统管理员 | 统一判定入口 | 按 owner 处理并审计 | ADR 0153 §4.7，本 ADR D7 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/routers/member_routes.py`、`src/cndb/plugins/workspaces/routers/teams.py`、`src/cndb/plugins/workspaces/routers/workspaces.py` | `tests/test_workspace_permission_hardening.py`（21 例） | 330b644 |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/files/services.py`、`src/cndb/plugins/workspaces/permissions.py` | `tests/test_workspace_permission_hardening.py`（34 例） | 22453ac |
| P2 | 已落地 | `src/cndb/plugins/change_requests/services.py`、`src/cndb/plugins/issues/services.py`、`frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | `frontend/src/pages/settings/WorkspaceSettingsContent.test.tsx`、`frontend/tests/e2e/critical/workspace-permissions.spec.ts` | 见 CHANGELOG |

## 交接（会话结束更新）

- 当前阶段：全部阶段已落地（P0 / P1 / P2）
- 已完成：权限审计；ADR 评审；H64-H67；P0（能力位 / 成员 / 所有权 / 可见性 / 团队等级 / `/capabilities` / 超管）；P1（表 / 文档 / 设计 / 文件 / 搜索统一到 `workspace_data_role`）；P2（修改申请 / 议题接入；前端能力位门控；e2e）
- 下一步：无（观察线上是否出现团队管理员 / private 相关回归；如需继续收紧，另立 ADR）
- 已知坑：① `/workspaces/{wid}` 详情对「有管理面无数据面」的团队管理员仍 404，前端无法直接进入该工作区设置页，团队管理员目前只能用 API 管理，UI 入口属产品待定；② `check_workspace_permission` 语义已切到数据面，403 文案对 team_grant 用户仍显示「非成员」；③ 资源层已无直接 `WorkspaceMember.role` 数据面判定，新增模块必须走 `workspace_data_role` / `require_capability`（H64）；④ e2e 依赖 `pnpm build` 同步 `src/cndb/static`，只改前端源码不重建会跑旧包
- 最近一次全绿：2026-11-26 `make check-fast`、`make cov`（7688 passed / 17 skipped，95.04%）、前端 `pnpm test`（3534 passed）、e2e `workspace-permissions.spec.ts`（通过）
