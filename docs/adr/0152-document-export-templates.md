# ADR 0152: 文档导出模板（可配置字体 / 标题 / 段落，一套模板同时供电 Word 与 PDF）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/services/export/theme.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/export/pdf_fonts.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/layouts/MainLayout.tsx`
需求卡片: `docs/requirements/0152-document-export-templates.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；约束编号 C1..C10 一律引用卡片，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「在大模型设置右侧」 | 顶栏「模板」图标紧接 `llm-settings-btn` 之后（`data-testid="template-settings-btn"`），移动端进用户菜单键 `template`；个人设置页签 `template` 排在 `llm` 之后 |
| C2 | 「首先增加文档模板」 | 面板只做「导出模板」一类；`DocumentTemplate` 表不带 `kind` 列，其他品类后续立项再加 |
| C3 | 「字体、标题、段落等可配置化」 | `ExportTemplateConfig`（pydantic 严格校验）五组：page/header_footer、body、headings(1..6)+numbering、table+captions、list+code；★ 项本期必做、☆ 项同期增强（见卡片 C3 明细） |
| C4 | 「符合企业规范」 | 表工作区级；`is_default` 至多一条；解析链 `显式 ref → 工作区默认 → 内置 standard`；随备份 v17 `templates[]` 往返 |
| C5 | 「论文、报告等内置模板」 | `BUILTIN_TEMPLATES` 8 套：`standard` / `research` / `techreport` / `trend` / `thesis` / `official` / `weekly` / `press`；代码常量不入库；`POST /templates` 带 `preset_key` 即另存为 |
| C6 | 「一套模板兼顾 PDF」 | 同一 `ExportTemplateConfig` 同时喂 `_render_docx` 与 `_render_pdf`；PDF 侧字体族经 `ensure_pdf_font(family)` 最佳匹配 + 回落（D11） |
| C7 | 「md生成的word」 | `GET /{doc_id}/export?format=docx\|pdf&template=<ref>`；`<ref>` = `builtin:<key>` 或正整数 id；缺省走默认链；`format=md` 忽略该参数 |
| C8 | （可配置化的可见性） | `POST /templates/preview?format=docx\|pdf` 用未保存配置渲染示例件（不落库、不写审计）；面板内另有纯 CSS 等比预览 |
| C9 | （权限与隔离） | 读 `_require_member`；写 `owner/editor`；内置 ref 写操作 400；跨工作区 id 404 |
| C10 | （兼容） | `standard` 与现 `DEFAULT_THEME` 逐项相同且 docx / pdf 默认输出不变（I2）；备份旧包缺 `templates` 按空；原件族预览不接模板（H19） |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 导出视觉预设是模块级常量 `DEFAULT_THEME`（`ExportTheme`：heading_font/sizes/colors、body_font/size、表头色、code_font），docx 里 `preset = DEFAULT_THEME` | `theme.py:44`、`docx.py:335`、`pdf.py:324` | 冻结 dataclass 表达不了「用户可配置 + 多套内置」 | 确认 |
| 2 | 标题字号两处硬编码：`docx.py` 的 `_HEADING_SIZES`、`pdf.py` 的 `_HEADING_SIZES` | `docx.py:57`、`pdf.py:343` | 配置化必须收敛到一处（模板 config） | 确认 |
| 3 | 段落级排版（列表缩进 `16 * level`、行距、段前段后、代码块边距 / 底色、表头底色、页眉页脚字号 8）均为字面量 | `docx.py:370`、`docx.py:384`、`pdf.py:416`、`pdf.py:476` | 无法满足「段落可配置」 | 确认 |
| 4 | 导出端点签名 `(workspace_id, doc_id, format)`，无模板选择 | `routers/documents.py:645` | 不能按模板导出 | 确认 |
| 5 | 前端 Word / PDF 导出是下拉项直连 `exportMut.mutate('docx' \| 'pdf')` | `DocumentEditorPage.tsx:1298`、`:1625` | 无模板选择入口 | 确认 |
| 6 | 个人设置页签 `profile / theme / table / doc / editor / llm`（`llm` 末位）；顶栏 `llm-settings-btn` 在帮助图标左侧 | `SettingsModal.tsx:681`、`MainLayout.tsx:1134` | 需在其右侧追加「模板」两端入口 | 确认 |
| 7 | 备份 `backup_io` 版本白名单 1..16，文档域已含 `charts` / `documents` | `backup_io.py:123` | 新表必须纳入（H14），版本升 17 | 确认 |
| 8 | PDF 只注册**一个**全局 CJK 字体（`_ensure_pdf_font()` 无参、三态缓存），正文 / 标题 / 表格 / 页眉全用它 | `pdf_fonts.py:236`、`pdf.py:323` | 「模板指定宋体 / 黑体 / 仿宋」在 PDF 侧只能按可用字体最佳匹配 | 确认（改为 C6 口径） |
| 9 | PDF 用 Platypus 自绘（`ParagraphStyle` / `TableStyle`），`bulletText` 列表、代码块矩形框 | `pdf.py:326` 起 | 字号 / 行距 / 缩进 / 对齐 / 表头色可直接映射；域（TOC / 题注）不可 | 确认 |
| 10 | Word 原件族（`content_type=word`）只读，预览走 `preview/office.py` | `models.py:79`、`services/preview/office.py` | 模板不参与原件预览与导入 | 排除（H19） |

**核心缺陷（需求要补的）**：Markdown → Word / PDF 的视觉参数是**编译期常量**，用户无法把企业排版规范（中文字体、小四号、1.5 倍行距、首行缩进 2 字符、标题分级与编号、表头与题注规范）落到导出物上。

设计目标（不变量）：

- **I1 单一解析入口**：`docx` / `pdf` 导出的排版配置只能来自 `resolve_export_template(...)`；导出器内部不再读取任何模块级视觉常量。
- **I2 存量零变化**：未指定模板且工作区无默认模板时，`docx` 与 `pdf` 的导出视觉与改造前逐项一致（由内置 `standard` 承载，单测锁定 `standard` 与 `DEFAULT_THEME` 对应字段相等）。
- **I3 一套配置两处渲染**：同一 `ExportTemplateConfig` 是 docx 与 pdf 的唯一排版来源；PDF 侧的降级只发生在字体族匹配与不支持项上，且必须静默降级、不得报错或改变可见内容。
- **I4 内置不可变**：内置模板只能被引用或另存为，任何写操作（改 / 删 / 设为默认指向内置）都不落库。

> 不新增跨需求长期生效的不变量，无需登记 CONSTRAINTS（H27）。

## Decision

### 1. 数据模型

新表 `documents_exporttemplate`（`ExportTemplate`，领域命名与 `ExportTheme` 对齐；不加 `kind`，见 D3）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `workspace_id` | FK `workspaces_workspace.id` ON DELETE CASCADE | 工作区级资源 |
| `name` | String(80) NOT NULL | 工作区内唯一 |
| `description` | String(200) NOT NULL DEFAULT '' | |
| `config` | JSON NOT NULL | `ExportTemplateConfig` 规范化 dump（校验后写入） |
| `is_default` | Boolean NOT NULL DEFAULT false | 每工作区至多一条（服务层 + 部分索引保证） |
| `created_by` | FK `users_user.id` ON DELETE SET NULL | 仅展示 |
| `created_at` / `updated_at` | TimestampMixin | |

约束：`UniqueConstraint(workspace_id, name)`、`Index(workspace_id, is_default)`。

配置形态（`services/export/templates.py::ExportTemplateConfig`，字段全部带边界，★/☆ 与卡片 C3 明细一致）：

```
page           : paper(A4|A3|Letter) / margin_{top,bottom,left,right}(cm)
header_footer  : header_text / page_number(none|plain|page|page_of_total)
                 first_page_different(bool) / font_size(8..14)
