# ADR 0154: 工作区链接（跨工作区只读引用）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/tables/routers/records.py`、`frontend/src/pages/workspace/TablesList.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0154-workspace-link.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「需要跨工作区数据汇总」 | `workspace_link` 只读引用：消费方按链接读取源工作区的**单表 / 单视图**（分页 + 该视图筛选），可导出 CSV；不搬迁、不缓存落库 |
| C2 | 「权限只有拥有团队有」（延伸） | 链接生命周期 = 消费方发起 → **源工作区 owner 批准** → 到期自动失效；`expires_at` 必填（默认 30 天，上限 365 天） |
| C3 | H15 天花板 | 取数判定唯一走 `resolve_capabilities(user, 源工作区)`：无 `READ` → 403；有 `READ` 时行级规则 / 字段隐藏 / 软删过滤与普通读取**同一入口**（`row_read_scope_where` + 隐藏字段集合） |
| C4 | 单向只读 | 链接只有 `GET` 读路径：`/{wid}/links/{id}/fields`、`/rows`、`/export`；不挂任何写路由，写入口一律 404 |
| C5 | 可解释 | 列表返回 `source_workspace`、`approved_by`、`expires_at`、`readable`（当前用户能否取数）；前端在只读网格顶部展示同信息，`readable=false` 时给「联系源工作区拥有者」文案 |
| C6 | 无泄露 | 未批准 / 已拒绝 / 已撤回 / 已过期 / 源表已删 / 目标不属于该源工作区 → 统一 404 |
| C7 | 不级联 | 链接表不可被再链接、不可作 lookup 源、不可进分析页与流水线、不可被文档 `{{table:}}` 引用（保存期校验拒绝）；MVP 不进入全局检索 |
| C8 | 备份边界 | `workspace_link` **不进**工作区备份（`backup_io` 不导出）；源工作区 / 源表删除时 `ON DELETE CASCADE` 清理 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区级判定已收敛为 `resolve_capabilities`（P0-P2），能力位含 `READ` / `WRITE` / `EXPORT` | `src/cndb/plugins/workspaces/permissions.py:resolve_capabilities` | 链接取数可直接复用，不需要新判定分支 | 确认（C3） |
| 2 | 行级读范围与字段隐藏有唯一入口：`row_read_scope_where` + `hidden_fields` | `src/cndb/plugins/tables/services/core/row_access.py`、`access.py` | 链接读必须经同一入口，否则会绕开 H15/H17 | 确认（C3） |
| 3 | 记录列表读缓存按 (表, 用户, 过滤签名) 分片（ADR 0046 D3） | `src/cndb/plugins/tables/routers/records.py`、`core/cache` | 链接读需独立缓存键（含 link_id），避免与本工作区读串味 | 新增 |
| 4 | 工作区备份自带「不导清单」（流水 / 事件 / 个人配置） | `src/cndb/plugins/workspaces/services/workspace_backup.py`、`backup_io.py` | 链接按同款口径排除，避免跨环境 id 悬空 | 新增（C8） |
| 5 | 表列表 / 侧栏按工作区模块渲染，只有本工作区表 | `frontend/src/pages/workspace/TablesList.tsx`、`layouts/MainLayout.tsx` | 需新增「外部链接」段（只读、无编辑入口） | 确认（C1/C4） |
| 6 | 跨工作区检索只覆盖「用户可读工作区」（P2 起含私有过滤） | `src/cndb/plugins/workspaces/services/search.py` | MVP 不把链接表纳入检索：避免跨工作区泄露与索引放大 | 确认（C7） |
| 7 | 分析 / 流水线 / lookup 都以 `workspace_id` 收敛数据源 | `plugins/analytics/`、`plugins/pipeline/`、`tables/services/core/lookup_sync.py` | MVP 一律不接链接，防止权限链式推断 | 确认（C7） |
| 8 | 表删除已支持软删 / 回收站（ADR 0139） | `tables/services/core/records.py`、`routers/tables.py` | 源表软删后链接应视为失效（404），彻底删除后级联清理 | 新增 |

**核心缺陷（需求要补的）**：工作区是硬边界（ADR 0153 保留），**跨工作区的只读汇总没有合法通道**——要么搬数据（重复、易腐），要么给总部人员逐个加部门工作区成员（授权噪声大且能写）。需求补的是「**受控、可解释、可到期**的只读引用通道」，而不是权限继承。

设计目标（不变量）：

