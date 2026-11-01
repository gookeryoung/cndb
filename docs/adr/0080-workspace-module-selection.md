# ADR 0080: 工作区类型改为可勾选功能模块与顶部导航适配

Status: Accepted（2026-11-01 用户评审通过；评审修订：C4/D4 质量检查页签恒显 + GitHub 风格双栏、D8 默认全选 + 选型 UI 优化）
Date: 2026-11-01
Related: `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/schemas/models.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`src/cndb/plugins/pipeline/routers/workflows.py`、`src/cndb/plugins/pipeline/services/checks/registry.py`、`frontend/src/utils/workspaceType.ts`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/pages/settings/WorkspaceSettingsContent.tsx`、`docs/adr/0076-pipeline-check-dsl.md`、`docs/adr/0079-design-3d-dsl-module.md`
需求卡片: `docs/requirements/0080-workspace-module-selection.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 类型选择改为可勾选的模块（数据表/文档/设计，任意项或多项） | 落库字段由 `workspace_type` 枚举改为 `modules` JSON 集合（非空、白名单 {tables, documents, design}）；创建弹窗与工作区设置页改卡片式模块勾选（图标 + 名称 + 说明，默认全选）；API 以 `modules` 替换 `workspace_type`（D2/D8） |
| C2 | 数据分析、数据源同步与数据表强绑定 | 二者为「数据表」的派生功能，不进勾选 UI 与 API 字段；由模块→功能绑定表唯一推导（D3） |
| C3 | 文档和设计模块暂未确定，后续开发 | 本期二者为独立单模块；模块清单与绑定关系收敛为后端 `workspaces/modules.py` 与前端 `workspaceModules.ts` 两处常量表，后续扩展只改表不改模型（D1） |
| C4 | 质量检查是否分散，适应性设计 | 质量检查保留工作区级集中页签且**所有工作区恒显**（含仅设计，为后续 design 域检查动作预留入口）；页面改 GitHub 风格双栏：左侧流水线规则清单、右侧检查结果历史（D4）；检查动作目录按已启用模块过滤，DSL 保存 / 校验期拒绝已禁用域动作 |
| C5 | 顶部导航布局调整 | 页签按勾选模块渲染，顺序固定：数据表 → 文档 → 设计 → 数据分析 → 数据源同步 → 质量检查 → 工作区设置；落地段取第一个可用模块（tables → documents → design）；未开放段重定向（D9） |
| C6 | 存量重构兼容 | 单条迁移映射旧枚举（D5）；备份协议 v11 → v12 写 `modules`、旧版按同一映射读（D7）；API 破坏性替换、前后端同仓同发（D2） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `WorkspaceType` 三值枚举（DATA_DOC/DATA/DOC）+ 中文标签表 | `src/cndb/plugins/workspaces/models.py:78-97` | 枚举仅能表达 3 种固定组合；三模块的 7 种非空组合中 4 种不可达（如「数据表+设计」「仅设计」） | 确认：C1 核心改造对象 |
| 2 | 落库列 `workspace_type`（Enum，server_default DATA_DOC） | `src/cndb/plugins/workspaces/models.py:147-154` | 列类型变更载体；Enum 落库为成员名 | 确认：改 `modules` JSON 列（D2） |
| 3 | 创建 / 更新 / 响应 schema 均带 `workspace_type` | `src/cndb/plugins/workspaces/schemas/models.py:26,38,51` | 三个 schema 同步替换为 `modules` + 校验器 | 确认：C1/C6 |
| 4 | 前端类型门控唯一入口：label/hint/options + `workspaceTypeFeatures` switch + 落地段 | `frontend/src/utils/workspaceType.ts:12-60` | 6 个 feature key 硬编码于 switch；类型→功能映射不可声明式扩展 | 确认：整体替换为 `workspaceModules.ts`（D9） |
| 5 | 顶部页签按 feature 拼装 + 未开放段重定向到落地页 | `frontend/src/layouts/MainLayout.tsx:240-292, 381-400` | 页签挂载点与门控分支现成，换输入源即可；`workspaceLandingSegment` 现仅 tables/documents 两值 | 确认：C5；落地段扩三值 |
| 6 | 创建弹窗单选 `Select`；卡片显示单个类型标签 | `frontend/src/pages/workspace/WorkspaceList.tsx:347-367, 456-510, 574` | 改 Checkbox.Group；类型标签改模块标签组 | 确认：C1 |
| 7 | 工作区设置页单选 `Select`（同款三选项） | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx:386-405, 521` | 改同款勾选组 | 确认：C1 |
| 8 | 备份 v11 元数据写 `workspace_type`；恢复 / 从备份创建按旧值回填 | `src/cndb/plugins/workspaces/services/workspace_backup.py:41,153`、`workspace_restore.py:194`、`routers/workspaces.py:344-354, 505-515` | 备份协议需升 v12；旧备份导入需按枚举映射 | 确认：C6（D7） |
| 9 | 质量检查 feature：`data` / `data_doc` 开、`doc` 关 | `frontend/src/utils/workspaceType.ts:39-54` | `doc` 型已有 `document/*` 检查动作却整页签关闭，口径不一致 | 确认：C4 自适应门控顺带修复该不一致（D4） |
| 10 | 检查动作命名 `域/动作`（table/* 4 个、document/* 3 个，design/* 暂无） | `src/cndb/plugins/pipeline/services/checks/registry.py:3-6`、`checks/table/`、`checks/document/` | 域前缀可直接推导所属模块，目录过滤零结构改动 | 确认：C4 |
| 11 | 检查动作目录端点为工作区级（带 `workspace_id`） | `src/cndb/plugins/pipeline/routers/workflows.py:164-191` | 过滤只改查询侧，不动路由 | 确认：C4 |
| 12 | alembic 迁移链头为 design 迁移 `z4a5b6c7d8e9`；工作区类型原始迁移 `e7f8a9b0c1d2` | `src/cndb/alembic/versions/z4a5b6c7d8e9_add_design_plugin.py:18-19` | 新迁移单条挂接链头 | 确认：C6（D6） |
| 13 | 帮助文档提及「工作区类型三选一」；CONTEXT.md 有「工作区类型」词条 | `frontend/src/pages/help/content/configuration.tsx`、`quickStart.tsx`、`CONTEXT.md:44` | 文案与术语随 P2 同步 | 确认：C6 收尾 |
| 14 | 前端 API 类型 `WorkspaceType` 联合类型，四处接口字段引用 | `frontend/src/api/types/common.ts:8`、`workspaces.ts:10,27,32,56` | 类型层同步替换，不留旧类型 | 新增（卡片漏列） |
| 15 | 侧栏形态按功能段切换；analytics / datasource / pipelines / 设置段自动折叠 | `frontend/src/layouts/MainLayout.tsx:318-351` | 模块化后各段路由不变，折叠逻辑零改动 | 排除：无需调整 |
| 16 | 后端各插件路由不做 `workspace_type` 级拦截（门控只在前端导航层） | `src/cndb/plugins/workspaces/routers/workspaces.py`（全文无门控分支） | 模块化沿用该口径，本期不新增后端路由拦截 | 排除：保持现状（边界 #2） |

**核心缺陷（需求要补的）**：现行单选枚举只能表达 3 种固定功能组合，用户无法按需勾选（「数据表 + 设计、不要文档」等 4 种组合不可达）；且类型→功能映射硬编码在前后端两处 switch，为文档 / 设计新增子模块（C3 的后续开发）需要改多处判定代码。

设计目标（不变量）：

- **I1 模块集合合法**：`modules` 非空且 ⊆ {tables, documents, design}；创建 / 更新 / 备份恢复导入全部写路径经同一 Pydantic 校验器（白名单 + 去重 + 按 `WORKSPACE_MODULES` 固定顺序归一化）。
- **I2 单一推导入口**：模块→开放功能只由绑定表推导——后端 `workspaces/modules.py::resolve_features`、前端 `workspaceModules.ts::workspaceModulesFeatures` 各为唯一入口；新增子模块只改绑定表（C3）。
- **I3 存量行为零变化**：迁移映射后，每个旧类型推导出的功能矩阵与迁移前逐项相等（data_doc 全开；data 无文档 / 设计；doc 无数据表 / 分析 / 同步，有设计）。
- **I4 备份兼容**：v12 元数据写 `modules`；≤v11 导入按 `legacy_type_to_modules` 映射；不承诺旧版本程序读取 v12。
- **I5 强绑定不可拆**：analytics / datasource 不出现在任何勾选 UI 与 API 字段中，仅作为 tables 的派生功能存在。

## Decision

### 1. 数据模型

`src/cndb/plugins/workspaces/models.py`：

- 新增 `WorkspaceModule`（StrEnum）：`TABLES = "tables"` / `DOCUMENTS = "documents"` / `DESIGN = "design"`；
- 新增有序常量 `WORKSPACE_MODULES: tuple[str, ...] = ("tables", "documents", "design")` 与 `MODULE_LABELS`（数据表 / 文档 / 设计）；
- `Workspace` 列变更：删除 `workspace_type`，新增 `modules: Mapped[list[str]]`（JSON，`nullable=False`，Python 侧 default 为全三模块）；同步删除 `WorkspaceType` 枚举与 `WORKSPACE_TYPE_LABELS`（`__all__` 收缩）。

JSON 集合载体对齐同表 `tags` 列先例（`models.py:141-144`），白名单与顺序约束由校验器保证而非数据库类型。

### 2. 判定算法（唯一入口）

**后端** `src/cndb/plugins/workspaces/modules.py`（新增，纯常量 + 纯函数）：

```python
MODULE_FEATURES: dict[str, frozenset[str]] = {
    "tables": frozenset({"tables", "analytics", "datasource"}),   # C2 强绑定
    "documents": frozenset({"documents"}),
    "design": frozenset({"design"}),
}

def resolve_features(modules: list[str]) -> dict[str, bool]: ...
def legacy_type_to_modules(workspace_type: str) -> list[str]: ...  # data_doc/data/doc 映射（D5）
```

**前端** `frontend/src/utils/workspaceModules.ts`（新增，替换 `workspaceType.ts`）：`WORKSPACE_MODULE_OPTIONS`（label / hint / icon）、`workspaceModulesFeatures(modules)`（quality 键恒为 true，D4）、`workspaceLandingSegment(modules)`（tables → documents → design 第一个可用段）。语义与后端逐项一致（I2/I3）。

**质量检查域校验** `src/cndb/plugins/pipeline/services/checks/` 新增 `domain_of(uses) -> str`（`table/*` → tables、`document/*` → documents、`design/*` → design）与 `assert_steps_in_enabled_modules(ir, modules)`；create / update / validate 三个端点编译后统一调用（C4）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces` | `workspace_type` → `modules: list[str]`（I1 校验器：非空、白名单、去重、固定顺序归一化） |
| `PUT /api/v1/workspaces/{wid}` | 同上（`None` 表示不改；空列表 / 非法值 422） |
| `GET /api/v1/workspaces`（列表 / 详情 / pinned） | 响应以 `modules: list[str]` 替换 `workspace_type`（破坏性替换，前后端同仓同发，D2） |
| `GET /api/v1/workspaces/{wid}/pipelines/checks` | 按工作区 `modules` 过滤动作目录（`domain_of` ∉ 已启用模块的条目不返回） |
| `POST/PUT /api/v1/workspaces/{wid}/pipelines`（含 `/validate`） | 保存 / 校验期拒绝已禁用域的动作：编译通过后 `assert_steps_in_enabled_modules` 不满足 → 400 |

### 4. 边界与例外

1. 仅勾选「设计」的工作区：质量检查页签照常显示（评审修订，为后续 design 域检查动作预留入口），目录为空时页面给「暂无可用检查动作」提示；落地页 `/w/:wid/design`。
2. 后端不新增模块级路由拦截：与现状一致（Context #16），门控是前端导航层职责；`modules` 收窄只隐藏入口不删数据——取消勾选「文档」后文档实体保留，重新勾选即恢复可见（对齐现状「类型可改」行为）。
3. 存量流水线不受目录过滤影响：已保存的工作流即使包含当前已禁用域的动作，仍可运行（目标数据还在，只是编辑器目录不再展示该动作；新建 / 保存路径才拦截）。
4. `modules` 校验失败（空集 / 未知值）在创建与更新路径均返回 422；备份恢复导入路径同走校验器，映射失败（旧备份未知枚举值）回退全三模块并记入导入 `errors`。
5. 顶部导航布局（顶栏品牌 / 工作区切换 / 搜索 / 右侧操作区）与页签行结构不变，本 ADR 只改「哪些页签渲染 + 落地 / 重定向段」；侧栏形态切换逻辑零改动（Context #15）。
6. 工作区下拉菜单与无 wid 兜底跳转中的硬编码 `/tables`（`MainLayout.tsx:452, 494`）改为按目标工作区模块取落地段，纯 doc / design 工作区不再被送进被重定向的段。

### 5. 迁移

单条迁移 `b6c7d8e9f0a1_workspace_modules.py`（`down_revision = "z4a5b6c7d8e9"`）：

1. `batch_alter_table` 新增 `modules` JSON 列（先 nullable）；
2. 回填：`CASE workspace_type` —— `DATA_DOC → ["tables","documents","design"]`、`DATA → ["tables"]`、`DOC → ["documents","design"]`（D5，I3）；
3. 置 `NOT NULL` 后 drop `workspace_type` 列（SQLite 经 batch 重建）；
4. 幂等：每步前查列存在性。

downgrade：重建 `workspace_type` 枚举列并按 modules 有损映射回填——含 tables 且含 documents → `DATA_DOC`；含 tables → `DATA`；其余（documents / design 组合）→ `DOC`——随后 drop `modules`。映射有损（如 `[tables, design]` 回退为 `DATA_DOC`），仅在降级路径接受（D6）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 判定入口 | `frontend/src/utils/workspaceModules.ts`（新增，删 `workspaceType.ts`） | 模块选项 / features / 落地段（D9） |
| API 类型 | `frontend/src/api/types/common.ts`、`workspaces.ts` | `WorkspaceModule` 联合类型；接口字段 `modules`（Context #14） |
| 创建弹窗 | `frontend/src/pages/workspace/WorkspaceList.tsx` | `Select` → 卡片式模块勾选（D8，默认全选、至少一项校验）；卡片类型标签 → 模块标签组；进入工作区按落地段导航 |
| 工作区设置 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | 同款卡片式勾选组 + 至少一项校验；展示模块标签组 |
| 布局门控 | `frontend/src/layouts/MainLayout.tsx` | `wsFeatures` ← `workspaceModulesFeatures`；质量检查页签恒显（D4）；重定向 / 落地段扩 design；工作区菜单与兜底跳转去掉硬编码 `/tables`（边界 #6） |
| 质量检查页 | `frontend/src/pages/pipelines/` | GitHub 风格双栏（D4）：左栏流水线规则清单（列表 / 新建入口），右栏选中规则（或未选中时全部）的运行结果历史（run 列表 → finding 明细）；目录为空给「暂无可用检查动作」提示 |
| 帮助文档 | `frontend/src/pages/help/content/configuration.tsx`、`quickStart.tsx` | 「三选一」文案改「按需勾选模块」 |
| 测试迁移 | `frontend/src/utils/workspaceType.test.ts` 等 | 同步改为 `workspaceModules.test.ts`，断言不放宽 |

### 7. 测试清单

**判定层（单测）**：`tests/test_workspace_modules.py` —— 绑定表全分支（7 种非空组合的 features 矩阵）、`legacy_type_to_modules` 三值映射、空集 / 未知值 / 重复 / 乱序输入的校验器行为（I1）。

**接口层**：`tests/test_workspace_modules_api.py` —— 创建 / 更新各组合落库与响应字段、空集与非法值 422、`pipelines/checks` 目录按模块过滤、DSL 保存含禁用域动作 400、`validate` 同款、存量流水线仍可运行（边界 #3）。

**迁移 / 备份**：`tests/test_workspace_modules_migration.py`（幂等 + downgrade 有损映射断言 + 回填映射逐值核对）、`tests/test_workspace_backup_v12.py`（v12 往返含 modules；v11 及更早旧备份导入按映射回填；未知旧枚举回退全三并记 errors）。

**前端单测**：`workspaceModules.test.ts`（与后端矩阵逐项对齐，I3）、`WorkspaceList.test.tsx`（卡片式勾选交互、至少一项阻断、模块标签）、`WorkspaceSettingsContent.test.tsx`、`PipelinesPage.test.tsx`（双栏布局：左规则清单、右运行历史；目录为空提示）、`MainLayout.test.tsx`（各组合页签集合、未开放段重定向、仅设计工作区落地 `/design` 且质量页签仍在）。

**e2e（前端）**：`frontend/tests/e2e/critical/workspace-modules.spec.ts` —— 新建工作区仅勾「文档 + 设计」→ 顶部页签断言（无数据表 / 数据分析 / 数据源同步）→ 质量检查页签仍显示且目录为空有提示 → 设置页取消「文档」→ 自动重定向到 `/design`。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `WorkspaceModule` 常量与模型列 + `modules.py` 判定入口 + schema 校验器 + API 替换 + 迁移（幂等 / downgrade）+ pipeline 目录过滤与保存域校验 + 备份 v12 / 旧版映射 + 后端测试 | 低 |
| **P1** | 前端 `workspaceModules.ts` + API 类型 + 创建 / 设置卡片式选型（D8）+ 列表卡片标签 + MainLayout 页签门控 / 落地 / 重定向 + 质量检查页 GitHub 风格双栏（D4）+ 前端单测 | 中（MainLayout 门控分支多，组合用例须覆盖 7 种组合；双栏页交互重构） |
| **P2** | 帮助文案、CONTEXT.md 术语与 ADR 索引回填、e2e 收口、全仓 `workspace_type` 残留清理 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 单选枚举 → 模块集合 + 声明式绑定表：`modules` 白名单集合落库，模块→功能映射收敛为前后端各一处常量表（C1/C3） | 7 种非空组合全可达；C3 后续为文档 / 设计加子模块只改绑定表，零迁移（Context #1 核心缺陷） | 扩枚举组合值（组合数随模块数阶乘增长，不可扩展）；三个布尔列（绑定关系无法声明，校验逻辑散落查询两侧） | `workspaces/models.py`、`workspaces/modules.py`、`frontend/src/utils/workspaceModules.ts` |
| D2 | 存储载体与 API 兼容 | `modules` JSON 列（对齐 `tags` 先例），drop 旧列；API 直接替换 `workspace_type` 不双写（C6） | 前后端同仓同发，无双端漂移；白名单由校验器保证（I1）；双字段会形成双真相源 | 保留枚举列兼容双写（双真相源必然漂移，违背 I2）；bitmask 整型（不可读、白名单与顺序校验弱） | `workspaces/models.py`、`schemas/models.py`、`routers/workspaces.py` |
| D3 | 强绑定口径 | analytics / datasource 是 tables 的派生功能：不进勾选 UI、不进 API 字段，仅由绑定表推导（C2/I5） | 用户原文即强绑定；派生口径杜绝「有分析无数据表」的非法中间态 | 四项独立勾选（可造非法态，且与需求相悖）；分析 / 同步单独成模块（需求明确绑定） | `modules.py::MODULE_FEATURES` |
| D4 | 质量检查归属与页面形态 | 保留集中页签且**所有工作区恒显**（评审拍板：仅设计工作区也显示，为后续 design 域检查动作预留入口）；页面改 GitHub 风格双栏——左侧流水线规则清单、右侧检查结果历史；目录按模块过滤，保存 / 校验期拒绝禁用域动作（C4） | ADR 0076 D11 已定「检查天然跨域，应集中」；恒显消除「doc 型有文档检查却整页签关闭」的不一致（Context #9）且让空目录工作区有明确入口；域前缀现成可推导（Context #10/#11）；双栏参考 GitHub Actions 左 workflow 清单右运行历史的布局 | 分散为表级 / 文档级 / 设计级入口（丢跨域编排——流水线 DSL 的 `jobs` 可混合域动作，分散后无法建跨域流水线）；仅 tables/documents 开（仅设计工作区无入口，后续加 design 域动作时需再改门控）；维持现状仅 tables 开（doc 型文档检查永不可达） | `pipeline/services/checks/`（`domain_of` + 断言）、`routers/workflows.py`、`MainLayout.tsx`、`frontend/src/pages/pipelines/` |
| D5 | 存量映射 | `data_doc → [tables, documents, design]`、`data → [tables]`、`doc → [documents, design]`（C6/I3） | 按现行 feature 矩阵逐项平移（`workspaceType.ts:49-54`），迁移前后行为零变化 | `doc → [documents]`（会移除现 doc 型已开放的设计页签，行为回退，违背 I3）；全部映射为全三模块（data 型凭空多出文档 / 设计入口） | 迁移 `b6c7d8e9f0a1`、`modules.py::legacy_type_to_modules` |
| D6 | 迁移与 downgrade | 单条迁移：加列 → CASE 回填 → 置非空 → drop 旧列；downgrade 有损映射（tables+documents→DATA_DOC、tables→DATA、其余→DOC）仅在回滚路径接受（C6） | 纯列变更存量零丢失语义；有损 downgrade 换取模型单真相（D2） | 无损 downgrade（需长期保留旧列，与 D2 单真相源冲突） | `alembic/versions/b6c7d8e9f0a1_workspace_modules.py` |
| D7 | 备份协议 | v12：workspace 元数据写 `modules`；≤v11 导入读旧 `workspace_type` 按 D5 映射；未知旧值回退全三并记 `errors`（C6/I4） | 协议逐版本演进有 v9→v10→v11 先例（ADR 0079 D9）；映射函数与迁移共用一份 | v11 内混装新字段（协议版本语义混乱）；备份不存 modules（跨环境导入丢模块口径，回退默认全开违背 I3） | `workspace_backup.py`、`workspace_restore.py`、`routers/workspaces.py` |
| D8 | 默认值、空集与选型 UI | 新建默认三模块全选（等价旧默认 data_doc，评审拍板）；`modules` 至少一项，空集 422；选型 UI 采用卡片式勾选（模块图标 + 名称 + 一句话说明，点击整卡切换选中态），创建弹窗与工作区设置同款（C1） | 与现行默认行为对齐；卡片式比裸 Checkbox 传达「勾了会开放什么」，降低误配 | 允许空集（无落地页可去，重定向死循环）；默认仅数据表（与现默认 data_doc 不符，升级后新建行为突变）；裸 Checkbox.Group（无说明文字，强绑定的分析 / 同步不直观） | `schemas/models.py` 校验器、`WorkspaceList.tsx` 初始值、`WorkspaceSettingsContent.tsx` |
| D9 | 前端门控入口与落地段 | `workspaceType.ts` 整体替换为 `workspaceModules.ts`；落地段顺序 tables → documents → design；页签顺序 数据表 → 文档 → 设计 → 数据分析 → 数据源同步 → 质量检查 → 工作区设置（C5） | 旧输入类型（WorkspaceType）已不存在，兼容层无消费方；设计页签排位沿用 ADR 0079 D8（文档之后） | 保留旧函数签名包一层（死代码）；落地段固定 tables（纯文档 / 纯设计工作区首屏必被重定向） | `frontend/src/utils/workspaceModules.ts`、`MainLayout.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：三模块 7 种非空组合全可达，工作区功能范围真正按需裁剪；模块→功能绑定声明式收敛（前后端各一处），文档 / 设计后续子模块零迁移扩展；质量检查门控顺带修复 doc 型不一致（Context #9）；「数据表强绑定分析 / 同步」由派生口径从根上杜绝非法组合。
- **负向**：API 破坏性替换 `workspace_type`（同仓同发可控，但外部脚本若有引用需同步）；downgrade 有损（仅回滚路径，I4 已声明）；`modules` 为 JSON 列，数据库层无外键级白名单（由校验器单点保证，I1）。
- **风险与缓解**：MainLayout 门控分支多、组合用例面大 → 判定层 7 组合矩阵前后端逐项对齐测试（I3）兜底；旧备份未知枚举值 → 回退全三模块并记 `errors`，不静默（边界 #4）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | Notion（Teamspaces） | 飞书（知识库 / 多维表格） | 本设计 |
|---|---|---|---|
| 工作区功能组合 | 模板 + 页面组件自由拼装 | 独立应用形态，功能由应用类型先天决定 | 模块勾选 + 派生绑定（D1/D3） |
| 范围裁剪粒度 | 页面级权限 | 应用级开关 | 工作区级模块集合，子功能随主模块派生（D3） |

来源：Notion 帮助中心（Teamspaces，notion.so/help）；飞书帮助中心（feishu.cn/help）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 质量检查入口 | `MainLayout` 页签 | 集中页签保留，门控改自适应（tables ∥ documents），修正 doc 型不一致 | ADR 0076 D11 / 本 ADR D4 |
| 设计模块门控 | 类型 feature 矩阵 | `design` feature 改由模块集合推导；doc 型仍开（映射平移，行为不变） | ADR 0079 D8 / 本 ADR D5 |
| 备份协议演进 | `payload/backup.json` | v12 增 `modules`，≤v11 兼容导入不破坏 | ADR 0075 / 0079 D9 / 本 ADR D7 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：评审通过（2026-11-01，用户逐项拍板 5 项未决问题，C4/D4/D8 按拍板修订），`Accepted`——进入实现，按 P0 → P1 → P2 推进、每期一提交
- 已完成：需求卡片 `docs/requirements/0080-workspace-module-selection.md`（C1-C6，未决问题全部有结论）、本 ADR（D1-D9，无待定项）、`docs/adr/README.md` 索引、`CONTEXT.md` 术语「工作区模块」
- 评审拍板结论：① 质量检查集中 + 页签恒显 + GitHub 风格双栏（左规则清单 / 右结果历史）；② 仅设计工作区也显示质量页签（后续加 design 域动作）；③ 存量映射认可（D5）；④ API 不保留 `workspace_type` 兼容字段（D2）；⑤ 新建默认三模块全选 + 卡片式选型 UI 优化（D8）
- 下一步：`implementer` 按 §8 分期实现，P0（后端模型 / 迁移 / API / 备份 v12 / pipeline 过滤与域校验）→ P1（前端全套）→ P2（帮助 / e2e / 残留清理 / 落地表回填）
- 已知坑：SQLite 列变更须走 `batch_alter_table`；JSON 列 server_default 不可移植，回填必须走迁移 UPDATE；`MainLayout` 重定向 effect 依赖 `currentWs`，设置页改勾选后自动触发重定向（测试须覆盖）；本机跑测试须先清空 `LD_LIBRARY_PATH`（trae 服务器旧 libsqlite3 遮蔽系统库）
- 最近一次全绿：`make check-docs` @ `95641259`（2026-11-01，仅文档变更，L0 门禁）
