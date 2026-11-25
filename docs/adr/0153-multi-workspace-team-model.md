# ADR 0153: 多工作区统一管理（团队层 + 工作区权限边界）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/routers/deps.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/design/models.py`、`frontend/src/pages/workspace/WorkspaceList.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0153-multi-workspace-team-model.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 团队下工作区维持列表，不需要树 | 团队↔工作区为平铺集合：`GET /teams/{id}/workspaces` 返回数组；团队页按列表渲染，不做树 / 折叠层级 |
| C2 | 部门单层架构，保持扁平 | `Team` **不含** `parent_team_id`；判定链固定「团队角色 → 工作区角色」两步，无向上遍历 |
| C3 | 默认看不到 | 管理面（`team_owner` / `team_admin`）与数据面（工作区角色）分离；团队角色不派生任何数据读权限 |
| C4 | 默认一对一 | `Workspace.team_id` 单值可空；空 = 个人工作区；不建 `workspace_team` 关联表 |
| C5 | 可考虑引用设计，但是权限只有拥有团队有 | 设计模块库新增 `visibility=team`：可见性 = 消费方用户 ∈ 拥有工作区所属团队；跨团队 404 |
| C6 | 按建议 | 不引入父-子工作区；跨工作区数据读取（工作区链接）不实现，留 P3 另立 ADR |
| C7 | 多个工作区的管理 | 团队域（CRUD + 成员 + 策略 + 工作区列表）+ 前端团队页 + 工作区切换器分组 |
| C8 | 工作区内实现权限分配 | 三档角色 + 表 `Role` + 视图三档 + 行级规则 + 文档权限**全部不变**；仅把判定收敛为 `resolve_capabilities` 并引入能力位映射 |
| C9 | 隐含：管理员不得变成全能可见 | 两平面分离（D4）+ 工作区 `visibility` 三档启用（D6） |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区完全扁平，无团队 / 部门 / 父级概念；列表只有 `pinned` 置顶 + `tags` 自由标签 + 前端「已收藏 / 其他」两组 | `src/cndb/plugins/workspaces/models.py:115`、`frontend/src/pages/workspace/WorkspaceList.tsx:190` | 部门内多人多项目时只能靠命名与标签约定，无统一管理入口 | 确认（C7） |
| 2 | 工作区角色三档 `owner > editor > viewer`，`ROLE_RANK` 单调；判定入口 `has_role` / `get_member_role` | `models.py:63`、`permissions.py:31` | 三档本身够用，但判定散落各路由，无法承载「继承来源」 | 确认（C8） |
| 3 | `Workspace.visibility` 三档（public / member / private）**无任何判定消费**：全仓只有写入、备份往返与展示 | `models.py:137`、`routers/deps.py:20` | 「看起来能公开、实际不能」的死字段，误导用户 | 新增（C9） |
| 4 | 资源级授权已分层：表成员 `Role`（`ACTION_KEYS` 能力位）/ 视图三档 / 行级规则 / 文档权限 | `models.py:224`、ADR 0003 / 0004 | 细粒度已成熟，不得改动 | 确认（C8） |
| 5 | 工作区列表 10s 进程内缓存按用户隔离，写路径失效 | `routers/workspaces.py:76` | 团队级变更（成员、策略）需扩维度失效，否则越权可见 | 新增 |
| 6 | 跨工作区原语只有 1 个：设计复用模块库 `public` / `workspace` 两档 | `src/cndb/plugins/design/models.py:36`、`design/routers.py:824` | `workspace` 档只到单工作区，部门内复用需新增 `team` 档 | 确认（C5） |
| 7 | 工作区备份自包含（`manifest.json` + `payload/backup.json` v9-v16），无外部引用 | `src/cndb/plugins/workspaces/services/backup_io.py`、ADR 0075 | 团队信息若进备份会破坏「单文件可迁移」 | 新增（D7） |
| 8 | 存储配额按工作区（`storage_quota_bytes` + 快照） | `models.py:170`、`services/storage_snapshot.py` | 团队层只做新建默认值下发，不做实时配额池 | 新增（D7） |
| 9 | 403 文案模板假设「一个工作区一个拥有者」，只列工作区角色 | `permissions.py:74`、ADR 0047 | 需补团队角色分支，否则团队管理员被拒时文案失真 | 新增（D5） |