- **L1 授权主体不新增**：链接不产生新的授权主体；有效读 ⇒ 用户在源工作区 `READ`（`resolve_capabilities().allows(READ)`），H15 / H17 口径原封不动。
- **L2 单向只读**：链接无任何写路径；消费方对链接表的所有写操作不可达（404 / 405）。
- **L3 到期即失效**：`expires_at` 必填，过期后所有读路径统一 404（不保留「只读结构」）。
- **L4 无泄露**：未批准 / 拒绝 / 撤回 / 过期 / 源表删除 / 目标不匹配全部 404，不区分原因。
- **L5 不级联**：链接不可再链接、不作 lookup / 分析 / 流水线 / 文档引用的数据源。
- **L6 备份不自包含**：链接不进工作区备份；随源删除级联清理。
- **L7 存量不变**：没有任何链接时，全部既有路径行为与升级前逐条一致。
- **L8 可解释**：任一链接都能回答「谁批准、何时到期、我为什么读不到」。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0154 L#`（H27，ADR 0119）。当前**未登记**：待方案评审通过后按 L1/L2/L3/L6 四条落 H 条目（L1 与既有 H15 同轴，需注明「链接不新增授权面」）。

## Decision

### 1. 数据模型

```python
# workspaces/models.py 新增
class WorkspaceLink(TimestampMixin, Base):      # workspaces_workspacelink
    __tablename__ = "workspaces_workspacelink"
    __table_args__ = (
        UniqueConstraint("workspace_id", "alias", name="uniq_workspace_link_alias"),
        {"extend_existing": True},
    )
    workspace_id: int            # 消费方，FK CASCADE
    source_workspace_id: int     # 源工作区，FK CASCADE
    target_type: str             # "table" | "view"（String(16)）
    target_table_id: int         # FK tables_datatable.id CASCADE
    target_view_id: int | None   # FK tables_dataview.id SET NULL（target_type=view 时必填）
    alias: str                   # String(64)，消费方内唯一显示名
    status: str                  # "pending" | "active" | "rejected"
    expires_at: datetime         # 必填；批准时写入 now + ttl
    created_by_id: int | None    # FK accounts_user SET NULL
    approved_by_id: int | None   # FK accounts_user SET NULL
    approved_at: datetime | None
    note: str                    # 申请备注（String(200)）
```

索引：`(workspace_id)`、`(source_workspace_id, status)`、`(target_table_id)`。

**不建**「团队级批量授权」表：授权主体恒为**源工作区 owner**（C2）；团队层不参与链接判定（与 ADR 0153 D11 一致：层级不产数据主体）。

### 2. 判定算法（唯一入口）

```python
# workspaces/services/links.py
def resolve_link(db, user, link_id) -> ResolvedLink:      # 404 统一出口
    # 1. link 存在 且 status=="active" 且 now < expires_at
    # 2. link.workspace_id 是当前工作区（路由上下文）
    # 3. 目标表 / 视图仍存在、未软删、且确实属于 source_workspace_id
    # 4. caps = resolve_capabilities(user, source_workspace)  → 必须 allows(READ)，否则 403
    ...
```

