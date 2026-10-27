# ADR 0049: MHTML 导入（内嵌素材入库，图片不丢失）

Status: Implemented（2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-27
Related: `src/cndb/plugins/documents/services/importers/`、`src/cndb/plugins/documents/routers/file_import.py`、`frontend/src/api/documents.ts`、`frontend/src/pages/documents/DocumentImportModal.tsx`；上游 ADR 0010 / 0025
需求卡片: `docs/requirements/0049-mhtml-import.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | MHTML 格式的导入 | `.mhtml` / `.mht` 进入 `CONVERTIBLE_SUFFIXES`；新增 `importers/mhtml.py`：标准库 `email` 解析 MIME multipart，取首个 `text/html` part 喂既有 `convert_html`；`reader.convert_file` 增加 MHTML 分派；单文件上限 32MB；损坏 / 空 / 无 HTML part 抛 `UnsupportedImport`（单条跳过） |
| C2 | 包含素材的 | 图片 part（`get_payload(decode=True)` 解 base64 / quoted-printable）建「src → (素材名, 字节)」索引传给 html 转换器新分支 `mhtml_resources`；正文引用改写为合成相对路径 `_assets/<name>`：`import_attachments` 开 → `image_sink` 落盘为站内附件（`file:` 引用 + 文档归属登记）；关 → 相对引用保留，素材展开为批次图片条目落为 `_assets` 文件夹的图片文档 |
| C3 | 避免引用图片丢失 | 匹配顺序：`Content-Location` 精确 → `cid:` → `Content-ID` → 唯一 basename 兜底；未命中 → 占位 + warning（与 HTML 本地图片同款）；未打包进 MHTML 的外链保留原 URL 不抓取 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 可转换白名单只有 `.md/.markdown/.docx/.html/.htm`，MHTML 被判「不支持的格式」跳过 | `src/cndb/plugins/documents/services/importers/formats.py:26` | `.mhtml` / `.mht` 无法进入转换管线 | 确认 |
| 2 | `convert_file` 按 MARKDOWN / DOCX / HTML 三分支分派，无 MHTML 分支；可转换单文件上限 8MB | `src/cndb/plugins/documents/services/importers/reader.py:35-45,134-145` | 需新增分派与独立上限 | 确认 |
| 3 | HTML 转换器本地图片按「批次相对路径」索引（`LocalImages`），`_resolve_local_src` 对绝对 URL（`http(s)://`、`//` 开头）直接判外链，MHTML 素材键是 URL，两套口径不通 | `src/cndb/plugins/documents/services/importers/html.py:27,166-187,222-242` | MHTML 的 `<img src>` 多为绝对 URL，走现管线会全部保留外链（图片丢失） | 确认（核心缺陷） |
| 4 | `data:` URI 图片已支持落盘；附件落盘 / 归属登记 / `import_attachments` 开关已有（关闭时 sink 返回 None → 占位 + 告警） | `src/cndb/plugins/documents/services/importers/html.py:222-242`、`importers/importer.py:41-97` | MHTML 开关语义可复用，但「关闭即丢图」与 C3 冲突 | 确认 |
| 5 | 导入编排 `analyze_files` / `import_files`、冲突三策略、文件夹映射、原件族落库已齐备 | `src/cndb/plugins/documents/services/importers/importer.py:128-335` | `_assets` 素材文档可直接走原件族路径 | 确认 |
| 6 | 前端 `accept` 与格式文案未含 MHTML | `frontend/src/api/documents.ts:329-330`、`frontend/src/pages/documents/DocumentImportModal.tsx:56-74,120,326` | 用户选不到 / 看不懂 MHTML | 确认 |
| 7 | 转换层与接口层测试基座已有 | `tests/test_documents_file_import_convert.py`、`tests/test_documents_file_import_api.py` | 新用例挂同一基座 | 确认 |
| 8 | Python 标准库 `email.parser` 可解析 MIME multipart（边界 / 传输编码 / Content-Location） | Python 标准库 | 无需第三方依赖 | 确认（新增结论：选标准库） |

**核心缺陷（需求要补的）**：MHTML（网页另存的主流格式）把图片打包在单文件里，现导入管线既不认识该格式，其 HTML 分支对绝对 URL 图片一律「保留外链」，导致转出的 Markdown 图片全部失效。

### 真实样例核对（2026-10-27，快照类 MHTML）

以 Chrome「另存为 MHTML」的长文（含目录锚点、合并单元格表格、mermaid / ECharts 内联 SVG）实测，转换产物存在 4 类失真；均为 HTML 转换器共用缺陷，一并修复：