**核心缺陷（需求要补的）**：现模型只有「工作区」一个组织维度，**部门内的统一管理（成员、策略、工作区集合）无处安放**；而唯一看着像组织维度的 `visibility` 字段并未参与判定。需求要补的是**组织层**，不是新的权限边界——权限边界必须继续留在工作区及其资源上。

设计目标（不变量）：

- **I1 天花板**：任何团队层权限都不放行工作区外的数据；`team_admin` 无工作区角色时读数据一律 404。
- **I2 两平面分离**：管理面（成员 / 设置 / 策略 / 备份）与数据面（读行、读文档、导出、下载附件）由不同来源决定，互不派生（唯一例外：D6 的 `public` 工作区显式授予团队成员只读）。
- **I3 存量不变**：迁移后每个用户 × 每个工作区的读写判定结果与升级前逐条一致（`team_id` 全空、`default_workspace_role=none`）。
- **I4 可归因**：任一有效权限都能映射到一条来源记录（工作区成员 / 团队角色 / 工作区可见性），并可用于 403 文案。
- **I5 删除安全**：删团队 → 工作区 `team_id` 置空并降级为独立工作区，不删任何业务数据；删工作区不影响团队与团队成员。
- **I6 单一判定**：列表 / 详情 / 成员 / 统计 / 备份 / 搜索 / 导入导出全部走 `resolve_capabilities`，禁止路由内直查 `WorkspaceMember`。
- **I7 基数固定**：一个工作区至多属于一个团队；团队不嵌套；解析路径深度恒为 2，不随配置变化。
- **I8 细粒度不动**：表 `Role` 能力位、视图三档、行级规则、文档权限的判定与天花板口径保持 ADR 0003 / 0004 / 0015 不变。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0153 I#`（H27，ADR 0119）；本 ADR 作废删除前，先迁移仍在生效的 H 条目。
> 登记状态（2026-11-25 人工确认）：I1/I2 → H49，I3/I4 → H50，I6 → H51，I5/I7 → H52。

## Decision

### 1. 数据模型

```python
# workspaces/models.py 新增（新表全部可空 / 有默认值，存量零迁移）

class TeamRole(enum.StrEnum):
    OWNER = "owner"    # 团队所有者：团队设置 + 成员管理 + 删除团队
    ADMIN = "admin"    # 团队管理员：工作区管理面（不含数据面）
    MEMBER = "member"  # 团队成员：默认无任何工作区权限（除非被加为工作区成员或工作区公开）

class Team(TimestampMixin, Base):            # workspaces_team
    __tablename__ = "workspaces_team"
    name: str                                 # String(128)，非空
    slug: str                                 # String(64)，非空，UNIQUE(uniq_team_slug)
    description: str                          # Text，默认 ""
    policy: dict                              # JSON，非空，默认 {}（见 §1.2）
    created_by_id: int | None                 # FK accounts_user.id ON DELETE SET NULL

class TeamMember(TimestampMixin, Base):      # workspaces_team_member
    team_id: int                              # FK workspaces_team.id ON DELETE CASCADE
    user_id: int                              # FK accounts_user.id ON DELETE CASCADE
    role: TeamRole                            # 非空，默认 MEMBER
    # UNIQUE(team_id, user_id)；INDEX(team_id)、INDEX(user_id)

class Workspace:                              # 加一列
    team_id: int | None                       # FK workspaces_team.id ON DELETE SET NULL，可空，INDEX
```

- **无 `parent_team_id`**（C2 / I7）：团队不可嵌套，删除「向上继承」这一整类复杂度。
- **无 `workspace_team` 关联表**（C4）：一个工作区一个团队，`NULL` 表示个人工作区。
- **角色不落「继承来的角色」**：`TeamMember` 只描述团队身份，继承结果每次实时解析（避免双写漂移）。

