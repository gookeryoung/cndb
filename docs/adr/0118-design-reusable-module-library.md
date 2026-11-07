# ADR 0118: 结构设计 DSL 可复用模块库与跨工作区引用

Status: Accepted
Date: 2026-11-07
Related: `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/design/services/files.py`、`src/cndb/plugins/design/services/keys.py`、`src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/dsl/limits.py`、`src/cndb/plugins/design/services/dsl/nodes.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/src/api/design.ts`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/designLang.ts`；上游 ADR 0079 / 0083 / 0084 / 0086 / 0103 / 0109 / 0075 / 0080
需求卡片: `docs/requirements/0118-design-reusable-module-library.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。约束沿用 C1..C11。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 可复用模块管理 | 新增全局实体「复用模块」（`design_library_module`）与不可变「模块版本」（`design_library_version`）；发布产物含稳定 `module_key`、公开参数签名、根零件原文与自包含依赖包 |
| C2 | 允许跨工作区引用复用模块 | DSL `use` 的字符串字面量新增保留前缀 `lib:`：`use "lib:<module_key>@<version>"(参数…) as <标签>`；编译器新增 `library_resolver` 回调，不再受 `workspace_id` 限制 |
| C3 | 可复用模块管理 + 跨工作区引用 | 库引用必须显式写版本号；发布新版本只让使用方出现「可升级」提示，不改写已保存设计；升级由前端改写 `@<n>` 后走既有保存端点落新版本 |
| C4 | 允许跨工作区引用复用模块 | 可见性二档：`public`（所有登录用户可检索、可跨工作区引用）/ `workspace`（仅所有者工作区可见，且禁止跨工作区引用）；无权访问按 404 |
| C5 | 可复用模块管理 | 模块版本只增不改；归档只阻止新引用，已被锁定引用的版本继续可编译（打开 / 刷新 / 版本恢复） |
| C6 | 可复用模块管理 | 发布时把根零件及其依赖闭包打包为版本快照；消费方编译库模块时只从该快照解析，不回落消费方同名 `file_key` |
| C7 | 可复用模块管理 | 发布与消费都按依赖闭包累计预算（1MB / 64 文件 / 深度 8 / 图元 2000 / module+system 256）；库快照计入消费方闭包 |
| C8 | 可复用模块管理 | 依赖快照新增 `source=workspace/library` 两类条目；新增 `design_libraryref` 当前直接引用索引；依赖面板展示库引用、锁定版本与可升级状态 |
| C9 | 允许跨工作区引用复用模块 | 备份 v14 增加 `library_refs[]`（按自然键去重的已锁定快照）；导入写入工作区级 `design_library_vendor`，离线环境按 vendor 编译 |
| C10 | 可复用模块管理 | 设计工作台增加「复用模块库」浏览、发布弹窗、库引用插入 / 补全、只读模块版本页与依赖面板扩展 |
| C11 | 可复用模块管理 | 既有 `use "<file_key>"`、版本快照、种子、v13 及更旧备份导入行为不变；库引用为纯增量能力 |

## Context

现状逐条核对（沿用需求卡片「现状影响面」编号，逐条给结论；新增条目从 #9 起）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `design_design` 的唯一键是 `(workspace_id, folder, title)` + `(workspace_id, file_key)`，无全局模块实体 | `src/cndb/plugins/design/models.py:33-74` | `file_key` 只在工作区内唯一，无法作为跨工作区引用身份 | 确认 C1/C2 |
| 2 | `build_resolver` 固定按 `workspace_id` 查询；其他工作区同名 key 一律视为缺失 | `src/cndb/plugins/design/services/files.py:64-128` | 跨工作区引用在解析层被硬阻断 | 确认 C2 |
| 3 | `use` 只解析字符串 `file_key`，`FileSource` 无来源 / 模块版本字段 | `src/cndb/plugins/design/services/dsl/compile.py:610-637`、`nodes.py` | 无法表达 `lib:` 引用、版本锁定与快照来源 | 确认 C2/C3/C6 |
| 4 | 依赖快照条目只有 `{file_id, file_key, version_number, content_hash}` | `src/cndb/plugins/design/models.py:61-62`、`routers.py:240-250` | 无法区分本地文件与库模块，备份恢复也无自然键可查 | 确认 C8/C9 |
| 5 | 引用索引只有 `design_designref(design_id, target_design_id)`，两者均工作区级 | `src/cndb/plugins/design/models.py:116-141` | 无法记录「设计 → 库模块版本」引用，也无法做库模块用量统计 | 确认 C8 |
| 6 | 删除被引用设计 409 只查同工作区引用方 | `src/cndb/plugins/design/routers.py:261-273`、`:581-600` | 库模块需要「归档而非删除」，且已发布版本不能被删除 | 确认 C5 |
| 7 | 备份 designs 段只导出工作区设计文件；导入用工作区 resolver 重编译 | `src/cndb/plugins/workspaces/services/workspace_backup.py:570-625`、`backup_io.py:1136-1284` | 引用库模块的设计在缺失模块的环境中恢复会断链 | 确认 C9 |
| 8 | 前端侧栏 / 依赖面板只认 `file_id`，节点点击按 `file_id` 打开源文件 | `frontend/src/pages/design/DesignStructureNav.tsx`、`DesignsPage.tsx`、`src/api/design.ts` | 库来源节点没有本工作区源文件，需要只读模块版本页 | 确认 C10 |
| 9 | `sync_refs` 只回填同工作区目标；`mark_referrers_stale` 只沿同工作区 ref 表传播 | `src/cndb/plugins/design/services/files.py:176-222` | 跨工作区库引用不会进入 stale / 升级提示链路 | 新增 C3/C8 |
| 10 | 保存 / 预览构建 resolver 时不携带用户身份；编译判定与权限完全解耦 | `src/cndb/plugins/design/routers.py:116-130`、`:374-380` | 库引用需要「按用户可见性校验新引用、按既有授权放行旧引用」 | 新增 C4 |
| 11 | 备份导入 / 恢复以 `designs[]` + 工作区 resolver 为准，无外部快照概念 | `backup_io.py:1233-1284`、`workspace_restore.py:124-128` | 需要新增 vendor 表并纳入恢复清理 | 新增 C9 |