| # | 症状（转换产物） | 根因 | 修复 |
|---|---|---|---|
| 9 | 目录与引注链接是 `file:///C:/.../page.html#s00`，入库后指向不存在的本地文件；目录 9 条链接挤在同一行 | 转换器对 `href` 原样输出，没有「文档自身」概念 | 指向根 HTML 自身的链接改写成文内标题锚点（D9） |
| 10 | `<pre class="mermaid">` 内渲染后的 SVG 被当代码块输出：几 KB 的 CSS 加节点文字拼成一大段围栏；ECharts 图表被静默丢弃，只剩图题 | `_code_block` 取 `<pre>` 全量纯文本、未跳过 `<svg><style>`；`<svg>` 整体在 `_SKIP_TAGS` 被静默跳过 | 纯文本跳过非正文子树；无源码的图表块丢弃并告警（D10） |
| 11 | 指标表行 `| 产业营业收入 | 亿元 | ... |` 缺「类别」列导致整表错位 | 原实现丢弃 `rowspan` / `colspan`，后续行少一格 | 合并单元格展开为普通网格（D11） |
| 12 | `1. **格局** ：用集中度…` 在标点前多出空格；列表项以空行分隔成「松散列表」 | 列表项各片段 `strip()` 后用空格拼接；每个列表行被当作独立块 | 片段按源码顺序拼接；同一列表输出为一个块（D12） |

设计目标（不变量）：

- **I1 白名单单一真相源**：格式注册只在 `formats.py` 一张表；`reader` / `importer` / 前端 accept 同源派生，不各写一套。
- **I2 逐条隔离**：单个 MHTML 损坏 / 超限只跳过该条，不中断整批（沿用 ADR 0010 C8）。
- **I3 素材不丢**：匹配成功的图片要么落为站内附件（`file:` 引用），要么落为 `_assets` 图片文档（相对引用）；只有匹配不到的才占位 + 告警。
- **I4 既有行为不变**：md / docx / html / 原件族的转换、上限、开关语义不受影响。

## Decision

### 1. 数据模型

无新表 / 新列 / 新迁移。素材复用既有两类载体：站内附件（`files` + `FileOwner`，文档粒度归属）与图片原件族文档（`content_type=image` + `asset_file_key`，ADR 0025）。

### 2. 判定算法（唯一入口）

- **解析入口** `mhtml.parse_mhtml(data) -> (html_text, resources, warnings)`：`email.parser.BytesParser().parsebytes`；`walk()` 全部 part（容忍嵌套 multipart）；首个 `text/html` part 为根 HTML（`decode_text` 解码）；`Content-Type: image/*` 的 part 经 `get_payload(decode=True)` 解码为素材（非图片 part 丢弃）；无 HTML part 或解析失败抛 `UnsupportedImport`。
- **转换入口** `mhtml.convert_mhtml(data, path, *, image_sink=None) -> (title, body, warnings, resources)`：建 src 匹配索引（`Content-Location` 原串 / `cid:<Content-ID>` / 唯一 basename），调 `convert_html(..., mhtml_resources=index)`；未被正文引用的图片素材在 `image_sink` 可用时直接落盘；返回全部图片素材 `(相对名, 字节)` 供 OFF 模式展开。
- **reader 分派**：`convert_file` 新增 `MHTML_SUFFIXES = (".mhtml", ".mht")` 分支，体积上限 `MHTML_MAX_FILE_BYTES = 32MB`（其余可转换格式维持 8MB，判定顺序：MHTML 分支先于通用 8MB 检查）。
- **html 转换器**：`_image_markdown` 增加首个分支——`src` 命中 `mhtml_resources` 时改写为 `_assets/<name>`：`sink` 可用且返回 key → `![alt](file:<key>)`；否则保留 `![alt](_assets/<name>)` 相对引用（OFF / 预览），不再产生「未导入」告警。
- **importer 展开**：`import_files` 在 `import_attachments=False` 时先跑 `_expand_mhtml_resources(items)` 预扫描，把每个 MHTML 的图片素材追加为 `UploadedItem("{md目录}/_assets/<name>", bytes)` → 走原件族路径落为 `_assets` 文件夹下的图片文档。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /{wid}/documents/import/files/analyze` | 行为扩展：接受 `.mhtml` / `.mht`（预览正文保留相对引用、匹配成功不告警）；无参数变更 |
| `POST /{wid}/documents/import/files` | 行为扩展：同上；`import_attachments=false` 时额外产出 `_assets` 素材文档；`import_attachments` 参数描述文案更新 |

### 4. 边界与例外

1. 空 MHTML / 无 `text/html` part / MIME 解析失败 → `UnsupportedImport`（单条跳过）。
2. 根 HTML 内的 `data:` URI 图片走 html 既有分支（OFF 模式下 sink 不可用 → 占位 + 告警，可接受：非「打包素材」引用形态）。
3. 素材重名：`img.png` / `img-2.png` 递增去重；文件名做安全清洗（沿用 `_safe_filename` 同级口径）。
4. `Content-Location` 带 query / fragment：按原串精确匹配，basename 兜底仅在**唯一**命中时生效，歧义视为未匹配。
5. analyze 预览不展开 `_assets` 条目：OFF 落库会比预览多 N 个素材文档（预览仍准确展示文档本体与冲突，差额在导入结果中体现）。
6. MHTML 文件名 / 素材名仅取 basename，目录层级不展开（素材一律平铺进 `_assets/`）。
7. `MAX_FILES` / 批次总体积校验在展开前完成；`_assets` 素材不计入文件数上限（由 32MB 单文件上限兜底）。
8. 二进制 part 的 quoted-printable 编码属非标准输入（RFC 2045 建议二进制走 base64，Chrome / Word 等现实生产者对图片一律 base64）：QP 解码仅承诺 HTML 文本 part 保真，二进制 QP 素材不承诺字节级还原。

### 5. 迁移

无（纯导入行为扩展，存量数据零迁移）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/documents.ts` | `FILE_IMPORT_ACCEPT` 追加 `.mhtml,.mht` |
| 导入弹窗 | `frontend/src/pages/documents/DocumentImportModal.tsx` | `FORMAT_LABEL` 增 `.mhtml` / `.mht` → 「MHTML」；错误提示与格式说明文案补 MHTML |

