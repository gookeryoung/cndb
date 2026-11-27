# ADR 0177: 文档模板整合（导出模板 / 内容模板双表并存，契约与入口收敛 + 文档级排版模板绑定）

Status: Implemented（2026-11-26 人工评审通过，含 H68 登记；P0–P3 已落地并提交）
Date: 2026-11-26
Related: `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/services/export/templates.py`、`src/cndb/plugins/documents/services/export_template_store.py`、`src/cndb/plugins/documents/services/content_templates.py`、`src/cndb/plugins/documents/routers/templates.py`、`src/cndb/plugins/documents/routers/content_templates.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/documents/ExportTemplatePanel.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`
需求卡片: `docs/requirements/0177-document-template-integration.md`（需求原文与约束编号的唯一副本）
上游：ADR 0152（导出模板）、需求 0169（内容模板）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；约束编号 C1..C11 一律引用卡片，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「1C」（C 方案） | 两张表**不合并**：只新增引用列与公共层，零表结构重构；ADR 0152 I2/I4 与需求 0169 的口径逐条保留（D1 / D2） |
| C2 | 「2直白」 | `DOCUMENT_SUBPAGES` 中 `templates` 的 label 改「导出模板」，`content-templates` 保持「内容模板」；页头副标题、空态、`CONTEXT.md`、`USER_DOC_MAP.md`、帮助教程同口径（D3） |
| C3 | 「整合二者」 | `/w/:wid/documents/templates?kind=export\|content` 单页双区；`/documents/content-templates` 重定向到 `?kind=content`；`kind` 是唯一分区来源，页签激活态由 pathname + query 共同判定（D4） |
| C4 | 「整合二者」 | 新增 `services/templates_common.py`：`ensure_name_free` / `commit_or_conflict` / `get_or_404` / `list_envelope`；两套服务与两个 router 复用；更新动词两侧同时接受 `PUT` 与 `PATCH`（D5 / D6） |
| C5 | 「整合二者」 | 内容模板补 JSON 导入导出（`kind=cndb-content-template`）、副本端点、Markdown 预览、`sort_order` 拖拽（D7） |
| C6 | 「3做」 | `documents_document.export_template_ref` + `documents_contenttemplate.export_template_ref`（String(64)，可空）；`resolve_export_template` 增加 `document_ref` 入参；「从模板新建」把内容模板的 ref 写入新文档（D8 / D9） |
| C7 | 「3做」 | 文档绑定解析失败 → 记 warning 后走工作区默认（不抛、不区分原因）；写入口用 `validate_export_template_ref` 校验，非法 → 400（D9） |
| C8 | （迁移 / 备份） | 单条迁移两列可空、存量零迁移、downgrade 可还原；备份两处清单增字段，旧包缺键按 `None`，不升版本号（D10 / D11） |
| C9 | （不回归） | 权限仍走 `resolve_capabilities`（H64），模板不进 H33 可见性判定；绑定字段只是导出参数，不参与任何可读性判定 |
| C10 | （设计约束） | 双区页沿用 `SectionBox` / `CnListMeta` / `.cn-page` 原语，token 与断点口径不变（H24 / H25 / H29 / H30） |
| C11 | （测试 / 文档） | 分期见 §8，测试清单见 §7，文档回填见 §落地状态 |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 两套模板模型并存，语义完全不同（`config` 排版参数 vs `content_markdown` 正文） | `models.py:444`、`models.py:476` | 数据结构上无合并必要 | 确认（C1 不动） |
| 2 | 页签为「模板」/「内容模板」 | `MainLayout.tsx:96-97` | 「模板」是泛称，用户无法判断哪一个管导出 | 确认（C2 修） |
| 3 | 两个独立页面、两套 `Draft` / 清单 / 未保存确认 | `DocumentContentTemplatesPage.tsx`（360 行）、`TemplatePanel.tsx`（1408 行） | 骨架重复，改一处要改两处 | 确认（C3 / C4 修） |
| 4 | 名称唯一性 + `IntegrityError→400` 兜底写了两遍 | `content_templates.py:97,132`、`export_template_store.py:_ensure_name_free,_commit` | 并发口径可能漂移 | 确认（C4 修） |
| 5 | `_require_member` + 跨工作区 404 + 序列化各写一份 | `routers/templates.py:42`、`routers/content_templates.py:27` | 门控重复，易漏改 | 确认（C4 修） |
| 6 | 列表 envelope 不一致（`{items, default_ref}` vs `{items, total}`）；更新动词 `PUT` vs `PATCH` | `routers/templates.py`、`routers/content_templates.py` | 前端无法写一套通用 hook | 确认（C4 修） |
| 7 | 内容模板无 JSON 导入导出 / 副本 / 预览 / 拖拽排序 | `contentTemplates.ts`（49 行） | 同类资源能力落差，用户按模板页预期会报 bug | 确认（C5 修） |
| 8 | `TemplatePanel` 已不是个人设置，但仍住 `pages/settings/` | `Pages/settings/TemplatePanel.tsx` | 目录语义漂移（ADR 0152 C1 已把入口迁到文档区） | 确认（C3 顺带修） |
| 9 | 导出解析链 `resolve_export_template(db, workspace_id, ref)` 三段：显式 → 工作区默认 → `research` | `export/templates.py:699` | 表达能力只到工作区级，「某篇文档固定用公文格式」无处存 | 确认（C6 扩一段） |
| 10 | `PATCH /{doc_id}` 管文档元数据（title/status/…），无排版模板字段 | `routers/documents.py:1326` | 文档级绑定没有落点 | 确认（C6 新增字段） |
| 11 | 备份 v17 已有 `templates[]` 与 `content_templates[]`，新增键**不升版本**（0169 先例） | `workspace_backup.py:56-63`、`backup_io.py:1151,1213` | 加字段可沿用同口径 | 确认（C8） |
| 12 | 原件族（`content_type=word/pdf/xlsx/…`）不参与 docx/pdf 渲染 | `services/export/` 与 ADR 0025 / H19 | 绑定对原件无意义，需明确忽略 | 新增（§4 边界） |
| 13 | 「创建副本」复制标题 / 标签 / 状态 / 最新正文 | 需求 0172 / `routers/documents.py:520` | 绑定属文档元数据，副本应一并复制 | 新增（§4 边界） |

