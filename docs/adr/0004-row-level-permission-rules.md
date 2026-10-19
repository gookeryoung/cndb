# ADR 0004: 行级权限规则（特定筛选规则数据行的查看 / 编辑控制）

Status: Proposed（待评审）
Date: 2026-10-19
Related: `plugins/tables/models.py`、`plugins/tables/services/core/access.py`、`plugins/tables/services/core/records.py`、`plugins/tables/routers/permissions.py`、`plugins/tables/routers/records.py`、`plugins/change_requests/services.py`（双轨制）；上游视图可见性三档模型取自 ADR 0003（该 ADR 文档已随视图权限调整移除，commit 30790638）
需求卡片: 无卡片（需求直接立项，原文见「口径」）

## 口径（需求 → 设计落点）

需求原文：**「更细颗粒度的数据表权限管理。包括特定筛选规则相关的数据行的编辑和查看权限控制。」**（本 ADR 无需求卡片，原文与 C 编号就地维护）

拆成三条可实施约束（C1..C3）：

| # | 需求句（原文片段） | 本设计的落地 |
|---|---|---|
| C1 | 更细颗粒度 | 授权对象从「工作区角色 / 表级成员档」下沉到**指定成员**与**表级成员档（read/write）**；授权粒度从「整表」下沉到「**行**」。 |
| C2 | 特定筛选规则相关的数据行 | 每条规则 = 一组筛选条件（复用现有 `{field_name, op, value}` + `AND/OR` 模型），**命中该条件的行**才受此规则约束。 |
| C3 | 编辑和查看权限控制 | 每条规则带 **action ∈ {view, edit}**：`view` 只给可查看，`edit` 给可编辑（隐含可查看），两者分别收放。 |

三项立项决策的结论只在「决策记录」写一次：授权对象 = D1，与现网关系 = D7，编辑受限行的处理 = D8。

## Context

现状逐条核对（以代码为准；本 ADR 无需求卡片，C 编号见「口径」）：

| # | 现状 | 位置 | 影响 | 对应约束 |
|---|---|---|---|---|
| 1 | `row_filters` 是**单一表级**过滤，**无主体维度** | `models.py:435`、`access.py:272-291` | 只能"给全表所有人同一套行过滤"，无法"某些行只给某些人"。 | C1 / C2 |
| 2 | 读与写**共用同一过滤** | `records.py:390`（list）/ `491` / `527` / `549` / `574` / `698`（update）/ `740`（delete）/ `897` | "能看但不能改"的行状态**不可表达**（要么全可见可改，要么不可见）。 | C3 |
| 3 | 字段隐藏 `hidden_fields` 只按**工作区角色**分桶 | `access.py:294-309` | 无法按个人 / 按行差异化隐藏字段。 | C1 |
| 4 | 权限主体只有两级：工作区角色 + `TableMember`（read/write） | `models.py:448-466`、`access.py:53-78` | 缺少"指定成员级"的行授权。 | C1 |
| 5 | 前端**没有任何 `row_filters` 编辑 UI** | `PermissionEditor.tsx`（仅成员 + 隐藏字段） | 现有行过滤能力实际是"隐形后端能力"，需求侧无法自助配置。 | C2 |
| 6 | 视图可见性三档已解决，且已定"视图不是安全边界" | `docs/adr/0003` | 行 / 字段边界本就属表级裁决 —— 本 ADR 正是补齐这块"行边界"。 | — |

**核心缺陷（需求要补的）**：`row_filters` 既无主体维度、又读写不分、且无 UI。需求要求的"特定筛选规则相关的数据行 → 给特定对象 → 分查看/编辑"三件事，无一能在现模型上表达。

设计目标（不变量）：