### 1.2 团队策略（`Team.policy`，JSON，键名固定）

| 键 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `default_workspace_role` | `"none" \| "viewer" \| "editor"` | `"none"` | 团队成员**未显式加入**工作区时的默认数据面角色；`none` = 不可见（存量等价） |
| `allowed_modules` | `list[str] \| null` | `null` | 团队内新建工作区可选的模块集合（`null` = 不限，取 `WORKSPACE_MODULES`） |
| `default_storage_quota_bytes` | `int \| null` | `null` | 团队内新建工作区的默认配额上限；`null` = 沿用系统默认 100MB |
| `allow_member_invite` | `bool` | `false` | 团队成员能否自助加入团队工作区（`false` = 仅 owner/admin 添加） |

本期**不提供**「团队管理员可读数据」开关（避免半成品能力）；将来需要时另立 ADR。

### 2. 判定算法（唯一入口）

```python
# workspaces/permissions.py
@dataclass(frozen=True)
class Capabilities:
    data_role: WorkspaceRole | None   # 数据面；None = 不可读（对外统一 404）
    can_manage: bool                  # 管理面
    can_manage_members: bool
    can_manage_backup: bool
    team_role: TeamRole | None
    sources: dict[str, str]           # {"manage": "team_admin@研发部", "data": "workspace_member:viewer"}

def resolve_capabilities(db: Session, user: User, workspace: Workspace) -> Capabilities: ...
def require_capability(cap: str, db, user, workspace) -> None: ...   # 失败走 ADR 0047 文案
```

判定顺序（**显式 > 策略默认 > 无**，每步写入 `sources`）：

1. `WorkspaceMember` 显式角色 → `data_role`（最高优先，团队策略**永不覆盖**显式角色）。
2. 无显式角色时：
   - 若 `workspace.visibility == PUBLIC` 且用户 ∈ 工作区所属团队 → `data_role = VIEWER`（来源 `workspace_public`）。
   - 否则若 `policy.default_workspace_role != "none"` 且用户 ∈ 团队 → 按该值（来源 `team_default`）。
   - 否则 `data_role = None`。
3. `can_manage = (data_role == OWNER) or (team_role in {OWNER, ADMIN})`；`can_manage_members` / `can_manage_backup` 同源细分。
4. `visibility == PRIVATE` 时：非 `OWNER` 成员的数据面为 `None`（管理面不受影响）。
5. 资源级判定不变，天花板来源改为 `Capabilities.data_role`（表 `Role`、视图三档、行规则、文档权限各自入口不改）。

必须复用该入口：`routers/workspaces.py`（列表 / 详情 / 更新 / 删除 / 导入导出 / 备份恢复）、`routers/member_routes.py`、`services/search.py`、`services/workspace_backup.py`、`services/workspace_restore.py` 以及需要工作区级门控的插件路由。

