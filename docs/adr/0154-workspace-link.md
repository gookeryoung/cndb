# ADR 0154: 工作区链接（跨工作区只读引用，两级授权）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/routers/member_routes.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/tables/routers/records.py`、`frontend/src/pages/workspace/TablesList.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0154-workspace-link.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「需要跨工作区数据汇总」 | `workspace_link` 只读引用：消费方按链接读取源工作区的**单表 / 单视图**（分页 + 该视图筛选），可导出 CSV；不搬迁、不物化 |
| C2 | 「权限只有拥有团队有」（延伸） | 生命周期 = 消费方发起 → **源工作区 owner 批准** → 到期失效；`expires_at` 必填（默认 30 天，上限 365 天） |
| C3 | H15 天花板 | 跨工作区读必须在源工作区产生**既有 READ 来源**：**A** 批量授予真实 `WorkspaceMember(viewer)`；**B′** 源 owner 授「团队 = viewer」（`team_grant` → 既有 `data_role`）。两者都不產生管理面、不改行级与字段隐藏 |
| C4 | 单向只读 | 链接只有 `GET`：`fields` / `rows` / `export`；写入口一律不可达 |
| C5 | 可解释 | 列表与详情返回 `source_workspace`、`approved_by`、`expires_at`、`grant_mode`（`members` / `team`）、`readable` |
| C6 | 无泄露 | 未批准 / 拒绝 / 撤回 / 过期 / 源表已删 / 目标不匹配 → 统一 404；有消费方身份但源工作区无读权 → 403 |
| C7 | 不级联 | 链接不可再链接、不作 lookup / 分析 / 流水线 / 检索 / 文档引用数据源（MVP） |
| C8 | 备份边界 | `workspace_link` / `workspace_team_access` **不进**工作区备份；源工作区 / 源表删除级联清理 |
| C9 | 授权分级（人工确认） | A（MVP）零新授权语义；B′（P3.1）一条授权行，主体是既有团队、角色是既有 `viewer`，**不产管理面、不改行级** |
| C10 | 可回收 | A 只删「链接创建的」成员行（`member_created=True`），不动原有成员；链接入口对过期/撤回立即失效，成员行由 `cndb link sweep` 回收 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区级判定已收敛为 `resolve_capabilities`，能力位含 `READ` / `WRITE` / `EXPORT` | `src/cndb/plugins/workspaces/permissions.py:resolve_capabilities` | A 走显式成员（无需改判定）；B′ 只多一个 `data_role` 来源 | 确认（C3） |
| 2 | 行级读范围与字段隐藏唯一入口：`row_read_scope_where` + `hidden_fields` | `tables/services/core/row_access.py`、`access.py` | 链接读必须经同一入口，否则绕开 H15 / H17 | 确认（C3） |
| 3 | 成员管理只有单人端点，无批量、无到期 | `workspaces/routers/member_routes.py:add_member`、`schemas/models.py:MemberAddRequest` | A 需要批量授予端点与「链接创建」标记 | 新增（C9 / C10） |
| 4 | 团队策略 `default_workspace_role` 与 `visibility=public` 已能给团队成员只读 | `workspaces/permissions.py`、`models.py` | 同团队汇总无需链接；跨团队才需要 A / B′ | 确认 |
| 5 | 记录列表读缓存按 (表, 用户, 过滤签名) 分片 | `tables/routers/records.py`、`core/cache` | 链接读需独立缓存键（含 link_id） | 新增 |
| 6 | 工作区备份自带「不导清单」 | `workspaces/services/workspace_backup.py`、`backup_io.py` | 链接与团队授权按同款口径排除 | 新增（C8） |
| 7 | 跨工作区检索只覆盖用户可读工作区 | `workspaces/services/search.py` | MVP 不把链接表纳入检索 | 确认（C7） |
| 8 | 表删除支持软删 / 回收站 | `tables/services/core/records.py`、`routers/tables.py` | 源表软删 → 链接 404；彻底删除 → 级联清理 | 新增 |
| 9 | 已有 cron 通道（`cndb sync tick` + `deploy/sync.sh`） | `cli/`、`deploy/sync.sh` | A 的成员的到期回收复用它，无需新调度设施 | 确认（C10） |

**核心缺陷（需求要补的）**：工作区是硬边界（ADR 0153 保留），**跨工作区的只读汇总没有合法通道**；而 H15 要求任何行读都必须伴随源工作区表 `READ`。因此需求补的是「**把消费方的人接进既有 READ 来源**（A 批量 viewer / B′ 团队授权）+ 可到期可撤回的入口」，**不是**新增一条绕过行级规则的授权面。