- **I1 天花板**：行级授权**永不放行**"表外的人"。任意用户 `u`，`有效行读(u) ⇒ 表 READ(u)`。
- **I2 默认收紧**：未命中任何规则的成员，只在其"默认档"范围内可见。
- **I3 存量不变**：未配置任何行规则的存量表，行为与今天**逐条一致**（仅 `row_filters` 生效，`row_filters_bypass` 口径不变）。
- **I4 读 ⊇ 写**：能编辑的行必然可查看（`edit` 规则隐含可查看）。
- **I5 判定单一**：记录读写 / 审计 / 导出 / 数据分析共用**同一个行范围判定入口**，不再各写各的。
- **I6 无泄露**：读范围外的行对调用者**不可见（列表不含）**；越界的单行读写按"不存在"处理，不做存在性提示。

## Decision

### 1. 主体（subject）与动作（action）

```python
class RowSubject(StrEnum):
    USER = "user"                # 指定成员：subject_id = accounts_user.id
    MEMBER_ROLE = "member_role"  # 表级成员档：subject_id ∈ {"read", "write"}


class RowAction(StrEnum):
    VIEW = "view"  # 命中行对该主体可查看
    EDIT = "edit"  # 命中行对该主体可编辑（隐含可查看，I4）
```

`MEMBER_ROLE` 的匹配口径 = 用户在该表的**有效档位**（D5）：

- `write`：`check_action(db, table, user, TableAction.EDIT_RECORDS)` 为真；
- `read`：通过 `TableAction.READ`、但不通过 `EDIT_RECORDS`。

> 不采用「仅匹配显式 `TableMember.role`」—— 绝大多数成员是靠**工作区角色**获权的、根本没有 `TableMember` 行，用后者会让规则对他们**永不命中**。

### 2. 数据模型

新表 `tables_rowpermission`（与 `TablePermission` 同域、独立生命周期）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | PK | |
| `table_id` | FK `tables_datatable` ON DELETE CASCADE, index | |
| `subject_type` | varchar(16) | `user` / `member_role` |
| `subject_id` | varchar(64) | user id 字符串，或 `read`/`write` |
| `action` | varchar(8) | `view` / `edit` |
| `filters` | JSON | 条件列表 `[{field_name, op, value}, ...]`（与 `row_filters`、视图 `filters` 同构） |
| `filter_type` | varchar(3) | `AND` / `OR`（与 `row_filter_type` 同构） |
| `granted_by_id` | FK `accounts_user` ON DELETE SET NULL | 审计入口 |
| `created_at` / `updated_at` | | `TimestampMixin` |

唯一键 `uniq_rowpermission_subject_action`：`(table_id, subject_type, subject_id, action)` —— **每个主体、每个动作至多一条规则**（D6）。多段行范围用 `filter_type=OR` 合进一条的 `filters`，不引入"多条规则 + 优先级排序"的冲突消解复杂度。

`row_filters`（默认档）**原样保留**，不迁移、不改语义（I3）。

### 3. 判定算法（唯一入口）

新增 `plugins/tables/services/core/row_access.py`：

```python
def applicable_row_rules(db, table, user) -> list[RowPermission]:
    """返回对该用户命中的规则：subject=user:me 或 subject=member_role:<有效档位>（D5）"""


def row_read_scope_where(db, table, sa_table, user) -> ColumnElement | None:
    """读范围 = 默认档(row_filters) ∪ view规则命中 ∪ edit规则命中；管理员豁免返回 None（全表）"""


def row_edit_scope_where(db, table, sa_table, user) -> ColumnElement | None:
    """写范围 = [base_edit 时: 默认档] ∪ edit规则命中；管理员豁免返回 None"""


def can_edit_row(db, table, row_values: dict, user) -> bool: ...
def can_view_row(db, table, row_values: dict, user) -> bool: ...
```

判定顺序（合成 SQL 条件，供 `list_rows` / `update_row` / `delete_row` / 审计 / 导出复用）：