**403 文案扩展**（ADR 0047 单一出口）：`permission_denied_detail` 增加团队分支——「你是【研发部】管理员（仅可管理设置），但不是该工作区成员；如需读取数据，请联系工作区拥有者【张三】加入」。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/teams` | 新增：返回本人可见团队（成员 / 管理员 / 所有者的并集）+ 每团队工作区数 |
| `POST /api/v1/teams` | 新增：任意登录用户可建团队（创建者 = `team_owner`） |
| `GET /api/v1/teams/{tid}` | 新增：团队详情 + 策略 + 本人角色 |
| `PATCH /api/v1/teams/{tid}` | 新增：名称 / 描述 / `policy`（仅 `team_owner`） |
| `DELETE /api/v1/teams/{tid}` | 新增：仅 `team_owner`；工作区 `team_id` 置空（不删工作区） |
| `GET /api/v1/teams/{tid}/members` | 新增：成员列表 |
| `POST /api/v1/teams/{tid}/members` | 新增：按 `username` 添加（仅 owner/admin） |
| `PATCH /api/v1/teams/{tid}/members/{mid}` | 新增：改角色（仅 owner；不得移除最后一个 `team_owner`） |
| `DELETE /api/v1/teams/{tid}/members/{mid}` | 新增：移除成员（仅 owner/admin；不影响其工作区成员身份） |
| `GET /api/v1/teams/{tid}/workspaces` | 新增：团队内工作区平铺列表（C1） |
| `GET /api/v1/workspaces` | 修改：响应增 `team: {id, name} | null`；支持 `?team_id=` 过滤；分组数据由 `GET /teams` 提供 |
| `POST /api/v1/workspaces` | 修改：增可选 `team_id`（校验调用者是该团队成员；`allowed_modules` 校验） |
| `PATCH /api/v1/workspaces/{wid}` | 修改：增可选 `team_id`（挂载 / 解绑；需 `can_manage` + 目标团队成员） |
| `GET /api/v1/workspaces/{wid}/capabilities` | 新增：返回 `Capabilities` 载荷（前端「权限说明」与按钮门控共用） |

### 4. 边界与例外

1. **最后一个 `team_owner`** 不得降级 / 移除 / 退出，否则 400（对齐工作区 owner 转让范式）。
2. **工作区删除仍只由工作区 `owner` 执行**：`team_admin` 不能删除含数据的工作区（防误删，D9）。
3. **工作区可见性 `PUBLIC`**：只授予团队成员 `VIEWER`，不授予管理面、不授予 `PRIVATE` 覆盖权；未挂团队（`team_id IS NULL`）时 `PUBLIC` 等价 `MEMBER`（不引入「全站可见」）。
4. **匿名 / 游客分享**（ADR 0017）不受影响：token 仍是唯一免登录入口。
5. **设计模块库**（D8）：`team` 档仅当拥有工作区 `team_id` 非空时成立；拥有工作区未挂团队时按 `workspace` 处理。
6. **导入 / 恢复**：归档导入**不自动挂团队**（跨环境错挂风险），导入后由调用者选择团队；覆盖恢复只恢复工作区内容，不改 `team_id`。
7. **系统管理员**（`is_superuser`）保留原口径：可绕过工作区门控但不产生「隐式数据可见」的新语义，403 文案中标注「系统管理员」。

### 5. 迁移

单条 alembic 迁移（`down_revision` 取当前 head）：

1. `op.create_table("workspaces_team", ...)`、`op.create_table("workspaces_team_member", ...)` + 唯一键 / 索引。
2. `op.add_column("workspaces_workspace", sa.Column("team_id", sa.Integer(), nullable=True))` + FK `ON DELETE SET NULL` + 索引。
3. **不做任何回填**（存量工作区 `team_id = NULL`，行为等价 I3）。
4. `downgrade`：删列 → 删两张表（顺序反解）；全程幂等（`if not exists` 语义通过 inspector 判定，对齐既有迁移范式）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/workspaces.ts` | 增 `teams` 域客户端（CRUD / 成员 / 工作区 / 策略）与 `capabilities` |
| 首页 | `frontend/src/pages/workspace/WorkspaceList.tsx` | 「团队 → 工作区」两段式列表（团队段平铺、无树）；个人工作区独立段；保留 pinned / tags 与 10s 缓存乐观更新 |
| 团队页 | `frontend/src/pages/team/TeamPage.tsx`（新增） | 团队概览（成员三区 / 工作区列表 / 策略表单）；`team_owner` 才有策略与角色编辑 |
| 工作区设置 | `frontend/src/pages/workspace/WorkspaceSettingsPage.tsx` | 增「所属团队」选择（`can_manage` 可见）与「权限说明」入口 |
| 门控工具 | `frontend/src/hooks/useCapabilities.ts`（新增） | 以 `GET /{wid}/capabilities` 为唯一门控源，替换散落的 `getMemberRole` 判断 |
| 设计库 | `frontend/src/pages/design/`（库检索抽屉） | 可见性选择增「团队」档 + 发布说明 |

### 7. 测试清单

**判定层（单测）** `tests/test_workspace_capabilities.py`