**核心缺陷（需求要补的）**：两类模板在数据结构上已经分清了，但在**入口、契约、能力集**上没有分清——同一个工作区里出现两个近乎同构的页面、两套 HTTP 约定、两套重复的名称校验；同时「这篇文档固定按公文格式导出」这种真实诉求在数据模型里无处可存，只能每次导出时手选。

设计目标（不变量）：

- **I1 语义不外溢**：整合只发生在契约层与 UI 层；导出模板的 `is_default` 唯一性、内置只读、内容模板「无内置**行** / 无默认锚点」（表里不预置内置行、不产生默认模板）逐条不变。ADR 0185 起内容模板另有一层**只读内置库**（代码常量、两级别分类 → 模板、不落表、无写端点），与本 I1 不冲突：内置库不产生 `documents_contenttemplate` 行，也不产生默认模板。
- **I2 绑定只影响视觉**：`export_template_ref` 只参与 docx / pdf 渲染参数解析，不参与任何权限、可见性、配额或列表过滤判定。
- **I3 绑定失败不得阻断导出**：绑定解析失败一律静默回落到「工作区默认 → `research`」，导出主流程永远能出文件，且错误信息不区分「不存在 / 跨工作区 / 已删除」。
- **I4 单一解析入口**：文档绑定的解析只能发生在 `resolve_export_template` 内部，导出器与 router 不得各自读取 `Document.export_template_ref`。

> I3 是跨需求长期生效的口径（「不泄露模板存在性」），已于 2026-11-26 登记为 **H68**（`docs/CONSTRAINTS.md`，来源 `ADR 0177 I3`，H27 / ADR 0119）。

## Decision

### 1. 数据模型

| 表 | 新列 | 类型 | 说明 |
|---|---|---|---|
| `documents_document` | `export_template_ref` | `String(64)` nullable | 文档级默认排版模板；`NULL` = 跟随工作区默认。格式与 ADR 0152 `template` 参数同源：`builtin:<key>` 或十进制 id |
| `documents_contenttemplate` | `export_template_ref` | `String(64)` nullable | 内容模板自带的排版模板；「从模板新建」时写入新文档 |

