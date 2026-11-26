# 0169 文档内容模板（S1）

- 编号：0169
- 来源 / 提出人：用户（会话 2026-11-26，P0 分析后确认「先做 P0，P2」→「先做 4 项 S1」）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；数据/迁移 H13/H14，备份 H14，设计 H24/H25/H29/H30，权限 H64）
- 状态：已确认范围（2026-11-26 选择「先做 4 项 S1」；卡片约束待复核）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 请分析文档部分功能对照典型知识库应用，功能上还有哪些需补齐完善的。

> 先做 P0，P2。

> （P0 分析结论）内容模板：现有 TemplatePanel 是 docx/pdf **导出排版模板**，非「从模板新建文档」——补会议纪要/周报等内容模板 + 新建入口。

补充确认：本卡只做**内容模板**（新建文档时套用的正文骨架）；导出排版模板（`documents_exporttemplate` / ADR 0152）原样不动，两者独立不互相替代。

## 方案（口径）

**范围**：新增 `documents_contenttemplate` 表（工作区级内容骨架），配套 CRUD 路由、前端模板管理页、以及「从模板新建文档」入口。落库 + 迁移 + 备份往返（H13/H14）；不改正文存储、不改导出模板、不改双链语法。

**数据模型**（新表）：`id`、`workspace_id`、`name`（工作区内唯一）、`content_markdown`（模板正文，Markdown）、`description`（可选说明，落地时由方案中的 summary 改名，避免与文档摘要 `Document.summary` 混淆）、`icon`（emoji/短标识，可选）、`sort_order`、`created_by_id`、`created_at`、`updated_at`。唯一约束 `(workspace_id, name)`。无 `is_default`（默认锚点会牵扯导出模板口径，本卡不引入）。

**权限**：模板读写沿用工作区角色（`resolve_capabilities` 的 `data_role`，H64）；建模板需 write，用模板建文档走现有 `create_document` 的 `require_editor`（已生效，不新开写路径）。模板本身不参与文档可见性 H33（它是配置，不是文档）。

**新建入口**：文档列表「新建」下拉增加「从模板新建」→ 模板选择弹层（只读列表 + 搜索）→ 选中后以 `content_markdown` 作为初始正文调用现有 `create_document`，跳转到编辑器。草稿态/直接写入口径与现有新建一致。