- 显式角色优先于团队策略（`viewer` 成员 + `policy.default_workspace_role=editor` → 仍 `viewer`）。
- `team_admin` 非工作区成员 → `data_role=None`、`can_manage=True`（I1 / I2）。
- `public` 工作区：团队成员 → `VIEWER`；非团队成员 → `None`；未挂团队 → 等价 `MEMBER`。
- `private` 工作区：非 owner 成员 `data_role=None`；`team_admin` 仍 `can_manage`。
- `sources` 归因完整；403 文案含团队角色分支（ADR 0047）。
- **I3 等价回归**：迁移态（`team_id=None`、`policy` 缺省）下，同一组用户 × 工作区判定结果与旧 `get_member_role` / `has_role` 逐条一致。

**接口层** `tests/test_teams_api.py`、`tests/test_workspace_capabilities_api.py`

- 团队 CRUD 权限矩阵（owner / admin / member / 非成员）；最后一个 `team_owner` 保护。
- 团队管理员试图读数据 → 404（不泄露存在性）。
- 工作区挂载 / 解绑团队；`allowed_modules` 越界 400；跨团队挂载 403。
- `?team_id=` 过滤与 `GET /teams` 分组数据一致；团队变更后列表缓存立即失效。

**迁移 / 备份** `tests/test_teams_migration.py`、`tests/test_workspace_backup_team.py`

- 迁移 upgrade / downgrade 往返幂等，存量工作区 `team_id` 全空（H13）。
- 备份往返：`manifest.json` 仅带提示性 `team: {name, slug}`，导入默认不挂团队，覆盖恢复不改 `team_id`（H14）。
- 新表**不进**工作区备份（`backup_io` 不含 `workspaces_team*`），断言导出 JSON 无团队载荷。

**前端单测 / e2e**

