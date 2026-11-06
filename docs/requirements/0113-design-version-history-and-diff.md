# 需求卡片：设计结构版本历史区分主动保存 / 自动小版本与版本 DIFF

- 编号：0113（与 ADR `docs/adr/0113-*.md` 同号）
- 来源 / 提出人：用户（产品需求）
- 日期：2026-11-06
- 关联 ADR：`docs/adr/0113-design-version-history-and-diff.md`（Proposed）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 设计结构的版本历史保存策略不友好，不好进行区分，应当区分用户主动保存的版本和自动保存的小版本，并且需要增加更友好的版本DIFF设计。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「应当区分用户主动保存的版本和自动保存的小版本」 | 版本记录落库区分来源类型（至少 `manual` / `auto`；依赖刷新与回滚可另设 `refresh` / `rollback`），列表 / 详情接口与前端均可读取该类型 | `plugins/design/models.py`、`schemas.py`、`routers.py` | `tests/test_design_api.py`：保存 / 自动保存 / 恢复各自落对应类型 |
| C2 | 「自动保存的小版本」 | 编辑器增加自动保存：编辑停止输入 3 秒（debounce）且编译通过、内容有变化时落一个 `auto` 版本；编译失败或内容无变化不落版本、不覆盖当前态，错误在编辑器可见 | `frontend/src/pages/design/DesignEditorPage.tsx`、`src/cndb/plugins/design/routers.py` | 前端单测（触发 / 跳过 / 失败保留草稿）、接口层测试 |
| C3 | 「不好进行区分」 | 版本编号口径：主动保存与自动小版本共用 `version_number` 序列，以 `change_type`（`manual` / `auto` / `refresh` / `rollback`）区分；自动保存同时推进当前内容态与最新版本号 | `routers.py`、`frontend/src/pages/design/*` | 版本列表断言编号连续、类型正确、当前版本号随自动保存推进 |
| C4 | 「不好进行区分」 | 版本历史面板按类型做视觉区分（主动保存为里程碑、自动保存为弱化小版本）；自动版本全量保留，UI 将连续自动版本折叠为「N 个自动小版本」并可展开 | `frontend/src/pages/design/DesignEditorPage.tsx`、`index.css` | 前端单测 + e2e 版本历史用例（折叠 / 展开 / 类型徽标） |
| C5 | 「增加更友好的版本DIFF设计」 | 新增两版本对比端点（`base` / `head` 版本号），返回 unified diff、增删行数与结构变化摘要（参数 / 节点 / 装配层级）；复用文档端的 diff 能力与权限口径 | `src/cndb/plugins/design/routers.py`、`schemas.py`、`services/`（复用 `documents/services/parse.py:unified_diff`） | `tests/test_design_api.py`：diff 正确性、结构摘要、404、只读成员可读 |
| C6 | 「更友好的版本DIFF设计」 | 版本历史支持任选两版对比（默认本版 vs 上一版），前端复用 `components/DiffView` 的统一 / 并排模式、双端行号、行内高亮与增删统计；结构变化摘要置于文本 diff 之前 | `frontend/src/pages/design/DesignEditorPage.tsx`、`components/DiffView/` | 前端单测覆盖摘要 / diff 展开收起 / 空差异；e2e 版本 DIFF 用例 |
| C7 | 隐含（只读与权限） | `viewer` 可查看版本与 DIFF，不可自动保存 / 手动保存 / 恢复；自动保存遵守 editor 权限 | `routers.py` 权限依赖、前端只读态 | 接口 403 用例 + 前端只读用例 |
| C8 | 隐含（草稿不丢） | 自动保存失败或编译失败时编辑器草稿保留，不静默丢弃，状态提示可见 | `DesignEditorPage.tsx` | 前端单测：失败后内容仍在且错误可见 |
| C9 | 隐含（存量兼容） | 存量 `design_designversion` 行迁移后默认视为 `manual`；迁移幂等且 `downgrade` 可还原，存量零迁移 | `src/cndb/alembic/versions/` | 迁移测试：升级 / 降级 / 幂等 |
| C10 | 隐含（备份口径） | 新增字段 / 表纳入工作区备份与恢复；旧备份缺字段按缺省值还原 | `plugins/workspaces/services/backup_io.py`、`workspace_backup.py` | `tests/test_workspace_backup_v*.py` 往返 + 旧备份兼容 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 版本模型无来源类型字段 | `src/cndb/plugins/design/models.py:73-104` | `DesignDesignVersion` 仅有 `version_number` / `content` / `comment` |
| 2 | 唯一落版入口 | `src/cndb/plugins/design/routers.py:187-211`（`_add_version`） | 所有保存路径共用，需按来源传类型 |
| 3 | 主动保存 | `src/cndb/plugins/design/routers.py:432` | 目前每次保存即落一版，无自动保存 |
| 4 | 依赖刷新 / 版本恢复也落版 | `src/cndb/plugins/design/routers.py:468`、`632` | 需归类为 `refresh` / `rollback` 而非 `manual` |
| 5 | 版本列表 / 详情端点 | `src/cndb/plugins/design/routers.py:581,615` | 无 diff 端点、无类型过滤 |
| 6 | 版本响应 schema | `src/cndb/plugins/design/schemas.py:151-169` | 需补 `change_type` 与 diff 响应 |
| 7 | 前端编辑器保存 / 历史面板 | `frontend/src/pages/design/DesignEditorPage.tsx:198-241`、`580-670` | 目前仅手动保存 + 原文回看，无自动保存、无 diff |
| 8 | 前端设计 API | `frontend/src/api/design.ts:194-258` | 需补 diff 接口与类型字段 |
| 9 | 可复用 DIFF 视图 | `frontend/src/components/DiffView/DocumentDiffView.tsx`、`diffModel.ts` | 文档端已实现统一 / 并排 + 行内高亮 |
| 10 | 可复用 unified diff 判定 | `src/cndb/plugins/documents/services/parse.py:218-245` | 跨插件复用需确认依赖方向 / 抽公共位置（ADR 决策） |
| 11 | 文档版本区分先例 | `src/cndb/plugins/documents/models.py:141-163`（`change_type`）、`frontend/src/pages/documents/VersionsDrawer.tsx` | 设计端可对齐命名与交互口径 |
| 12 | 备份 / 恢复 | `src/cndb/plugins/workspaces/services/backup_io.py:1101-1200` | 设计版本表已进备份，新增字段需兼容旧备份 |
| 13 | 迁移 | `src/cndb/alembic/versions/z4a5b6c7d8e9_add_design_plugin.py` | 需新增幂等迁移 + downgrade |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 已确认口径（2026-11-06 需求方确认）

| # | 问题 | 结论 |
|---|---|---|
| Q1 | 自动保存触发时机 | 编辑停止输入 3 秒（debounce）；仅编译通过且内容有变化时落 `auto` 版本 |
| Q2 | 编号口径 | 共用 `version_number` 序列 + `change_type` 徽标；自动保存同时推进当前内容态与最新版本号 |
| Q3 | 自动版本保留策略 | 全量保留；UI 将连续自动版本折叠为「N 个自动小版本」，可展开查看与对比 |
| Q4 | DIFF 粒度 | 文本行级 unified diff + 结构变化摘要（参数 / 节点 / 装配层级），摘要先于文本 diff |
| Q5 | 跨插件复用 | 复用文档端 `unified_diff` 与 `components/DiffView`；抽取方式（公共工具 vs 依赖 documents 服务）由 ADR 决策 |

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方确认卡片（Q1-Q5 已确认，整卡已确认，进入 ADR 评审）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