```
0. 管理员豁免：row_filters_bypass(owner / 工作区 OWNER / 超管) → 读=全部、写=全部（D3，沿用现网口径）
1. 默认档 default = compile_filters(table, sa_table, row_filters, row_filter_type)   （空 → 无默认限制）
2. 命中规则 view_or = compile_filters(..., 所有 view 规则的 filters, OR)
        edit_or = compile_filters(..., 所有 edit 规则的 filters, OR)
3. 读范围 = OR(default, view_or, edit_or)
   写范围 = OR( default if base_edit else ∅ , edit_or )      # base_edit = check_action(EDIT_RECORDS)
```

要点：

- **默认档行"能看即可改"的前提是有 `EDIT_RECORDS`**（`base_edit`）；没有表编辑权的人，默认档行仍只能查看，不能改（避免 viewer 误得写权）。
- **`edit` 规则的写权独立于表 `EDIT_RECORDS`**（D2）：这是需求"特定行给某人可编辑"的主用例；否则行级 edit 只能"收"不能"放"。
- **读 ⊇ 写**（I4）：`edit_or` 同时并入读范围。任一读/写范围内的行，跨越"行不可见"的情况不会出现。
- 规则 filters 若引用了**当前用户被隐藏的字段** → 该条条件**静默丢弃**并置 `degraded_filters`（侧信道保护，与 ADR 0003 §7-1 同源）。

### 4. 写路径分派（与双轨制 / 修改申请衔接）

现状 `_dispatch_or_403`（`routers/records.py:48-62`）= `can_write_directly`（工作区级） **AND** `check_action(EDIT_RECORDS)`。新口径下沉到"按行"：

| 场景 | 判定 |
|---|---|
| `update` / `delete` 目标行**在写范围内** | 直编（直接落库） |
| 目标行**可查看但不在写范围内** | 生成 `ChangeRequest`，返回 **202**（可看不可改 → 提议修改，用户已选） |
| 目标行**在读范围外** | **404**（不泄露存在性，I6） |
| `create`（新行） | 无行身份 → 沿用表级 `EDIT_RECORDS` + 双轨制**不变**（D4） |
| 批量 update / delete | 沿用表级 `EDIT_RECORDS` 门槛（**批量端点不为"仅有行级 edit 权"的主体开旁路**；此类主体走单行端点）。见 §7-6 |
| `ChangeRequest` 合并落库 | 由 owner/editor 审核合并，合并动作**不受行规则约束**（审阅者的写权来自表级 `EDIT_RECORDS` / 管理员身份），但其"能否看到该申请"仍按读范围过滤 |

### 5. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/row-permissions` | **新增**：列出规则（需 `EDIT_SCHEMA`，与现有 `/permissions` PUT 同级——规则配置属敏感信息，普通成员不应读到明文，只按规则效果隐式生效） |
| `POST /{wid}/tables/{tid}/row-permissions` | **新增**：创建规则（校验见 §6），写 `AuditLog` |
| `PATCH/DELETE /{wid}/tables/{tid}/row-permissions/{rule_id}` | **新增**：改 / 删（需 `EDIT_SCHEMA`）。 |
| `GET /{wid}/tables/{tid}/row-permissions/subjects` | **新增**：可授权对象列表（工作区成员 ∧ 对该表有 `READ`；表级成员档固定 `read`/`write`），供前端选择器（参考 ADR 0003 `shareable-members`） |
| `POST /{wid}/tables/{tid}/row-permissions/preview` | **新增**（可选）：规则命中行 dry-run 预览（返回命中行数 + 样例若干，复用 `compile_filters`） |
| `GET/POST/ PATCH/DELETE /{wid}/tables/{tid}/records**` | 读写按 §4 分派；**响应体不新增规则明文**（除既有 202 载荷） |
| `GET /{wid}/tables/{tid}/audit` | 行裁剪改用 `row_read_scope_where` 统一入口（`routers/audit.py:89-103`） |
| `GET /{wid}/tables/{tid}/export`（含 `bulk_export`） | 行过滤改用 `row_read_scope_where`（导出不得越过读范围） |
| 分析（analytics）/ 智能推荐 | 取数复用 `row_read_scope_where`（延续"取数复用行级权限与字段隐藏"的既有口径） |