**核心缺陷（需求要补的）**：现有模型把「设计文件」完全关在工作区内，没有**跨工作区的稳定模块身份、不可变发布版本与自包含快照**；因此既不能安全复用，也无法在引用方复现「当时用的是哪一版模块」。

设计目标（不变量）：

- **I1 单一真相源**：模块版本以发布时的根零件原文 + 依赖闭包快照为唯一真相源；版本行不可修改，消费方只读。
- **I2 显式锁定**：库引用必须带版本号；同一 `module_key` 的版本号单调递增；不存在「隐式最新」语义。
- **I3 自包含**：模块版本打包其完整依赖闭包；消费方编译库模块时只在该闭包内解析，禁止回落使用方同名文件。
- **I4 历史可复现**：依赖快照记录库模块自然键 + 版本 + 内容哈希；发布新版本、归档、可见性变化都不改变已保存版本的编译结果。
- **I5 权限不放大**：`workspace` 私有模块不可跨工作区引用；`public` 模块可跨工作区引用；无权访问返回 404；已授权引用的编译不因后续权限变化而失效。
- **I6 预算有界**：库快照计入消费方依赖闭包预算，不得通过发布 / 多模块组合放大既有上限。
- **I7 前端零求解**：库解析、版本校验、参数绑定、预算判定仍只在后端 `compile_design` 完成；前端只消费 IR / 诊断。
- **I8 可移植**：工作区备份内置已锁定模块快照，恢复到没有该模块的环境仍能打开与编译。
- **I9 向后兼容**：既有同工作区 `use`、IR v1-v5、v13 及更旧备份导入、种子与重构 CLI 行为不变。

## Decision

### 1. 术语与产品边界

- **复用模块（Library Module）**：从某个工作区的 `part` 设计文件发布出来的、具有稳定全局标识与参数接口的可复用单元。
- **模块版本（Module Version）**：一次发布产生的不可变快照，包含根零件原文、依赖包、公开参数签名与内容哈希。
- **库引用（Library Reference）**：DSL 中 `use "lib:<module_key>@<version>"` 形式的跨工作区引用。
- **发布工作区（Owner Workspace）**：模块所属工作区，决定 `workspace` 私有可见性与模块设置权限。

MVP 只允许 **`part` 文件**发布为模块，且发布时**禁止模块内部再使用 `lib:` 引用**（即模块必须来自单一工作区的依赖闭包）。理由：现有 `use` 只允许指向 `part`（ADR 0086 D3），自包含单层模块已覆盖「标准件 / 通用零件」主场景；嵌套库模块涉及跨发布者的命名空间与授权链，留作后续需求，不在本 ADR 暗含。

### 2. 数据模型

新增四张表；均为全局或工作区级，不修改既有 `design_design` / `design_designversion` 的业务列。

**`design_library_module`（全局）**

| 列 | 类型 | 口径 |
|---|---|---|
| `module_key` | `String(64)`，非空 | 全局唯一、创建后不可变；DSL `lib:` 引用它；字符集同 `file_key` |
| `name` | `String(200)`，非空 | 展示名，可改 |
| `description` | `String(500)`，非空，默认 `""` | 发布说明 |
| `visibility` | `String(16)`，非空，默认 `workspace` | `public` / `workspace` |
| `owner_workspace_id` | FK `workspaces_workspace.id`，可空，`ON DELETE SET NULL` | 发布工作区；工作区删除后模块保留（公开模块继续可用） |
| `source_design_id` | FK `design_design.id`，可空，`ON DELETE SET NULL` | 溯源用，不参与编译 |
| `is_archived` | `Boolean`，非空，默认 `false` | 归档后禁止新引用，已有锁定引用继续可编译 |
| `created_by_id` / `updated_by_id` | FK `accounts_user.id`，可空 | 审计 |

