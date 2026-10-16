# ADR 0003: 视图可见性三档模型与开放范围上限

Status: Accepted — 2026-10-16 决策落定：**D1** 存量 `table` + 新建 `private`（+ 每表至少一个 `table` 档）/ **D2** 私有视图对非创建者完全不可见 / **D3** 保留孤儿视图 / **D4** 开放 `table` 档需表 `EDIT_VIEWS` / **D5** 彻底移除匿名分享
Date: 2026-10-16
Related: `plugins/tables/routers/views.py`、`plugins/tables/services/core/access.py`、`plugins/tables/models.py`、`plugins/documents/services/document_permissions.py`（白名单模式参考）

## 口径（先对齐需求措辞）

需求原文：**「全部视图默认继承数据表的编辑查看权限，新建视图默认本人可见，增加权限开放功能，最大可放宽至数据表范围内」**。

拆成三条可实施约束：

| 需求句 | 本设计的落地 |
|---|---|
| 全部视图默认继承数据表的编辑查看权限 | **存量视图**迁移为 `visibility=table`：可见 = 表的 `READ` 门槛，可改 = 表的 `EDIT_VIEWS` 门槛。迁移零行为变化。 |
| 新建视图默认本人可见 | `CREATE` 的 `visibility` 默认值 = `private`（创建者独占）。 |
| 权限开放，最大放宽至数据表范围内 | 新增 `shared`（指定成员）/ `table`（表内全量）两档放开；**表权限是硬天花板**，视图授权永不放行表外的人与超表的动作。 |

> 口径已定（D1，2026-10-16）：存量视图继承表权限 + 新建默认本人可见，两者并存不矛盾——"继承表权限"是**默认策略作用于存量**，"本人可见"是**新建动作的默认值**。另按飞书实践补一条硬约束：**每张表至少保留一个 `table` 档视图**（默认视图「全部」不可转私有），否则新人进表看到空白。

## Context

现状是**二元**可见性：`DataView.owner_id IS NULL` = 公共视图（表内所有人可见），`owner_id IS NOT NULL` = 个人视图（仅创建者可见）。判定散落在 `views.py` 各处，没有统一的视图级判定函数，也没有"部分共享"这一档。逐条核对现有代码，已确认 8 个问题（含 4 个越权/泄露读取）：

| # | 问题 | 位置 | 性质 |
|---|---|---|---|
| 1 | `rows`/`kanban`/`calendar` 只校验表 `READ` + 视图归属，**不校验视图可见性** | `views.py:348 / 380 / 449` | 越权读取：拿到他人私有视图 id 即可用其筛选规则取数 |
| 2 | `reorder` 要求 `EDIT_VIEWS`，但返回该表**全部**视图 | `views.py:325-342` | 越权读取：泄露他人私有视图的完整配置 |
| 3 | `TableDetailResponse.views` 直接取 `dt.views` 全量 | `tables.py:427-428` | 越权读取：表详情页返回他人私有视图 |
| 4 | `_get_visible_view` 对公共视图要求 `EDIT_VIEWS`，但 `list_views` 对仅 `READ` 用户也返回公共视图 | `views.py:70-79` vs `192-209` | 一致性缺陷：列表能看到、点开 403 |
| 5 | 有 `EDIT_VIEWS` 者可 **PATCH/DELETE 他人私有视图**（仅靠 id） | `views.py:268-313` | 越权写入：列表隐藏但可直接改删 |
| 6 | 默认视图「全部」被写成 `owner_id=表 owner` → 按现语义是**私有视图**，其他成员视图栏为空 | `models.py:258` + `tables.py:197` | 功能性缺陷：新表对非 owner 无任何视图 |
| 7 | `uniq_table_view_name(table_id, name)` 让私有视图参与全局命名 | `models.py:185` | 命名冲突：A 建了私有「我的待办」，B 建同名直接 400，而 B 根本看不到 A 的视图 |
| 8 | 匿名公开分享 `list_rows(..., user=None)` → `hidden_fields` 不生效 | `public.py:71-79` + `records.py:355` | 越权读取：分享链接泄露被隐藏字段（`row_filters` 仍生效） |

同时存在语义错位：`is_default` 是**表级**标记（`_create_view_obj` 会清掉同表其他 default），却允许个人视图持有 → 个人视图可抢占全表落地页。

设计目标（不变量）：