设计目标（不变量）：

- **L1 不新增越权通路**：链接读的有效权限恒等于「用户在源工作区的 `resolve_capabilities().data_role`」；A 通过显式成员取得，B′ 通过 `team_grant` 取得。两者都不产生管理面能力位，行级规则 / 字段隐藏 / 视图口径完全复用普通读路径（H15 / H17 原文不变）。
- **L2 单向只读**：链接无任何写路径（404 / 405）。
- **L3 到期即失效**：过期后**入口立即失效**（读 404），与成员行是否已清扫无关。
- **L4 无泄露**：未批准 / 拒绝 / 撤回 / 过期 / 源表删除 / 目标不匹配统一 404。
- **L5 不级联**：链接不可再链接、不作 lookup / 分析 / 流水线 / 检索 / 文档引用数据源。
- **L6 备份不自包含**：链接与团队授权不进工作区备份；随源删除级联清理。
- **L7 存量不变**：没有任何链接 / 团队授权时，全部既有路径行为与升级前逐条一致。
- **L8 可解释**：任一链接能回答「按什么方式授权、谁批准、何时到期、我为什么读不到」。
- **L9 授权可回收且不误伤**：A 撤回 / 过期只删「链接创建」的成员行；原本就是成员的账号不受影响。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0154 L#`（H27，ADR 0119）。
> 登记状态（2026-11-25 人工确认）：L1 → H53，L2 → H54，L3 → H55，L9 → H56；D11（团队数据授权边界）→ H57。

## Decision

### 1. 数据模型

**A（MVP，P0）**

```python
class WorkspaceLink(TimestampMixin, Base):        # workspaces_workspacelink
    workspace_id: int            # 消费方，FK CASCADE
    source_workspace_id: int     # 源工作区，FK CASCADE
    target_type: str             # "table" | "view"
    target_table_id: int         # FK tables_datatable CASCADE
    target_view_id: int | None   # FK tables_dataview SET NULL
    alias: str                   # 消费方内唯一（uniq_workspace_link_alias）
    granted_member_ids: JSON     # 批准时展开的用户 id 列表（审计与回收依据）
    created_member_ids: JSON     # 其中「由链接创建」的成员 user_id（撤回只删这些，L9）
    status: str                  # "pending" | "active" | "rejected"
    expires_at: datetime         # 批准时 = now + ttl_days
    created_by_id / approved_by_id / approved_at
    note: str                    # 申请备注（String(200)）
```

`granted_member_ids` 与人数的上限：200 人/链接（超出 400，要求改用 B′）。成员行仍写 `WorkspaceMember(role=VIEWER)`，不改其表结构。

**B′（P3.1）**

```python
class WorkspaceTeamAccess(TimestampMixin, Base):   # workspaces_teamaccess
    workspace_id: int            # 源工作区（授出方），FK CASCADE
    team_id: int                 # 被授团队，FK CASCADE
    role: str                    # 固定 "viewer"（MVP 不允许 editor）
    expires_at: datetime
    granted_by_id: int | None
    # UNIQUE(workspace_id, team_id)
```

### 2. 判定算法（唯一入口）

```python
# workspaces/services/links.py
def resolve_link(db, user, link_id) -> ResolvedLink:      # 404 / 403 统一出口
    # 1. 链接存在、属于路由上下文里的消费方工作区
    # 2. status == "active" 且 now < expires_at           → 否则 404（L3 / L4）
    # 3. 目标表 / 视图仍存在、未软删、确属 source_workspace_id → 否则 404
    # 4. caps = resolve_capabilities(user, source_workspace)
    #    A：用户在源工作区是 viewer（链接授予或原本就在）
    #    B′：team_grant 命中 → caps.data_role = viewer
    #    必须 caps.allows(READ)，否则 403（文案指向源工作区拥有者，ADR 0047）
```

- 取数**复用**普通读路径：`row_read_scope_where(...)` + 隐藏字段集合 + 视图筛选 / 排序 / 分页，与本工作区读同源。
- `resolve_capabilities` 仅供 B′ 增一处来源，插入顺序为：**显式工作区角色 > `team_grant` > 团队策略默认 > 可见性 `public`**；`team_grant` 只写 `data_role`，**不写** `sources["manage"]`，也不并入 `TEAM_MANAGE_CAPABILITIES`（H49 不受影响：团队角色仍不放行数据，放行数据的是源 owner 签署的授权行）。