### 7. 测试清单

**判定层（单测）**（`tests/test_documents_file_import_convert.py`）：
- 基础转换：`<title>` → 标题、正文结构、空白规整与 html 同口径；QP 编码的中文 HTML part 解码正确；
- 素材落盘（ON）：base64 图片 `file:` 引用 + 落盘字节与原素材一致（长度 + 前缀）；
- 相对引用保留（sink=None / OFF）：正文 `![alt](_assets/name)`，匹配成功不产生「图片未导入」告警；
- 匹配：`cid:` 命中、basename 唯一兜底命中、basename 歧义未命中、未命中占位 + warning；
- CSS 等 `text/css` part 丢弃；未被引用的图片素材仍落盘 / 展开；素材重名递增；
- 保真修复（对应「真实样例核对」9-12）：自身绝对链接 → 标题锚点（无标题引注退化到最近标题、跨文档 / 外链保留）、`rowspan` / `colspan` 表格逐行对齐、`<pre>` 内渲染 SVG 不输出 CSS 且告警、图表 `<figure>` 保留图题并告警、列表标点前无多余空格且整表为一个块；
- 体积：8MB < MHTML ≤ 32MB 通过（reader 层），> 32MB 跳过；空文件 / 无 HTML part → `UnsupportedImport`；
- 混合批次：mhtml + md + html 同批互不影响。

**接口层**（`tests/test_documents_file_import_api.py`）：
- ON 导入：1 篇文档 + 附件归属绑定 + 正文 `file:` 引用；
- OFF 导入：文档 + `_assets` 文件夹 + 图片文档（原件可取回）+ 正文相对引用 + 素材不绑附件；
- analyze：预览含 MHTML 且无「图片未导入」告警；损坏 MHTML 计入 `skipped`。

**迁移 / 备份**：无。

**e2e（前端）**：无（accept / 文案由前端单测覆盖，导入主流程 e2e 已被 ADR 0010 覆盖）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `mhtml.py` 解析 + 转换入口、`html.py` 的 `mhtml_resources` 分支、`reader` 分派与 32MB 上限、判定层单测 | 低 |
| **P1** | `importer` OFF 模式 `_assets` 展开、接口层测试 | 中 |
| **P2** | 前端 accept / 文案、CONTEXT.md 术语、CHANGELOG 收尾 | 低 |

### 9. 转换保真修复（真实样例核对后）