唯一键 `UNIQUE(module_key)`；索引 `(visibility, updated_at)`、`(owner_workspace_id)`。

**`design_library_version`（全局，不可变）**

| 列 | 类型 | 口径 |
|---|---|---|
| `module_id` | FK `design_library_module.id`，`ON DELETE CASCADE` | 所属模块 |
| `version_number` | `Integer`，非空 | 每模块从 1 单调递增 |
| `content` | `Text`，非空 | 根零件 DSL 原文 |
| `files` | `JSON`，非空，默认 `[]` | 自包含依赖包：`[{file_key, kind, content, content_hash}]`，按 `file_key` 排序；不含根文件 |
| `params` | `JSON`，非空，默认 `[]` | 公开参数签名 `[{name, default}]`，供检索 / 补全 / 调用提示 |
| `content_hash` | `String(64)`，非空 | 根原文 SHA-256 |
| `bundle_hash` | `String(64)`，非空 | 规范化 `files` 的 SHA-256 |
| `comment` | `String(200)`，非空，默认 `""` | 发布说明 |
| `created_by_id` | FK `accounts_user.id`，可空 | 发布人 |

唯一键 `UNIQUE(module_id, version_number)`；不提供更新 / 删除端点。

**`design_libraryref`（工作区级当前直接引用索引）**

| 列 | 口径 |
|---|---|
| `workspace_id` | 消费方工作区，`ON DELETE CASCADE` |
| `design_id` | 引用方设计，`ON DELETE CASCADE` |
| `module_id` / `module_version_id` | 被引用模块与锁定版本 |
| 唯一键 | `UNIQUE(design_id, module_version_id)` |
| 索引 | `(module_id)`、`(workspace_id)` |

**`design_library_vendor`（工作区级备份内置快照）**

| 列 | 口径 |
|---|---|
| `workspace_id` | 所属工作区，`ON DELETE CASCADE` |
| `module_key` / `version_number` / `content_hash` / `bundle_hash` | 自然键与完整性校验 |
| `content` / `files` / `params` | 与模块版本同构的快照内容 |
| 唯一键 | `UNIQUE(workspace_id, module_key, version_number, content_hash)` |

vendor 行只由备份导入写入、只读，不进入模块库检索。

**依赖快照扩展**（`design_design.dependencies` / `design_designversion.dependencies`，JSON 超集）：

```json
[
  {"source": "workspace", "file_id": 12, "file_key": "轮毂", "version_number": 3, "content_hash": "..."},
  {"source": "library", "module_key": "轮毂-标准件", "version_number": 2,
   "content_hash": "...", "bundle_hash": "..."}
]
```

存量条目无 `source` 字段时按 `workspace` 解释，迁移不回填。

### 3. DSL 与编译（唯一入口）

DSL 不新增关键字，只在 `use` 的字符串字面量中定义保留前缀；`file_key` 允许字符集不含 `:`，因此无歧义：

```text
use "lib:轮毂-标准件@2"(d = 40, w = 16) as wheel_fl
```

- `lib:` 后为 `module_key@<正整数版本号>`；缺版本、版本非正整数、key 非法均报带行列诊断。
- 本地文件 key 禁止以 `lib:` 开头（创建 / 生成 / 备份导入三处校验），避免遮蔽。

编译入口签名扩展：

```python
def compile_design(
    content: str,
    overrides: Mapping[str, float] | None = None,
    *,
    file_kind: str = "assembly",
    file_id: int | None = None,
    resolver: Callable[[str], FileSource | None] | None = None,
    library_resolver: Callable[[str, int], LibrarySource | None] | None = None,
) -> CompileResult: ...
```

判定顺序：

1. 解析 `use` 字符串；`lib:` 引用走 `library_resolver(module_key, version)`，其余走工作区 `resolver`。
2. `library_resolver` 返回 `LibrarySource`：`module_id / module_key / version_number / content / content_hash / bundle_hash / params / files`；缺失、版本不存在、归档、无可见性均返回 `None`，由编译器统一报 `未找到引用的复用模块 'key@vN'`（不泄露归档 / 私有原因）。
3. 进入库模块编译时建立**快照作用域**：`use "<key>"` 只查 `files` 包，不查消费方工作区；包内缺失直接报错（发布时已保证完整）。
4. 预算：库版本根原文 + `files` 中未计过的文件计入消费方 `_Closure`；同一 `module_version_id` 多次实例化只计一次文件与字节，参数不同仍复用编译模板缓存。
5. 依赖输出：每个库模块版本产生一条 `source=library` 快照；IR 大纲的 `assembly` 节点带 `ref.source=library`，库来源节点不写 `file_id`。
6. 同一输入（消费方原文 + 参数覆盖 + 锁定模块版本集合）必须产出同一 IR（I3）。

