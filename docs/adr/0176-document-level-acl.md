# ADR 0176: 文档级 ACL（受限可见性 + 只读白名单）

Status: Proposed（待评审）
Date: 2026-11-26
Related: ADR 0161（权限边界收紧）、ADR 0153（团队与两平面）、ADR 0047（403 文案）、ADR 0004（行级权限，仅作判定风格参考）、ADR 0172（文档副本）、ADR 0173（事件审计）、`src/cndb/plugins/documents/services/visibility.py`、`src/cndb/plugins/workspaces/permissions.py`
需求卡片: `docs/requirements/0176-document-level-acl.md`

## 口径（需求 → 设计落点）

需求原文见卡片 §需求原句；卡片约束沿用 C1..C11，本表只补设计落点。

| 卡片约束 # | 需求片段 | 本设计的落地 |
|---|---|---|
| C1 | 文档级覆盖 | `Document.acl_mode ∈ {inherit, restricted}`；`restricted` 仅对 published 生效，白名单主体可读（D1 / D3 / D4） |
| C2 | 只收紧读、不放大写 | `documents_acl` 只存 READ 主体；写仍走 `resolve_write_mode`，ACL 不参与（D4 / I2） |
| C3 | 管理员与创建者 | 超管 / 工作区 OWNER 恒可读；`created_by_id` 恒可读（D3） |
| C4 | 单一判定（H64） | 新入口 `resolve_document_access`；`visibility.visible_condition` 扩展为 ACL 感知 SQL，所有读路径复用（D5） |
| C5 | 私有工作区（H66） | `data_role is None` 直接拒绝，ACL 不参与放宽（D3 / I4） |
| C6 | 管理入口 | owner 或（editor+ 且文档创建者）可读写 ACL；viewer 403；跨区 404（D6） |
| C7 | 分享链接 | 既有 token 不回收；新建 / 停用分享沿用现有 editor+ 门槛；风险记录（D7 / Consequences） |
| C8 | 生命周期 | 软删保留 ACL；跨区移动丢弃目标区不存在的用户主体；备份含 ACL、旧包缺键按 inherit（D8） |
| C9 | 审计 | `document.acl_update` 事件只记模式与主体计数（D9） |
| C10 | 前端 | 文档抽屉「权限」页 + 列表 / 树「受限」图标（§6） |
| C11 | 测试与文档 | 判定 / 接口 / 迁移 / 备份 / 前端用例见 §7 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 文档可见性只有状态维度：published 全员、draft/archived 仅创建者与 OWNER/超管 | `visibility.py:43,59,125` | 无法表达「这篇 published 只给某几个人看」 | 确认 C1 |
| 2 | 工作区数据面唯一判定 `resolve_capabilities`，资源层不得直查成员角色（H64） | `permissions.py:207` | ACL 必须叠加在 data_role 之上，不能另起一套成员判定 | 确认 C4 |
| 3 | 表级权限已有 `read_role` 先例（角色门槛 + 所有者/超管豁免） | `tables/models.py:466`、`tables/services/core/access.py:36` | 表达方式可借鉴；但文档需要「按用户白名单」，表级没有等价物 | 参考 |
| 4 | 历史 `documents_permission` 文档授权表已随协作者功能删除 | 迁移 `2c3d4e5f6a70` | 不复用旧表名与旧语义，重建新表 | 确认 |
| 5 | `private` 工作区非 owner 数据面恒为空（H66） | `permissions.py:236`、`visibility.py:46` | ACL 不得成为 private 的旁路 | 确认 C5 |
| 6 | 游客分享是独立 token（capability URL），与成员权限并行 | `documents/models.py:210-221` | ACL 与已有 token 的关系必须明确 | 确认 C7 |
| 7 | 跨工作区移动保留文档 id / 版本链 / 文件 / 分享 | `services/move.py:264` | ACL 主体是工作区成员，移动后需过滤 | 确认 C8 |
| 8 | 备份 / 恢复按表导出文档与其 shares / issue | `backup_io.py:587`、`workspace_backup.py:183` | ACL 需纳入往返，旧包缺键要兼容 | 确认 C8 |
| 9 | 读路径（列表 / 树 / 检索 / 图谱 / 反链 / 导出 / 版本）统一走 `visible_condition` 或 `can_view_document` | `services/content.py:794`、`services/search.py`、`services/visibility.py:59` | ACL 只要改这两个单点即可全量生效 | 确认 C4 |
| 10 | 超管 / OWNER 在可见性判定中直接放行 | `visibility.py:46` | ACL 必须保持该豁免 | 确认 C3 |