- `frontend/src/pages/workspace/WorkspaceList.test.tsx`：团队段平铺（无树节点）、无团队时回退现布局。
- `frontend/src/pages/team/TeamPage.test.tsx`：策略表单校验、非 owner 只读。
- `frontend/tests/e2e/critical/workspace-team.spec.ts`：建团队 → 挂工作区 → 加成员 → 管理员看不到数据（403 文案）→ 成员按策略读到只读数据。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `resolve_capabilities` 抽取（语义与现状完全等价）+ `GET /{wid}/capabilities` + 前端 `useCapabilities` 替换散落判断 + 首页团队分组占位（无 DDL） | 低 |
| **P1** | Team 域最小闭环：迁移、团队 API、团队页、管理面 / 数据面分离、`visibility` 三档启用、403 文案团队分支、备份提示性元数据、缓存扩维度失效 | 中（权限口径变化，需 ADR Accepted） |
| **P2** | 团队策略生效（`default_workspace_role` / `allowed_modules` / `default_storage_quota_bytes` / `allow_member_invite`）、设计模块库 `team` 档、团队内跨工作区搜索、团队级审计事件（`core_event` 增 `team.*`） | 中 |
| **P3**（可选，另立 ADR） | 「工作区链接」：只读引用另一工作区的表 / 视图（显式授权 + 到期），仍然不做权限继承 | 高 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 新增「团队层」作为组织层，工作区仍是唯一权限与数据边界 | 部门内需要统一管理，但权限继承的复杂度不应扩散到全仓 `workspace_id` 判定 | ① 仅扁平 + 标签增强：没有组织层，部门统一管理无处安放；② 父-子工作区树：每个判定点都要「向上继承 + 本层覆盖」，403 可解释性、备份协议、配额、搜索、审计全树化，成本数倍于收益 | 本 ADR §1 / §2 |
| D2 | 层级深度 | 团队单层扁平，无 `parent_team_id`；工作区在团队下平铺列表 | C1 / C2；解析链固定两步（I7） | 多层部门树：解析链可变长，测试矩阵与文案分支爆炸 | `workspaces/models.py` |
| D3 | 工作区归属基数 | `Workspace.team_id` 单值可空，空 = 个人工作区 | C4；多对多会让权限变成并集，不确定性高 | `workspace_team` 关联表（多归属）：口径与 UI 都需「哪个团队授权了我」的二次解释 | 同上 |
| D4 | 管理面 / 数据面 | 分离：`team_owner` / `team_admin` 管设置与成员，默认**不含**数据读 | C3；对齐 GitHub org owner / GitLab group maintainer / Notion workspace admin 的「管理权 ≠ 数据权」 | ① 团队管理员自动继承工作区 owner：等于管理员可读全部门数据；② 团队管理员完全无管理权：团队层失去意义 | `workspaces/permissions.py` |
| D5 | 判定入口 | 唯一入口 `resolve_capabilities`，顺序「显式角色 > 团队策略默认 > 无」，每步可归因 | I4 / I6；403 文案需要来源 | 各路由保留现状分散判定：无法承载策略与归因 | `workspaces/permissions.py`、`routers/deps.py` |
| D6 | `visibility` 死字段 | 启用：`private`=仅 owner（+团队管理面）、`member`=工作区成员（现状）、`public`=团队成员只读 | 字段已在库与备份中，删除需迁移兼容；启用成本更低且给出部门内「只读公开」能力 | 删除该列：需迁移 + 备份兼容处理，且丢掉「部门内公开」这一真实需求 | `models.py`、`permissions.py`、备份 |
| D7 | 配额与备份边界 | 配额按工作区（快照不变）；团队**不进**工作区备份，仅在 manifest 记提示性 `team.name/slug`；P2 才做新建默认配额 | ADR 0075 的单文件自包含承诺；H14 口径不摇摆 | 团队随备份往返：破坏跨环境可迁移性，且团队是环境级配置 | `services/backup_io.py` |
| D8 | 跨工作区复用 | 设计模块库新增 `visibility=team`：可见 = 消费方用户 ∈ 拥有工作区所属团队；`public` / `workspace` 不变；归档仍只阻断新引用 | C5；复用 ADR 0118 已有可见性范式，不新造机制 | 允许跨团队引用私有模块：违反「权限只有拥有团队有」 | `design/models.py`、`design/services/files.py` |
| D9 | 删除语义 | 删团队 → 工作区 `team_id` 置空降级；删工作区仅工作区 `owner` 可执行 | I5；防团队管理员误删含数据工作区 | 删团队连带删工作区：不可接受的数据丢失风险 | `routers/workspaces.py`、团队路由 |
| D10 | 工作区内权限分配 | 三档角色不变；引入「能力位」映射（`MANAGE_MEMBERS` / `MANAGE_SETTINGS` / `MANAGE_BACKUP` / `EDIT_SCHEMA` / `MERGE_CR`），P2 才允许自定义角色 | C8；档位增加会成倍放大组合与测试矩阵 | 现在扩到 5+ 档（admin / reviewer / guest）：收益远小于复杂度 | `workspaces/models.py`、`permissions.py` |
| D11 | 父-子工作区与跨工作区数据 | 本期不做；需要跨工作区数据汇总时走 P3「工作区链接」另立 ADR | C6；权限继承不可解释风险最高 | `parent_workspace_id` 树：见 D1 否决理由 | 无（本期不落码） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：部门获得统一管理入口，而不改动任何资源级细粒度授权；`visibility` 死字段得到结论；403 文案可解释到「哪个来源给了你什么」。
- **负向**：判定链从 1 步变 2 步（工作区角色 + 团队策略），需一次性收敛所有直查 `WorkspaceMember` 的路径；团队成为新的环境级配置实体（不随工作区备份迁移）。
- **风险与缓解**：① 缓存越权可见 → 团队 / 成员 / 策略变更统一走失效（对齐 H18）；② 迁移破坏存量 → I3 以「逐用户逐工作区判定快照对比」锁定（H13 / H16 同款思路）；③ 团队层被做成第二个权限系统 → 团队只产「管理权 + 授权模板」，数据主体仍在工作区，I6 以单一入口约束。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性三档 | `tables_dataview.visibility` | 判定与天花板口径不变，天花板来源改 `Capabilities.data_role` | ADR 0003（I1 不变） |
| 行级权限 | `tables_rowpermission` | 完全不变；「表外的人」定义仍以工作区成员为准 | ADR 0004（H15） |
| 403 文案 | `workspaces/permissions.py` | 单一出口不变，新增团队角色分支 | ADR 0047 |
| 工作区备份 | `workspace_backup` / `backup_io` | 协议不变，manifest 只加提示性 `team` 字段 | ADR 0075 |
| 工作区模块 | `workspaces_workspace.modules` | 口径不变；P2 由团队策略 `allowed_modules` 限定新建取值 | ADR 0080 |
| 设计复用模块库 | `design_library_module.visibility` | 增 `team` 档，其余（版本不可变、归档只阻断新引用）不变 | ADR 0118 |
| 硬约束台账 | `docs/CONSTRAINTS.md` | I1-I8 待评审后登记 | ADR 0119（H27） |