`FileSource` 增加 `source`（`workspace` / `library`）与可选 `module_id` / `module_version_id`；`LibrarySource` 为新增冻结 dataclass。`compile_design` 仍是唯一判定入口，禁止路由层另写库解析。

### 4. 发布 / 升级 / 归档

**发布**（工作区 editor+）：

1. 目标设计必须 `kind=part`、未软删。
2. 用当前工作区 resolver 编译；失败拒绝发布。
3. 解析 AST，若存在任何 `use "lib:…"` → 报 `design_library_nested_ref_unsupported`（MVP 边界）。
4. 收集依赖闭包，读取每个依赖的当前版本原文，形成 `files`；闭包预算按 §3 口径校验。
5. 首次发布生成全局唯一 `module_key`（标题清洗 + 全局冲突递增后缀，规则复用 `services/keys.py`）；后续发布沿用同一 `module_key`。
6. 落一条新 `design_library_version`（版本号 = 当前最大 + 1），`visibility` / `name` / `description` 由发布请求给出；模块默认 `workspace`。

**升级**：不做服务端源码改写。前端在依赖面板展示「有更新版本」，用户确认后把正文中的 `@<n>` 改为目标版本并调用既有 `PUT /{wid}/designs/{id}/content`；保存时按新版本编译落版。批量替换只替换该 `module_key` 的完整 `lib:` 字面量，避免误伤。

**归档 / 可见性**：模块所有者工作区的 owner（或系统管理员）可修改 `visibility` 或置 `is_archived=true`。归档与新可见性只影响「新引用」；已存在 `design_libraryref` 的锁定版本继续编译（I4/I5）。模块不提供硬删除。

**工作区删除**：`owner_workspace_id` 置 NULL，模块与版本保留；公开模块继续可用，私有模块仅剩既有引用可用，由系统管理员后续归档。

### 5. 权限

| 动作 | 门槛 |
|---|---|
| 浏览 / 检索模块库 | 当前工作区成员；返回 `public` 模块 + **当前工作区**发布的 `workspace` 模块 |
| 查看模块详情 / 版本 / 只读预览 | 同上；无权访问返回 404（不区分不存在与无权限） |
| 发布新版本 | 设计所在工作区 editor+ |
| 修改可见性 / 归档 | 模块 `owner_workspace_id` 的 owner，或系统管理员 |
| 在 DSL 中新增库引用 | 保存 / 预览时校验：模块未归档；`public` 任意成员可用；`workspace` 仅当消费方工作区 == 所有者工作区 |
| 重新编译既有的库引用 | 以 `design_libraryref` 中已落库的版本授权为准，不因后续转私有 / 归档而失败（I5） |

解析器回调由路由层构造并捕获 `(db, user, workspace_id, design_id)`；`compile_design` 本身保持纯函数。预览（未保存内容）对新引用执行同一校验，对既有设计已授权的版本直接放行。

### 6. API 变更清单

全部挂在 design 插件既有 `route_prefix="workspaces"` 下，避免新增插件与重复权限入口。

| 端点 | 变更 |
|---|---|
| `POST /{wid}/designs/{id}/publish` | **新增**：发布为复用模块 / 新版本；请求含 `visibility`、`name?`、`description?`、`comment?`；返回模块与版本摘要 |
| `GET /{wid}/design-library/modules` | **新增**：模块列表；支持 `q`、`visibility`、`owned_only`、`include_archived`（仅所有者工作区 owner 可含归档） |
| `GET /{wid}/design-library/modules/{module_id}` | **新增**：模块详情 + 版本列表 + 参数签名；无权 404 |
| `GET /{wid}/design-library/modules/{module_id}/versions/{n}` | **新增**：版本原文 + 依赖包元数据（`files` 逐项 `file_key/content_hash`，不回传全文时可只回传根原文） |
| `POST /{wid}/design-library/modules/{module_id}/versions/{n}/preview` | **新增**：只读预览（参数覆盖，无落库），与设计预览同口径 |
| `PATCH /{wid}/design-library/modules/{module_id}` | **新增**：改 `name / description / visibility / is_archived`；仅所有者工作区 owner / 系统管理员 |
| `GET /{wid}/designs/{id}/dependencies` | 响应增加 `library_items[]`（模块键 / 版本 / 可见性 / 归档 / 是否有更新版本）；`referrers` 仍是同工作区文件引用方 |
| `POST /{wid}/designs/{id}/versions/{n}/restore` | 依赖快照含库条目时按自然键解析；缺失返回 `400 design_library_dependency_missing` |
| `GET /{wid}/designs/{id}/versions/{n}` | `dependencies` 为超集，旧客户端忽略新字段 |
| `GET /{wid}/designs/{id}/ir` | IR 升 v6，大纲 `ref` 增加 `source` 与库标识；ETag 口径不变 |

