# ADR 0010: 文档通用文件导入（md / docx / html，单文件与文件夹模式）

Status: Accepted（已评审）
Date: 2026-10-20
Related: `plugins/documents/routers/vault.py`、`plugins/documents/services/obsidian.py`、`plugins/documents/services/parse.py`、`plugins/documents/services/content.py`、`plugins/documents/services/export/docx.py`、`frontend/src/pages/documents/ObsidianImportModal.tsx`
需求卡片: `docs/requirements/0010-document-file-import.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 文档，导入，增加…导入模式 | 新增导入服务 `services/importers/`，新增端点 `POST /{wid}/documents/import/files/analyze` 与 `POST /{wid}/documents/import/files`（multipart 文件批次）；前端新增导入入口弹窗。 |
| C2 | 单个文件…导入模式 | 批次含 1 个文件即单文件模式：解析为 1 篇文档，落在 `parent_id`；无相对路径或路径仅文件名时即为单文件。 |
| C3 | …或者文件夹导入模式 | 批次含多个文件且带相对路径：按路径段构建文件夹层级（`_folder_chain` 同款递增去重），每个文件 → 一篇文档。 |
| C4 | 支持…md、docx、html三种格式 | 格式分派按扩展名：`.md`/`.markdown`、`.docx`、`.html`/`.htm`；其余扩展名进 `skipped`（不中断整批）。 |
| C5 | 导入时能够自动格式化 | 三种源格式统一转换为 **Markdown**（项目正文唯一格式）；转换器：md 语义无损规整、docx（`python-docx`）→ md、html（标准库 `html.parser`）→ md。 |
| C6 | 自动识别标题和正文内容 | 标题提取器：内嵌标题（md front-matter `title` / docx Heading1 或 core properties / html `<title>`/首个 `<h1>`）→ 文件名（去扩展名）；**命中标题行从正文剥离**，不重复出现。 |
| C7 | 自动清理多余空格 | 规整器 `normalize_markdown`：行尾空白、连续 ≥3 空行折叠为 1、行内连续空格折叠为 1、行首缩进空白清理；**跳过代码围栏 / front-matter / 表格对齐空白**（保语义）。 |
| C8 | 完善功能和单元测试，足够健壮 | 转换器/规整器/标题提取各配单测；防御：体积与条目上限、编码兜底、畸形 docx/html 不崩溃（降级为纯文本）、逐条失败不中断整批。 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 导入仅 Obsidian 库 zip，两道式 `analyze`/`import` | `routers/vault.py:62-108`、`services/obsidian.py:1016-1225` | 无单文件 / 多文件（文件夹）上传通道 | 确认（复用其两段式与写入骨架） |
| 2 | `.docx` 仅作附件白名单与导出渲染，无「读入转 Markdown」 | `obsidian.py:116`、`services/export/docx.py:21-28` | 需新增 docx → Markdown 方向解析 | 确认（C4/C5 主缺口） |
| 3 | `.html` 未支持（白名单无、无解析器） | `obsidian.py:95-126` | 需新增 html → Markdown 解析 | 新增 |
| 4 | 正文格式统一 Markdown，`content_type` 仅 `markdown`/`folder` | `models.py:43-44` | 导入产物一律 Markdown，无需新类型 | 确认（I1 依据） |
| 5 | 标题清洗已有，但**正文级空白规整缺失** | `obsidian.py:351-363`（`_clean_title`/`_safe_filename`） | C7 无落点 | 确认（复用 `_clean_title` 口径） |
| 6 | 结构识别能力已有（front-matter / TOC / 摘要 / 双链） | `services/parse.py:29-97` | 可复用，无需新造 | 确认（复用） |
| 7 | 写入复用 `content.create_document` / `update_content`（版本化 + 分级存储 + 标签） | `services/content.py:211-228` | 导入产物走同一写入路径 | 确认（复用） |
| 8 | 冲突策略 `skip/rename/overwrite` 已有 | `obsidian.py:131-134` | 复用，默认 `rename` | 确认（复用） |
| 9 | 前端导入入口仅 Obsidian 弹窗（`accept=".zip"`） | `ObsidianImportModal.tsx:237-260`、`DocumentsPage.tsx:884` | 需扩展 / 新增导入 UI | 确认（前端入口候选） |
| 10 | 附件落盘 + 归属登记机制已有 | `obsidian.py:971-1013`（`_AttachmentStore`） | docx/html 内嵌图可选复用 | 确认（受 D2 决定） |
| 11 | 上传大小校验分散（zip 校验收口在 `VaultArchive`） | `routers/vault.py:37-48` | 新批次上传需自己的体积 / 条目 / 单文件上限校验 | 新增 |

**核心缺陷（需求要补的）**：现有导入只认 Obsidian 库 zip，**既不能单文件上传、也不能把 docx/html「读入并转成 Markdown」**，且没有任何正文级空白规整与「内嵌标题识别」。需求要的三件事（单文件/文件夹通道、三种格式转换、自动标题 + 空白清理）在现模型上无一可表达。

设计目标（不变量）：

- **I1 正文格式单一**：导入后一切文档正文均为 Markdown（`content_type=markdown`），docx/html 一律转换为 Markdown，不引入新内容类型。
- **I2 写入可回溯**：导入产物经 `create_document`/`update_content` 落库，产生 `DocumentVersion`，`change_type=auto_import`；冲突策略复用 `skip/rename/overwrite`。
- **I3 清理不破语义**：空白规整**不得**改动代码围栏、front-matter、表格分隔行内的空白（Markdown 会因之失真）。
- **I4 权限一致**：导入需 `editor+`（复用 `content.require_editor`），与既有导入一致。
- **I5 逐条隔离**：单个文件解析失败 / 超限 / 格式不支持时**只跳过该条**，整批继续，结果以 `skipped` 明细回传（部分成功）。

## Decision

### 1. 数据模型

无新表、无新列、无新枚举。导入产物复用 `documents_document` / `documents_documentversion`；`Document.content_type` 恒为 `markdown`，`is_folder` 表达文件夹节点。格式来源（md/docx/html）**不落库**（仅作转换输入），避免为「来源格式」引入字段（I1）。

### 2. 转换管线（唯一入口）

新增 `plugins/documents/services/importers/`（包），单一入口：

```python
@dataclass
class ImportedDoc:
    path: str            # 批次内相对路径
    title: str           # 识别后的标题
    body: str            # 规整后的 Markdown 正文
    source_suffix: str   # .md/.docx/.html
    warnings: list[str]