约定：

- **不设外键**：ref 允许指向代码常量（`builtin:<key>`），也允许在模板删除后保留成「悬空引用」——外键会引入级联删除或写失败，而悬空引用在本设计里由 I3 兜住（D8）。
- **不加索引**：读取全部发生在「已有文档行 → 渲染」路径上，按主键命中，无按 ref 反查需求。
- 长度 64 足够：`builtin:` + 最长 key（`techreport`）= 19 字符；id 串最长 19 位。

### 2. 判定算法（唯一入口）

```python
# services/export/templates.py
def validate_export_template_ref(db, workspace_id: int, ref: str | None) -> str | None
    # 写入口用：normalize_ref + 存在性校验；非法 / 跨工作区 / 未知内置 key → ValueError（路由转 400）

def resolve_export_template(
    db, workspace_id: int, ref: str | None = None, *, document_ref: str | None = None
) -> ResolvedTemplate
```

解析顺序（顺序本身是不变量，导出与预览共用）：

1. `ref`（显式 `?template=`）——失败 → `NotFoundError`（既有 404 行为不变，前端已有「删除自愈重试」逻辑）。
2. `document_ref`（文档级绑定）——`validate` 失败 → **记 warning 后跳过**，继续第 3 步（I3）。
3. 工作区默认（`is_default` 唯一）。
4. 内置 `research`。

约束：

