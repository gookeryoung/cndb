# 需求卡片：工作区类型改为可勾选功能模块与顶部导航适配

- 编号：0080（与 ADR `docs/adr/0080-workspace-module-selection.md` 同号）
- 来源 / 提出人：用户（2026-11-01 会话）
- 日期：2026-11-01
- 关联 ADR：`docs/adr/0080-workspace-module-selection.md`（立项即建，Status: Proposed）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请重构当前工作区类型设计和进入工作区后的顶部导航布局。工作区类型选择改为可勾选的模块，包括数据表、文档和设计三个功能模块，允许勾选其中任意项或多项。数据分析模块、数据同步和数据表功能模块强绑定。文档和设计的功能模块暂未确定，后续开发。质量检查模块是否分散到数据表、文档和设计当中，进行适应性设计。请针对工作区的展示形式该如何调整制定可行方案。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「工作区类型选择改为可勾选的模块，包括数据表、文档和设计三个功能模块，允许勾选其中任意项或多项」 | 工作区落库字段由单选枚举 `workspace_type`（data_doc/data/doc，共 7 种组合中仅 3 种可达）改为模块集合 `modules ⊆ {tables, documents, design}` 且非空；创建弹窗与工作区设置页改为卡片式模块勾选（图标 + 名称 + 说明，默认全选，至少勾选一项） | `workspaces` 插件（模型/迁移/schema/API）+ `frontend` 创建与设置页 | 后端：`tests/test_workspace_modules_*.py`（组合校验、空集 422）；前端：`WorkspaceList.test.tsx` / `WorkspaceSettingsContent.test.tsx` 勾选交互用例 |
| C2 | 「数据分析模块、数据同步和数据表功能模块强绑定」 | 勾选「数据表」即同时开放数据分析（`/analytics`）与数据同步（`/datasource`）页签；二者不提供独立勾选项，取消「数据表」即一并关闭；绑定关系以声明式绑定表维护 | `frontend/src/utils/workspaceModules.ts`（新增，替代 `workspaceType.ts`） | `workspaceModules.test.ts`：tables→analytics+datasource 联动断言 |
| C3 | 「文档和设计的功能模块暂未确定，后续开发」 | 本期文档/设计为独立单模块（无绑定子模块）；模块清单与绑定规则收敛为常量表（模块目录 + 模块→功能映射），后续为文档/设计新增子模块只改常量表，不改模型与迁移 | `workspaces` 插件 `modules.py`（后端唯一判定入口）+ `frontend/src/utils/workspaceModules.ts` | 判定层单测覆盖常量表全部分支 |
| C4 | 「质量检查模块是否分散到数据表、文档和设计当中，进行适应性设计」 | 质量检查按域拆分入口：数据表域 `/w/:wid/pipelines`、文档域 `/w/:wid/documents/pipelines`（文档区胶囊页签，留在文档上下文）；两域共享 GitHub 风格双栏页面（左规则清单 / 右结果历史），规则、动作目录、运行历史均带 `domain` 过滤；工作区级质量检查页签在文档 / 设计上下文隐藏（文档上下文由文档区胶囊页签承载；设计模块不承载质量检查入口，2026-11-02 用户口径），数据表段与设置段显示；检查动作目录按已启用模块 + 域过滤（动作名域前缀 `table/`、`document/` 对应模块），DSL 保存期拒绝已禁用域的动作 | `pipeline` 插件（`domain` 过滤 + 保存校验）+ `App.tsx` 文档域路由 + `MainLayout` 文档区页签 + 质量检查页按域复用 | 接口层：域过滤 / 未知域 400 / 模块未启用为空用例；前端：`PipelinesPage.test.tsx` 文档域用例、`MainLayout.test.tsx` 文档区页签跳转 |
| C5 | 「进入工作区后的顶部导航布局」调整 | 工作区页签按勾选模块渲染（一级模块在顶栏，需求 0081）；内容区二级页签顺序固定：数据列表 → 质量检查 → 数据分析 → 数据同步（2026-11-02 用户口径）；URL 落在未开放功能段时重定向到落地页（落地段取第一个可用模块：tables → documents → design）；侧栏形态沿用现有切换逻辑 | `frontend/src/layouts/MainLayout.tsx` | `MainLayout.test.tsx`：各模块组合的页签集合与重定向断言 |
| C6 | 「重构当前工作区类型设计」（存量兼容） | 单条迁移将存量枚举映射为模块集合：`data_doc → [tables, documents, design]`、`data → [tables]`、`doc → [documents, design]`；备份协议升 v12（workspace 元数据写 `modules`，v11 及更早按同一映射读旧字段）；API 响应以 `modules` 替换 `workspace_type`，前后端同仓同步切换不留双字段 | `workspaces` 插件（迁移/备份/恢复）+ 前端 API 类型 | 迁移幂等 + downgrade 用例；备份 v12 往返 + v11 旧备份导入用例 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 类型枚举与中文文案 | `src/cndb/plugins/workspaces/models.py:78-97` | `WorkspaceType` 三值枚举 + `WORKSPACE_TYPE_LABELS` |
| 2 | 落库列 | `src/cndb/plugins/workspaces/models.py:147-154` | `workspace_type` Enum 列，server_default DATA_DOC |
| 3 | 创建/更新/响应 schema | `src/cndb/plugins/workspaces/schemas/models.py:26,38,51` | 三个 schema 均带 `workspace_type` |
| 4 | 前端类型门控唯一入口 | `frontend/src/utils/workspaceType.ts:12-60` | label/hint/options/features switch/落地段，5 个 feature key |
| 5 | 顶部页签拼装与 URL 门控 | `frontend/src/layouts/MainLayout.tsx:240-292, 381-400` | `wsTabItems` 按 feature 过滤；未开放段重定向 |
| 6 | 创建弹窗单选下拉 | `frontend/src/pages/workspace/WorkspaceList.tsx:347-367` | `Select` + `WORKSPACE_TYPE_OPTIONS`；卡片类型标签 `456-510` |
| 7 | 工作区设置单选下拉 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx:386-405,521` | 同款 Select |
| 8 | 备份/恢复读写类型字段 | `src/cndb/plugins/workspaces/services/workspace_backup.py:153`、`workspace_restore.py:194`、`routers/workspaces.py:344-354,505-515` | 备份 v11 元数据含 `workspace_type`；恢复按旧值回填 |
| 9 | 质量检查页签门控 | `frontend/src/utils/workspaceType.ts:39-54` | quality 仅 tables 型开启（doc 型即使有文档检查也不显示） |
| 10 | 检查动作域前缀 | `src/cndb/plugins/pipeline/services/checks/registry.py:3-6` | 动作名 `域/动作`：table/* 4 个、document/* 3 个、design/* 暂无 |
| 11 | 历史迁移与链头 | `src/cndb/alembic/versions/e7f8a9b0c1d2_add_workspace_type.py`、链头 `z4a5b6c7d8e9` | 新迁移挂 design 迁移之后 |
| 12 | 帮助文档文案 | `frontend/src/pages/help/content/configuration.tsx`、`quickStart.tsx` | 提及工作区类型三选一 |
| 13 | 术语表 | `CONTEXT.md:44` | 「工作区类型（WorkspaceType）」词条需改写为模块词条 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（2026-11-01 用户拍板，全部有结论）

- [x] 质量检查集中还是分散 → **按域拆分入口**：数据表域 `/pipelines`、文档域 `/documents/pipelines`，共用双栏页面并按 `domain` 过滤规则 / 动作 / 运行历史（2026-11-01 修订：文档模块的质量检查不跳数据表段，两模块可用规则不同）
- [x] 仅勾选「设计」的工作区质量检查页签 → **不显示**（2026-11-02 用户口径：设计模块移除质量检查二级导航；文档段的质量检查由文档区胶囊页签承载，数据表 / 设置段页签仍在）
- [x] 存量映射 `doc → [documents, design]` → **认可**（按现行 feature 矩阵平移，行为零变化）
- [x] API 是否保留 `workspace_type` 兼容字段 → **不保留**（前后端同仓同发；旧数据兼容由迁移与备份映射承担）
- [x] 新建工作区默认勾选 → **三模块默认全选**，并优化工作区选型 UI 设计（卡片式勾选）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（均为提议结论，随 ADR 评审一并请需求方拍板）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