### 3. API 变更清单

| 端点 | 期 | 变更 |
|---|---|---|
| `POST /api/v1/workspaces/{wid}/links` | P0 | 新增：发起申请（`target_table_id` / `target_view_id?` / `alias` / `ttl_days` / `audience` / `note`）；要求消费方 `EDIT_SETTINGS`；`audience` = `members`（默认，展开为消费方工作区成员）或 `team:{}`（B′，P3.1 才启用） |
| `GET /api/v1/workspaces/{wid}/links` | P0 | 新增：链接列表（`status` / `expires_at` / `approved_by` / `grant_mode` / `readable`） |
| `GET /api/v1/workspaces/{wid}/links/inbox` | P0 | 新增：待我批准（源工作区 owner 视角） |
| `POST /api/v1/workspaces/{wid}/links/{id}/approve` | P0 | 新增：源 owner 批准；A 时**批量授予 viewer 成员**并记录 `created_member_ids` |
| `POST /api/v1/workspaces/{wid}/links/{id}/reject` | P0 | 新增：源 owner 拒绝 |
| `DELETE /api/v1/workspaces/{wid}/links/{id}` | P0 | 新增：撤回；A 时删除 `created_member_ids` 对应成员（L9） |
| `POST /api/v1/workspaces/{wid}/members/batch` | P0 | 新增：批量加成员（`[{username, role}]`，上限 200，角色不得为 owner）；仅 owner |
| `GET /api/v1/workspaces/{wid}/links/{id}/fields` | P1 | 新增：结构（按隐藏字段裁剪） |
| `GET /api/v1/workspaces/{wid}/links/{id}/rows` | P1 | 新增：只读行（分页 / 视图筛选 / 排序），无写方法 |
| `GET /api/v1/workspaces/{wid}/links/{id}/export` | P1 | 新增：CSV（同一行 / 列裁剪 + 行数上限，ADR 0148） |
| `GET /{wid}/team-access`、`POST`、`DELETE /{wid}/team-access/{id}` | P3.1 | 新增：源 owner 授 / 查 / 撤「团队 = viewer」（含 `expires_at`，上限 365 天） |

### 4. 边界与例外

1. `ttl_days` 1–365，缺省 30；`expires_at` 在批准时落库。
2. 同一 `(消费方, 源表, 视图)` 只允许一条 `active` 链接；重复申请 400。
3. `audience=members` 时只展开「消费方工作区当前成员」；申请后新增的成员不会自动进入（需重新申请或改走 B′）。
4. 已有成员被列入 `granted_member_ids` 但 `member_created_ids` 不含 ⇒ 撤回不删（L9）。
5. 源表 / 源视图软删 → 读 404；彻底删除 → 级联清理链接。
6. 源工作区 `visibility=private`（ADR 0153 D6）：非 owner 一律 403。
7. 链接不参与工作区统计（`table_count` / `total_rows`），避免口径混乱。
8. **清扫任务**：`cndb link sweep`（复用 `deploy/sync.sh` 的 cron 通道，默认每 5 分钟）回收过期链接创建的成员行并写 `workspace.link_expired` 事件；清扫停摆时链接入口仍按 L3 立即失效（成员行残留但不可用于链接读，且会显示在源工作区成员列表里，可人工移除）。
9. B′ 的 `role` 固定 `viewer`；要 `editor` 必须另立期并重新评审（避免「只读汇总」变成「跨工作区写」）。

### 5. 迁移

- **P0**：建 `workspaces_workspacelink`（唯一键 + 索引），无回填（存量零迁移，L7）；downgrade 删表。
- **P3.1**：建 `workspaces_teamaccess`（`UNIQUE(workspace_id, team_id)`），无回填；downgrade 删表。
- 两条迁移各自 `down_revision` 取当前 head（P0 为 `f2b3c4d5e6a7`，P3.1 以当时的 head 为准）；幂等（表已存在则跳过）。

### 6. 前端