def convert_file(path: str, data: bytes) -> ImportedDoc:
    """按扩展名分派 → 解码 → 提取标题 → 转 Markdown → 规整；不支持时抛 UnsupportedImport。"""

def convert_batch(files: list[UploadedItem]) -> tuple[list[ImportedDoc], list[dict]]:
    """逐条转换（I5 隔离）；返回（成功项, 跳过明细）。"""
```

子模块职责：

| 文件 | 职责 |
|---|---|
| `importers/__init__.py` | facade re-export（`convert_file` / `convert_batch` / 常量） |
| `importers/reader.py` | 批次读取：体积 / 条目 / 单文件上限、扩展名分派、编码兜底（`utf-8-sig`→`utf-8`→`gb18030`→`chardet`→latin-1） |
| `importers/normalize.py` | `normalize_markdown`：空白规整（I3 跳过围栏/front-matter/表格） |
| `importers/markdown.py` | md 源：front-matter 标题提取 + 正文剥离 + 规整 |
| `importers/docx.py` | docx → Markdown（`python-docx`：Heading→`#`、段落、列表、表格→ pipe table、（可选）图片） |
| `importers/html.py` | html → Markdown（标准库 `html.parser`：h1-h6/段落/列表/链接/strong/em/code/table） |
| `importers/importer.py` | 落库编排：文件夹层级 / 冲突策略 / 附件登记 / 统计汇总 |

标题识别顺序（唯一）：

```
1. 源内嵌标题：md front-matter.title → docx 首个 Heading1 → docx core.title → html <title> → html 首个 <h1>
2. front-matter / 首行的显式标题行（# ...）              （去重：命中的标题行从正文剥离）
3. 文件名去扩展名（_clean_title 同款清洗，上限 500）
```

规整规则（C7）：