不新增「删除模块」端点；不经由设计删除端点删除模块。

### 7. 边界与例外

1. **模块粒度**：仅 `part`；`assembly` / `system` 发布在后续需求评估，不在本 ADR 承诺。
2. **模块自包含**：发布时禁止内部 `lib:` 引用；模块依赖包必须在单工作区闭包内闭合。
3. **版本锁定**：`@<n>` 必填；不提供 `latest` 关键字；升级是显式改写 + 保存。
4. **不可变**：版本行不可更新；发布会话失败时不落半成品版本（先编译、后落库）。
5. **归档 / 可见性**：只影响新引用；已锁定引用永久可编译（I4/I5）。
6. **同名遮蔽**：库快照内部解析不使用消费方文件；消费方同名 `file_key` 不影响库模块几何（I3）。
7. **预算**：发布与消费都受闭包预算约束；超限报诊断，不落库、不发布。
8. **私有跨工作区**：`workspace` 模块在消费方工作区 != 所有者工作区时，新增引用直接诊断拒绝；浏览时不可见。
9. **公开内容责任**：`public` 发布即对所有登录用户可见，发布弹窗需明确提示；MVP 不引入管理员审核。
10. **移除发布工作区**：模块保留，公开模块可用；私有模块不因此变成公开。
11. **IR 兼容**：旧 v1-v5 快照继续渲染；新保存一律 v6；库来源节点无 `file_id`，前端不得按源文件打开。

### 8. 迁移

单条 Alembic 迁移（`down_revision` 以 `alembic heads` 为准）：

- 新建 `design_library_module`、`design_library_version`、`design_libraryref`、`design_library_vendor` 四表及索引 / 唯一键。
- 不改既有表结构；`dependencies` JSON 为纯数据超集，无需 DDL 回填。
- `downgrade`：按依赖倒序 drop 四表。已知限制：降级后正文含 `lib:` 引用的设计在旧代码下无法编译；备份中的 `library_refs` 段被旧导入器忽略。该限制写入交接，不静默改正文。

### 9. 备份与恢复

备份协议升 **v14**（v13 超集）：

- 新增顶层 `library_refs[]`：扫描本工作区所有设计与版本依赖快照中的 `source=library` 条目，按 `(module_key, version_number, content_hash)` 去重，写入 `{module_key, version_number, content_hash, bundle_hash, content, files, params}`。
- 模块发布产物本身不随工作区备份导出；发布工作区的源设计仍按普通 `designs[]` 导出，可在目标环境重新发布。
- 导入 / 恢复：
  1. 先写 `design_library_vendor`（幂等 upsert）。
  2. 再按既有两阶段流程编译设计；库解析优先级为「当前环境同自然键且哈希一致的模块版本 → vendor 快照 → 缺失诊断」。
  3. `sync_refs` 同时重建 `design_libraryref`（能解析到模块行时），无法解析时只保留依赖快照与 vendor。
- 覆盖恢复前清理工作区内容时一并删除 `design_library_vendor`，再按备份重建。
- v13 及更旧备份无 `library_refs`，导入路径跳过，行为不变（I9）。

### 10. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/design.ts` | 模块 / 版本 / 发布 / 依赖库条目类型；IR v6 `ref.source`；`file_id` 可空 |
| 工作台侧栏 | `frontend/src/pages/design/DesignsPage.tsx`、`DesignStructureNav.tsx` | 侧栏增加「复用模块库」分区（本工作区发布 + 公开），支持搜索与版本展开 |
| 发布 | 新增 `frontend/src/pages/design/PublishModuleModal.tsx` | part 设计「更多」菜单入口；可见性选择（默认私有）、说明、公开责任提示、发布结果 key/版本 |
| 插入 / 补全 | `designLang.ts`、`designCompletion.ts` | `use "lib:` 补全模块 key 与版本；插入模板带参数占位 |
| 依赖面板 | 新增 / 扩展 `frontend/src/pages/design/DesignLibraryPanel.tsx` | 列出库引用、来源工作区、锁定版本、可升级版本；一键升级改写正文并保存 |
| 只读模块页 | 新增 `frontend/src/pages/design/LibraryModulePage.tsx` | 模块详情、版本切换、DSL 只读、3D 预览；作为库来源节点的打开目标 |
| 结构树 | `DesignStructureNav.tsx` | 库来源节点按 `ref` 打开只读模块页，不按 `file_id` 打开工作区文件；归档 / 私有已授权节点显示状态标记 |
| 帮助 | `frontend/src/pages/help/content/` | 发布、跨工作区引用、版本锁定与升级、归档影响说明 |