- **I1 天花板**：对任意用户 `u`、任意视图 `v`，`有效读(v,u) ⇒ 表 READ(u)`；`有效改(v,u) ⇒ 表 EDIT_VIEWS(u)`。表外、表权限未覆盖的动作一律不可达。
- **I2 默认收紧**：新建视图默认 `private`，主动开放才扩大范围。
- **I3 存量不变**：迁移后每个用户可见的视图集合与迁移前逐条一致（仅修正 #6）。
- **I4 归属稳定**：`owner_id` 恒为创建者，授权不转移归属，收回授权不掉落他人视图。
- **I5 判定单一**：`list / get / rows / kanban / calendar / export / reorder / detail` 共用同一个判定函数，不再各写各的。
- **I6 无泄露**：不可见视图统一 404。
- **I7 权级单调**：放宽可见性只增加"谁能看"，不提升"谁能改"；改权上限恒为表 `EDIT_VIEWS`。

## Decision

### 1. 枚举与动作

```python
class ViewVisibility(StrEnum):
    TABLE = "table"  # 继承表权限（表内公开）：读=表READ，改=表EDIT_VIEWS
    SHARED = "shared"  # 指定成员：仅名单内可见，可再区分 viewer/editor
    PRIVATE = "private"  # 仅本人（新建默认）


class ViewAction(StrEnum):
    VIEW_READ = "VIEW_READ"  # 查看/使用：列表可见、get、rows/kanban/calendar/export
    VIEW_EDIT = "VIEW_EDIT"  # 改配置：name/filters/sortings/field_options/view_options/order
    VIEW_MANAGE = "VIEW_MANAGE"  # 改可见性、授权名单、删除、设默认
```

### 2. 数据模型

`tables_dataview` 增列（**不重载 `owner_id`**，它是创建者语义）：

```python
visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private", index=True)
scope_key: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0=共享命名空间；user_id=私有命名空间
```

唯一约束由 `(table_id, name)` 改为 `(table_id, scope_key, name)` —— 私有视图只在本人命名空间内唯一（修 #7）。

新表 `tables_dataviewpermission`（与 `documents_permission` 同构，复用项目既有白名单模式）：

| 列 | 类型 | 说明 |
|---|---|---|
| `view_id` | FK `tables_dataview` ON DELETE CASCADE | |
| `subject_type` | varchar(8) | `user`（`subject_id`=user.id）/ `role`（=Role.code 或内置 read/write） |
| `subject_id` | varchar(64) | |
| `role` | varchar(16) | `viewer` / `editor`（**无 owner**：所有者天然全权） |
| `granted_by_id` | FK `accounts_user` ON DELETE SET NULL | 审计入口 |

唯一键 `(view_id, subject_type, subject_id)`。该表**只在 `visibility=shared` 时参与判定**；切回 `private`/`table` 时数据保留但失效（便于来回切换不丢名单），仅当收回全部成员时清理。

`is_default` 语义收紧：**只允许 `visibility=table` 的视图持有**。私有视图的"我的落地页"复用既有用户偏好 `preferences.active_views[table_id]`（`accounts/routers/preferences.py:39`），不再占用表级标记。

### 3. 判定算法（唯一入口）

```python
def resolve_view_action(db, view, user, action) -> bool:
    table = view.table
    # 0. 天花板：看不到表 → 看不到任何视图（I1）
    if not check_action(db, table, user, TableAction.READ):
        return False
    # 1. 创建者对自己的视图：读写管理全通（读已在 0 处保证）
    if view.owner_id is not None and view.owner_id == user.id:
        return True
    # 2. 私有视图对**一切**非创建者不存在（D2：含表 owner / 工作区 OWNER / 超管）
    #    owner_id IS NULL 的 private 视图 = 孤儿（§7-2），对所有人（含超管）返回 False
    if view.visibility == ViewVisibility.PRIVATE:
        return False
    # 3. 管理视角（**仅对非私有档生效**）：超管 / 表 owner / 工作区 OWNER
    if is_table_admin(db, table, user):
        return True
    # 4. 指定共享：看名单
    if view.visibility == ViewVisibility.SHARED:
        grant = view_grant_for(db, view.id, user)  # 直接 user 授权 + role 授权取最大
        if action == ViewAction.VIEW_READ:
            return grant is not None
        if action in (ViewAction.VIEW_EDIT, ViewAction.VIEW_MANAGE):
            return grant == "editor" and check_action(db, table, user, TableAction.EDIT_VIEWS)
        return False
    # 5. 继承表权限
    if action == ViewAction.VIEW_READ:
        return True
    return check_action(db, table, user, TableAction.EDIT_VIEWS)
```