- 第 4 步失败返回 **403**（用户确实是消费方成员，只是对源工作区无读权，文案按 ADR 0047 指出源工作区拥有者）；1-3 失败返回 **404**。
- 取数**复用**普通读路径：`row_read_scope_where(...)` + 隐藏字段集合 + 视图筛选 / 排序 / 分页参数，与本工作区读同源，不另写一套裁剪。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/links` | 新增：发起链接申请（`target_table_id` / `target_view_id?` / `alias` / `ttl_days` / `note`）；要求消费方 `EDIT_SETTINGS` |
| `GET /api/v1/workspaces/{wid}/links` | 新增：消费方链接列表（含 `status` / `expires_at` / `approved_by` / `readable`） |
| `GET /api/v1/workspaces/{wid}/links/inbox` | 新增：待我批准（源工作区 owner 视角） |
| `POST /api/v1/workspaces/{wid}/links/{id}/approve` | 新增：源工作区 owner 批准（写 `expires_at`） |
| `POST /api/v1/workspaces/{wid}/links/{id}/reject` | 新增：源工作区 owner 拒绝 |
| `DELETE /api/v1/workspaces/{wid}/links/{id}` | 新增：消费方 owner 或源工作区 owner 撤回（物理删除） |
| `GET /api/v1/workspaces/{wid}/links/{id}/fields` | 新增：结构（按隐藏字段集合裁剪） |
| `GET /api/v1/workspaces/{wid}/links/{id}/rows` | 新增：只读行（分页 / 视图筛选 / 排序），**无写方法** |
| `GET /api/v1/workspaces/{wid}/links/{id}/export` | 新增：CSV 导出（受同一行 / 列裁剪与行数上限，ADR 0148） |

### 4. 边界与例外

1. `ttl_days` 取值 1–365，缺省 30；`expires_at` 在批准时按 `now + ttl_days` 落库（申请期不预占）。
2. 同一 `(消费方, 源表, 视图)` 只允许一条 `active` 链接；重复申请 → 400（避免多份到期时间打架）。
3. `target_type=view` 时行范围 = 该视图的筛选与排序 + 用户行级规则；视图本身不可见给用户（ADR 0003）→ 仍按表 `READ` 判定，不额外要求 `VIEW_READ`（简化口径，写入决策记录）。
4. 源表 / 源视图被软删 → 链接读 404（不自动清理）；彻底删除 → `ON DELETE CASCADE` 移除链接。
5. 源工作区 `visibility=private` 时：非 owner 一律 403（`resolve_capabilities` 已在 D6 收口）。
6. 链接不参与工作区统计（`table_count` / `total_rows` 不计），避免口径混乱。
7. 系统管理员沿用既有口径（可绕过门控），403 文案标注「系统管理员」。

### 5. 迁移

单条 alembic 迁移（`down_revision` 取当前 head `f2b3c4d5e6a7`）：建 `workspaces_workspacelink` + 两个唯一键 / 索引；**无回填**（存量零迁移，L7）；`downgrade` 删表。幂等：表已存在则跳过。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/links.ts`（新增） | 发起 / 列表 / 批准 / 拒绝 / 撤回 / fields / rows / export |
| 表列表 | `frontend/src/pages/workspace/TablesList.tsx` | 侧栏新增「外部链接」段：`pending` 显示「待源工作区批准」，`active` 可打开只读网格，过期置灰并提示 |
| 只读网格 | `frontend/src/pages/grid/LinkedTablePage.tsx`（新增） | 路由 `/w/:wid/links/:linkId`；复用网格只读渲染，隐藏所有编辑入口；顶部展示来源 / 批准人 / 到期时间 / 可读状态 |
| 批准入口 | `frontend/src/pages/workspace/TablesList.tsx` 或工作区设置 | 「待我批准的链接」列表（源工作区 owner 可见），批准时可改 `ttl_days` |
| 门控 | `useCapabilities` | 发起申请要求 `EDIT_SETTINGS`；批准要求源工作区 owner（用源工作区的 `/capabilities`，不新增能力位） |

### 7. 测试清单

**判定层（单测）** `tests/test_workspace_links.py`
- `resolve_link`：pending / rejected / 过期 / 源表软删 / 目标不属于源工作区 → 404；
- 消费方成员但源工作区无 `READ` → 403；源工作区 `private` → 403（D6 联动）；
- 行级规则外行不可见、隐藏字段不返回（H15 / H17 回归）；
- 视图筛选与排序生效；`ttl_days` 越界 400；重复 active 400。

**接口层** `tests/test_workspace_links_api.py`
- 发起 / 批准 / 拒绝 / 撤回全链路；非 owner 批准 → 403；
- 只读：`POST/PATCH/DELETE` 到 `/links/{id}/rows` 一律 404/405；
- 导出 CSV 受行数上限与列裁剪约束；
- 链接不进 `GET /{wid}/export` 与归档备份（C8）。

**迁移 / 备份** `tests/test_workspace_links_migration.py`
- upgrade / downgrade / 幂等；源工作区删除级联清理；备份 JSON 不含链接键。