### 11. 测试清单

**判定层（`tests/test_design_dsl.py` / 新增 `tests/test_design_library.py`）**：`lib:` 语法解析（合法 / 缺版本 / 版本为 0 或非整数 / key 非法）；未知 key / 未知版本 / 归档 / 私有跨工作区诊断；快照优先于消费方同名 `file_key`；库模块多实例参数独立；闭包预算（文件 / 字节 / 图元 / module+system）超限；同输入两次 IR 相等；IR v6 大纲 `ref`；旧 v5 夹具逐字节行为不变。

**发布层（`tests/test_design_library.py`）**：非 part 拒绝；编译失败拒绝；嵌套 `lib:` 拒绝；`module_key` 全局生成与冲突递增、创建后不可变；重复发布版本单调递增；版本不可更新；发布失败零残留。

**接口层（`tests/test_design_api.py`）**：发布权限（viewer 403）；模块列表可见性过滤；私有模块跨工作区 404；`PATCH` 仅 owner / 管理员；归档后新引用 400、既有设计打开 / 刷新 / 恢复成功；依赖响应含库条目；版本恢复按锁定版本；无删除端点。

**迁移 / 备份**：四表 up/down；v14 往返含 `library_refs`；恢复到无模块环境按 vendor 编译；v13 及更旧备份导入不变；覆盖恢复清空 vendor 后重建。

**前端单测**：模块库列表 / 搜索 / 可见性标记；发布弹窗校验；补全与插入；依赖面板升级改写；库来源节点打开只读页；IR v6 类型；归档 / 私有状态提示。

**e2e（`frontend/tests/e2e/critical/design-library.spec.ts`）**：工作区 A 发布公开模块 v1 → 工作区 B 引用并预览 / 导出 → A 发布 v2，B 仍为 v1 → B 依赖面板升级到 v2 并落新版本 → A 归档，B 既有设计仍可打开 → B 备份导入新工作区，模块离线仍可打开。