要点：
- **D2 收紧后的顺序意义**：`PRIVATE` 判定必须在"管理视角"**之前**。放在之后会让表 owner / 超管绕过私有语义——这正是缺陷 ⑤（有 `EDIT_VIEWS` 者能改删他人私有视图）的根因。私有档是唯一不给管理员开口子的档位，代价见 §7-2（孤儿处置）。
- **表 `EDIT_VIEWS` 是任何人修改"非自己视图"的硬门槛**（I7）。`shared` 档的 `editor` 授权也过不了这条路——它只是"多给了看"，不构成改权的旁路。

`VIEW_MANAGE` 是**容量**判定，"开放到哪一档"另设目标档位校验（在 API 层，不入布尔函数）：

```python
def require_can_publish_to_table(db, table, user):  # 开放为 table 档（D4）
    if check_action(db, table, user, TableAction.EDIT_VIEWS):
        return
    raise PermissionDeniedError("将视图开放给表内所有人需 EDIT_VIEWS 权限")
```

### 4. 开放范围的强制校验（「最大可放宽至数据表范围内」的落地）

授予名单时逐条校验，任一不过即 422：

```python
def assert_grantee_in_table_scope(db, table, operator, target_user, role) -> None:
    get_member_role(target_user, workspace_of(table), db) or 422("只能授权给本工作区成员")
    check_action(db, table, target_user, TableAction.READ) or 422("该成员无此表查看权限，无法共享视图")
    if role == "editor":
        check_action(db, table, target_user, TableAction.EDIT_VIEWS) or 422("该成员无此表视图编辑权限")
    target_user.id != operator.id or 400("无需给自己授权")
```

生效权 = **min(视图授权, 表权限)**，且是**实时求值**：被授权者若随后被降级（表内 editor → viewer），视图授权自动失效，无需回填清理。

**授权者与选择器**：`shared` 档只要求操作者是**创建者**（D4：仅 `table` 档才需 `EDIT_VIEWS`）。但 `GET /{wid}/tables/{tid}/members` 需 `_require_table_admin`（`members.py:24`），普通 viewer 拿不到成员列表 → 必须新增 `GET /views/{id}/shareable-members`：需 `VIEW_MANAGE`，返回「本工作区成员 ∧ 对该表有 `READ`」的精简列表（id / 昵称 / 有效角色）。只暴露"谁可以被授权"，不暴露任何视图，与 D2 不冲突。

### 5. 创建规则

| 场景 | 判定 |
|---|---|
| 有表 `READ` 即可建视图，默认 `visibility=private` | 普通 viewer 也能有自己的筛选视角 |
| `visibility=shared` | 需 `VIEW_MANAGE`（创建者天然满足）+ 名单校验 |
| `visibility=table` | 额外需表 `EDIT_VIEWS` |
| `is_default=true` | 仅当 `visibility=table`，否则 400 |
| `import` 批量导入 | 与创建同规则，按导入者权限定档（无 `EDIT_VIEWS` → 全部 `private`） |
| **每表至少一个 `table` 档视图**（D1 硬约束） | 默认视图「全部」**不可**转 `private`（`visibility=private` + 该视图为最后一个 `table` 档 → 400「每张表需至少保留一个表内可见视图」）；建表时由 `ensure_default_view` 保证 |

### 6. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /views` | 改用 `VIEW_READ` 过滤；响应加 `visibility / can_edit / can_manage / grantee_count` |
| `POST /views` · `POST /views/import` | body 加 `visibility`（默认 `private`），写 `scope_key`，按 §5 定档 |
| `GET /views/{id}` | 不可见 404；可见但无权改正常返回（附 `can_edit=false`） |
| `PATCH /views/{id}` | 需 `VIEW_EDIT`；`is_default` 校验见 §2 |
| `DELETE /views/{id}` | 需 `VIEW_MANAGE`；default 转移只在 `table` 档候选里挑 |
| `GET /views/{id}/rows` · `/kanban` · `/calendar` | **补 `VIEW_READ` 校验**（修 #1） |
| `GET /views/export` | 已按可见性过滤，改用统一判定 |
| `POST /views/reorder` | 只重排**当前用户可见**子集（可见视图按新序重新落 order，不可见视图 order 不变），响应只含可见视图（修 #2） |
| `POST /views/{id}/visibility` | 新增：`{visibility, members?}` 一次完成开档 + 授权（需 `VIEW_MANAGE`，`table` 档再需 `EDIT_VIEWS`） |
| `GET/PUT/DELETE /views/{id}/members[/{user_id}]` | 新增：名单读写，需 `VIEW_MANAGE` 或本人；PUT role ∈ `viewer/editor` |
| `GET /views/{id}/shareable-members` | 新增：可授权对象列表（见 §4），供前端共享选择器 |
| `GET /{wid}/tables/{tid}` | `views` 按 `VIEW_READ` 过滤（修 #3） |
| `POST/DELETE /views/{id}/share` · `GET /api/v1/public/share/{slug}` | **整条删除**（D5，见 §7-4） |