### 6. 授权校验（授予时的强制约束）

```python
def assert_row_rule_valid(db, table, operator, subject_type, subject_id, action) -> None:
    # user 型：必须是本工作区成员 且 对该表有 READ
    # member_role 型：subject_id ∈ {"read", "write"}
    # 表所有者天然全权，无需/不允许给自己配规则（与 ADR 0003 §4 一致：target != operator）
```

生效权 = **min(行规则, 表 READ)**，实时求值：被授权者随后失去表 `READ`（移出工作区 / 降级到不可读），其所有行规则**自动失效**，无需回填清理。

### 7. 边界与例外

1. **字段隐藏仍叠加、不改动**：`hidden_fields` 继续按工作区角色裁决；行规则只裁决"哪些行"，不裁决"行内哪些字段"。规则 filters 引用当前用户被隐藏的字段 → 条件静默丢弃 + `degraded_filters`。
2. **本次只做行级、不做行内字段级**：需求落在"数据行"的查看/编辑；"某行某字段可编辑"属字段级细粒度，另开决策。
3. **与视图配置无耦合**：视图 `filters` 决定"看哪个视角"，行规则决定"能看哪些行"；`list_rows` 里两者**叠加**（视图业务过滤 AND 行权限范围）。**视图不得放大行权限**（延续 ADR 0003 共识"视图不是安全边界"）。
4. **管理员豁免保留（D3）**：owner / 工作区 OWNER / 超管对行规则豁免，与 `row_filters_bypass` 一致（I3）。副作用：管理员始终看到全表——这是现网既有口径，本 ADR 不改变。
5. **默认档与规则的读侧关系**：因采用**并集**，规则的"读侧开放"只在**默认档已收紧**（`row_filters` 非空）时才有意义；若默认档为空（人人可见全表），新规则的**读侧**不产生额外效果，但其**写侧**（`edit`）独立有效。
6. **批量的边界**：只有 `edit` 行规则、无表 `EDIT_RECORDS` 的主体，通过单行端点直编命中行；批量 update/delete 仍要求表 `EDIT_RECORDS`（避免在批量里做"逐行分轨"，语义与实现都更简单）。
7. **缓存**：记录列表缓存 TTL 5s + 事件失效（`records.py:42`）。规则增删改后必须失效相关表的记录缓存（复用 `_invalidate_table_list_cache` + 记录缓存清理），否则收紧后旧缓存会短暂泄漏。
8. **审计**：规则增删改写 `tables_auditlog`（新增 action `row_rule_create/update/delete`，detail 记录主体 / 动作 / 条件摘要）。
9. **备份 / 恢复**：`workspaces/services/backup_io.py` 需纳入 `tables_rowpermission`（导出 + 导入 + 旧版备份兼容：缺该表时按"无规则"还原）。
10. **主体失效（孤儿规则）**：`subject_id` 为 varchar、非 FK（因可能是 `read`/`write` 常量）。判定时**实时校验**主体仍是本工作区成员（user 型）→ 失效规则不命中，**自动失效、无需回填**；规则行保留以便成员回归工作区后自动恢复（与 ADR 0003 D3 的"保留"取向一致）。

### 8. 迁移

单条 alembic 迁移，**只建新表，不动存量**：

```python
# 新增 tables_rowpermission + 唯一索引 uniq_rowpermission_subject_action + 外键两处
# 幂等：表/索引按名缺失才建；形状守卫与 ADR 0003 迁移同款
# downgrade：drop 表（不改存量 TablePermission）
```

存量表**零数据迁移**（`row_filters` 原地保留，I3）：升级后未配置任何行规则的库，行为与升级前逐条一致。

