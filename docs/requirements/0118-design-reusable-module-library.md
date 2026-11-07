# 需求卡片：结构设计 DSL 可复用模块管理与跨工作区引用

- 编号：0118（对应 ADR `docs/adr/0118-design-reusable-module-library.md`）
- 来源 / 提出人：用户（2026-11-07 会话提出）
- 日期：2026-11-07
- 关联 ADR：ADR 0118（立项后回填）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对结构设计DSL的可复用模块管理制定方案，允许跨工作区引用复用模块。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 可复用模块管理 | 零件设计文件可「发布」为复用模块；发布产物为**不可变版本**，含模块标识、公开参数签名与自包含依赖包；支持检索、查看版本与归档 | `design` 插件、新全局表 `design_library_module` / `design_library_version` | 判定层 / 接口层测试：发布、重复发布递增版本、归档后拒绝新引用 |
| C2 | 允许跨工作区引用复用模块 | DSL `use` 支持库引用形式 `use "lib:<module_key>@<version>"(参数…) as <标签>`；解析不再限定当前工作区 | `design/services/dsl/{lexer,parse,compile}.py`、`design/services/files.py` | DSL 单测：库引用解析、缺失版本 / 未知 key / 归档模块诊断 |
| C3 | 可复用模块管理 + 跨工作区引用 | 库引用必须**显式锁定版本**；使用方升级版本是显式动作，发布新版本不自动改变已保存设计 | `design/services/files.py`、`design/routers.py` | 接口层：发布 v2 后旧引用 IR 不变；升级后落新版本 |
| C4 | 允许跨工作区引用复用模块 | 可见性二档：`public`（所有登录用户可检索 / 可跨工作区引用）、`workspace`（仅所有者工作区成员可见，不可跨工作区引用）；越权访问按 404 | `design/routers.py`、权限判定 | 权限测试：私有模块跨工作区引用拒绝、公开模块任意成员可用 |
| C5 | 可复用模块管理 | 模块版本不可修改；归档模块不能被新引用，但已被引用的锁定版本必须继续可编译 | `design/models.py`、`design/services/files.py` | 接口层：归档后既有设计打开 / 刷新 / 版本恢复仍成功 |
| C6 | 可复用模块管理 | 发布产物自包含：发布时快照根零件及其依赖闭包；引用方编译只从快照解析，禁止回落到使用方同名 `file_key` | `design/services/dsl/compile.py`、`design/services/files.py` | 判定层：使用方存在同名零件时仍按快照编译；快照缺失报诊断 |
| C7 | 可复用模块管理 | 编译预算沿用依赖闭包累计口径（1MB / 64 文件 / 深度 8 / 图元 2000 / module+system 256），库快照同样计数 | `design/services/dsl/limits.py`、`compile.py` | 判定层：库快照使闭包超限报诊断 |
| C8 | 可复用模块管理 | 引用关系进入依赖快照与当前引用索引；依赖面板展示库引用来源、锁定版本与升级可用性 | `design_designref` / 新 `design_libraryref`、`DesignEditorPage`、`DesignConstraintsPanel` 同级依赖 UI | 接口层 + 前端单测 |
| C9 | 允许跨工作区引用复用模块 | 工作区全量备份 / 恢复内置已锁定模块快照，恢复到无该模块的环境仍可编译 | `workspace_backup.py`、`backup_io.py`、新 `design_library_vendor` 表 | 备份往返测试 + 跨环境恢复测试 |
| C10 | 可复用模块管理 | 前端提供复用模块库入口、发布入口、库引用插入与只读版本预览 | `frontend/src/pages/design/`、`frontend/src/api/design.ts` | 前端单测 + e2e |
| C11 | 可复用模块管理 | 不破坏既有同工作区 `use "<file_key>"` 语义、版本快照、种子与旧备份兼容 | `design/`、`workspace_backup.py` | 回归：既有 design 测试全绿、v13 备份导入成功 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 设计文件身份与唯一键只到工作区级 | `src/cndb/plugins/design/models.py:33-74` | 无全局模块实体，`file_key` 仅工作区唯一 |
| 2 | resolver 只查当前工作区 | `src/cndb/plugins/design/services/files.py:64-128` | 跨工作区同名 key 视为缺失（ADR 0086 边界 §5.4） |
| 3 | `use` 只接受字符串 key，无版本 / 来源概念 | `src/cndb/plugins/design/services/dsl/parse.py`、`compile.py:610-637` | 需区分本地文件与库引用 |
| 4 | 依赖快照只含工作区 `file_id` | `src/cndb/plugins/design/models.py:61-62`、`routers.py:240-250` | 备份恢复按 `file_id` 重映射，无法表达库模块 |
| 5 | 引用索引只记录工作区内引用方 | `src/cndb/plugins/design/models.py:116-141`、`routers.py:261-273` | 跨工作区「谁引用了我」与删除 / 归档判定缺失 |
| 6 | 删除被引用文件 409 只看同工作区 | `src/cndb/plugins/design/routers.py:581-600` | 库模块需要归档而不是删除 |
| 7 | 备份 designs 段只有工作区文件 | `src/cndb/plugins/workspaces/services/workspace_backup.py:570-625` | 恢复后库引用可能断链 |
| 8 | 编辑器依赖面板 / 侧栏只认 `file_id` | `frontend/src/pages/design/DesignStructureNav.tsx`、`DesignsPage.tsx`、`frontend/src/api/design.ts` | 库节点无源文件可打开，需只读版本页 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 引用语义：发布快照 + 按版本引用（需求方 2026-11-07 确认，结论见 ADR 0118 D1）
- [x] 可见范围：公开 + 工作区私有（需求方 2026-11-07 确认，结论见 ADR 0118 D4）
- [x] 版本策略：显式锁定版本、可手动升级（需求方 2026-11-07 确认，结论见 ADR 0118 D5）
- [x] 备份口径：备份内置已锁定快照（需求方 2026-11-07 确认，结论见 ADR 0118 D9）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