**核心缺陷**：现有可见性只有「按状态」一档，无法表达「同一工作区内，这篇文档只对指定的人 /
角色开放」，也无法让 owner 在不改工作区可见性的前提下收窄单篇文档。

设计目标（不变量）：

- **I1 单一读判定**：文档读权限只由 `resolve_document_access` 给出，SQL 过滤与单篇判定共用同一口径。
- **I2 ACL 不提权写**：ACL 只授 READ；任何条目不得改变 `resolve_write_mode` 的结论。
- **I3 不削弱 H33**：`restricted` 仅在 `published` 状态生效；draft / archived 仍只对创建者与管理员可见。
- **I4 私有优先**：`visibility=private` 时非 owner 的 `data_role` 为 `None`，ACL 不得放宽（H66）。
- **I5 分享语义不变**：分享 token 是显式能力凭据，ACL 不追溯失效已发出的 token。

> 本 ADR 的 I1 / I2 属跨需求长期口径，`Proposed → Accepted` 前需登记入 `CONSTRAINTS.md`
> （建议 H70 / H71，来源 `ADR 0176 I1/I2`）。

## Decision

### 1. 数据模型

**Document 新增列**：

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `acl_mode` | String(16) | `inherit` | `inherit`（沿用状态可见性）/ `restricted`（仅白名单） |

**新表 `documents_acl`**（迁移单条，downgrade 删表 + 删列）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `document_id` | FK documents CASCADE, index | |
| `subject_type` | String(8) | `user` / `role` |
| `subject_key` | String(64) | user id 的字符串，或角色值 `viewer`/`editor` |
| `created_by_id` | FK accounts SET NULL | 授权人 |
| `created_at` | TimestampMixin | |

唯一键 `(document_id, subject_type, subject_key)`；索引 `(document_id)`。
角色主体只有两个合法值：`viewer`（对所有成员生效）、`editor`（editor 及以上）。
`restricted` 且白名单为空 = 仅创建者 / 管理员可见（合法状态，不是错误）。

### 2. 判定算法（唯一入口）

`documents/services/access.py::resolve_document_access(db, workspace_id, doc, user)`：

```python
@dataclass(frozen=True)
class DocumentAccess:
    can_read: bool
    can_write: bool
    source: str   # superuser / owner / creator / acl:user / acl:role / status:public / status:owner-only / private / denied
```

判定顺序：

1. `user is None` → 全 false（游客走分享端点，不进本入口）。
2. `is_superuser` 或 `workspace_data_role == OWNER` → 读 true，写 true（写仍受文档状态限制）。
3. `workspace_data_role is None` → 全 false（**H64：ACL 不跨工作区放行**）。
4. `workspace.visibility == private` 且非 owner → 全 false（**H66，ACL 不参与**）。
5. `doc.status != published` → 仅 `created_by_id == user.id` 可读（**H33 不变**），写按双轨制。
6. `doc.acl_mode == inherit` → 读 true（published 全员）。
7. `doc.acl_mode == restricted`：
   - `created_by_id == user.id` → 读 true；
   - 命中 `acl(user, user.id)` 或 `acl(role, viewer)` → 读 true；
   - 命中 `acl(role, editor)` 且 `data_role == EDITOR` → 读 true；
   - 否则读 false（对外 404）。
8. `can_write = can_read and resolve_write_mode(...) != denied`；**ACL 不改变写模式**。

### 3. SQL 过滤（列表 / 树 / 检索 / 图谱 / 反链）

扩展 `visibility.visible_condition(db, workspace_id, user)`：

```sql
workspace_id = :ws AND is_deleted = 0 AND (
  :is_admin
  OR created_by_id = :uid
  OR (
    status = 'published'
    AND (
      acl_mode = 'inherit'
      OR EXISTS (SELECT 1 FROM documents_acl a
                 WHERE a.document_id = documents_document.id
                   AND ( (a.subject_type='user' AND a.subject_key=:uid)
                      OR (a.subject_type='role' AND a.subject_key='viewer')
                      OR (a.subject_type='role' AND a.subject_key='editor' AND :is_editor) ))
    )
  )
)
```