`_get_visible_view` 保留但语义统一为：**不可见 → 404**（不泄露存在性），**可见不可改 → 403**（由动作判定给出）。D2 生效后，"他人私有视图"对所有人都是 404，因此 PATCH/DELETE 他人私有视图在路由层就返回 404（不再需要单独判"是否为创建者"）。

### 7. 边界与例外

1. **字段隐藏 / 行过滤仍叠加，视图不得放大表权限**：`rows` 等查询继续叠加 `row_filters` + `hidden_fields`。若视图 `filters` 引用了当前用户被隐藏的字段，该条 filter **静默丢弃**并返回 `degraded_filters: [...]`——否则可通过"视图结果差集"反推隐藏字段值（侧信道）。视图配置里引用隐藏字段的 `view_options`（如看板分组字段）同样降级处理。
2. **孤儿视图（D3 已决策：保留）**：私有视图在以下两种情形失去创建者后成为**孤儿**——① 创建者被移出工作区；② 账号被删除。
   - 语义：孤儿 = `visibility='private'` **且** `owner_id IS NULL`（或指向的用户已非本工作区成员）。按 D2，孤儿视图对**所有**身份（含超管、表 owner）判定为不可见 → 不进入任何列表、不参与 `is_default` 转移、不占用他人命名空间（`scope_key` 仍为该用户 id）。
   - 因此**必须**把 `owner_id` 外键由 `ON DELETE CASCADE` 改为 `ON DELETE SET NULL`：否则"删账号 → 连带删视图"会让 D3 的"保留"无从实现，且删除是不可逆的。改 FK 同时消解了"移出工作区"与"删除账号"的语义混淆。
   - 清理出口：既然 D2 关闭了管理员可见通道，孤儿只能由运维清理 → 提供 CLI `cndb views prune-orphans --workspace X [--table T] [--dry-run]`（列出并可选删除孤儿视图，输出归属表 / 名称 / 创建时间 / 最后修改时间），默认 `--dry-run`。
   - 代价明示：孤儿视图会长期占用命名唯一键位（`(table_id, scope_key, name)`），若创建者重新加入工作区则自动恢复可见——这正是"保留"优于"删除"的地方。
3. **表转让**：视图归属不变（视图跟人不跟表）；表 owner 变更后新 owner 自动获得**非私有档**视图的管理视角（D2 下私有档仍不可见）。
4. **匿名公开分享（D5 已决策：彻底移除）**：`is_public` / `public_slug` 属"表范围之外"的暴露面，与需求口径直接冲突，整条删除。移除面（已核对）：

   | 层 | 待删对象 |
   |---|---|
   | 路由 | `plugins/tables/routers/public.py`（整文件，`/api/v1/public/share/{slug}`，含 `LOCAL_MODE` 分支）；`app.py:38` import + `app.py:109` `include_router`；`plugins/tables/routers/__init__.py:17` 的 `noqa` 转发 import |
   | 视图路由 | `views.py:497-539` `POST/DELETE /views/{id}/share`（含 `uuid` import 与 `public_slug` 生成） |
   | 模型 | `models.py:211-212`（`is_public` / `public_slug`）；迁移中先 `UPDATE ... SET is_public=0, public_slug=NULL` 清数据，列可延后一版再删（SQLite 删列需 `batch_alter_table` 重建） |
   | 前端 | `pages/public/PublicSharePage.tsx` + `.test.tsx`、`api/public.ts`、`App.tsx:26/108`（lazy import + `/s/:slug` 路由）、`components/helpContent.tsx:207`（帮助文案） |
   | 测试 | `tests/test_local_mode.py`、`tests/test_spa_fallback.py`、`tests/test_views_api.py`、`tests/test_coverage_tail.py`、`tests/test_migration_missing_model_columns.py` |
   | 文档 | `README.md:16 / 147`、`CHANGELOG.md`（历史条目保留，新增"移除匿名分享"条目） |

   - **缺口填补**：移除后"对外分发"需求改由**登录态分享**承接——链接携带 `view_id`、访问时校验表 `READ` + 视图 `VIEW_READ`，属表范围内，不引入匿名面（前端 `/s/:slug` 可改造为 `/share/view/:id` 的登录校验页，或直接复用现有深链 `?view=`）。
   - **范围边界**：`plugins/documents/routers/public.py`（文档公开分享 `/api/v1/documents/share/{token}`）**本次不动**，但口径已不一致，建议后续同批收敛（另开决策）。