- **自身链接**：`convert_html` 新增 `base_url`（MHTML 取根 part 的 `Content-Location`）；`href` 的 scheme / netloc / path 与 `base_url` 相同（或无 scheme 且 basename 与 `ctx.path` 相同）时视为文内链接 —— 该 id 在原文有对应标题则映射到 `#doc-h-<标题 slug>`（与前端 `outline.headingAnchor` 同算法，预览区标题 id 即由此生成，跳转才真正生效），无标题的引注 id 退化到最近标题，其余保留 `#fragment`；跨文档链接原样保留。
- **非正文子树**：`_node_text` 跳过 `_SKIP_TAGS`（script / style / noscript / template / svg / canvas / iframe），围栏代码块不再吞 CSS；`<pre>` 去除非正文后为空且原含 `<svg>` 时整块丢弃并告警「内联 SVG 图表无法转换为文本」。
- **图表**：`<figure>` 内含内联 SVG 且无 `<pre>` 时告警一次；图题（`figcaption`）保留。不把 SVG 转成图片（当前图片通道只接受位图字节，见「交接」已知坑）。
- **表格**：`rowspan` 覆盖的后续行重复单元格文本，`colspan` 多出的列留空，保证列数与表头一致；`rowspan` / `colspan` 非法按 1、上限 1000。
- **列表**：列表项内片段按源码顺序直接拼接（不再逐片段 `strip()` 后插空格），整表列表输出为一个块，避免松散列表。

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体选型 | MHTML 作为第 4 种可转换源格式，解包根 HTML 后复用 ADR 0010 的 html → Markdown 管线，不引第三方库 | 标准库 `email` 足以解析 MIME；转换 / 标题 / 规整口径零重复 | 自建 MIME 解析器（重复造轮子）；引 `mhtml` 第三方库（增加依赖无增益） | `importers/mhtml.py` |
| D2 | 根 HTML 与传输编码 | `email.parser.BytesParser` + `walk()` 全 part；首个 `text/html` 为根；`get_payload(decode=True)` 解 base64 / QP | Chrome / Edge「另存为 MHTML」的标准形态 | 只认 `multipart/related` 顶层（嵌套结构会漏） | `mhtml.parse_mhtml` |
| D3 | 素材匹配口径 | `Content-Location` 精确 → `cid:` → `Content-ID` → 唯一 basename 兜底；未命中占位 + 告警；外链原样保留 | C3「不丢图」要求覆盖相对 / 绝对 / cid 三种引用形态；歧义 basename 静默猜中风险高 | 只做精确匹配（相对引用全丢）；basename 多命中时取第一个（可能张冠李戴） | `mhtml.convert_mhtml` |
| D4 | 引用改写与两种落盘形态 | 正文引用统一改写为合成相对路径 `_assets/<name>`；`import_attachments` 开 → sink 落盘 `file:` 引用；关 → 相对引用保留 + 素材展开为 `_assets` 文件夹图片文档（用户拍板） | 开态站内预览最优；关态素材不丢、树内可管理，与 Obsidian 附件目录习惯一致 | 关态降级占位（丢图，违背 C3）；关态仍绑 `file:` 附件（架空开关语义） | `html.py` `_image_markdown`、`importer._expand_mhtml_resources` |
| D5 | 体积上限 | MHTML 单文件 32MB（= `MAX_ASSET_BYTES`），其余可转换格式维持 8MB | MHTML 把图片打包进单文件，8MB 易触顶（用户拍板） | 全部可转换格式放宽到 32MB（无需求，放大内存峰值） | `reader.MHTML_MAX_FILE_BYTES` |
| D6 | 非图片素材 | `text/css` 等非图片 part 一律丢弃 | HTML 转换不消费样式；保留只会产生孤儿文件（用户拍板） | 保存 CSS 供导出还原样式（当前导出无此消费方） | `mhtml.parse_mhtml` |
| D7 | 产物形态 | 只产出 Markdown 文档，不保留 MHTML 原件 | 与 docx / html 一致；避免双份存储（用户拍板） | 按 ADR 0025 原件族另存原件（双份存储，正文已是转换产物） | `reader.convert_file` |
| D8 | analyze 预览口径 | 预览（sink=None）匹配成功的引用保留相对路径且不告警；预览不展开素材条目 | 预览不误导（不显示成片「未导入」）；落库差额在结果中体现 | 预览走占位 + 告警（每图一条告警，观感即「图片全丢」） | `importer.analyze_files` |
| D9 | 文档自身链接 | `href` 指向根 HTML 自身（绝对地址与 `Content-Location` 相同，或无 scheme 且文件名相同）时改为文内标题锚点：原文 id 有对应标题 → `#doc-h-<标题 slug>`（与前端 `outline.headingAnchor` 同算法）；无标题 id → 最近标题；否则保留 `#fragment` | 快照 MHTML 的目录与引注全是 `file:///...#s01`，入库后该路径必然失效；Markdown 不保留元素 id，只有映射到标题锚点预览里才真能跳转 | 只保留 `#s01`（预览无此 id，点了不动）；全部 `file:` 链接一律剥成锚点（跨文件链接会错指）；保留原绝对地址（指向不存在的本地文件） | `html._anchor_index`、`html._same_document_fragment`、`mhtml.convert_mhtml` |
| D10 | 渲染型图表 | 纯文本跳过 script / style / svg 等非正文子树；`<pre>` 去除非正文后为空则整块丢弃；图表 `<figure>` 与空 `<pre>` 各告警一次，图题保留 | CSS 不是正文，几 KB 样式灌进围栏代码块属明显失真；内联 SVG 无位图字节，当前图片通道无法落盘 | 把 SVG 内文字拼进代码块（无结构、含 CSS）；静默丢弃（用户不知图表缺失） | `html._node_text`、`html._code_block`、`html._blocks` |
| D11 | 合并单元格表格 | `rowspan` 覆盖的后续行重复该单元格文本，`colspan` 多出的列留空；非法值按 1、上限 1000 | Markdown 无合并单元格；重复类别列保证逐列语义与表头对齐 | 丢弃 rowspan（列错位，误读指标）；横向铺开隐藏列（表格宽度不可控） | `html._table_markdown` |
| D12 | 列表拼接 | 列表项片段按源码顺序直接拼接（不插空格）并折叠空白；同一列表输出为一个块 | 源码 `**格局**：` 无空格，人为插入会在中文标点前多出空格；逐行成块会让列表变松散 | 逐片段 `strip()` 后空格拼接（现状缺陷）；逐行成块（松散列表） | `html._render_list`、`html._blocks` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：网页另存（MHTML）一键进库，图片不再丢失；`_assets` 目录化管理与 Obsidian 习惯一致；零新依赖、零迁移。真实快照样例（78KB → 30KB 正文）不再输出 CSS 块，目录 / 引注变为文内锚点，合并单元格表格列对齐。
- **负向**：`html.py` 图片分派多一个分支；OFF 模式导入条目数与预览存在差额（D8）；渲染型 SVG 图表只保留图题 + 告警，图形本身不入库（D10）。
- **风险与缓解**：MHTML 变体（非标准 Content-Location）靠 basename 兜底 + 未命中告警兜住，坏例只丢单条（I2）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 通用文件导入格式与管线 | `importers/` 白名单 + 转换器 | MHTML 为可转换族第 4 种，复用管线 | ADR 0010 |
| 原件族落库 | `_assets` 图片文档 | 复用 ADR 0025 原件族路径（`content_type=image`） | ADR 0025 |
| 附件开关语义 | `import_attachments` | 开=站内附件；关=素材文档化（MHTML 专属扩展） | 本 ADR |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/importers/mhtml.py`、`src/cndb/plugins/documents/services/importers/html.py`、`src/cndb/plugins/documents/services/importers/reader.py`、`src/cndb/plugins/documents/services/importers/formats.py` | `tests/test_documents_file_import_convert.py` | `5b563bea` |
| P1 | 已落地 | `src/cndb/plugins/documents/services/importers/importer.py` | `tests/test_documents_file_import_api.py` | `4e9fed9f` |
| P2 | 已落地 | `frontend/src/api/documents.ts`、`frontend/src/pages/documents/DocumentImportModal.tsx`、`src/cndb/plugins/documents/routers/file_import.py`、`CHANGELOG.md` | `frontend/src/pages/documents/DocumentImportModal.test.tsx` | `6878197e` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地（2026-10-27）；同日按真实快照 MHTML 完成转换保真修复（D9-D12，已提交）
- 已完成：需求卡片与 ADR（用户确认全部未决问题）→ P0 解析器 + reader 分派（提交 `5b563bea`）→ P1 关态 `_assets` 展开 + 接口测试（`4e9fed9f`）→ P2 前端入口与 CHANGELOG（`6878197e`）→ 真实样例核对与 D9-D12 修复（本提交：`html.py` / `mhtml.py` / 判定层 7 例）
- 下一步：如需保留渲染型图表，先扩展图片通道接受 SVG 字节（D10 当前只告警 + 留图题）
- 已知坑：① 转换器对 QP 编码仅承诺 HTML 文本 part 保真，二进制 QP 素材不承诺字节级还原（边界 8，现实生产者对图片一律 base64）；② OFF 态 `conflict=skip` 时 MHTML 被跳过但其素材仍会落为图片文档（预扫描先于冲突判定，D4 口径，量级小可接受）；③ `docs/adr/0048` 存量 `adr-check` 报 Related 花括号路径错误，与本期无关；④ mermaid / ECharts 等内联 SVG 图表只保留图题 + 告警，图形不入库（D10）
- 最近一次全绿：2026-10-27 真实样例修复后 `make check-fast` 全绿、`make test` 5773 passed / 3 skipped