**内置模板**：不预置内置行（避免与导出模板「内置不可变」口径混淆）；空态引导用户自建首个模板。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「从模板新建文档」 | 新增 `documents_contenttemplate` 表及 alembic 迁移；字段见方案；存量零迁移、downgrade 可还原（H13） | `models.py`、新迁移 | 迁移单测：upgrade/downgrade 往返、唯一约束、存量库升级无数据变更 |
| C2 | 「模板 CRUD」 | 新增 `GET/POST/PATCH/DELETE /{workspace_id}/document-content-templates`；写操作走工作区 write 门控（H64） | `routers/`（新）、`schemas/`（新） | 接口单测：增删改查、越权 404/403、重名校验 |
| C3 | 「备份」（H14） | 新表纳入 `backup_io`：备份含 `content_templates[]`，恢复覆盖重建，旧备份（无该键）按缺省还原 | `workspace_backup.py`、`workspace_restore.py` | 备份往返测试：新备份还原一致；旧备份兼容用例不改即全绿 |
| C4 | 「从模板新建文档」入口 | 文档列表「新建」增「从模板新建」→ 模板选择弹层 → 以模板正文调 `create_document` 建文档并跳转；保存口径与直接新建一致 | `DocumentsPage.tsx`、`api/documents.ts`（或新 api 封装） | 前端单测：入口可见、选中模板后建文档携带正确正文、草稿口径不回归 |
| C5 | 「会议纪要/周报等内容模板」 | 模板管理页（文档区二级页签「内容模板」或现有「模板」页新增分区）支持新建/编辑/删除/排序；正文为 Markdown，用现有 `MarkdownLiveEditor` 编辑 | 新页面 / `TemplatePanel.tsx` 分区 | 前端单测：CRUD 交互、Markdown 正文保存、无内置行时空态引导 |
| C6 | （导出模板不回归） | `documents_exporttemplate`、ADR 0152 内置 6 套模板、导出入口与 UI 逐项不变 | `models.py`、`routers/templates.py`、`DocumentTemplatesPage.tsx` | 既有导出模板用例不改断言即全绿 |
| C7 | （可见性/权限不回归） | 模板不进文档可见性 H33 过滤；用模板建文档后的可见性与直接新建逐条一致；工作区判定走 `resolve_capabilities`（H64） | 路由 / 服务 | 接口单测 + 既有 H33/H64 用例全绿 |
| C8 | （设计约束） | 断点只用 767.98/575.98px；间距/字号/颜色只用 `--cn-*` token；线条用 `--cn-border`；选中态 `--cn-bg-selected`（H24/H25/H29/H30） | 新页面 / 弹层样式 | `mobileCaliber.test.ts`、`make check-frontend` |
| C9 | （测试 / 文档） | 同轮补迁移 / 备份 / 接口 / 前端单测；CHANGELOG 增条目；本卡回填落地结果 | 测试文件、`CHANGELOG.md` | `make flow` / `make test` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导出模板模型 | `src/cndb/plugins/documents/models.py:444 ExportTemplate` | C6 不改，仅对照 |
| 2 | 导出模板路由 | `src/cndb/plugins/documents/routers/templates.py` | C6 不改 |
| 3 | 文档创建服务 | `src/cndb/plugins/documents/services/content.py:233 create_document` | C4 复用 |
| 4 | 备份 / 恢复 | `workspace_backup.py`、`workspace_restore.py` | C3 |
| 5 | plugin 路由注册 | `src/cndb/plugins/documents/plugin.py` | C2 新路由挂载 |
| 6 | 前端新建入口 | `frontend/src/pages/documents/DocumentsPage.tsx` | C4 |
| 7 | 前端模板页 | `frontend/src/pages/documents/DocumentTemplatesPage.tsx`、`pages/settings/TemplatePanel.tsx` | C5/C6 |
| 8 | Markdown 编辑器 | `frontend/src/components/Document/MarkdownLiveEditor.tsx` | C5 复用 |

## 不做

- 改导出模板（`documents_exporttemplate` / ADR 0152）任何行为。
- 内置内容模板行、默认模板锚点、模板变量占位符（如 `{{date}}`）——如需另立卡片。
- 模板跨工作区复用 / 导入导出 / 分享。
- 块级结构模板（依赖 P0 块模型，后做）。
- 新依赖、部署变更。

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

## 落地结果

- 代码落点：
  - 后端 `models.py::ContentTemplate`（`documents_contenttemplate`）、迁移 `d9e0f1a2b3c5`；
  - `services/content_templates.py`（CRUD + `resolve_template_content`）、`routers/content_templates.py`（`GET/POST/PATCH/DELETE /{wid}/document-content-templates`）、`plugin.py` 挂载、schemas 两枚；
  - 备份 `workspace_backup.py` 增 `content_templates[]`、`backup_io.py::_import_content_templates`、`workspace_restore.py::clear_workspace_content` 清表；
  - 前端 `api/contentTemplates.ts`、`pages/documents/DocumentContentTemplatesPage.tsx`（文档区二级页签「内容模板」）、`DocumentsPage.tsx` 新建下拉「从模板新建」+ 模板选择弹层。
- 测试：后端 `tests/test_documents_content_templates.py` 8 例（CRUD / 重名 / 跨区 / 非成员 / 备份往返 / 旧包兼容 / 覆盖恢复 / 正文解析）；前端 `DocumentContentTemplatesPage.test.tsx` 6 例 + `DocumentsPageContentTemplate.test.tsx` 3 例（含「先开新建文件夹再取消」残留回归）；`make check-fast` 与 `pnpm check` 全绿。
- 体验补充：新建模板按现有清单生成唯一默认名（未命名模板 / 未命名模板 2…），删除走 Popconfirm 二次确认、切换未保存时弹确认；从模板新建弹层支持按名称/说明搜索，接口失败显示错误与重试而非空态。
- 提交 sha：432c771e。