5. **审计**：可见性变更、授权/收回、开放 `table` 档、折叠/展开他人私有视图的读取尝试（可选）→ 复用 `services/core/audit.py`。D5 后不再有"开放公开分享"审计项。
6. **缓存**：`_invalidate_table_list_cache` 不含视图维度，本次无影响；若后续把表列表的 `view_count` 改为"可见计数"需同步失效。
7. **测试补丁**：现有 `test_delete_default_view_transfers_flag` / `test_create_view_set_default_replaces_others` 断言的是"个人视图可持 default"，需按 §2 改写。

### 8. 迁移（五步，可回滚）

```sql
-- Step 1 加列（默认 private，先不改行为）
ALTER TABLE tables_dataview ADD COLUMN visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE tables_dataview ADD COLUMN scope_key  INTEGER      NOT NULL DEFAULT 0;
-- Step 2 存量映射（零行为变化，仅 #6 为有意修正）
UPDATE tables_dataview SET visibility='table',   scope_key=0
  WHERE owner_id IS NULL OR is_default = 1;
UPDATE tables_dataview SET visibility='private', scope_key=owner_id
  WHERE owner_id IS NOT NULL AND is_default = 0;
-- Step 3 换唯一约束（SQLite 需 batch_alter_table 重建表）
DROP INDEX uniq_table_view_name;
CREATE UNIQUE INDEX uniq_table_view_scope_name ON tables_dataview(table_id, scope_key, name);
-- Step 4 D3：owner_id 外键 CASCADE → SET NULL（SQLite 需 batch_alter_table 重建表）
-- Step 5 D5：已于 P1（a4b5c6d7e8f9）提前执行，本迁移不再重复
```

配套代码修正：`ensure_default_view` 落 `visibility='table'`（修 #6）；`tables.py:197` 不再把 `owner_id` 当作可见性来源；每表至少一个 `table` 档的兜底校验（D1）。

## 决策记录（2026-10-16 已定）

行业对照见附录 A。飞书多维表格与 Airtable 对"视图可见性"的抽象高度一致（公共/协同 · 指定 · 个人 三档 + 锁定档），本设计的 `table/shared/private` 与两家一一对应，`VIEW_EDIT`/`VIEW_MANAGE` 与飞书「可新增、删除、修改视图」权限位、Airtable「可改视图配置的等级」对应。

| # | 议题 | **结论** | 依据 | 被否决项（及理由） |
|---|---|---|---|---|
| D1 | 默认档位 | **存量 → `table`（必须）；新建 → `private`**；强制**每表至少一个 `table` 档视图**（默认视图「全部」不可转私有） | 需求指定 private 默认；飞书硬约束"每个数据表至少需要一个公共视图或锁定视图"，否则他人进表看到空白。Airtable 新视图默认 Collaborative | 新建也默认继承 → 失去"免打扰个人视角"这一主用例，与需求相反 |
| D2 | 表管理员能否看到他人私有视图 | **完全不可见**（含表 owner / 工作区 OWNER / 超管，一律 404） | 飞书：个人视图仅创建者可见，且**高级权限对视图可见性的设置明确排除个人视图** | Airtable 式"可见但只读"（管理排障能力更强）→ 与"新建视图默认本人可见"的强隐私语义不符 |
| D3 | 创建者离开（移出工作区 / 删账号）后私有视图 | **保留孤儿视图**：不删除、不转交，归属置空，对所有人不可见；提供 CLI 清理出口 | 数据零损失，创建者重新加入即恢复；避免"人走视图删"的不可逆操作 | ① 转交表 owner（Airtable 有先例，但与 D2 冲突：管理员看不到就别转交，否则是隐式越权）；② 级联删除（有损） |
| D4 | 开放为 `table` 档的门槛 | **需表 `EDIT_VIEWS`**；`shared` 档仅需创建者本人 | 飞书：视图可见性是独立权限位，且"指定视图可见"与"可增删改视图"互斥；Airtable：Editor+ 才能建协同视图 | 仅需创建者（等价于给全表成员 Views 栏写入权）；需表 owner/工作区 OWNER（会阻断成员间正常共享） |
| D5 | 匿名公开分享链接 | **彻底移除**（表与视图两层入口一并删） | 飞书：开高级权限后原"链接分享"全部失效 —— 细粒度权限与公开链接互斥；与"最大放宽至数据表范围内"直接冲突 | ① 默认关闭 + 补字段隐藏（保留能力但仍留匿名面）；② 保留现状（隐藏字段泄露） |