### 12. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 四表 + Alembic；`lib:` 解析；`library_resolver` + 快照作用域 + 预算 + IR v6；发布流程；可见性 / 归档判定；判定层测试 | 中（编译器作用域与权限注入） |
| **P1** | 模块库 API（列表 / 详情 / 版本 / 预览 / PATCH）；依赖快照 `source` 与 `design_libraryref`；依赖面板；前端模块库 / 发布 / 补全 / 只读页 / 升级 | 中高（跨工作区权限与前端联动） |
| **P2** | 备份 v14 + vendor + 恢复优先级；跨环境 e2e；帮助文档 / CHANGELOG / 收尾 | 中（备份兼容与离线恢复） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 新增「发布快照模块库」：发布产生不可变版本，消费方按版本引用 | 历史可复现；源工作区改动 / 删除不影响使用方；权限面最小；与现有依赖快照范式一致 | ① 实时跨工作区引用：历史不可复现、源删除即断链、权限随源变化；② 复制为新设计文件：无稳定版本与升级路径 | `design/models.py`、`design/services/files.py` |
| D2 | 引用身份与语法 | `module_key` 全局唯一不可变；DSL 用 `use "lib:<key>@<n>"(…)`；`lib:` 为本地 key 保留前缀 | 不改 lexer 关键字；字符串字面量承载全部信息；全局可读、可移植 | ① 新增 `library` 关键字：改动语法与高亮面更大；② 按工作区 + 标题引用：改名 / 转移即断链 | `design/services/dsl/compile.py`、`parse.py`、`services/keys.py` |
| D3 | 模块粒度 | 仅 `part`；发布时禁止嵌套 `lib:`，依赖闭包必须单工作区闭合 | 现有 `use` 只支持 part；避免跨发布者命名空间 / 授权链；标准件场景已覆盖 | ① 允许 assembly 模块：与「use 只指 part」冲突；② 允许嵌套库模块：需命名空间重写与递归授权 | `design/services/dsl/compile.py`、`routers.py` |
| D4 | 可见性 | `public` 全员可检索 / 跨工作区引用；`workspace` 仅所有者工作区可见且禁止跨工作区引用 | 覆盖通用共享与团队内部预发布；私有边界可一句话判定 | ① 仅公开：无法内部试用；② 工作区白名单：新增授权表与 UI，MVP 过重 | `design/models.py`、`routers.py` |
| D5 | 版本策略 | 显式锁定版本，升级由使用方显式改写并保存；不提供隐式最新 | 与 ADR 0086 D6 的「依赖陈旧 + 显式刷新」同构；避免静默漂移 | ① 始终最新：破坏历史复现；② 锁定 + 跟踪最新双模式：语法与判定分支翻倍 | `design/services/files.py`、前端依赖面板 |
| D6 | 编译解析优先级 | 库模块内部只查版本快照，不回落消费方工作区；同名 key 不遮蔽 | 保证自包含与可复现；防止消费方本地文件改变库模块几何 | ① 先本地后快照：同名文件劫持；② 合并解析：版本边界不清 | `design/services/dsl/compile.py` |
| D7 | 数据模型 | 模块 / 版本 / 引用 / vendor 四表分离；版本不可变、不提供删除 | 发布产物与工作区文件解耦；引用索引可查用量；vendor 承载离线快照 | ① 直接给 `design_design` 加全局可见列：破坏工作区唯一键与权限模型；② 只存依赖 JSON 不建表：无法检索 / 授权 / 归档 | `design/models.py` |
| D8 | 权限与既有引用 | 新引用按当前可见性校验；已落库引用以 `design_libraryref` 授权为准，后续转私有 / 归档不失效 | 业务连续性优先；避免设计突然打不开；授权在引用时已发生 | ① 每次编译重查可见性：归档 / 转私有会让历史设计不可用；② 永久公开：无法收紧 | `design/routers.py`、`design/services/files.py` |
| D9 | 备份口径 | 备份 v14 内置已锁定快照（`library_refs[]`），导入写 workspace 级 vendor；模块本身不导出 | 备份自包含、可跨环境恢复；避免把全局资源复制成模块 | ① 不导出：离线恢复断链；② 导出模块本体：恢复时产生重复全局实体与所有权问题 | `workspace_backup.py`、`backup_io.py`、`workspace_restore.py` |
| D10 | 路由归属 | 库端点全部挂在 design 插件 `/{wid}/design-library` 下 | 复用现有插件与工作区上下文权限；不新增插件注册 / 备份 / 模块推导 | ① 新建独立插件：权限、模块开关、备份都要再接一遍；② 顶层 `/design-library`：绕过工作区上下文，权限判定分散 | `design/routers.py`、`plugin.py` |
| D11 | IR 版本 | 升 v6：大纲 `ref` 增加 `source` / 库标识；库节点不写 `file_id` | 前端需区分「打开工作区文件」与「打开只读模块版本」；旧快照保持 v1-v5 兼容 | ① 保持 v5 只加可选字段：版本语义不清；② 库节点伪造 `file_id`：会错误跳转 | `design/services/dsl/compile.py`、`frontend/src/api/design.ts` |
| D12 | 迁移与降级 | 单条迁移只建四表，不回填；降级 drop 四表，正文不回改 | 存量零迁移；不 import 编译器；降级限制显式记录 | ① 迁移中扫描 / 改写正文：风险高且不可逆；② 不提供 downgrade：违反仓库迁移规范 | `src/cndb/alembic/versions/` |
| D13 | 测试门禁 | 判定 / 发布 / 接口 / 迁移备份 / 前端 / e2e 六层，覆盖离线恢复与归档后可用 | 对齐仓库测试规范；跨工作区能力必须有权限与恢复门禁 | ① 只做单测：权限与备份断链无回归；② 只做人工验收：跨工作区行为不可守 | `tests/`、`frontend/src/pages/design/`、`frontend/tests/e2e/critical/` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：零件可在工作区间以稳定身份复用；发布版本不可变、按版本锁定，历史设计可复现；消费方无需访问源工作区即可编译；归档 / 转私有不破坏既有设计；备份可离线恢复。
- **负向**：新增四张表与一套跨工作区权限判定；编译作用域从「单工作区 resolver」变为「工作区 + 库快照双解析」；发布产物是内容的完整副本，存储随模块版本增长；MVP 限制模块为单层自包含 `part`。
- **风险与缓解**：① 快照与源文件漂移 → 版本不可变、哈希校验、发布后不回溯；② 权限绕过 → 新引用强校验 + 无权 404 + 既有引用按 ref 授权；③ 预算被库模块放大 → 快照计入消费方闭包并复用现有上限；④ 备份协议升级 → v14 超集 + v13 及更旧导入回归；⑤ 公开内容误发 → 默认私有 + 发布弹窗显式确认。

## 行业对照

| 维度 | SolidWorks Toolbox / PDM | Fusion 360 团队库 | 本设计 |
|---|---|---|---|
| 复用单元 | 标准件库 / 库特征，按配置复用 | 团队共享零件 / 衍生设计 | 发布模块：稳定 `module_key` + 不可变版本 |
| 引用方式 | 引用库文件 / 配置 | 引用云端文档，可插入衍生 | `use "lib:<key>@<n>"`，显式版本锁定 |
| 版本与更新 | PDM 版本 / 修订，可锁定 | 云端版本，可跟随更新 | 锁定版本；升级由使用方显式改写 |
| 权限 | 库 / 文件夹 ACL | 团队 / 项目共享 | `public` / `workspace` 二档 |
| 离线 / 归档 | 本地库缓存 | 云端依赖 | 备份内置快照（vendor）+ 归档保留既有引用 |