**前端单测 / e2e**
- `LinkedTablePage.test.tsx`：只读渲染、无编辑入口、到期与不可读文案；
- `TablesList.test.tsx`：外部链接段三态；
- `frontend/tests/e2e/critical/workspace-link.spec.ts`：发起 → 批准 → 打开只读网格 → 到期后 404。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 + 迁移 + 发起 / 批准 / 拒绝 / 撤回 + 列表（不含取数） | 低 |
| **P1** | 只读取数（fields / rows / export），复用行级与隐藏字段入口 | 中（权限口径，需 H15 回归） |
| **P2** | 前端入口：侧栏段 + 只读网格 + 批准入口 + 过期提示 | 中 |
| **P3**（可选，需另立 ADR） | 分析页把链接作为数据源 / 团队级批量授权 / 链接汇总 | 高 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 通道形态 | 实时只读引用（不搬迁、不物化） | 数据不重复、不腐化；汇总口径随源实时更新 | ① 定时复制（ETL）：重复存储 + 延迟 + 口径漂移；② 物化视图：跨库 / SQLite 无原生支持，失效策略复杂 | `workspaces/models.py`、`services/links.py` |
| D2 | 授权主体 | 源工作区 owner 逐条批准，到期自动失效 | C2；「拥有者说了算」与 0153 的两平面口径一致 | 团队级批量授权：MVP 下把数据授权扩到团队，放大误授面（留 P3） | `routers/links.py` |
| D3 | 是否新授权面 | **不新增**：取数仍要求用户在源工作区 `READ` | 保 H15/H17；避免「链接成为绕过行级权限的后门」 | 链接自带列白名单 + 行过滤（真·零成员汇总）：与 H15 冲突，须先改台账（卡片未决问题，默认不做） | `services/links.py` |
| D4 | 写能力 | 无（只挂 GET） | C4；单向可解释 | 允许写入回源：跨工作区写入的事务与并发语义（ADR 0140）无法在 P3 内说清 | `routers/links.py` |
| D5 | 视图口径 | `target_type=view` 只取该视图的筛选 / 排序，权限仍按表 `READ` | 简化：避免叠加 `VIEW_READ` 造成「看得见表却打不开链接」的困惑 | 要求 `VIEW_READ`：与 ADR 0003 的三档授权叠加后解释成本过高 | `services/links.py` |
| D6 | 失效表达 | 过期 / 撤回 / 源删除一律 404；无读权 403 | 沿用 ADR 0004 I6（无泄露）与 ADR 0047（可解释）两条既有口径 | 200 + 空数据：让前端与用户都分不清「没数据」与「没权限」 | `services/links.py` |
| D7 | 级联范围 | 不进备份；源工作区 / 源表删除级联清理 | C8；跨环境 id 无意义，悬空链接比缺失更糟 | 随备份往返：导入到另一环境必然指向不存在的表 | `services/backup_io.py` |
| D8 | 生态接入 | MVP 不接分析 / 流水线 / lookup / 检索 / 文档引用 | C7；每个接入面都要重新证明不越权，风险递增 | 直接全接：权限链式推断（链接→lookup→视图→分享）无法在单期验证 | 无（列入 P3） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：总部汇总场景有合法通道且可到期；不搬迁数据；不新增授权主体，H15 口径不破。
- **负向**：跨工作区读仍是「两个工作区都要有身份」，真正零成员汇总做不了（明确写进卡片未决问题）；每加一个生态接入面都要重新证明不越权。
- **风险与缓解**：① 链接读绕过行级规则 → L1 + 判定层单测锁死（行级规则外行不可见）；② 缓存串味 → 缓存键含 link_id；③ 悬空链接 → L6 不进备份 + 级联删除 + 404 降级。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 工作区边界 | `workspace_link` | 跨工作区只读引用，不做父子 / 继承 | ADR 0153 D11 |
| 行级权限 | `tables_rowpermission` | 链接读与普通读同一入口，天花板不变 | ADR 0004（H15 / H17） |
| 视图三档 | `tables_dataview.visibility` | 只取筛选 / 排序，不叠加视图授权 | ADR 0003 |
| 403 / 404 文案 | `workspaces/permissions.py` | 403 指源工作区拥有者；404 不区分原因 | ADR 0047、ADR 0004 I6 |
| 工作区备份 | `backup_io` | 链接不进备份，随源删除级联 | ADR 0075 |
| 读性能与导出上限 | `records` / 导出 | 复用缓存与行数上限 | ADR 0046、ADR 0148 |
| 硬约束台账 | `docs/CONSTRAINTS.md` | L1 / L2 / L3 / L6 待评审后登记 | ADR 0119（H27） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/routers/links.py` | `tests/test_workspace_links_api.py` | — |
| P1 | 未开始 | `src/cndb/plugins/workspaces/services/links.py` | `tests/test_workspace_links.py` | — |
| P2 | 未开始 | `frontend/src/pages/grid/LinkedTablePage.tsx`、`frontend/src/pages/workspace/TablesList.tsx` | `frontend/src/pages/grid/LinkedTablePage.test.tsx` | — |
| P3 | 未开始 | 另立 ADR | — | — |

## 交接（会话结束更新）

- 当前阶段：方案（ADR `Proposed`，**未进入实现**，H5）
- 已完成：需求卡片 0154（C1-C8）；ADR 决策记录 D1-D8、不变量 L1-L8、数据模型与 API 清单
- 下一步：人工评审 D1 / D3 / D2（尤其 D3：是否要做「零成员汇总」的新授权面）；通过后①把 L1/L2/L3/L6 登记进 `CONSTRAINTS.md`；②开 P0（模型 + 迁移 + 申请 / 批准）
- 已知坑：① D3 是全局取舍点——若将来要放宽成「链接自带列白名单 + 行过滤」，必须先改 H15 口径并写明「链接是新授权面」，否则会留下越权后门；② 缓存键必须含 link_id，否则与本工作区读串味（ADR 0046 D3 同款问题）；③ 源工作区 `private`（ADR 0153 D6）下链接一律 403，前端文案要与工作区设置页保持一致；④ 迁移 `down_revision` 需取最新 head（当前 `f2b3c4d5e6a7`），并行会话新增迁移后要同步改
- 最近一次全绿：`make check-docs` @ `8c625f7f`（2026-11-25）