> D2 + D3 的组合后果已在 §7-2 展开：管理员不可见 ⇄ 孤儿不可管理，必须配 CLI 清理出口，且 `owner_id` 外键**必须**改为 `ON DELETE SET NULL`（否则 D3 的"保留"无法实现）。这是本次唯一接受"需要运维手段兜底"的取舍。

## 实施分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 安全修复**（✅ 2026-10-16 已落地） | 修 #1 #2 #3 #4 #5：补 `VIEW_READ` 校验、`reorder` 只返可见、`PATCH/DELETE` 他人视图一律 404、表详情过滤、统一 404/403 口径。**不依赖新模型** | 低 |
| **P1 移除匿名分享**（D5，✅ 2026-10-16 已落地） | 删表/视图两层分享入口 + 前端公开页 + 相关测试/文档；迁移 `a4b5c6d7e8f9` 删除 `is_public`/`public_slug` 两列与唯一索引。顺带消解缺陷 #8 | 低（**破坏性**：`/public/share/{slug}` 与前端 `/s/:slug` 旧链接全部失效，需在发版说明标注） |
| **P2 模型与迁移** | `visibility`（默认 `private`）/ `scope_key` / `tables_dataviewpermission` + 迁移 Step 1–5（含 D3 的 FK 改 SET NULL）+ `is_default` 收紧 + 每表至少一个 `table` 档 + `resolve_view_action` 统一替换 | 中（迁移 / 唯一约束 / FK 重建） |
| **P3 开放功能** | `visibility` / `members` / `shareable-members` 端点 + 前端权限 Drawer（三档单选 + 成员选择器 + viewer/editor）+ 视图标签三态 + CLI `views prune-orphans`（D3 出口） | 中 |

### P0 落地记录（2026-10-16）

新增单一判定入口 `plugins/tables/services/core/view_access.py`：`ViewAction`（`VIEW_READ`/`VIEW_EDIT`/`VIEW_MANAGE`）、`resolve_view_action`、`get_view_or_404`、`visible_view_filter`（查询场景用）、`is_view_visible`（已加载对象用）。二元模型下的判定即 `resolve_view_action` 的 P2 形态降级版 —— 个人视图判定**先于**管理豁免，这就是缺陷 ⑤ 的根因位置；P2 只需把"二元"替换为"三档"，接口层无需再动。

| 文件 | 改动 |
|---|---|
| `services/core/view_access.py` | **新增**（上述入口） |
| `routers/views.py` | 删 `_get_visible_view`，全端点改用 `get_view_or_404` / `visible_view_filter`；`reorder` 只重排可改子集且只返回可见视图；`rows/kanban/calendar` 补 `VIEW_READ`；`is_default` 守卫（创建 400 / 更新 400 / 导入降级）；`share` 两处补 `VIEW_MANAGE`（P1 整体删除前的最小护栏） |
| `routers/tables.py` | `get_table` 的 `views` 按可见性过滤；`view_count`（单表与批量两条路径）改为可见计数 |
| `routers/bulk_export.py` | `?view_id=` 改用 `get_view_or_404`（原仅比对 `table_id`） |
| `accounts/routers/preferences.py` | `active-view` 的 GET/PUT 都要求视图对当前用户可见 |
| `tests/test_view_access_p0.py` | **新增** 26 条回归（含表 owner / 超管对他人个人视图全动作 404 的反向断言） |

**P0 未覆盖（留待后续）**：缺陷 #6（`ensure_default_view` 与 `tables.py` 建表时把默认视图落成 owner 私有 —— 会在 P2 随 `visibility` 列一并修正）、#7（私有视图同名冲突，需换唯一键）、#8（匿名分享忽略 `hidden_fields` —— 已随 P1 整体移除而消失）；工作区级 `view_count` 统计仍为全量（低危，仅暴露数量）。

### P1 落地记录（2026-10-16）

整体移除"表范围之外"的匿名读取通道。移除后**不存在任何绕过表权限的数据读取路径**——"最大可放宽至数据表范围内"成为可验证的闭环。