```
- 换行统一 \n；行尾空白剔除
- 行内连续空格 → 单空格（I3：代码围栏 / 表格行 内不动）
- 连续空行 > 2 → 保留 1 个空行；文末多余空行剔除
- 行首 0~3 空格视为无效缩进清理（列表 / 引用 / 围栏缩进保留）
- 首尾整体 strip
```

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /{wid}/documents/import/files/analyze` | **新增**：multipart 批次（`files[]` + 可选 `paths[]`）→ 只读预览（篇数 / 文件夹 / 冲突 / 跳过 / 告警），不落库 |
| `POST /{wid}/documents/import/files` | **新增**：按确认的冲突策略 / 状态真正导入，返回 `created/updated/skipped/folders_created/documents/warnings`（结构对齐既有 `import_vault`） |
| `POST /{wid}/documents/import/analyze`、`POST /{wid}/documents/import` | 不变（Obsidian zip 通道保留；是否并入将随 D5 决定） |

上传批次校验：条目数上限、单文件字节上限、总字节上限、扩展名白名单（`.md/.markdown/.docx/.html/.htm`）——收口在 `importers/reader.py`（对应现状 #11 的新增项）。

### 4. 边界与例外

1. **相对路径安全**：`paths` 一律归一化（拒绝绝对路径 / `..` / 盘符），复用 `obsidian._normalize_entry_path` 同款口径；隐藏目录跳过规则复用 `_is_skipped_path`。
2. **编码**：md/html 解码按 `utf-8-sig`→`utf-8`→`gb18030`→`chardet`→`latin-1(errors=replace)`；任一步失败不抛 500（I5）。
3. **畸形文档**：docx 非 zip / 结构损坏、html 无有效标签 → 降级（docx 失败记 skip；html 取纯文本），不崩溃。
4. **空文档**：正文为空的文件仍导入为文档（标题兜底「未命名」），或按 D 决定跳过。
5. **标题重名**：同目录同名走冲突策略（默认 rename 追加「 (2)」）；目标是文件夹时按 rename 处理（沿用 `import_vault` 两类分支）。
6. **图片 / 附件**：docx/html 内嵌图与链接的处理见 D2。
7. **超限**：单文件超限只跳过该条；批次总量超限整体 400（与 `VaultArchive` 口径一致）。
8. **缓存**：导入后失效文档树缓存（复用 `invalidate_document_tree_cache`）。
9. **权限**：`require_editor`（I4）；目标 `parent_id` 必须是文件夹。

### 5. 迁移

无（不新增表 / 列 / 索引，复用既有文档与版本模型）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 导入弹窗 | `frontend/src/pages/documents/DocumentImportModal.tsx`（新增，或扩展 `ObsidianImportModal.tsx`，见 D5） | 单文件 / 文件夹模式切换；`accept=".md,.markdown,.docx,.html,.htm"`；文件夹模式用目录选择（`webkitdirectory`，取 `file.webkitRelativePath` 作为 `paths`）；两段式 analyze→import；预览表 + 冲突策略 + 状态选择 |
| 入口 | `frontend/src/pages/documents/DocumentsPage.tsx`（`~:884` 附近） | 工具栏新增「导入文件」入口按钮 |
| API | `frontend/src/api/documents.ts` | 新增 `filesAnalyze` / `filesImport`（multipart：`files` + `paths` + 选项） |
| 类型 | `frontend/src/api/documents.ts` | `FileImportAnalyzeResult` / `FileImportResult` / `FileImportOptions` |

### 7. 测试清单

**判定层（单测）**

- 标题识别：`front-matter.title` 优先；docx Heading1；html `<title>` / `<h1>`；均缺省取文件名；标题行从正文剥离不重复；
- `normalize_markdown`：行尾空白、连续空行折叠、行内多空格折叠、行首缩进清理；**围栏 / front-matter / 表格内空白不变**（I3）；文末空行剔除；
- 格式分派：`.md/.markdown/.docx/.html/.htm` 命中；`.txt/.pdf/.zip` → skip；
- 编码兜底：UTF-8-BOM / GB18030 中文样例解得正确；
- docx 转换：标题层级、段落、列表、表格（pipe table）、空段处理；
- html 转换：h1-h6、`<p>`、`<ul>/<ol>`、`<a>`、`<strong>/<em>`、`<code>/<pre>`、`<table>`；嵌套列表；脏 HTML（未闭合标签）不崩溃。

**接口层**

- `analyze`：预览篇数 / 文件夹 / 冲突 / 跳过 / 告警，**不落库**（复查库内无新增）；
- `import`：三种格式各一例落库，正文 == 规整后 Markdown，标题 == 识别结果；
- 文件夹模式：两层相对路径 → 两级文件夹节点 + 文档；隐藏目录 / 非法路径跳过；
- 冲突策略：`skip`/`rename`/`overwrite` 三态；`overwrite` 走 `update_content` 生成新版本且 `change_type=auto_import`；
- 权限：非 editor → 403；非成员 → 403；`parent_id` 非文件夹 → 409；
- 超限：单文件超限只跳过该条；总条目/总量超限 → 400；
- 部分成功：混合合法与畸形文件，返回 `skipped` 明细且合法项已落库（I5）。

**迁移 / 备份**

- 无新表，无需迁移用例；既有文档备份往返不受影响（回归抽查）。

**e2e（前端）**

- 单文件导入：选 1 个 `.docx` → 预览 → 导入 → 新文档标题/正文正确；
- 文件夹导入：选目录 → 预览显示文件夹层级 → 导入 → 树出现文件夹与文档；
- 不支持的扩展名被拒 / 提示。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 转换管线 + 判定单测** | `services/importers/`（reader / normalize / markdown / docx / html）+ 标题识别 + 规整器 + 全量单测。不开放端点 | 低 |
| **P1 端点接入 + 落库** | `import/files/analyze` + `import/files` 两个端点；文件夹层级 / 冲突策略 / 权限 / 边界（I5）；接口层测试 | 中 |
| **P2 前端入口** | 导入弹窗（单文件 / 文件夹模式）+ Page 入口按钮 + api 封装 + 前端单测 + e2e | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | **新增独立转换管线 `services/importers/` + 两个新端点**，转换器按格式拆分；不改造 Obsidian 通道内部 | C4/C5 需要「源 → Markdown」的正向转换，既有 obsidian 只处理库内 md 语法改写，职责不同 | ① 塞进 `obsidian.py` 单文件（职责膨胀，且 zip 与文件批次载体不同）；② 只支持 md（不满足 C4） | `services/importers/` + `routers/file_import.py` |
| D2 | docx / html 内嵌图片处理 | **抽取为站内附件**（复用 `_UploadStore`）；html 外链图片保留原 URL 不下载 | 用户 2026-10-20 确认；既有导入已具备附件机制，复用成本低 | 仅保留占位（体验差）/ 一并下载外链（引入 SSRF 与超时风险） | `importers/docx.py`、`importers/html.py` |
| D3 | 标题识别优先级 | **内嵌标题 > 首个显式标题行 > 文件名**；命中标题行从正文剥离 | 用户确认；C6 要求「自动识别标题和正文内容」，需固定优先级并防标题重复 | 仅用文件名（丢失文档内标题）/ 保留标题行在正文（重复） | `importers/*.py` 标题提取 |
| D4 | 空白规整边界 | **保守清理**：只清行尾空白、折叠连续空行、折叠行内连续空格、清无效行首缩进；**不删中英文间空格**，不改围栏/front-matter/表格 | 用户确认；「中英文间空格」误伤风险高（I3 保语义） | 激进删除所有空格（破坏可读性/语义） | `importers/normalize.py` |
| D5 | 与既有 Obsidian 导入的关系 | **新建独立入口「导入文件」**，保留 Obsidian 通道不动 | 用户确认；载体不同（文件批次 vs zip）、格式集合不同（三类源 vs 库语法），独立更清晰 | 合并为一个入口（模式分支增多，zip 与目录上传 UI 语义不同） | `DocumentImportModal.tsx` / `DocumentsPage.tsx` |
| D6 | 文件夹模式上传载体 | **浏览器目录选择**（`webkitdirectory`，多文件 + `paths`）；zip 由 Obsidian 通道承担 | 用户确认；浏览器无原生目录树上传，zip 已在既有通道 | 仅支持 zip（不够直观）/ 仅支持多选文件（丢失目录结构） | `importers/reader.py` + 前端 |
| D7 | 导入文档默认状态 | **草稿**（`draft`），与既有导入默认一致 | I4 一致 + 降低误发风险 | 已发布（导入即对全工作区可见） | 端点 Form 默认值 |
| D8 | 冲突默认策略 | **`rename`**（保留两份） | 与既有导入默认一致（无损、可回溯） | `skip` / `overwrite` 作默认（有丢失或覆盖风险） | 端点 Form 默认值 |
| D9 | 转换失败的粒度 | **逐条隔离**（I5）：单条失败只记 `skipped`，整批继续 | C8「足够健壮」；批量导入不应因单文件中断 | 整批失败（一个坏文件毁掉整批） | `importers/reader.convert_batch` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。D2/D3/D4/D5/D6 已于 2026-10-20 由需求方拍板，本表无「待定」，`Status` 置 `Accepted`。

## Consequences

- **正向**：文档模块首次具备「通用文件导入」通道——单文件 / 文件夹、三种格式（md/docx/html）统一转 Markdown 落库，复用既有版本化、标签、冲突策略、附件与权限骨架；转换器与规整器分模块，单测可独立覆盖；逐条隔离保证批量健壮。
- **负向**：
  1. docx/html → Markdown 是**有损转换**（复杂样式、合并单元格、浮动图片、内联样式无法完全还原），需在 UI 明示「自动格式化」的边界。
  2. 新增 `.docx` 读取路径复用 `python-docx`（依赖已在）；html 用标准库解析，但样式/脚本一律丢弃，保真度有限。
  3. 多文件批次上传与文件夹相对路径校验引入新的攻击面（路径穿越 / 解压炸弹不再适用，改用条目与体积上限），需专门用例。
  4. 与 Obsidian 通道并存可能造成入口冗余（待 D5 收敛）。
- **风险与缓解**：转换保真度不达预期 → 规整器只做「保守清理」（D4）；大文件 / 图表文档 → 体积上限 + 逐条隔离（I5）。

## 行业对照（可选）

| 维度 | 飞书云文档「导入」 | Notion Import | 本设计 |
|---|---|---|---|
| 支持格式 | doc/docx/pdf/md/txt 等 | md/html/docx/txt/zip | md/docx/html（C4 限定三类） |
| 目录结构 | 单文件为主 | zip 保留目录树 | 单文件 / 文件夹（多文件 + 相对路径，D6） |
| 转换目标 | 自有块结构 | 自有块结构 | Markdown（项目正文唯一格式，I1） |

来源：飞书云文档帮助中心《导入文件》；Notion Help《Import your content》。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 转换管线 + 判定单测 | 已落地 | `src/cndb/plugins/documents/services/importers/reader.py`、`src/cndb/plugins/documents/services/importers/normalize.py`、`src/cndb/plugins/documents/services/importers/markdown.py`、`src/cndb/plugins/documents/services/importers/docx.py`、`src/cndb/plugins/documents/services/importers/html.py` | `tests/test_documents_file_import_convert.py` | a322f993 |
| P1 端点接入 + 落库 | 已落地 | `src/cndb/plugins/documents/routers/file_import.py`、`src/cndb/plugins/documents/services/importers/importer.py` | `tests/test_documents_file_import_api.py` | a322f993 |
| P2 前端入口 | 已落地 | `frontend/src/pages/documents/DocumentImportModal.tsx`、`frontend/src/api/documents.ts`、`frontend/src/pages/documents/DocumentsPage.tsx` | `frontend/src/pages/documents/DocumentImportModal.test.tsx`、`frontend/tests/e2e/critical/document-file-import.spec.ts` | a322f993 |

## 交接（会话结束更新）

- 当前阶段：P0/P1/P2 均已落地，功能与测试完成，待收尾提交
- 已完成：转换管线（md/docx/html → Markdown，标题三级识别 + 剥离，保守空白规整）；两段式端点（analyze/import）+ 落库编排（文件夹层级 / 冲突三策略 / 附件登记）；前端弹窗（单文件 / 文件夹模式）+ Page 入口
- 测试：后端新模块覆盖率 99%（整体 98.12% ≥ 95%）；前端单测 6 例；e2e 单文件 / 文件夹 2 例通过
- 已知坑：模块名为 `importers`（`import` 是 Python 保留字，无法作为包名）；antd `Radio.Group optionType="button"` 的可点击目标是 label，`getByRole("radio")` 命中的是隐藏 input；本环境浏览器不支持给 webkitdirectory input 注入目录，e2e 文件夹模式在页面内合成含 `webkitRelativePath` 的 FileList 后走真实 UI/后端
- 下一步：无（功能已完结）
- 最近一次全绿：见本次收尾 `make check` 结果