- 该条件已是所有读路径的唯一 SQL 入口（`content.list/search/graph/backlinks` 均复用），
  因此 ACL 自动覆盖，无需逐端点改造；
- 单篇路径 `get_visible_document_or_404` 也改为调用 `resolve_document_access`，与 SQL 语义逐条对齐
  （由同一组用例双跑校验）。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/documents/{doc_id}/acl` | 新增：`{mode, entries:[{subject_type, subject_key}], effective_role}`（管理权限者可见） |
| `PUT /{wid}/documents/{doc_id}/acl` | 新增：整体替换 `{mode, entries}`；角色主体去重；`subject_type=user` 校验该用户是工作区成员 |
| `GET /{wid}/documents` / `/tree` / `/search` / `/links/graph` | 无签名变化，结果按新可见性过滤；`DocumentItem` 增加 `acl_mode` 字段 |

### 5. 边界与例外

1. **draft / archived**：ACL 忽略，仍按 H33；`restricted` 只对 published 有意义（I3）。
2. **owner 给自己收窄**：不允许。OWNER / 超管 / 创建者恒可读，避免「把自己锁在门外」。
3. **角色主体语义**：`viewer` = 所有 workspace_data_role 非空者；`editor` = EDITOR / OWNER（OWNER 已豁免）。
4. **跨区移动**：`subject_type=user` 中不属于目标工作区成员的行删除并记 warning；`role` 行保留。
5. **复制副本**（0172）：副本默认 `inherit`，不继承源文档 ACL（避免隐性扩散）。
6. **软删 / 恢复**：ACL 行保留；恢复后继续生效。
7. **分享 token**：不追溯失效（I5）；「谁能新建分享」沿用现有 editor+ 门槛；风险见 Consequences。
8. **修改申请**：restricted 文档的可见者可正常提交申请（写仍按双轨制）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 抽屉 | `DocumentAclPanel.tsx`（新） | 模式切换（继承 / 受限）、用户选择器、角色勾选、保存 |
| 文档详情 | `DocumentEditorPage.tsx` | 抽屉增加「权限」页签（仅管理权限者可见） |
| 列表 / 树 | `DocumentTable.tsx` / `DocumentTree.tsx` | restricted 文档显示锁形图标（图标优先，`--cn-text-secondary`，不靠颜色区分） |
| API | `api/documents.ts` | `getDocumentAcl / updateDocumentAcl`；`DocumentItem.acl_mode` |

### 7. 测试清单

**判定层（单测）**：inherit published 全员可读；restricted 未授权 404；用户白名单命中；
role=viewer / editor 命中；creator 恒可读；owner / 超管豁免；private + ACL 仍 404；
draft + ACL 仍仅创建者；ACL 授权后 viewer 仍走修改申请（写不放大）。

**SQL / 单篇一致性**：同一组文档 / 用户矩阵，`visible_condition` 结果与 `resolve_document_access` 逐条一致。

**接口层**：ACL 读写权限（owner / creator-editor / viewer 403 / 跨区 404）；`subject_type=user` 非成员 400；重复主体去重。

**生命周期**：软删恢复 ACL 保留；跨区移动用户主体过滤；副本不继承；备份往返 + 旧包缺键。

**前端**：模式切换与保存；受限图标；无权限者看不到面板。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 列 + 表 + 迁移 + `resolve_document_access` + SQL 条件 | 中（SQL 与单篇语义对齐） |
| **P1** | ACL 读写接口 + 审计 + 备份 / 移动 / 副本接入 | 中（生命周期边界） |
| **P2** | 前端权限面板 + 图标 + 测试 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 表达方式 | `acl_mode` + 白名单条目（user / role） | 同时支持「收窄」与「按人放行」，结构简单 | 只做角色门槛（无法按人）；allow/deny 列表（优先级歧义） | 表 `documents_acl`、列 `acl_mode` |
| D2 | 是否允许拒绝条目 | 不允许 | 只用「受限 + 白名单」，避免 deny 优先级的组合爆炸 | allow + deny（判定与文案复杂） | 同上 |
| D3 | 判定顺序 | 超管/owner → 非成员 → private → 状态 → ACL | 与 H64 / H66 / H33 的既有优先级一致 | ACL 优先于状态（会削弱 H33） | `services/access.py` |
| D4 | 写权限 | ACL 只授读，写仍走双轨制 | 防止 ACL 成为提权通道（H64 精神） | ACL 可授写（需重做写判定与文案） | 同上 |
| D5 | SQL 与单篇是否共用 | 共用语义，双跑校验 | 避免列表能看、详情 404 的经典裂缝 | 只改单篇（列表泄漏） | `visibility.visible_condition` |
| D6 | 管理权限 | owner 或 editor+creator | 创建者最了解文档受众；viewer 不应授权 | 仅 owner（创建者无法自管）；所有 editor（越权） | ACL 路由 |
| D7 | 分享与 ACL | 不追溯失效已发出 token | capability URL 语义，回收需额外状态机 | ACL 立即拦截分享（破坏既有链接） | 分享路径 |
| D8 | 跨区移动 | 用户主体按目标成员过滤，角色保留 | 用户 id 跨区无意义；角色语义通用 | 全部保留（指向非成员的空授权）；全部清空（丢配置） | `services/move.py` |
| D9 | 审计粒度 | 只记模式 + 主体计数 | H38 精神：不落名单明细 | 记完整名单（事件表泄漏权限信息） | `routers/documents.py` |
| D10 | 副本是否继承 | 不继承，默认 inherit | 避免副本成为绕过 ACL 的分享通道 | 继承（副本可能被无权限者创建） | `services/content.py::duplicate_document` |

## Consequences

- **正向**：单篇文档可收窄到指定人 / 角色；读路径单点改造即全量生效；与 H33/H64/H66 的优先级明确；
  表级 `read_role` 的经验可复用（角色门槛）。
- **负向**：可见性判定从「状态两分支」变成「状态 + 模式 + 白名单」，SQL 与单篇需长期双跑校验；
  ACL 变更会让列表缓存失效，需接入既有 `invalidate_tree` 钩子。
- **风险与缓解**：
  - 分享 token 绕过 ACL（D7）→ 管理面提示「该文档存在 N 个有效分享链接」，由文档管理者决定是否停用；
  - 用户离职后 ACL 残留 → 成员移除时清理该用户在所有文档的 ACL 行（P1 接入成员移除钩子）；
  - 角色主体 `viewer` 语义变化（未来新增角色）→ 角色枚举是封闭集合，新增角色须评审本 ADR。

## 行业对照（可选）

| 维度 | Notion | 语雀 | 本设计 |
|---|---|---|---|
| 页面 / 文档权限 | 继承空间 + 页面级成员 / 访客 | 文档级可见范围（私有 / 团队 / 指定人） | inherit / restricted + 用户 / 角色白名单（D1） |
| 写权限 | 页面权限含编辑级别 | 文档权限含可编辑 | ACL 只授读，写走工作区双轨制（D4） |
| 链接分享 | 可关闭 / 设到期 | 可设密码 / 到期 | 保持现有 token，不追溯（D7） |

来源：Notion Help「Sharing & permissions」、语雀帮助「文档权限」（口径级参考）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 工作区数据面 | `resolve_capabilities` | ACL 在其之上叠加，不替换 | ADR 0161 / H64 |
| 私有工作区 | `visibility=private` | ACL 不放宽 | ADR 0161 / H66 |
| 文档可见性 | 状态三态 | restricted 仅 published 生效，不改 draft 规则 | H33 |
| 分享 | `DocumentShare.token` | 语义不变，风险显式记录 | ADR 0017 |
| 副本 | 0172 | 副本不继承 ACL | ADR 0172 |
| 审计 | 0173 | ACL 变更写事件 | ADR 0173 |
| 批注 | 0175 | 批注继承文档可读性，本 ADR 生效后随之收窄 | ADR 0175 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

## 交接（会话结束更新）

- 当前阶段：ADR 评审前（Proposed）
- 已完成：需求卡 0176、ADR 决策表（无待定）
- 下一步：人工评审 D1..D10；通过后登记 H70/H71 并开 P0（先做判定 + 双跑校验）
- 已知坑：SQL 条件与单篇判定必须逐条对齐；分享 token 不追溯是已知风险，需在管理面提示
- 最近一次全绿：`make flow` @ `e7e4720e`（2026-11-26）