| 层 | 文件 | 期 | 改动 |
|---|---|---|---|
| API 封装 | `frontend/src/api/links.ts`（新增） | P0 | 申请 / 列表 / 批准 / 拒绝 / 撤回 / fields / rows / export |
| 表列表 | `frontend/src/pages/workspace/TablesList.tsx` | P0 | 侧栏「外部链接」段：`pending` 待批准、`active` 可打开、过期置灰 |
| 只读网格 | `frontend/src/pages/grid/LinkedTablePage.tsx`（新增） | P1 | 路由 `/w/:wid/links/:linkId`；只读渲染 + 隐藏编辑入口；顶部展示来源 / `grant_mode` / 批准人 / 到期时间 / 可读状态 |
| 批准入口 | 同上 + 工作区设置 | P0 | 「待我批准的链接」列表（源 owner 可见），批准时可改 `ttl_days` 与受众 |
| 团队授权 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | P3.1 | 源工作区设置页新增「团队只读授权」分区（选择团队 + 到期时间 + 撤销） |

### 7. 测试清单

**判定层（单测）** `tests/test_workspace_links.py`
- `resolve_link`：pending / rejected / 过期 / 源表软删 / 目标不属于源工作区 → 404；
- A：链接成员读 200；被移出成员后 403；源工作区 `private` → 403（D6 联动）；
- B′：`team_grant` 命中 → `data_role=viewer` 且 `can_manage=False`、`capabilities` 不含 `EDIT_SETTINGS`（H49 回归）；过期 `team_grant` 不生效；
- 行级规则外行不可见、隐藏字段不返回（H15 / H17 回归）；视图筛选与排序生效。

**接口层** `tests/test_workspace_links_api.py`
- 发起 / 批准（含批量成员创建与 `created_member_ids` 记录）/ 拒绝 / 撤回（L9：原成员不被删）；
- 非 owner 批准 403；`audience` 超 200 人 400；重复 active 400；
- 只读：`POST/PATCH/DELETE` 到 `/links/{id}/rows` 一律 404/405；
- 导出 CSV 受行数上限与列裁剪；
- 链接与团队授权都不出现在 `GET /{wid}/export` 与归档备份（C8）。

**迁移 / 备份** `tests/test_workspace_links_migration.py`
- 两条迁移 upgrade / downgrade / 幂等；源工作区删除级联清理；备份 JSON 不含链接键。

**清扫任务** `tests/test_link_sweep.py`
- 过期链接创建的成员被移除、原成员保留、写 `workspace.link_expired` 事件；重复执行幂等。