body           : latin_font / east_asia_font / size(8..72) / bold / color(#RRGGBB)
                 align(left|center|right|justify) / line_spacing_rule(multiple|fixed)
                 line_spacing(1.0..3.0) / line_spacing_pt(10..60)
                 space_before / space_after(0..36) / first_line_indent_chars(0..8)
                 char_spacing(-2..10) / widow_control(bool) / keep_with_next(bool)
headings       : 1..6 → {latin_font, east_asia_font, size, bold, color, align,
                          space_before, space_after, first_line_indent_chars, keep_with_next}
numbering      : heading(none|arabic_multilevel|chapter_chinese|cn_ordinal)
table          : style(single|three_line) / header_bg / header_color / header_bold
                 latin_font / east_asia_font / size / border_color
                 header_repeat(bool) / zebra(bool) / cell_valign(top|center)
captions        : figure(enabled, position(above|below), numbering(n|n-n), font/size)
                 table(同上)
list           : indent_chars(0..8) / space_after(0..12) / marker(bullet|dash|dot)
code           : latin_font / east_asia_font / size(6..24) / bg / border / left_bar(bool)
```

内置预设（`BUILTIN_TEMPLATES`，代码常量，不入库；`standard` 与现 `DEFAULT_THEME` 字段逐项相等）：

| key | 名称 | 排版要点 |
|---|---|---|
| `standard` | 标准 | 现默认视觉（Calibri 10.5pt、单倍行距、无首行缩进），供存量口径 |
| `research` | 研究报告 | 宋体 / Times New Roman 12pt、1.5 倍行距、首行缩进 2 字符、两端对齐；H1 黑体 16pt、H2 14pt、H3 12pt；三线表 |
| `techreport` | 技术报告 | 宋体 / Calibri 11pt、1.5 倍行距、首行缩进 2 字符；H1 黑体 18pt 居中、H2 15pt、H3 13pt；表头浅蓝底 |
| `trend` | 趋势分析 | 宋体 / Calibri 11pt、1.5 倍行距、首行缩进 2 字符；标题左对齐、`1 / 1.1 / 1.1.1` 编号；图表题注在下、`图 1` |
| `thesis` | 论文 | 宋体 / Times New Roman 12pt、1.5 倍行距、首行缩进 2 字符；H1 黑体 18pt 居中；`第一章` 编号；三线表 + 题注 |
| `official` | 公文 | 仿宋 16pt（三号）、固定行距 28pt、首行缩进 2 字符；H1 22pt 居中；`一、` 编号；页脚 `第 X 页 共 Y 页` |
| `weekly` | 周报 | 宋体 / Calibri 11pt、1.5 倍行距；H1 15pt、H2 13pt；列表紧凑、表格斑马纹 |
| `press` | 宣传报道 | 宋体 / Calibri 12pt、1.75 倍行距、无首行缩进、左对齐；H1 18pt 居中、H2 15pt |

字体以「字体名 + 东亚映射」双写（`w:rFonts` 的 `ascii` + `eastAsia`）；PDF 侧见 D11。

### 2. 判定算法（唯一入口）

`src/cndb/plugins/documents/services/export/templates.py`：

```python
def validate_config(raw: Mapping[str, Any]) -> ExportTemplateConfig  # 越界 / 缺字段 / 未知字段 → ValueError
def normalize_ref(ref: str | None) -> TemplateRef                    # 'builtin:<key>' | int id | None
def resolve_export_template(db, workspace_id: int, ref: str | None) -> ResolvedTemplate
def render_sample(fmt: str, config: ExportTemplateConfig) -> bytes   # preview 用，fmt ∈ {docx, pdf}
```

`resolve_export_template` 判定顺序（唯一）：

1. `ref` 非空 → `builtin:<key>` 命中内置；数字 id 命中本工作区行；否则 `NotFoundError`（跨工作区同 404）。
2. `ref` 为空 → 本工作区 `is_default=True` 的行。
3. 仍为空 → `BUILTIN_TEMPLATES["standard"]`。

导出器签名：

```python
_render_docx(markdown, title="", images=None, tables=None, template: ResolvedTemplate | None = None) -> bytes
_render_pdf(markdown, title="", images=None, tables=None, template: ResolvedTemplate | None = None) -> bytes
render_export(markdown, fmt, title="", images=None, tables=None, template=None) -> bytes
```

`template=None` 时内部取 `BUILTIN_TEMPLATES["standard"]`。`theme.py` 的 `DEFAULT_THEME` 降级为**兼容基线**，仅用于单测比对（I2）与历史调用兜底，导出器不再 import 其字段做排版。

### 3. API 变更清单

新路由 `src/cndb/plugins/documents/routers/templates.py`（挂 `/api/v1/workspaces/{workspace_id}/documents/templates`）：

| 端点 | 变更 |
|---|---|
| `GET /documents/templates` | 新增：`{items: [{ref, name, description, source: builtin/custom, is_default, config, updated_at}], default_ref}`；成员可读 |
| `GET /documents/templates/{ref}` | 新增：单个模板（内置 key 或行 id）；跨工作区 404 |
| `POST /documents/templates` | 新增：`{name, description?, preset_key?, config?}`（owner/editor）；`preset_key` 复制内置配置；重名 400 |
| `PUT /documents/templates/{id}` | 新增：`{name?, description?, config?, is_default?}`；设默认时同事务清空其它默认 |
| `DELETE /documents/templates/{id}` | 新增：删除自定义；被删的是默认模板时回落内置 standard（不报错） |
| `POST /documents/templates/preview` | 新增：`{config}` 或 `{ref}` + `format=docx\|pdf` → 示例件字节流（不落库、不写审计） |
| `GET /documents/{doc_id}/export?format=docx\|pdf&template=<ref>` | 修改：新增 `template` 查询参数；`md` 分支忽略 |

### 4. 边界与例外

1. **内置只读**：`PUT` / `DELETE` 指向内置 ref → 400（`内置模板不可修改，请另存为自定义模板`）；`is_default` 不允许指向内置（缺省即 standard）。
2. **跨工作区**：id 不属于当前工作区 → 404（不区分「不存在」与「无权限」）。
3. **命名冲突**：同工作区重名 → 400（提示已存在）。
4. **配置越界**：字号 / 行距 / 缩进 / 颜色 / 枚举非法 → 400 指明字段，不做静默夹取。
5. **删除默认**：自动回落内置 standard，`default_ref` 变 `builtin:standard`。
6. **模板与 Markdown 显式语法的关系**：模板决定字体 / 字号 / 间距 / 对齐 / 底色 / 编号 / 题注 / 页眉页脚；正文里显式的表格对齐、列宽百分比、图片宽度、代码块内容不变。
7. **导出参数容错**：`format=md` 带 `template` → 忽略；非法 ref → 404；空串按缺省处理。
8. **PDF 降级**（I3）：字体族按服务器可用 CJK 字体最佳匹配，无匹配时回落默认 CJK 字体（与改造前一致），不报错；字间距 / 题注域 / 目录 / 三线表细边框等 PDF 不可表达的项静默跳过。
9. **无工作区上下文**：模板面板空态提示「请先进入工作区」，不请求接口；顶栏入口在工作区外与移动端用户菜单同时隐藏。
10. **并发与幂等**：设默认同事务先清后置，重复设同一模板幂等。
11. **历史导出不追溯**：模板修改 / 删除只影响之后的导出。

### 5. 迁移

单条 alembic 迁移（`down_revision` 取当前 head）：建 `documents_exporttemplate` + 唯一约束 + 索引（`inspect` 判存后建，幂等）；`downgrade()` `drop_table`。存量零迁移（无默认模板 = 走内置）。

备份：`workspace_backup` 导出 `templates[]`（`name / description / config / is_default / created_by`），版本 16 → 17；`backup_io` 白名单加 `17`，导入时 `templates` 缺失按空列表；异常包多行 `is_default` 时保留首条、其余置 false。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 类型 | `frontend/src/store/ui.ts` | `SettingsTab` 增 `'template'` |
| API | `frontend/src/api/exportTemplates.ts`（新增） | 列表 / 详情 / 新建 / 更新 / 删除 / preview（blob，含 `format`） |
| API | `frontend/src/api/documents.ts` | `exportFile` 增可选 `template?: string` |
| 面板 | `frontend/src/pages/settings/TemplatePanel.tsx`（新增） | 左列模板列表（内置分组 + 自定义分组、默认标记、新建 / 另存为 / 删除）；右侧五组配置（页面与页眉页脚 / 正文 / 标题与编号 / 表格与题注 / 列表与代码，折叠面板）+ CSS 等比预览 + 「下载示例 Word / PDF」 |
| 字号 | `frontend/src/pages/settings/templateOptions.ts`（新增） | 中文字号↔磅值映射（小四 12pt / 四号 14pt / 三号 16pt…）、纸张与编号枚举选项，单一来源 |
| 页签 | `SettingsModal.tsx` | 新增 `template` 页签，位置在 `llm` 之后 |
| 顶栏 | `MainLayout.tsx` | `llm-settings-btn` 右侧新增 `template-settings-btn`（`SnippetsOutlined`），`openSettings('template')`；移动端用户菜单同项 |
| 导出 | `DocumentEditorPage.tsx` | 导出下拉的 Word / PDF 项改为子菜单：默认模板 / 各内置 / 各自定义（列表接口数据）；`exportMut.mutate({format, template})` |

样式只用 `--cn-*` token 与设计标尺（H24 / H25 / H29）；面板随设置弹窗 lazy chunk，不新增首屏依赖（H31）。

### 7. 测试清单

**判定层（单测）**
- 8 套内置全部通过 `validate_config`；`standard` 与 `DEFAULT_THEME` 对应字段逐项相等（I2）。
- `normalize_ref`：`builtin:thesis` / `"3"` / `None` / `"builtin:nope"` / `"abc"` / 空串。
- `validate_config` 边界：字号 7 / 73、行距 0.9 / 3.1、缩进 9、颜色 `#12` / `red`、未知字段、枚举外取值。
- `resolve_export_template`：显式 > 默认 > standard；跨工作区 id 404。
- 标题编号：`arabic_multilevel` / `chapter_chinese` / `cn_ordinal` 的前缀生成。

**接口层**
- 列表：未建模板时返回 8 套内置且 `default_ref == 'builtin:standard'`；viewer 可读。
- 写：owner/editor 建立 / 更新 / 删除 / 设默认；viewer 403；重名 400；改删内置 400；跨工作区 404。
- preview：`format=docx` 返回 `PK\x03\x04`、`format=pdf` 返回 `%PDF`；配置生效（docx 解压 `word/styles.xml` 断言字体）。
- 导出：`format=docx&template=builtin:thesis` 正文字体宋体、H1 18pt；`format=pdf&template=builtin:official` 200 且页数 > 0；不带 template 与改造前一致；`format=md&template=...` 忽略参数仍 200。

**迁移 / 备份**
- 迁移 upgrade 幂等（跑两次）、downgrade 删表可还原。
- 备份 v17 往返：名称 / 配置 / 默认标记一致；旧备份（v16，无 `templates`）导入成功且无自定义模板；多默认异常包只保留首条。

**前端单测**
- `TemplatePanel`：列表渲染内置 / 自定义、套用预设填充表单、保存调用、删除二次确认、预览请求带当前配置、未进工作区空态。
- `SettingsModal`：`template` 页签存在且紧跟 `llm`。
- `MainLayout`：`template-settings-btn` 紧邻 `llm-settings-btn` 右侧并打开对应页签。
- `DocumentEditorPage`：导出 Word / PDF 子菜单列出模板并带 `template` 参数。

**e2e（前端）**
- 进入模板面板 → 另存为「论文（自定义）」→ 改正文字号 → 保存 → 文档页导出 Word 选该模板 → 下载成功（断言 200 与文件名）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `ExportTemplateConfig` + 8 套内置 + `resolve_export_template` + 迁移 + 备份 v17 | 低（纯新增，未接调用方） |
| **P1** | `_render_docx` 全量改读配置（含标题编号 / 题注 / 三线表 / 页眉页脚 / 页边距）+ 导出端点 `template` 参数 + preview 端点 | 中（排版回归，以 I2 断言兜底） |
| **P2** | `_render_pdf` 改读同一配置 + `pdf_fonts.ensure_pdf_font(family)` 族匹配与回落 | 中（字体可用性差异，需固定降级口径） |
| **P3** | 模板 CRUD 路由 + 前端面板 / 页签 / 顶栏入口 / 导出子菜单 + 测试 | 中（权限与默认链口径） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 模板归属粒度 | 工作区级（共享、随备份） | 企业规范要求同工作区导出一致；备份已按工作区组织 | 个人级（同文档不同人导出不一致，与 C4 冲突）；全局内置（不可按部门定制） | `documents_exporttemplate` |
| D2 | 内置模板是否入库 | 代码常量 + 「另存为」落表 | 升级不覆盖用户改动；内置不可变语义零成本 | seed 入库（需 `is_builtin` 列 + 回填 + 升级去重） | `services/export/templates.py` |
| D3 | 表名与品类列 | `documents_exporttemplate`，不带 `kind` 列 | 本期只有导出模板一种；将来加品类再迁移，避免现在写死的空枚举 | `documents_documenttemplate` + `kind`（当前只有一种值，属过度设计） | 迁移 |
| D4 | 配置存储形态 | 单 JSON 列 + pydantic 严格校验 | 排版项持续增加，避免每加一项都做迁移 | 多列（迁移 / 校验成本高）；YAML 文本（无法强类型校验） | `config` 列 |
| D5 | 生效格式范围 | **docx + pdf 共用一份配置** | 需求方要求一套模板兼顾 PDF（C6）；两者本就同源（Markdown → 块），差异只在渲染器 | 只做 docx（导出物与模板承诺不一致，用户在 PDF 里看着像另一套规范）；两套独立模板（配置翻倍、易漂移） | `docx.py`、`pdf.py` |
| D6 | PDF 字体族策略 | `ensure_pdf_font(family)`：按 config 的中文字体族在已装 CJK 字体里最佳匹配，失败回落默认字体（静默、不报错）；按族缓存注册名 | PDF 只能嵌入服务器已装字体；模板改字体不应让导出失败 | 强制嵌入字体文件（需分发字体、许可风险）；忽略字体只对字号生效（模板承诺打折） | `pdf_fonts.py` |
| D7 | PDF 不支持项处理 | 字间距 / 题注域 / 目录 / 三线表细边框：PDF 侧静默跳过或近似；docx 侧完整生效 | I3 要求降级不报错、不改可见内容 | 为 PDF 单独裁剪配置（模板语义分叉）；PDF 直接 400（导出不可用） | `pdf.py` |
| D8 | 模板解析入口 | 唯一 `resolve_export_template` | 与仓库既有「判定唯一入口」范式一致，避免前后端各写默认链 | 前端拼默认（同工作区结果可能不同） | `templates.py` |
| D9 | 默认模板数量 | 每工作区至多一条 `is_default`，未设即内置 standard | 导出缺省行为可预测 | 无默认（每次必须选，易误用）；多默认（取决顺序，不可预测） | 服务层 + 索引 |
| D10 | `template` 参数形态 | `builtin:<key>` 或正整数 id | 一个参数覆盖内置与自定义 | 两个参数（`preset` / `template_id`，校验分叉） | `routers/documents.py` |
| D11 | 备份版本 | 16 → 17，新增 `templates[]`；旧包缺键按空 | H13 / H14：新表必须往返且旧包可导入 | 复用 v16（格式变更无标记，排查困难） | `workspace_backup.py`、`backup_io.py` |
| D12 | 面板入口形态 | 顶栏图标（大模型设置右侧）+ 个人设置页签双入口，同一面板 | 与「大模型设置」既有范式一致（C1） | 独立整页路由（多一层导航，与 C1 不符） | `MainLayout.tsx`、`SettingsModal.tsx` |
| D13 | 预览实现 | 服务端 `preview` 返回真实 docx / pdf + 面板内 CSS 等比预览 | 所见即所得需真实文件；CSS 预览保证即时反馈且不落库 | 只做 CSS（看不清真实效果）；只做下载（反馈慢） | `TemplatePanel.tsx`、`routers/templates.py` |
| D14 | 字号输入形态 | UI 同时显示中文号名与磅值（小四 = 12pt），存磅值 | 国内企业规范按号数沟通，存储保留数值精度 | 只存号名（不同号制口径不一，且 Word 用磅） | `templateOptions.ts` |
| D15 | 明确非目标 | 目录 / 封面 / LOGO / 双栏 / 脚注尾注不纳入本期 | 域代码与分页成本高，收益待验证 | 一并做（P0-P3 无法收敛） | — |

## Consequences

- **正向**：Word / PDF 导出从「一种硬编码样式」变为可按企业规范配置；8 套内置覆盖论文 / 报告 / 公文 / 周报 / 宣传等常见书面语体；模板随工作区共享与备份，团队口径统一。
- **负向**：新增一张表、一套 CRUD、一份较大的配置模型；两个渲染器都要逐处替换硬编码取值，P1/P2 改动面大。
- **风险与缓解**：字体缺失（用户填了服务器没有的字体）→ Word 端由 Word 回落、PDF 端按 D6 最佳匹配回落，面板内提示「字体需在打开文档的机器 / 服务器上可用」；配置项过多导致面板臃肿 → 五组折叠 + ★/☆ 分层，首屏只展开「正文」。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | `src/cndb/plugins/documents/services/export/templates.py` | `tests/test_export_templates.py` | — |
| P1 | 未开始 | `src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/routers/documents.py` | `tests/test_export_templates.py` | — |
| P2 | 未开始 | `src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/export/pdf_fonts.py` | `tests/test_export_templates_pdf.py` | — |
| P3 | 未开始 | `src/cndb/plugins/documents/routers/templates.py`、`frontend/src/pages/settings/TemplatePanel.tsx` | `frontend/src/pages/settings/TemplatePanel.test.tsx` | — |

## 交接（会话结束更新）

- 当前阶段：方案评审（Proposed，等待人工确认 C3 明细与 8 套内置清单）
- 已完成：需求卡片 0152（含澄清结论）、本 ADR、现状核对（`export/theme.py`、`docx.py`、`pdf.py`、`pdf_fonts.py`、`routers/documents.py`、`SettingsModal.tsx`、`MainLayout.tsx`、`backup_io.py`）
- 下一步：确认后按 P0 → P3 实现；P0 先落 `templates.py` 与迁移，并用单测锁定 I2（standard == DEFAULT_THEME）
- 已知坑：`_HEADING_SIZES` 在 `docx.py` 与 `pdf.py` 各有一份需一并收敛；备份版本升 17 要同步 `backup_io` 白名单与旧包兼容用例；PDF 字体族匹配需在无 CJK 字体环境下也保持「回落不报错」
- 最近一次全绿：未开始实现
