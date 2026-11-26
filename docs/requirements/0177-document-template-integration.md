# 0177 文档模板整合（S2）

- 编号：0177
- 来源 / 提出人：用户（会话 2026-11-26，先做整合分析，确认「C 方案 + 直白命名 + 文档记住排版模板」）
- 日期：2026-11-26
- 关联 ADR：`docs/adr/0177-document-template-integration.md`
- 状态：已实现（2026-11-26 P0–P3 全部落地，待提交；ADR 0177 落地状态与交接已回填）

> 本卡片是需求原文与约束编号的唯一副本：ADR 只引用 C1..Cn，不复制原文；需求变更先改本卡片，再改 ADR 与代码（H26）。

## 需求原句（逐字）

> 同时存在内容模板和导出模板，请分析如何整合二者，给出最佳实践建议

> 1C,2直白，3做

对应的三项决策（会话内确认，落在 C1 / C2 / C6）：

1. 「1C」= 采用分析中的 **C 方案**：`documents_exporttemplate` 与 `documents_contenttemplate` **不合并为一张表**，改为「模型双表 + 契约/UI 收敛」。
2. 「2直白」= 页签命名取**直白**一套：「导出模板」/「内容模板」（不取「排版模板」）。
3. 「3做」= **要做**「文档记住排版模板」：内容模板可绑定一份排版模板，「从模板新建」建出的文档记住该绑定，导出时默认用它。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「1C」 | **不合并表**：`documents_exporttemplate`、`documents_contenttemplate` 两张表及其语义边界保持独立；ADR 0152 的 I2（默认锚点 `research`）/ I4（内置只读）与需求 0169 的「无内置行、无默认锚点」逐条不放宽 | `documents/models.py` | 既有 `tests/test_export_templates.py`、`tests/test_documents_content_templates.py` 断言不改即全绿 |
| C2 | 「2直白」 | 文档区二级页签 `templates` 的 label 由「模板」改「**导出模板**」，`content-templates` 保持「内容模板」；两页页头副标题、空态、Doc 树/帮助文案统一为该口径（排版模板 = 导出 Word / PDF 的版式；内容模板 = 从模板新建文档的正文骨架） | `frontend/src/layouts/MainLayout.tsx`、两页页头 | 前端单测（页签文案、页头可见）+ `docs/USER_DOC_MAP.md` 与帮助文案同步 |
| C3 | 「整合二者」 | **前端单页双区**：`/w/:wid/documents/templates?kind=export\|content` 一个模板页承载两类模板（沿用仓库既有 `?section=` 范式）；旧路由 `/documents/content-templates` 保留为**重定向**（深链不断、右键新开可用） | `frontend/src/App.tsx`、`MainLayout.tsx`、`pages/documents/DocumentTemplatesPage.tsx` | 前端单测：`?kind=` 切换分区、旧路径重定向到 `?kind=content`、页签激活态正确 |
| C4 | 「整合二者」 | **后端公共契约层**：抽 `services/templates_common.py` 承载「工作区内名称唯一 + 并发重名转 400 + 跨工作区 404 + 列表 envelope」，两套服务共用；列表统一返回 `{items, total, default_ref?}`；更新动词两侧**同时接受** `PUT` 与 `PATCH`（只加不删，存量消费者不受影响） | `documents/services/templates_common.py`（新增）、`export_template_store.py`、`content_templates.py`、两个 router | 接口单测：两套端点行为一致（重名 400 文案、跨区 404、PUT/PATCH 等价） |
| C5 | 「整合二者」 | **能力对齐**：内容模板补齐导出模板已有的四件套——JSON 导入 / 导出（`kind=cndb-content-template` / `version=1`，与排版模板的 `cndb-document-template` **互不兼容且明确报错**）、创建副本、Markdown 预览、拖拽排序 | `frontend/src/pages/documents/*`、`api/contentTemplates.ts`、`services/content_templates.py`、router | 前端单测（导入 / 导出 / 副本 / 排序）+ 接口单测（副本端点） |
| C6 | 「3做」 | **文档级排版模板绑定**：`documents_document.export_template_ref`（可空）与 `documents_contenttemplate.export_template_ref`（可空）两列；内容模板绑定后，「从模板新建」建出的文档继承该 ref；导出解析链扩为「显式 `template` 参数 → 文档绑定 → 工作区默认 → 内置 `research`」 | `models.py`、`services/export/templates.py`、`routers/documents.py`（`PATCH /{doc_id}` + `GET /{doc_id}/export`）、新建入口 | 接口单测：绑定生效 / 显式参数优先 / 建文档继承 / 未绑定行为不变 |
| C7 | 「3做」 | **绑定 fail-safe**：文档绑定指向的模板被删 / 跨工作区 / 格式非法时，导出**静默回落**到工作区默认（不报错、不区分失败原因，防模板存在性泄漏）；写入口（`PATCH /{doc_id}`、内容模板 CRUD）提交非法 ref 一律 400 | `services/export/templates.py`、两个 router | 接口单测：删除绑定模板后导出仍 200 且用默认；跨区 id 绑定写入 400 |
| C8 | （迁移 / 备份） | 单条 alembic 迁移新增两列（可空、无默认值），存量零迁移、downgrade 可还原（H13）；`documents[]` 与 `content_templates[]` 备份清单各增一字段，旧包缺键按 `None` 还原（H14），**不升备份版本号**（沿用需求 0169 的兼容口径） | `alembic/versions/`、`workspace_backup.py`、`backup_io.py` | 迁移单测（往返 + 存量库升级无数据变更）+ 备份往返 / 旧包兼容用例 |
| C9 | （不回归） | 权限口径走 `resolve_capabilities`（H64）：模板读 = 成员、写 = editor+；文档绑定写与建文档同口径；模板不进文档可见性过滤（H33），绑定字段不参与 H33 判定 | 两个 router、`documents/router` | 既有 H64 / H33 用例全绿 + 新增越权用例 |
| C10 | （设计约束） | 断点只用 `767.98` / `575.98px`；间距 / 字号 / 颜色只用 `--cn-*` token；线条 `--cn-border`；选中态 `--cn-bg-selected`；页面根 `.cn-page`（H24 / H25 / H29 / H30） | 新页面 / 弹层样式 | `mobileCaliber.test.ts`、`make check-frontend` |
| C11 | （测试 / 文档） | 同轮补迁移 / 备份 / 接口 / 前端单测；`CHANGELOG.md` 增条目（带 `(ADR 0177 Pn)`）；`CONTEXT.md` 合并术语、`USER_DOC_MAP.md` 与帮助教程改两个 L3 小节；本卡片与 ADR 回填落地结果 | `tests/`、`frontend/src/**/*.test.tsx`、`docs/` | `make flow` / `make test` 全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导出模板模型 | `src/cndb/plugins/documents/models.py:444` | C1 不改语义，C6 只加引用列 |
| 2 | 内容模板模型 | `src/cndb/plugins/documents/models.py:476` | C1 不改语义，C6 加引用列 |
| 3 | 导出解析唯一入口 | `src/cndb/plugins/documents/services/export/templates.py:699` | C6 / C7 |
| 4 | 导出模板服务 | `src/cndb/plugins/documents/services/export_template_store.py` | C4 |
| 5 | 内容模板服务（重名 / 404 重复实现） | `src/cndb/plugins/documents/services/content_templates.py:97,132` | C4 |
| 6 | 两个 router 的 `_require_member` 重复 | `routers/templates.py:42`、`routers/content_templates.py:27` | C4 |
| 7 | 文档导出端点 | `src/cndb/plugins/documents/routers/documents.py:856` | C6 |
| 8 | 文档元数据更新端点 | `src/cndb/plugins/documents/routers/documents.py:1326` | C6 / C7 |
| 9 | 新建文档服务 | `src/cndb/plugins/documents/services/content.py::create_document` | C6 |
| 10 | 导出模板面板（1408 行、仍在 settings 目录） | `frontend/src/pages/settings/TemplatePanel.tsx` | C3 |
| 11 | 内容模板页 | `frontend/src/pages/documents/DocumentContentTemplatesPage.tsx` | C3 / C5 |
| 12 | 页签定义与激活态 | `frontend/src/layouts/MainLayout.tsx:96,97,567-575` | C2 / C3 |
| 13 | 备份 / 恢复 | `workspace_backup.py:662,807`、`backup_io.py:1151,1213` | C8 |
| 14 | 帮助与术语 | `CONTEXT.md`、`docs/USER_DOC_MAP.md:51-52`、`frontend/src/pages/help/content/tutorials.tsx:681` | C2 / C11 |

## 不做

- 合并两张模板表（C1 明确否决，见 ADR D1）。
- 给内容模板加内置预设行 / 工作区级默认锚点（守住需求 0169 的口径；如需要另立卡片）。
- 改导出模板的视觉参数结构、内置 6 套预设内容、`resolve_export_template` 的既有回落链终点（`research`）。
- 模板跨工作区复用 / 分享（BACKLOG 已判与工作区隔离口径冲突）。
- 文档级绑定参与导出模板的「默认唯一」约束（`is_default` 仍是工作区级唯一，不受文档绑定影响）。

## 未决问题

- [x] 方案选型（A 只改名 / B 合表 / C 共享契约）→ C（C1）
- [x] 页签命名 → 直白（导出模板 / 内容模板）（C2）
- [x] 是否做文档级绑定 → 做（C6 / C7）
- [x] C7 的「绑定静默回落、不泄露模板存在性」已登记为跨需求不变量 **H68**（`docs/CONSTRAINTS.md`）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题结论已由需求方确认；H65 顺延编号为 H68 并已登记