**前端单测 / e2e**
- `LinkedTablePage.test.tsx`：只读、无编辑入口、过期与不可读文案；
- `TablesList.test.tsx`：外部链接三态与批准入口；
- `frontend/tests/e2e/critical/workspace-link.spec.ts`：发起 → 批准 → 打开只读网格 → 到期后 404。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `workspace_link` + 批量 viewer 授予 + 申请 / 批准 / 拒绝 / 撤回 + `cndb link sweep` 骨架 + 列表 | 低 |
| **P1** | 只读取数（fields / rows / export），复用行级与隐藏字段入口 | 中（权限口径，H15 回归） |
| **P2** | 前端：侧栏段 + 只读网格 + 批准入口 + 过期提示 | 中 |
| **P3.1** | B′：`workspace_team_access` + `resolve_capabilities` 的 `team_grant` 来源 + 源工作区设置页「团队只读授权」+ H 条目登记 | 中（新增 `data_role` 来源，需重新证明「不产管理面、不改行级」） |
| **P3.2**（可选，另立 ADR） | 分析页把链接作为数据源 / 链接汇总 / 链接的链接 | 高 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 通道形态 | 实时只读引用（不搬迁、不物化） | 数据不重复、不腐化；汇总口径随源实时更新 | ① 定时复制（ETL）：重复存储 + 延迟 + 口径漂移；② 物化视图：SQLite 无原生支持，失效策略复杂 | `workspaces/models.py`、`services/links.py` |
| D2 | 授权主体 | 源工作区 owner 逐条批准，到期失效 | C2；「拥有者说了算」与 0153 两平面口径一致 | 团队级**批量批准**（免逐条）：放大误授面，留 P3.1 的分级方案 | `routers/links.py` |
| D3 | 不新增授权面怎么解 | **A + B′ 两级**（2026-11-25 人工确认）：A = 批准即批量授予真实 `WorkspaceMember(viewer)`（零新授权语义）；B′ = 源 owner 授「团队 = viewer」，一条授权行 → 既有 `data_role` | 跨工作区读必须在源工作区产生既有 READ 来源（H15）；A 不动任何判定，B′ 只增 `data_role` 来源 | ① 「零角色、零成员、按列白名单」：等于新增授权面，与 H15 冲突，须先改台账（明确不做）；② 只做 A：部门人数多时成员表膨胀、撤销靠清扫；③ 只做 B′：MVP 就要改 `resolve_capabilities`，风险前移 | `services/links.py`、`permissions.py`、`models.py` |
| D4 | 写能力 | 无（只挂 GET） | C4；单向可解释 | 允许写入回源：跨工作区写的事务与并发语义（ADR 0140）无法在本期说清 | `routers/links.py` |
| D5 | 视图口径 | `target_type=view` 只取该视图筛选 / 排序，权限仍按表 `READ` | 简化：避免叠加 `VIEW_READ` 造成「看得见表却打不开链接」 | 额外要求 `VIEW_READ`：与 ADR 0003 三档叠加后解释成本过高 | `services/links.py` |
| D6 | 失效表达 | 过期 / 撤回 / 源删除 404；有身份但源工作区无读权 403 | 沿用 ADR 0004 I6（无泄露）与 ADR 0047（可解释） | 200 + 空数据：用户分不清「没数据」与「没权限」 | `services/links.py` |
| D7 | 级联范围 | 不进备份；源工作区 / 源表删除级联清理 | C8；跨环境 id 无意义，悬空链接比缺失更糟 | 随备份往返：导入另一环境必然指向不存在的表 | `services/backup_io.py` |
| D8 | 生态接入 | MVP 不接分析 / 流水线 / lookup / 检索 / 文档引用 | C7；每接一个面都要重新证明不越权 | 直接全接：权限链式推断无法在单期验证 | 无（列 P3.2） |
| D9 | A 的成员归属 | 链接只删 `created_member_ids` 的成员；`granted_member_ids` 里原本就是成员的不动 | L9：撤回不能误伤既有协作关系 | 按 `granted_member_ids` 全删：会把源工作区原有成员踢出去 | `routers/links.py`、`services/links.py` |
| D10 | A 的到期回收 | `cndb link sweep`（复用 cron，默认 5 分钟）+ 读路径惰性检查 | 权限来自成员行本身，必须有人回收；惰性检查保证清扫停摆也不放行（L3） | 只靠惰性检查：成员行残留会出现在成员列表里 | `cli/link.py`、`deploy/sync.sh` |
| D11 | B′ 的能力位边界 | `role` 固定 `viewer`；只写 `data_role`，不写管理面、不并 `TEAM_MANAGE_CAPABILITIES` | H49 不被放宽：团队角色仍不放行数据，放行的是源 owner 签署的授权行 | 允许 `editor` / 允许管理面：等于跨工作区写 / 跨团队管，须另立期 | `permissions.py` |
| D12 | 批量成员端点 | `POST /{wid}/members/batch`，上限 200，禁止 `owner` | A 需要一次性给一组人只读；现有单端点无法支撑 | 逐个调用单端点：N 次事务 + N 次审计，失败半途难回滚 | `routers/member_routes.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：跨团队汇总有两条合法通道且都可到期；A 期零改判定（H15 原文不动），B′ 期只增一个 `data_role` 来源；同团队场景继续用 0153 的 `public` / 策略默认，不必建链接。
- **负向**：A 期成员表会短期膨胀（≤200 人/链接），撤销依赖清扫；B′ 期 `resolve_capabilities` 多一个来源，需重新证明「不产管理面、不改行级」；两期都要「源 owner 批准」，无法做到完全自助。
- **风险与缓解**：① 链接读绕过行级规则 → L1 + 判定层用例锁死；② A 误删原有成员 → D9 的 `created_member_ids` 白名单；③ 清扫停摆 → L3 惰性检查兜底；④ 缓存串味 → 缓存键含 link_id。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 工作区边界 | `workspace_link` / `workspace_team_access` | 跨工作区只读引用，不做父子 / 继承 | ADR 0153 D11 |
| 行级权限 | `tables_rowpermission` | 链接读与普通读同一入口，天花板不变 | ADR 0004（H15 / H17） |
| 团队层 | `Team` / `TeamMember` | B′ 的授权主体是既有团队，但不改变团队角色语义（团队角色 ≠ 数据权） | ADR 0153 D4 / H49 |
| 工作区可见性 | `visibility` | `private` 下链接一律 403 | ADR 0153 D6 |
| 视图三档 | `tables_dataview.visibility` | 只取筛选 / 排序，不叠加视图授权 | ADR 0003 |
| 403 / 404 文案 | `workspaces/permissions.py` | 403 指源工作区拥有者；404 不区分原因 | ADR 0047、ADR 0004 I6 |
| 工作区备份 | `backup_io` | 链接与团队授权不进备份 | ADR 0075 |
| 读性能与导出上限 | `records` / 导出 | 复用缓存与行数上限 | ADR 0046、ADR 0148 |
| 硬约束台账 | `docs/CONSTRAINTS.md` | L1 / L2 / L3 / L9 待评审后登记 | ADR 0119（H27） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/routers/links.py`、`src/cndb/plugins/workspaces/routers/member_routes.py`、`src/cndb/plugins/workspaces/services/links.py`、`src/cndb/plugins/workspaces/schemas/models.py`、`src/cndb/alembic/versions/a9b8c7d6e5f4_add_workspace_links.py`、`src/cndb/cli/link.py` | `tests/test_workspace_links_api.py`、`tests/test_link_sweep.py`、`tests/test_cli_link.py`、`tests/test_teams_migration.py` | `a4b82873` |
| P1 | 已落地 | `src/cndb/plugins/workspaces/services/links.py`、`src/cndb/plugins/workspaces/routers/links.py` | `tests/test_workspace_links.py` | `5e781c9d` |
| P2 | 已落地 | `frontend/src/pages/grid/LinkedTablePage.tsx`、`frontend/src/pages/workspace/WorkspaceLinksPanel.tsx`、`frontend/src/api/links.ts` | `frontend/src/pages/grid/LinkedTablePage.test.tsx`、`frontend/src/pages/workspace/WorkspaceLinksPanel.test.tsx` | `ad0ba22e` |
| P2 | 已落地 | `frontend/src/pages/grid/LinkedTablePage.tsx`、`frontend/src/pages/workspace/WorkspaceLinksPanel.tsx`、`frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/api/links.ts` | `frontend/src/pages/grid/LinkedTablePage.test.tsx`、`frontend/src/pages/workspace/WorkspaceLinksPanel.test.tsx` | 未提交 |
| P3.1 | 已落地 | `src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/routers/team_access.py`、`src/cndb/plugins/workspaces/services/links.py`、`src/cndb/alembic/versions/b8c7d6e5f4a3_add_workspace_team_access.py` | `tests/test_workspace_team_access.py`、`tests/test_teams_migration.py` | `9440ad8e` |
| P3.2 | 未开始 | 另立 ADR | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 / **P3.1 已落地**（含团队数据授权 `team_grant`）；P3.2（分析数据源 / 链接汇总 / 链接的链接）未立项
- 已完成：需求卡片 0154（C1-C10）；ADR 不变量 L1-L9、决策 D1-D12；P0（`workspace_link` 迁移、申请 / 批准 / 拒绝 / 撤回、`POST /{wid}/members/batch`、`cndb link sweep`、`MANAGE_LINKS` 能力位仅所有者）；P1（`GET /{wid}/links/{id}/fields|rows|export`，复用 `list_rows` 的行级读范围与隐藏字段裁剪；H53-H56 已登记）
- 下一步：①前端补「团队只读授权」入口（P3.1 后端与链接 `audience=team` 已就绪，设置页 UI 待做）；②P3.2 若要做需另立 ADR（分析页把链接作为数据源 / 链接汇总）
- 已知坑：① A 期的成员行是**真实授权**——清扫停摆时「链接入口已 404 但成员仍能直接进源工作区」，必须在验收时用 `cndb link sweep` 日志确认回收；② `created_member_ids` 必须由批准事务内记录，撤回按它删（不要按 `granted_member_ids`）；③ 缓存键必须含 link_id，否则与本工作区读串味（ADR 0046 D3 同款）；④ B′ 接入时 `resolve_capabilities` 的顺序必须写在注释与用例里（显式 > team_grant > 策略默认 > public），否则后续改动容易悄悄放宽；⑤ 迁移 `down_revision` 取最新 head（当前 `f2b3c4d5e6a7`），并行会话新增迁移后要同步
- 最近一次全绿：`make check-fast` + `make cov`（7509 passed，95.06%）+ 本 ADR 相关用例（links-api 29 / links 取数 14 / sweep 6 / cli 7 / 迁移 4）+ 前端链接用例 9（只读页 4 / 面板 5）@ `ad0ba22e`；P3.1 `make cov`（7577 passed，95.03%）@ `9440ad8e`（2026-11-25）
