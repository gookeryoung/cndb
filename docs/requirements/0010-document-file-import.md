# 需求卡片：文档导入（单文件 / 文件夹，md / docx / html，自动格式化）

- 编号：0010（与 ADR `docs/adr/0010-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-20
- 关联 ADR：`docs/adr/0010-document-file-import.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档，导入，增加单个文件或者文件夹导入模式，支持文件格式包含md、docx、html三种格式。导入时能够自动格式化，自动识别标题和正文内容，自动清理多余空格。请完善功能和单元测试，确保其足够健壮。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 文档，导入，增加…导入模式 | 在 documents 插件新增「通用文件导入」端点与前端入口：上传本地文件（单文件 / 文件夹）→ 落库为文档（或文件夹树 + 文档） | `plugins/documents/routers/`、`plugins/documents/services/`、`frontend/src/pages/documents/` | 接口测试：上传样例后文档存在且正文/标题正确 |
| C2 | 单个文件…导入模式 | **单文件模式**：一次上传 1 个文件 → 生成 **1 篇**文档（放在 `parent_id` 指定文件夹或根目录） | 导入服务（单文件路径） | 测试：单文件导入后仅新增 1 篇，标题/正文符合规则 |
| C3 | …或者文件夹导入模式 | **文件夹模式**：一次提交同一目录树下的多个文件（含相对路径）→ 目录层级映射为**文件夹节点**，每个文件映射为一篇文档 | 导入服务（文件夹路径）、前端目录选择 | 测试：两层目录 → 两级文件夹 + 文档；空目录/隐藏目录处理 |
| C4 | 支持文件格式包含md、docx、html三种格式 | 接受 `.md`/`.markdown`、`.docx`、`.html`/`.htm` 三种源格式；其它扩展名按「不支持」跳过并计入 `skipped`，不影响整批 | 导入服务（格式分派 + 白名单） | 测试：三种格式各一例均成功；`.txt`/`.pdf` 被跳过 |
| C5 | 导入时能够自动格式化 | 导入正文**统一为 Markdown**：docx 按标题样式/段落/列表/表格/图片转为 Markdown；html 按元素树转为 Markdown；md 做语义无损规整 | 导入服务（`docx`/`html`/`markdown` 转换器） | 测试：docx/html 转换结果断言为预期 Markdown |
| C6 | 自动识别标题和正文内容 | **标题识别优先级**：源文档内显式标题（md front-matter `title` / docx 首个 Heading 1 或 metadata title / html `<title>` 或首个 `<h1>`）→ 文件名（去扩展名）；**标题行从正文中剥离**，正文保留其余结构 | 导入服务（标题提取）+ `services/parse.py` | 测试：有内标题取内标题；无内标题取文件名；标题不重复出现在正文 |
| C7 | 自动清理多余空格 | 正文规整：行尾空白、连续（≥3）空行、段内连续空格、行首缩进空白的清理；**不破坏 Markdown 语义**（代码围栏 / 表格 / front-matter 内原样保留） | 导入服务（`normalize` 规整器） | 测试：脏样例被规整为干净 Markdown；代码块内空白不变 |
| C8 | 请完善功能和单元测试，确保其足够健壮 | 转换器/规整器/标题识别均配单元测试；边界与防御：体积与条目上限、编码兜底、畸形 docx/html 不崩溃、逐条失败不中断整批（部分成功返回）、权限与冲突策略复用既有口径 | `tests/`、`frontend/src/**/*.test.tsx` | `make cov` 后端 ≥95%；前端双门槛；新增用例全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 现有导入仅支持 Obsidian 库 zip（`.md`/`.markdown` + canvas/base + 附件） | `plugins/documents/routers/vault.py:62-108`、`plugins/documents/services/obsidian.py` | 无单文件/多文件上传通道 |
| 2 | `.docx` 仅作附件白名单与导出渲染，无「读入转 Markdown」 | `obsidian.py:116`、`plugins/documents/services/export/docx.py:21-28` | 需新增 docx → Markdown 解析 |
| 3 | `.html` 完全未支持（附件白名单无、无解析器） | `obsidian.py:95-126` | 需新增 html → Markdown 解析 |
| 4 | 正文格式统一 Markdown，`content_type` 仅 markdown/folder | `plugins/documents/models.py:43-44` | 转换产物一律 Markdown |
| 5 | 标题清洗已有（NFKC + 空白折叠），但**正文级空白规整缺失** | `obsidian.py:351-363`（`_clean_title`/`_safe_filename`） | 需求 C7 的落点 |
| 6 | 结构识别能力已有（front-matter / TOC / 摘要 / 双链） | `plugins/documents/services/parse.py:29-97` | 复用，避免重复造轮子 |
| 7 | 内容版本化 / 分级存储 / 标签复用既有服务 | `plugins/documents/services/content.py:211-228`（`create_document`/`update_content`） | 导入产物走同一写入路径 |
| 8 | 冲突策略 `skip/rename/overwrite` 已有 | `obsidian.py:131-134` | 复用，默认 rename |
| 9 | 前端导入入口仅 Obsidian 弹窗（`accept=".zip"`） | `frontend/src/pages/documents/ObsidianImportModal.tsx:237-260`、`DocumentsPage.tsx:884` | 需扩展/新增导入 UI |
| 10 | 附件落盘与归属登记机制已有 | `obsidian.py:971-1013`（`_AttachmentStore`） | docx/html 内嵌图片可选择复用 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **文件夹模式的上传载体**：浏览器「目录选择」（`webkitdirectory`，多文件 + 相对路径）；zip 由既有 Obsidian 通道承担（用户 2026-10-20 确认）。
- [x] **docx / html 内嵌图片的处理**：抽取为站内附件（复用 `_AttachmentStore`）；html 外链图片保留原 URL 不下载（用户确认）。
- [x] **标题识别优先级**：内嵌标题 > 首个显式标题行 > 文件名；命中标题行从正文剥离（用户确认采纳建议）。
- [x] **空白清理边界**：保守清理——只清行尾空白、折叠连续空行、折叠行内连续空格、清无效行首缩进；**不删中英文间空格**，不改代码围栏 / front-matter / 表格（用户确认）。
- [x] **与既有 Obsidian 导入的关系**：新建独立入口「导入文件」，保留 Obsidian 通道不动（用户确认）。
- [x] **文档状态与冲突策略默认值**：默认草稿（`draft`）+ 冲突默认 `rename`，与既有导入一致（用户确认采纳建议）。
- [x] **别名扩展名**：支持 `.markdown` 与 `.htm`（用户确认采纳建议）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-20）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