来源：SolidWorks Toolbox / PDM 帮助、Fusion 360 团队库文档（只作概念对照，不作为实现依赖）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| DSL / IR 契约 | `compile_design` / `DesignIR` | 新增 `lib:` 引用、`library_resolver`、IR v6 大纲来源；本地 `use` 语义不变 | ADR 0079 / 0086 |
| 工作区文件引用边界 | `build_resolver` / `design_designref` | 修订 ADR 0086 I2 / D9 / 边界 §5.4 的「引用限同工作区」：**仅工作区文件引用继续成立**，`lib:` 引用由本 ADR 约束 | ADR 0086 |
| 依赖版本与陈旧 | `dependencies` / `dependencies_stale` | 库引用进入依赖快照；发布新版本不自动改已保存版本，升级是显式动作 | ADR 0086 D6 |
| 结构大纲 | `outline` / 侧栏树 | v6 为库来源节点加 `ref.source`；点击打开只读模块版本 | ADR 0083 / 0103 / 0109 |
| 工作区备份 | `backup.json` designs 段 | v14 增加 `library_refs[]` 与 vendor 恢复；模块本体不导出 | ADR 0075 |
| 工作区模块开关 | `resolve_features` | 入口仍受 `design` 模块门控；不新增工作区模块 | ADR 0080 |
| 浏览器基线 | Chrome / Edge 81 | 只读模块页与 3D 预览须在该基线冒烟 | ADR 0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/models.py`、`src/cndb/alembic/versions/d7e8f9a0b1c2_design_library.py`、`src/cndb/plugins/design/services/dsl/nodes.py`、`src/cndb/plugins/design/services/dsl/parse.py`、`src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/files.py`、`src/cndb/plugins/design/services/keys.py`、`src/cndb/plugins/design/services/library.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py` | `tests/test_design_dsl.py`、`tests/test_design_library.py`、`tests/test_design_library_migration.py` | - |
| P1 | 已落地 | `src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/design/services/library.py`、`src/cndb/plugins/design/plugin.py`、`frontend/src/api/design.ts`、`frontend/src/api/index.ts`、`frontend/src/App.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/LibraryModulePage.tsx`、`frontend/src/pages/design/PublishModuleModal.tsx`、`frontend/src/pages/design/DesignMoreMenu.tsx`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/DslEditor.tsx`、`frontend/src/pages/design/designCompletion.ts` | `tests/test_design_library.py`、`frontend/src/pages/design/DesignStructureNav.test.tsx`、`frontend/src/pages/design/LibraryModulePage.test.tsx`、`frontend/src/pages/design/PublishModuleModal.test.tsx`、`frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/src/pages/design/designCompletion.test.ts` | - |
| P2 | 未开始 | `src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/tests/e2e/critical/design-library.spec.ts` | `tests/test_workspace_backup_v14.py`、`frontend/tests/e2e/critical/design-library.spec.ts` | - |

## 交接（会话结束更新）

- 当前阶段：P1 已落地，待 P2（备份 v14 + vendor 恢复、跨环境 e2e、文档收尾）
- 已完成：P0 四表 + 迁移；`use "lib:<key>@<n>"` 解析与语法校验；`library_resolver` + 快照作用域 + 统一预算 + IR v6；`POST /{design_id}/publish` 发布流程；可见性 / 归档判定与既有引用授权；判定层与迁移测试。P1 模块库 API（列表 / 详情 / 版本 / 预览 / PATCH）；依赖快照 `source` 与 `design_libraryref`；恢复历史版本时库依赖缺失即 400；依赖面板升级改写；前端侧栏模块库 / 发布弹窗 / DSL 补全 / 只读模块页
- 下一步：P2 备份 v14 `library_refs[]` + `design_library_vendor` 写入 / 恢复、`backup_io._import_designs` 接 vendor、跨环境 e2e、帮助文档收尾
- 已知坑：`lib:` 为本地 `file_key` 保留前缀，创建 / 生成 / 备份导入三处都要校验；库快照解析必须与消费方工作区 resolver 隔离；既有引用按 `design_libraryref` 授权放行，不能每次编译重查可见性；`backup_io._import_designs` 目前用工作区 resolver 重编译，接 vendor 时先写 vendor 再编译；`GET /modules?include_archived` 仅工作区 OWNER 或系统管理员可用；`PATCH /modules/{id}` 的 owner 工作区缺失返回 400 `design_library_owner_missing`
- 最近一次全绿：2026-11-07，`make check-fast` + `make test`（6728 passed, 3 skipped）；前端 `typecheck` / `lint` / 相关 vitest（71 passed）全绿