| 层 | 对象 | 处理 |
|---|---|---|
| 路由 | `plugins/tables/routers/public.py` | **删除整文件**（`GET /api/v1/public/share/{slug}`） |
| 路由注册 | `app.py`（import + `include_router`）、`tables/routers/__init__.py` | 移除 tables 公开路由挂载；**documents 公开路由保持不动**（见下） |
| 视图路由 | `routers/views.py` | 删 `POST/DELETE /{view_id}/share` 两处 + `uuid` 导入 |
| 模型 | `plugins/tables/models.py` | 删 `is_public` / `public_slug` 两列 |
| 迁移 | `alembic/versions/a4b5c6d7e8f9_drop_dataview_public_share.py` | **新增**：先删索引再删列（SQLite 不允许 DROP 带索引的列）；幂等 + 表缺失跳过 + downgrade 可还原结构与索引（slug 值不可还原） |
| 前端 | `pages/public/PublicSharePage.tsx` + `.test.tsx`、`api/public.ts`、`layouts/PublicLayout.tsx` + `.test.tsx` | **删除**（`/public` 整条路由随之消失） |
| 前端接线 | `App.tsx`（路由 + lazy import）、`api/index.ts`（re-export + 挂载说明）、`api/types/files.ts`（`SharedGrid`） | 移除 |
| 前端文案 | `components/helpContent.tsx` | "如何让别人查看数据"改为**加成员 + 授权**（登录态）的口径 |
| 测试 | `test_local_mode`（单机 403 用例）、`test_views_api`（5 例分享用例 + 1 例 404 覆盖）、`test_coverage_tail`（public router 两例）、`test_spa_fallback`（路径样例）、`test_migration_missing_model_columns`（改写为"历史迁移加列 / head 删列"两端语义） | 改写 |
| 文档 | `README.md`（特性清单、API 表）| 更新 |

**迁移链约定**：历史迁移 `f7a8b9c0d1e2` 仍会加这两列（历史迁移不可改写，升级链要能从任意旧版本重放），由新的 head 迁移 `a4b5c6d7e8f9` 负责删除。二者方向相反但语义一致：终态不含这两列。`heal_schema_drift` 只做增量补列，ORM 元数据已不再声明它们，因此不会被自愈层加回来。

**对外分发的缺口填补**：登录态深链承接——链接携带 `view_id`，访问时校验表 `READ` + 视图 `VIEW_READ`，仍在表权限天花板内。P3 做 `shared` 档后，可直接用"指定成员可见"的视图链接替代原先的匿名链接。

**范围边界（未动，需你确认是否收敛）**：`plugins/documents/routers/public.py`（文档公开分享 `/api/v1/documents/share/{token}`）本次未动。它同样是"绕过表/工作区权限的匿名读取面"，与本次口径不一致——但文档不属于"数据表范围"，且不在 ADR 0003 的视图权限域内，建议另开决策同批收敛。

## 测试清单（新增/改写）

判定层：表外用户对任意视图全动作 False；`private` 视图对他人 404；`shared` 名单内 viewer 可读不可改；名单内 editor 在表 `EDIT_VIEWS` 被撤销后编辑失效；`table` 档仅 `READ` 用户可读不可改。
**D2 回归（关键）**：表 owner / 工作区 OWNER / 超管 对他人私有视图 `GET` / `PATCH` / `DELETE` / `rows` 一律 404（对应缺陷 ⑤ 的反向断言）。
创建层：默认 `private`；`visibility=table` 无 `EDIT_VIEWS` → 403；`is_default` + `private` → 400；私有视图同名互不冲突（两个用户各建「我的待办」均成功）；**最后一个 `table` 档视图转 `private` → 400**（D1）。
接口层（P0 回归）：他人私有视图 `rows/kanban/calendar` → 404；`reorder` 响应不含他人视图；表详情 `views` 不含他人视图。
共享层：授权给无表 `READ` 的表内成员 → 422；`shared → private` 切换后名单失效但保数据；`private → table` 无 `EDIT_VIEWS` → 403；`shareable-members` 对普通 viewer 可用且不含无表 `READ` 成员。
**D3 孤儿**：删账号后视图仍在且 `owner_id IS NULL`；孤儿对超管同样 404；`prune-orphans --dry-run` 只列不删；创建者重新加入工作区后视图恢复可见。
**D5 移除**：`GET /api/v1/public/share/{slug}` → 404（路由不存在）；`POST /views/{id}/share` → 404；`PublicSharePage` 相关前端用例删除而非跳过。
降级层：视图 `filters` 引用用户被隐藏字段 → 返回 `degraded_filters` 且不泄露值。

## Consequences