### 9. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 权限编辑器 | `pages/grid/permissions/PermissionEditor.tsx` | 新增「行级权限」区：规则列表（主体 / 动作 / 条件摘要 / 命中行数）+ 规则编辑器（主体选择：指定成员 / 表级成员档；动作：可查看 / 可编辑；条件构建器） |
| 条件构建器 | 复用视图过滤条件模型（`ColumnFilterDropdown` / `filterValueRules`） | 抽出共享"筛选条件编辑器"组件（当前仅 `ViewConfigDialog` 内有），行规则与视图过滤共用 |
| API | `api/permissions.ts` / `api/types/*` | `listRowRules` / `createRowRule` / `updateRowRule` / `deleteRowRule` / `rowRuleSubjects` / `previewRowRule` |
| 门控 | 后端下发 `can_edit_schema`（或复用现有表权限位） | 无权限时整区置灰 + 说明 |
| 只读行渲染 | `gridTableSection.tsx` / `GridCell`（可选） | 行若不在写范围，编辑入口置灰（体验增强；后端 §4 兜底） |

### 10. 测试清单

**判定层（单测）**

- 无任何行规则时行为 == 今天（`row_filters` 生效、其余全可见，I3）；
- `user` + `view`：指定成员额外可见命中行，其他成员仍不可见；
- `user` + `edit`：命中行可直编；**可查看但未命中**的行 → 编辑返回 202 修改申请；
- `member_role` 按**有效档位**匹配（工作区 `editor` 命中 `write`，`viewer` 命中 `read`，无需 `TableMember` 行）；
- 读 ⊇ 写（I4）：`edit` 规则命中行同时可读；
- 管理员豁免（表 owner / 工作区 OWNER / 超管）看到全表且不受规则限制（D3）；
- **越界行** update / delete → 404，且**不落库**；
- 规则 filters 引用当前用户隐藏字段 → 丢弃该条件 + `degraded_filters` 且不泄露值；
- **表外用户（无表 `READ`）** 配了任何行规则仍全不可读（I1）。

**接口层**

- `row-permissions` 增删改查需 `EDIT_SCHEMA`，普通成员读列表 → 403；
- `subjects` 选择器不含"对该表无 `READ`"的成员；
- 审计 / 导出 / 分析的行范围与记录读取一致（同一 `row_read_scope_where`）；
- 规则变更后记录列表缓存失效（收紧后无旧数据泄漏窗口）。

**备份 / 迁移**

- 备份导出含 `tables_rowpermission`，往返一致；旧版备份（无该表）还原为"无规则"；
- 迁移幂等 + downgrade 可还原。

**e2e（前端）**

- 规则编辑器增删改；"可看不可改"行在前端渲染为只读并提示"已提交修改申请"。