## 行业对照（参考口径，非规范）

| 维度 | Notion（teamspace） | GitLab（group / project） | 本设计 |
|---|---|---|---|
| 组织层 | teamspace 内含页面，权限继承 + 页面级覆盖 | group 角色继承到 project，project 可覆盖成员 | 团队只在管理面与策略层生效，不进入资源级判定（D4 / D5） |
| 管理员可见数据 | 可（workspace owner 可见全部） | 可（Owner 可读 project） | **默认不可**，数据面只认工作区角色（D4） |
| 删除上级 | 需先迁移内容 | 删 group 连带删 project | 删团队只解绑，不删数据（D9） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/routers/deps.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/routers/member_routes.py`、`src/cndb/plugins/workspaces/schemas/models.py`、`frontend/src/hooks/useCapabilities.ts`、`frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | `tests/test_workspace_capabilities.py`、`tests/test_workspace_capabilities_api.py`、`frontend/src/hooks/useCapabilities.test.tsx` | 未提交 |
| P1 | 未开始 | `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/routers/teams.py`、`src/cndb/alembic/versions/`、`frontend/src/pages/team/TeamPage.tsx` | `tests/test_teams_api.py`、`tests/test_teams_migration.py`、`frontend/src/pages/team/TeamPage.test.tsx` | — |
| P2 | 未开始 | `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/services/files.py`、`src/cndb/plugins/workspaces/services/search.py` | `tests/test_design_library_team_scope.py`、`tests/test_workspace_backup_team.py` | — |
| P3 | 未开始 | 另立 ADR | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 已落地（能力位单一入口），待人工确认 D1 / D4 / D6 / D7 后开 P1（团队域 + 迁移）
- 已完成：需求卡片 0153（C1-C9）；ADR 决策记录 D1-D11 与不变量 I1-I8；H49-H52 已登记；P0 能力位抽取（`WorkspaceCapability` / `ROLE_CAPABILITIES` / `resolve_capabilities` / `require_capability`）+ `GET /{wid}/capabilities` + 前端 `useCapabilities`；I3 等价回归用例（与旧 `get_member_role` / `has_role` 逐条对齐）
- 下一步：`P1` 建 `workspaces_team` / `workspaces_team_member` + `workspaces_workspace.team_id` 迁移，接入团队角色与 `policy.default_workspace_role`，启用 `visibility` 三档（启用前先补 D6 行为变更用例）
- 已知坑：① `Workspace.visibility` 目前仍无判定消费（P0 刻意未启用，避免 P0 改变行为），P1 启用必须同时补「private / public 新语义」用例并复核存量工作区；② 其他插件仍直接调 `get_member_role`（数据面视图，语义等价），P1 加团队来源后需逐个改为 `resolve_capabilities`（H51 只约束工作区级门控）；③ 前端仍有若干 `current_user_role === 'owner'` 判断未迁移（设计模块 / 模板面板等），迁移时保持与 `/capabilities` 一致
- 最近一次全绿：`make check-fast` + `make test`（7317 passed）+ 前端 `vitest run`（3383 passed）@ 未提交（2026-11-25）