- **正向**：可见性从二元升为三档且**有上限**，"开放"不再能顺手越权；8 个缺陷（其中 3 个越权读取、1 个匿名泄露）分两期收敛；私有视图在 D2 下成为真正的隐私档（对管理员也不可见）；D5 移除后产品边界变得干净——**不存在任何绕过表权限的读取路径**，"最大可放宽至数据表范围内"成为可验证的闭环；判定收敛到单一函数后，新增视图类型（画廊/看板/图表等 7 种）不必再各写权限分支；命名空间隔离让私有视图不再互相干扰。
- **负向**：
  1. 多一张表与一次迁移（SQLite 需两次重建表：换唯一约束 + 改 FK）。
  2. `resolve_view_action` 成为所有视图接口的必经路径，批量场景（表详情、列表）需按 `TableAccessPreload` 模式扩展 view 维度预取，否则 N+1。
  3. **D2 取消了管理员通道**，孤儿视图只能靠 CLI 兜底 → 运维手册需补 `cndb views prune-orphans` 一条；同时"创建者离职后其视角不可被接管"会成为可预期的用户反馈。
  4. **D3 孤儿视图长期占用命名唯一键位**（`(table_id, scope_key, name)`），同名重建需先清理。
  5. **D5 是破坏性变更**：既有 `/s/{slug}` 公开链接全部失效，需发版说明 + 引导改用登录态深链。
  6. 前端需从"我的/公共"二元标签改为三态展示，并处理"表内所有人"档位的权限门控置灰说明。
- **已否决的替代方案**：① 继续用 `owner_id IS NULL` 编码共享（无法承载"指定成员"档，也无法区分创建者与可见性）；② 视图级独立 ACL 不设表天花板（会出现"视图可见但表不可见"的悬空权限）；③ 只做前端过滤（后端接口仍按 id 可枚举，等于没做）；④ 让表管理员可见他人私有视图（与"默认本人可见"的隐私承诺冲突，且需要额外的"只读"约束才能防误改）；⑤ 保留匿名分享但补字段隐藏（仍留一个绕过登录的读取面，与需求口径不符）。

## 附录 A：行业最佳实践对照（2026-10 核对）

| 维度 | 飞书多维表格 | Airtable | 本设计 |
|---|---|---|---|
| 档位划分 | 公共视图 / 锁定视图 / 个人视图 | Collaborative / Locked / Personal | `table` / `shared` / `private`（+ 可选锁定档） |
| 新建默认档 | **公共视图** | **Collaborative** | `private`（需求指定，比两家更保守） |
| 个人视图可见性 | **仅创建者可见**，其他协作者无法查看 | 默认从他人侧边栏隐藏，但**可 toggle 显示**（只读） | **飞书式**：对非创建者（含管理员）一律 404（D2） |
| 个人视图可改性 | 仅创建者可设为个人视图，他人无法修改 | 仅 owner 可改配置 | 仅创建者，管理员亦不可改（D2） |
| 硬约束 | **每表至少一个公共/锁定视图** | —— | 采纳（D1） |
| 改视图配置的权限位 | 独立权限位「可新增、删除、修改视图」；选了"指定视图可见"就不能再勾它 | Editor+ 可建协同视图；Commenter 只能管自己的个人视图 | `VIEW_EDIT` / `VIEW_MANAGE`，开放 `table` 档再需表 `EDIT_VIEWS`（D4） |
| 细粒度权限与公开链接 | 开启高级权限后，原"链接分享"**全部失效** | 分享视图链接为显式功能，受权限位约束 | **彻底移除匿名分享**，改登录态深链（D5） |
| 创建者离职/转交 | 未提供视图转交 | 支持把个人视图 **reassign 给新 owner** | **保留孤儿 + CLI 清理**（D3）；与 D2 自洽（管理员不可见 ⇏ 可转交） |
| 共识 | 「视图不是安全边界」：视图只决定"看哪个视角"，数据行/字段权限由表级 `row_filters` / `hidden_fields` 裁决 | 同 | 已落为不变量 I1 / I7 |

来源：飞书帮助中心《关于多维表格保护视图的说明》《使用多维表格高级权限》；Airtable support《Personal views》《Getting started with views》、Airtable 官方 onboarding 指南。

### 决策 → 代码落点

| 决策 | 落地位置 | 已选值 |
|---|---|---|
| D1 | `DataView.visibility` 列默认值 + `ensure_default_view` + 转私有校验 | `private`（新建）/ `table`（存量与默认视图）；「每表至少一个 `table` 档」校验 |
| D2 | `resolve_view_action` 中 `PRIVATE` 判定置于管理豁免**之前**（无开关，硬编码） | 非创建者一律 404 |
| D3 | `owner_id` 外键 CASCADE → **SET NULL**；`cndb views prune-orphans` CLI | 保留孤儿 + CLI 清理 |
| D4 | `shared` 档仅需创建者；`table` 档调用 `require_can_publish_to_table()` | 开 `table` 档需表 `EDIT_VIEWS`（不设 `view_share_policy` 开关） |
| D5 | 删除 `routers/public.py`、`views.py` 分享端点、模型两列、前端公开页 | 彻底移除 |