### 11. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 模型 + 判定入口** | `tables_rowpermission` 模型 + 迁移 + `row_access.py`（`row_read_scope_where` / `applicable_row_rules`）+ **读路径**接入（`list_rows` / 审计 / 导出 / 分析）。**不开放写入端点**，仅判定层就位 | 低 |
| **P1 写路径接入** | `row_edit_scope_where` + `can_edit_row`；`update`/`delete` 单行分派（直编 / 202 / 404）；批量边界按 §7-6 | 中（触及双轨制分派） |
| **P2 规则写入面 + 前端** | 规则 CRUD 端点 + `subjects` + `preview` + 前端「行级权限」区 + 条件构建器抽取 + `AuditLog` + 备份纳入 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 授权对象粒度 | **`user`（指定成员）+ `member_role`（表级 read/write）** | 需求方确认：既要"特定行给特定人"，也要"按编辑者/查看者两档批量" | ① 仅按工作区角色（粒度不够，无法针对个人）；② 自定义分组（需额外组模型 + 维护 UI，成本最高） | `tables_rowpermission.subject_type` 枚举 + 前端主体选择器 |
| D2 | `edit` 规则能否独立于表 `EDIT_RECORDS` 授予写权 | **能**（行级写 ACL 独立于表门槛） | 需求"细颗粒度"的主用例就是"把某些行开放给某人可编辑"，若仍以表 `EDIT_RECORDS` 为天花板，则行级 edit 只能"收"不能"放" | 以表 `EDIT_RECORDS` 为天花板（行级 edit 只作收紧，失去主用例） | `row_access.row_edit_scope_where`（`base_edit` 与 `edit_or` 并列）+ `records._dispatch_or_403` 按行分派 |
| D3 | 管理员是否受行规则约束 | **豁免**（沿用 `row_filters_bypass`） | I3 存量不变 + 现网既有口径；owner 是表的兜底责任人 | 管理员受限（改变现网行为，且 owner 看不到全表将无法兜底排障） | `row_access` 首行复用 `row_filters_bypass` |
| D4 | 新建行是否受行规则约束 | **不受**，沿用表级 `EDIT_RECORDS` + 双轨制 | 新行尚无行身份，无法参与"按行判定" | 新建即自动命中默认档（语义含混） | `create` 路径不改判定 |
| D5 | `member_role` 匹配口径 | **按用户有效档位**（`EDIT_RECORDS` 通过=write，否则 READ=read） | 覆盖绝大多数靠工作区角色获权、无 `TableMember` 行的成员 | 仅匹配显式 `TableMember.role`（对多数成员永不命中） | `row_access.applicable_row_rules` 用 `check_action(EDIT_RECORDS)` 定档 |
| D6 | 每主体每动作规则条数 | **至多一条**（唯一键 `(table, subject_type, subject_id, action)`），多段范围用 `filter_type=OR` | 避免"多条规则 + 优先级"的冲突消解复杂度 | 多条规则 + priority 排序（冲突语义复杂，收益低） | 唯一键 `uniq_rowpermission_subject_action` |
| D7 | 与现有 `row_filters` 的关系 | **扩展并存**：`row_filters` 作为默认档，新规则并集叠加 | 需求方确认；存量零迁移（I3） | ① 替换进规则表（需迁移且要保证逐条不变）；② 仅叠加收紧（无法表达"把默认隐藏的行开放给某人"） | `TablePermission.row_filters` 原地保留 + `row_access` 并集合成 |
| D8 | 可查看但不可编辑的行如何处理 | **转为「修改申请」待审（202）**，复用既有双轨制 | 需求方确认；不为行级写权另造审批链 | 直接 403（用户已选 202）/ 静默忽略（用户无反馈） | `records._dispatch_or_403` + `plugins/change_requests/services.py` |
| D9 | 整体方案选型（为何新建表 + 单一入口） | **新增独立 `tables_rowpermission` + `row_access.py` 单一判定入口**；字段级另开决策 | 需求只覆盖数据行的查看 / 编辑；判定收敛后读写 / 审计 / 导出 / 分析复用同一入口 | ① 只做前端过滤（后端可按 id 枚举，等于没做）；② 复用 `row_filters` 单表存所有规则（读不出主体与动作，且与默认档混同）；③ 引入通用 ACL 不设表天花板（会出现"行可见但表不可见"的悬空权限）；④ 行级规则同时做字段级（本次范围外） | `tables_rowpermission` + `plugins/tables/services/core/row_access.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：行级权限从"单一表级、读写不分、无 UI"升为"**按主体（指定成员 / 成员档）× 按动作（查看 / 编辑）× 按筛选条件**"的可配置模型；"可看不可改"的行状态首次可表达，并**复用既有修改申请**衔接协作；判定收敛到单一入口后，读写 / 审计 / 导出 / 分析不必各写一套；`row_filters` 原地保留，存量零迁移、零行为变化。
- **负向**：
  1. 多一张表与一次迁移（建表，SQLite 无重建风险）。
  2. 判定从"一次 `compile_filters`"变为"默认档 ∪ 命中规则"，`list_rows` 的 WHERE 复杂度上升；批量场景需按 `TableAccessPreload` 模式预取规则，否则 N+1。
  3. 写路径从"表级布尔"变为"按行三态（直编 / 202 / 404）"，双轨制分派逻辑变复杂，需单点分派与严格回归。
  4. `member_role` 主体与工作区角色是"间接映射"（按有效档位），文档与 UI 需明确说明，避免"给 editor 档配了规则但某人靠工作区角色获权"这类困惑。
  5. 管理员豁免（D3）意味着行规则**不是**"连管理员也挡"的合规级隔离；如需该语义另开决策。

被否决的替代方案见「决策记录」D9（方案级）与各行「被否决项」，此处不重复。

## 行业对照（2026-10 核对）

| 维度 | 飞书多维表格（高级权限·记录权限） | Airtable（记录级权限，企业版） | 本设计 |
|---|---|---|---|
| 记录权限粒度 | 按**角色 / 协作者**给"可查看 / 可编辑"的**记录**权限，条件为筛选规则 | 按**协作者 / 角色**限定可见记录，条件为筛选 | 按**指定成员 / 表级成员档**，条件为筛选（D1） |
| 条件的自由文本/公式 | 支持 | 支持 | 复用现有 `{field_name, op, value}` + AND/OR（先不做公式） |
| 查看与编辑分离 | 支持（可查看 / 可编辑两档） | 支持 | `view` / `edit` 两档（§1） |
| 管理员是否受限 | 高级权限对管理员亦可约束 | 具备者不受限 | **豁免**（D3，沿用现网口径） |
| 与"提议修改"衔接 | 无（无此机制） | 无 | **复用修改申请**（202，用户已选） |

来源：飞书帮助中心《使用多维表格高级权限（记录权限）》；Airtable support《Record-level permissions》。

## 与既有 ADR 的关系

两条 ADR 处理**两条正交的细粒度轴**，互不越界：

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| **视图可见性**（看哪个视角 / 谁能用这个视角） | `DataView.visibility` + `tables_dataviewpermission` | 谁能看到并使用某个视图配置 | ADR 0003 |
| **数据行可见性**（能看 / 能改哪些行） | `TablePermission.row_filters` + `tables_rowpermission`（本 ADR） | 谁能看、谁能改哪些数据行 | ADR 0004 |

共识不变：**视图不是安全边界**。视图不得放大行权限；行/字段边界由表级裁决。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 模型 + 判定入口 | 已落地 | `src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/alembic/versions/c8d9e0f1a2b3_add_rowpermission.py` | `tests/test_row_access_rules.py` | `1ae26783` |
| P1 写路径接入 | 已落地 | `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/row_access.py` | `tests/test_row_write_dispatch.py` | `d8560007` |
| P2 规则写入面 + 前端 | 已落地 | `src/cndb/plugins/tables/routers/row_permissions.py`、`src/cndb/plugins/tables/schemas/models.py`、`frontend/src/pages/grid/permissions/PermissionEditor.tsx`、`frontend/src/api/tables.ts`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/tables/services/core/audit.py` | `tests/test_row_permissions_api.py`、`tests/test_row_level_permissions_e2e.py`、`frontend/src/pages/grid/permissions/PermissionEditor.test.tsx` | `cde4130e` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地；ADR 仍为 `Proposed`，等待人工评审回填 `Accepted`
- 已完成：P0（模型 + 读路径）、P1（写路径分派）、P2（CRUD / subjects / preview / 前端 / 审计 / 备份）
- 下一步：评审 D1..D9 与测试清单；确认是否补行级权限的 Playwright 专项用例；评审通过后更新 `Status`
- 已知坑：`member_role` 按有效档位匹配（D5）；管理员豁免（D3）；读 ⊇ 写（I4）；批量端点不开放行级旁路（§7-6）；规则增删改后必须清记录缓存（§7-7）；规则 filters 引用隐藏字段时静默丢弃
- 最近一次全绿：`make flow` 通过（2026-10-20，本地工作区）