- 导出端点只把 `document.export_template_ref` 作为 `document_ref` 传入，不自行判断有效性（I4）。
- `POST /documents/templates/preview` 不接 `document_ref`（预览是「未保存配置 / 某个模板」的渲染，不涉及文档）。
- `format=md` 忽略整条链（既有口径不变）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/documents/templates` | 响应补 `total`（保留 `default_ref`） |
| `PATCH /{wid}/documents/templates/{id}` | 新增，与既有 `PUT` 等价（D6） |
| `GET /{wid}/document-content-templates` | item 增 `export_template_ref`；响应 `{items, total}` |
| `POST /{wid}/document-content-templates` | 接受可选 `export_template_ref`（非法 400） |
| `PATCH \| PUT /{wid}/document-content-templates/{id}` | `PUT` 为新增别名；接受 `export_template_ref`（`null` = 清除绑定） |
| `POST /{wid}/document-content-templates/{id}/duplicate` | 新增副本（名称 `原名 副本`，重名递增，沿用 0172 口径） |
| `GET /{wid}/documents/{doc_id}` | 响应增 `export_template_ref` |
| `PATCH /{wid}/documents/{doc_id}` | 接受 `export_template_ref`（非法 400；`null` 清除） |
| `GET /{wid}/documents/{doc_id}/export` | `template` 缺省时按「文档绑定 → 工作区默认 → `research`」解析；显式传入仍最高优先 |
| `POST /{wid}/documents/{doc_id}/duplicate` | 副本复制 `export_template_ref` |
| `POST /{wid}/documents`（建文档） | 接受可选 `export_template_ref`，供「从模板新建」透传 |

### 4. 边界与例外

1. **文件夹不参与绑定**：`is_folder=true` 时 `PATCH` 带 `export_template_ref` → 400（文件夹没有导出物）。
2. **原件族忽略绑定**：`content_type ∈ {word, pdf, xlsx, pptx, mhtml, image}` 的文档可存 `export_template_ref` 但不生效（不参与 docx/pdf 渲染，H19 口径不变）；编辑器不展示「本文档默认排版模板」区块。
3. **副本复制绑定**：与标题 / 标签 / 状态同口径（需求 0172）。
4. **跨工作区移动（ADR 0155）**：`builtin:<key>` 保留；数字 id 型 ref 是**源工作区**的局部编号，移动时清空（置 `NULL`，回落目标工作区默认），不尝试重映射。
5. **备份导入 / 恢复**：数字 id 型 ref 跨工作区无意义，导入时置 `NULL`；`builtin:<key>` 保留；包内 ref 指向包内不存在的模板时**保留原值**（导出时由 I3 兜底），不静默清空 —— 避免「先导入模板再导入文档」的顺序依赖丢数据。
6. **模板删除**：删除导出模板**不**清理引用（无级联），存量绑定退化为悬空引用并由 I3 兜底；删除接口的响应不变。
7. **内容模板删除**：已建文档的绑定是**复制值**，不随内容模板删除而改变。

### 5. 迁移

单条迁移（`revision = e0f1a2b3c4d6`，`down_revision = d9e0f1a2b3c5`）：

```python
op.add_column("documents_document", sa.Column("export_template_ref", sa.String(64), nullable=True))
op.add_column("documents_contenttemplate", sa.Column("export_template_ref", sa.String(64), nullable=True))
# downgrade: 两条 drop_column
```

- 存量零迁移：两列全 `NULL` ⇒ 导出行为与升级前逐条一致（走「工作区默认 → `research`」）。
- 幂等 + `downgrade` 可还原（H13）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 导航 | `layouts/MainLayout.tsx` | 页签 label 改「导出模板」；激活态按 `pathname + ?kind` 判定；`content-templates` 段仍映射「内容模板」 |
| 路由 | `App.tsx` | `templates` 单页；`content-templates` 改 `<Navigate replace to="...templates?kind=content">` |
| 容器 | `pages/documents/DocumentTemplatesPage.tsx` | 由 18 行壳升级为双区容器：`?kind=export`（缺省 / 脏值）→ `ExportTemplatePanel`，`?kind=content` → `ContentTemplatePanel`；**分区开关就是文档区页签本身**，页内不再放 `Segmented`（避免两套开关） |
| 面板（迁移） | `pages/documents/ExportTemplatePanel.tsx` | 由 `pages/settings/TemplatePanel.tsx` 迁入（逻辑、`templateFile.ts` / `templateOptions.ts` 与测试一并搬迁，`settings/` 下删除） |
| 面板（迁移） | `pages/documents/ContentTemplatePanel.tsx` | 由 `DocumentContentTemplatesPage.tsx` 迁入并改名；保留自带页头（两类模板的口径说明不同） |
| 公共骨架 | `components/Template/TemplateListBox.tsx` | 共用左栏外壳：`SectionBox flush` + 计数 + 空态；只抽外壳不抽业务（D5）。原计划的通用 `useTemplateCollection` hook **不做**：两套 draft / 校验 / 动作集差异大于共性，硬抽会退化成 `kind` 分支 |
| API | `api/contentTemplates.ts` | 增 `export_template_ref`（P3）、`duplicate`、`put` 别名调用（P1 已加，P2 已接 UI） |
| 文件格式（P2） | `pages/documents/contentTemplateFile.ts` | `kind=cndb-content-template` / `version=1`；`parseContentTemplateFile` 遇 `cndb-document-template` 明确报「这是导出模板文件，请到『导出模板』页导入」；名称去重与读文件复用 `templateFile.ts` 的 `suggestImportName` / `readTextFile` |
| 面板能力（P2） | `pages/documents/ContentTemplatePanel.tsx` | 导入（逐条创建、同名加「（导入）」）、导出当前 / 导出全部、创建副本、编辑 / 预览切换（`MarkdownPreview` 只读渲染草稿）、左侧清单 HTML5 拖拽排序（落点后按 10 的倍数写 `sort_order`，只 PATCH 变化项）；样式 `.cn-qc-row--draggable` / `--drop` / `-handle` 走 `--cn-*` token |
| API | `api/exportTemplates.ts` | 列表类型补 `total` |
| 编辑器 | `pages/documents/DocumentEditorPage.tsx` | 导出二级菜单标出「本文档默认」；新增「设为本文档默认 / 取消」入口（调 `PATCH /{doc_id}`）；原件族不展示该入口 |
| 新建 | `pages/documents/DocumentsPage.tsx` | 「从模板新建」透传模板的 `export_template_ref` 到 `create_document`；模板编辑弹层可选绑定排版模板（下拉复用导出模板候选） |
| 文档 | `CONTEXT.md`、`docs/USER_DOC_MAP.md`、`pages/help/content/tutorials.tsx` | 术语合并为「文档模板 → 导出模板 / 内容模板」，帮助合并为一个主题下的两个 L3 小节 |

### 7. 测试清单

**判定层（单测）**

- `validate_export_template_ref`：内置 key 通过 / 未知内置 key 拒绝 / 本区 id 通过 / 跨区 id 拒绝 / 非法格式拒绝。
- `resolve_export_template`：显式 → 文档绑定 → 工作区默认 → `research` 四段顺序各一例；文档绑定悬空 / 跨区 / 已删 → 回落且不抛。

**接口层**

- 内容模板：`PUT` 与 `PATCH` 等价（`test_put_alias_matches_patch`）；列表 `{items, total}`（`test_list_envelope_has_total`）；`duplicate` 名称递增（`test_duplicate_endpoint_increments_name`）；非法 `export_template_ref` 400 / 跨区 404（P3）。
- 导出模板：列表带 `total`；`PATCH` 等价 `PUT`（`test_patch_alias_matches_put`）；重名 400 与内容模板同文案（公共层回归）。
- 文档：`PATCH /{doc_id}` 设 / 清绑定；文件夹 400；建文档透传绑定；副本复制绑定；`export` 未传 `template` 时用文档绑定；显式 `template` 覆盖绑定；绑定模板删除后导出仍 200。

**迁移 / 备份**

- 迁移 upgrade / downgrade 往返；存量库升级后两列全 `NULL` 且导出行为不变。
- 备份往返含两处新字段；旧包缺键按 `None`；导入时 id 型 ref 清空、`builtin:` 保留。

**前端（单测）**

- `?kind=` 分区切换与页签激活（`DocumentTemplatesPage.test.tsx`：缺省 / `content` / 脏值三档；`MainLayout.test.tsx`：点「内容模板」页签落到 `templates?kind=content` 且回到该 query 时激活）；旧路径重定向由路由保证（`App.tsx` 的 `<Navigate>`）。
- 内容模板能力对齐（P2，`ContentTemplatePanel.test.tsx` 新增 9 例）：副本调用服务端并选中副本、编辑 / 预览切换（预览只读渲染正文）、导出 JSON（`kind=cndb-content-template`）、导入（同名加「（导入）」后逐条创建）、导入排版模板文件不发创建请求、拖拽两行按新顺序写 `sort_order`；纯函数层（`contentTemplateFile`）另 4 例：导出回读、单条 / 多条兼容、排版模板文件报错指向「导出模板」页、非法文件中文错误（含版本过新 / 缺名称 / 正文非文本 / 空清单）。
- 编辑器「设为本文档默认」调 `PATCH` 且菜单标出当前默认；原件族不展示。
- 从模板新建携带 `export_template_ref`。

**e2e（前端）**：`critical/document-template-integration.spec.ts`——模板页切到内容模板 → 建模板并绑定「公文」→ 从模板新建文档 → 导出 docx 走绑定（响应 200 且文件名符合）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 术语与导航：页签改「导出模板」+ 页头副标题 + `CONTEXT` / `USER_DOC_MAP` / 帮助（C2） | 低（纯文案与文档） |
| **P1** | 公共契约层 `templates_common.py` + 单页双区 + `TemplatePanel` 目录迁移 + `PUT`/`PATCH` 双支持（C3 / C4） | 中（前端重构，路由重定向需保深链） |
| **P2** | 内容模板能力对齐：JSON 导入导出 / 副本 / 预览 / 拖拽排序（C5） | 低（新增能力，无迁移） |
| **P3** | 文档级绑定：迁移 + 两列 + 解析链 + 导出/新建/副本/移动/备份接入 + UI（C6 / C7 / C8） | 高（迁移 + 解析链 + 备份协议） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | C：模型双表 + 契约/UI 收敛，分 P0–P3 落地 | 歧义与重复集中在入口与契约，不在数据模型 | A（只改页签名）：不解 P-2/P-3/P-4 重复与能力落差；B（合并成单表 + `kind`）：须双表迁移 + 备份 v18 + ADR 0152 全部不变量重述 + 68 例既有测试改写，收益仅「少一张表」，且 `is_default` / 内置只读只对一种 kind 生效，表内语义分叉更重 | — |
| D2 | 是否合并 `documents_exporttemplate` / `documents_contenttemplate` | 不合并，语义边界保持 | 一份是渲染参数（`config` JSON + `is_default`），一份是正文内容（`content_markdown` + `sort_order`）；合并会把「内置只读」「默认唯一」变成条件逻辑 | 同 D1 的 B | `models.py:444`、`models.py:476` 保持 |
| D3 | 页签命名 | 「导出模板」/「内容模板」（直白） | 用户明确选直白；「排版模板」更贴语义但需二次解释 | 「排版模板」/「内容模板」 | `MainLayout.tsx:96` |
| D4 | 入口形态 | 单页双区 `/documents/templates?kind=` + 旧路径重定向 | 复用仓库既有 `?section=` 范式（团队页 / 统计页 / 工作区设置）；一页内切换不丢上下文 | 保留两个并列页签：仍是两个平行入口，无法共享骨架 | `DocumentTemplatesPage.tsx`、`App.tsx` |
| D5 | 公共层抽什么 | 只抽「名称唯一 + 并发 400 + 跨区 404 + 列表 envelope + 门控」；**不抽业务**（排版配置与正文骨架各管各的） | 两套业务的校验与序列化差异远大于共性 | 抽统一 `TemplateService` 基类含业务方法：会引入 `kind` 分支，等价于部分合并 | `services/templates_common.py`（新增） |
| D6 | 更新动词 | 两侧同时接受 `PUT` 与 `PATCH`，只加不删 | 存量消费者（前端、脚本、e2e）不受影响 | 统一改成单一动词：破坏既有契约且无收益 | 两个 router |
| D7 | 内容模板文件格式 | 独立 `kind=cndb-content-template` / `version=1`；导入时遇到 `cndb-document-template` 明确报错「这是排版模板文件」 | 两类模板字段无交集，共用一个 kind 只能靠猜 | 复用 `cndb-document-template` + `type` 字段：旧版本解析器会静默接受错误结构 | `contentTemplates.ts`、`templateFile.ts` 同类实现 |
| D8 | 绑定列的存储形态 | `String(64)`、可空、**无外键** | ref 可为代码常量（`builtin:<key>`）；外键会让「模板删除」变成「文档写失败 / 级联清字段」 | 两个列（builtin_key + template_id）：查询与校验都要分叉；外键 + 级联：把删除放大成写路径 | `models.py` |
| D9 | 解析链顺序与失败策略 | 显式 `template` → 文档绑定 → 工作区默认 → `research`；显式失败 404（既有），绑定失败**静默回落** | 显式选择失败要让用户看见（前端已有自愈重试）；文档绑定是「默认值」，失败不该阻断出文件 | 绑定失败也 404：一次误删模板会让一批文档导不出来；绑定失败报错文案区分原因：泄露模板存在性 | `export/templates.py:699` |
| D10 | 跨工作区导入 / 移动的 ref 处理 | 数字 id 型 ref 清空为 `NULL`，`builtin:<key>` 保留；包内悬空引用保留原值 | id 是工作区局部编号，跨区复用会指到别人的模板 | 尝试按名称重映射：名称可重复且语义易错 | `workspace_backup.py`、`backup_io.py`、`services/move.py` |
| D11 | 备份版本号 | 不升（沿用需求 0169 先例：新增键、旧包缺键按缺省） | 归档协议向后兼容；旧端读新包忽略未知键 | 升 v18：需要额外兼容分支且无实际收益 | `workspace_backup.py:56-63` |
| D12 | 不变量登记 | 以 **H68** 登记（H65–H67 已被 ADR 0161 占用）：「文档级排版模板绑定解析失败必须静默回落，不区分原因；写入口非法 ref 400；绑定不参与权限 / 可见性」 | I3 是跨需求长期安全口径（H27） | 只写在 ADR：后续实现容易退回「报错中断」 | `docs/CONSTRAINTS.md` H68（已写入，2026-11-26 人工确认） |

门禁：2026-11-26 人工评审通过，`Status → Accepted`，D1–D12 全部定稿，无「待定」。

## Consequences

- **正向**：一个入口说清两类模板（消除「模板」泛称歧义）；清单 / 编辑 / 导入导出 / 权限门控只有一份实现；内容模板不再是「功能更少的那个」；「这篇文档固定按公文格式导出」变成可存、可继承的能力。
- **负向**：解析链从三段变四段，导出相关测试需要补顺序断言；前端一次结构性重构（`TemplatePanel` 迁移 + 双区容器）；新增两列需要迁移与备份清单同步。
- **风险与缓解**：① 路由重定向破坏深链 → `?kind=` 与旧路径双向保留并有单测/e2e 覆盖；② 绑定悬空导致「导出风格突变」→ 编辑器显式标出「本文档默认」，失效时在导出菜单回落并提示「原模板已不存在」；③ 迁移未回填 → 全 `NULL` 等价旧行为，可 `downgrade` 直接还原。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 导出视觉参数解析 | `resolve_export_template` | 在原三段链**末尾追加**文档绑定一段，终点仍为内置 `research` | ADR 0152 I1 / I2（本 ADR 扩展 D9） |
| 内置预设只读 | `BUILTIN_TEMPLATES` | 不变；绑定可指向内置 key | ADR 0152 I4 |
| 内容模板范围 | `documents_contenttemplate` | 仍无内置行、无工作区级默认锚点；只新增「可选绑定排版模板」 | 需求 0169 |
| 内容模板内置库 | `documents/services/content_builtins.py` | 只读代码常量，不落表、不进备份、无写端点；「无内置行 / 无默认锚点」仍成立 | ADR 0185 |
| 文档元数据 | `PATCH /{doc_id}` | 新增一个纯视觉字段，不参与权限 / 可见性 | ADR 0161（H64 口径不变） |
| 跨工作区移动 | `services/move.py` | 移动时清空 id 型 ref、保留 builtin | ADR 0155 |
| 文档副本 | 需求 0172 | 副本复制绑定 | 需求 0172 |
| 备份协议 | `CHUNKED_BACKUP_VERSION = 17` | 新增字段不升版本号 | ADR 0075（0169 先例） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/documents/ExportTemplatePanel.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`CONTEXT.md`、`docs/USER_DOC_MAP.md` | `frontend/src/layouts/MainLayout.test.tsx`、`frontend/src/pages/documents/ExportTemplatePanel.test.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.test.tsx`、`frontend/src/pages/help/*.test.tsx` | 9a89f6c9 |
| P1 | 已落地 | `src/cndb/plugins/documents/services/templates_common.py`（新增）、`src/cndb/plugins/documents/services/content_templates.py`、`src/cndb/plugins/documents/services/export_template_store.py`、`src/cndb/plugins/documents/routers/content_templates.py`、`src/cndb/plugins/documents/routers/templates.py`、`frontend/src/pages/documents/DocumentTemplatesPage.tsx`、`frontend/src/pages/documents/ExportTemplatePanel.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/components/Template/TemplateListBox.tsx`（新增）、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/App.tsx`、`frontend/src/api/contentTemplates.ts`、`frontend/src/api/exportTemplates.ts` | `tests/test_documents_content_templates.py`、`tests/test_export_templates.py`、`frontend/src/pages/documents/DocumentTemplatesPage.test.tsx`、`frontend/src/pages/documents/ExportTemplatePanel.test.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | 9a89f6c9 |
| P2 | 已落地 | `frontend/src/pages/documents/contentTemplateFile.ts`（新增）、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/index.css`、`frontend/src/api/contentTemplates.ts` | `frontend/src/pages/documents/ContentTemplatePanel.test.tsx` | 9a89f6c9 |
| P3 | 已落地 | `src/cndb/plugins/documents/models.py`、`src/cndb/alembic/versions/e0f1a2b3c4d6_add_template_ref_bindings.py`（新增）、`src/cndb/plugins/documents/services/export/templates.py`、`src/cndb/plugins/documents/services/content_templates.py`、`src/cndb/plugins/documents/services/content/`、`src/cndb/plugins/documents/services/move.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/routers/content_templates.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/api/contentTemplates.ts`、`frontend/src/api/documents.ts` | `tests/test_documents_template_binding.py`（新增）、`tests/test_export_templates.py`、`tests/test_documents_content_templates.py`、`frontend/src/pages/documents/ContentTemplatePanel.test.tsx`、`frontend/src/pages/documents/DocumentsPageContentTemplate.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx`、`frontend/tests/e2e/critical/document-template-integration.spec.ts`（新增） | 165402df |

## 交接（会话结束更新）

- 当前阶段：P0–P3 已落地并提交（P0–P2 `9a89f6c9`、P3 `165402df`）；ADR 0177 收口
- 已完成：
  - P3（C6 / C7 / C8）：两列迁移 `export_template_ref`（可空、无外键、存量零迁移、downgrade 可还原）；写入校验 `validate_export_template_ref`（非法 / 跨区 400）与解析链追加「文档绑定 → 工作区默认 → research」一段（绑定失败 warning 静默回落，H68）；导出 / 建文档 / 副本 / 跨工作区移动 / 备份导入全部接入；内容模板可绑定排版模板并在「从模板新建」时继承；编辑器导出菜单标出「本文档默认」并提供设置 / 清除入口（原件族不展示）。
  - P0（C2）：页签「导出模板」+ 两页页头副标题 + `CONTEXT` 术语父行 + `USER_DOC_MAP` + 帮助教程两节改写（顺手修正导出模板帮助里「模板只承载导出选项」的旧口径错误）。
  - P1（C3 / C4）：后端 `services/templates_common.py`（名称唯一 / 并发 400 / 跨区 404 / `{items,total}` envelope / 成员门控）两个服务与两个 router 复用；两侧更新动词 `PUT` 与 `PATCH` 双支持；内容模板新增 `POST /{id}/duplicate`；前端单页双区 `?kind=export|content` + 旧路径 `<Navigate>` 重定向 + 页签激活按 query 判定；`TemplatePanel` → `pages/documents/ExportTemplatePanel.tsx`、`DocumentContentTemplatesPage` → `ContentTemplatePanel.tsx`（连同 `templateFile.ts` / `templateOptions.ts` 迁出 `pages/settings/`）；共用左栏外壳 `components/Template/TemplateListBox.tsx`。
  - P2（C5）：内容模板能力对齐——`contentTemplateFile.ts`（`kind=cndb-content-template`，与排版模板文件互不兼容且明确报错）、导入 / 导出当前 / 导出全部、创建副本按钮、编辑 / 预览切换（`MarkdownPreview` 只读）、左侧清单拖拽排序（写 `sort_order`）。
- 下一步：P3 已收口，H68 已生效；后续只剩提交与观察（本 ADR 无未完成期）
- 已知坑：
  - `e0f1a2b3c4d6` 是当前 alembic head（P3 两列迁移，`down_revision = d9e0f1a2b3c5`）；`CHUNKED_BACKUP_VERSION` 保持 `17`，旧包缺 `export_template_ref` 按 `None`。
  - 备份 / 跨工作区移动 / 导入的绑定引用只保留 `builtin:`：id 型 ref 指向来源工作区的模板行，导入或移动后必然悬空，按 ADR 0177 C8 清空。
  - 通用 `useTemplateCollection` hook **按 D5 不做**（两套 draft / 校验 / 动作差异大于共性）；P1 只抽了 `TemplateListBox` 外壳。ADR §6 已同步。
  - 分区开关用文档区页签本身，页内不再放 `Segmented`（避免两套开关）；`?kind` 脏值回落导出模板。
  - 拖拽排序用 HTML5 DnD（不依赖 `dataTransfer`，落点状态走 React state），落库按 `index * 10` 写 `sort_order`，只 PATCH 变化项；失败时回读服务端顺序避免假排序。
  - **bundle budget**：P0/P2 的帮助文案让 `HelpTutorials` 超原上限 32000（31.32 KiB）。已按 H32 走脚本：`--update --only HelpTutorials`（基线 30449 → 32071）+ `--set-budget 33500 --only HelpTutorials`（+4.7%，<10% 无需 PR 说明），理由写进 `bundle-budget.json` 的 reason/history。散文内容无 lazy 可拆。
  - 基线修复（非本 ADR 引入、但阻塞 `make test`）：仓库里另一处 WIP 把 `content.py` 内联阈值改为 `RAW_INLINE_MAX_SIZE` 后遗留 `INLINE_MAX_SIZE` 未用导入与 `tests/test_documents_robustness.py::test_inline_compressed_roundtrip` 对旧常量的引用，已就近清理（删未用导入 + 用例改用 9KB 文本，行为口径不变）。
- 最近一次全绿：`make check-fast` + `make check-frontend`（覆盖率双门槛达标）+ `pnpm build` + `pnpm bundle:budget` @ 2026-11-26；后端全量 7778 passed / 17 skipped（P2 未改后端）
