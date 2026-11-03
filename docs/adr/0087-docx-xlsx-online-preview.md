# ADR 0087: Word（docx）/ Excel（xlsx）原件在线预览

Status: Implemented（P0-P2 全部落地，2026-11-03 需求方按 B 方案确认）
Date: 2026-11-03
Related: `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/services/importers/formats.py`、`src/cndb/plugins/documents/services/importers/reader.py`、`src/cndb/plugins/documents/services/importers/importer.py`、`src/cndb/plugins/documents/routers/file_import.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/preview/office.py`、`frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/pages/documents/DocumentImportModal.tsx`、`frontend/src/components/Document/docFormat.ts`、`frontend/src/api/documents.ts`；上游 ADR 0010 / 0025 / 0049 / 0061 / 0064
需求卡片: `docs/requirements/0087-docx-xlsx-online-preview.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。
>
> 与 ADR 0025 的关系：原件族「原样存档 + 只读阅读器 + 按格式图标」的模型不变，本 ADR 只补 `word` 一个内容类型与 Office 预览能力；与 ADR 0010 的关系：`.docx` 默认仍走「源格式 → Markdown」转换通道（I1 不变）；与 0064 的关系：预览端点沿用「后端生成自包含 HTML + 前端沙箱 iframe」的既有形态，只把可预览内容类型从 `mhtml` 扩到 `xlsx` / `word`。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C7），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「xlsx 文件在线预览」 | `GET /{wid}/documents/{doc_id}/asset/preview` 对 `content_type=xlsx`（且 MIME 非旧版 `.xls`）返回 `openpyxl` 渲染的自包含 HTML：**多工作表按标签页分页**（`radio + label` 纯 CSS 切换，一次只显示一个表；标签条横向滚动 + 顶部吸附；单表不渲染标签条），每个面板内是 `<table>`，**带 Excel 行列号**：列号 A/B/C…（表头行，`thead th` 顶部吸附）、行号取原件真实行号（首列 `th`，左侧吸附；整行为空的行跳过，因此行号可能不连续），数据单元格为 `<td>`，数值 / 日期 / 布尔转文本；预览页铺满 iframe 高度（标签条固定、面板内滚动，不再用 `70vh` 高度上限留出底部空白） |
| C2 | 「docx 文件在线预览」 | 导入新增 `docx_mode ∈ {convert, archive}`（默认 `convert`）：`archive` 时 `.docx` 走原件族落盘，`content_type=word`、`asset_mime=…wordprocessingml.document`；预览端点对 `content_type=word` 用 `python-docx` 渲染标题 / 段落 / 加粗斜体 / 列表 / 表格 / 内嵌图片（`data:` URI） |
| C3 | （安全口径） | 预览 HTML 只由后端模板拼接且所有来源文本 `html.escape`；响应带 `Content-Security-Policy: sandbox` / `X-Content-Type-Options: nosniff` / `Content-Disposition: inline`；前端 `<iframe sandbox="">`（禁脚本、禁同源、禁表单）；权限走 `visibility.get_visible_document_or_404` 与 `/asset` 同源 |
| C4 | （有界口径） | `preview/office.py` 固定上限：工作表 20 / 单表 2000 行 × 100 列 / 全局 50000 单元格 / 单元格文本 2000 字符 / 图片 200 张且合计 16MB / 输出 HTML 4MB；触顶即截断并在页面尾部提示「已截断」 |
| C5 | （兼容口径） | `convert` 默认值保持 `.docx → Markdown`；`xlsx/xls/pptx/ppt/pdf/图片` 导入行为不变；`.xls`（`application/vnd.ms-excel`）与 `.doc` 保持下载卡（后端返回 400、前端不请求预览）；无 DDL / 无备份协议变更（`content_type` 与原件字段本就随备份导出） |
| C6 | （展示口径） | `docFormat.ts` 的 `word` 映射改为原件族（`asset: true`），并把 `word` 加入 `DOC_ASSET_CONTENT_TYPES`；导入弹窗新增「Word 原样存档」开关（默认关 = 转换），切换后重新 `analyze` 以刷新 `is_asset` / `format` |
| C7 | （文档口径） | 帮助教程「文档导入」条目补 Word 原样存档与在线预览说明；CHANGELOG 增条目（本 ADR 号）；CONTEXT.md 补 `word` 原件族与 Office 预览术语 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。编号沿用卡片「现状影响面」，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `.xlsx` 属原件族但阅读器只给「不支持在线预览，请下载后查看」下载卡 | `frontend/src/pages/documents/DocumentAssetView.tsx:186-205` | 表格类文档必须下载才能看 | 确认（C1） |
| 2 | `.docx` 在 `CONVERTIBLE_SUFFIXES` 内，导入即转 Markdown，原件不落盘 | `src/cndb/plugins/documents/services/importers/formats.py:27`、`reader.py:176-188` | 无原件可供预览，排版 / 表格样式丢失 | 确认（C2） |
| 3 | `content_type` 取值只有 `markdown / folder / pdf / image / xlsx / pptx / mhtml` | `src/cndb/plugins/documents/models.py:44-52` | 无法表达「存档的 Word 原件」 | 新增（C2 / C6） |
| 4 | 预览端点硬编码 `content_type != "mhtml"` → 400 | `src/cndb/plugins/documents/routers/documents.py:782-825` | 预览能力锁死在 MHTML | 确认（C1-C3） |
| 5 | 导入端点 / 编排只有 `mhtml_mode`，无 Word 模式 | `src/cndb/plugins/documents/routers/file_import.py:66-116`、`importers/importer.py:169-200` | 无法选择原件存档 | 确认（C2） |
| 6 | 前端 `word` 映射 `asset: false`，不在 `DOC_ASSET_CONTENT_TYPES` | `frontend/src/components/Document/docFormat.ts:39-52` | 存档的 Word 会被当成可编辑 Markdown | 确认（C6） |
| 7 | 导入弹窗只有 MHTML 模式开关 | `frontend/src/pages/documents/DocumentImportModal.tsx:101-165` | 无 Word 模式入口 | 确认（C6） |
| 8 | `python-docx` / `openpyxl` 已是运行依赖（导入、导出、表格传输均使用） | `src/cndb/plugins/documents/services/importers/docx.py:15`、`src/cndb/plugins/tables/services/transfer/xlsx_rows.py:42` | 预览渲染无需新增依赖、无包体积增量 | 复用 |
| 9 | MHTML 预览已建立「后端 HTML + 沙箱 iframe」范式与响应头口径 | `routers/documents.py:791-825`、`frontend/src/pages/documents/DocumentAssetView.tsx:161-172` | Office 预览按同一范式扩展，避免重复设计 | 复用 |
| 10 | 前端已有 `PptxPreview`（纯前端渲染 PPTX）先例 | `frontend/src/pages/documents/PptxPreview.tsx` | 若 Office 也走前端库会破 `bundle-budget` 基线（SheetJS / mammoth 数百 KB） | 排除前端库路线（D2） |

**核心缺陷（需求要补的）**：原件族只有「浏览器原生渲染（PDF / 图片）」与「MHTML 转 HTML」两条预览路径，Office 文档没有可用的服务端渲染，且 Word 原件在导入阶段就被转换成 Markdown 而丢弃。

设计目标（不变量）：

- **I1 默认行为不变**：`.docx` 默认仍转 Markdown；只有显式 `docx_mode=archive` 才落原件。
- **I2 原件即事实**：`content_type=word` 与既有原件族一样只读（`ensure_text_document` 复用），不参与 Markdown 写路径。
- **I3 渲染在服务端且唯一**：Office → HTML 只在 `preview/office.py` 实现，前端只渲染 HTML，不做格式解析。
- **I4 不可信内容**：预览 HTML 视为不可信，一律沙箱渲染 + 全量转义，脚本永不执行。
- **I5 有界**：解析与输出都有硬上限，超限截断提示而非失败或 OOM。
- **I6 权限同源**：预览 / 下载 / 正文读都走同一可见性判定，不引入裸链接。

## Decision

### 1. 数据模型

无表结构变更（零迁移）。仅扩展枚举：

- 新增 `CONTENT_TYPE_WORD = "word"`，并入 `ASSET_CONTENT_TYPES`；
- `documents_document.content_type` 取值集合变为 `markdown / folder / pdf / image / xlsx / pptx / mhtml / word`；
- `asset_file_key` / `asset_mime` / `content_size` 复用，`word` 原件与既有原件族同构（备份 v13 已按 `content_type` + 原件文件通用导出，无需协议变更）。

### 2. 判定入口（唯一）

- 导入模式判定在 `importers/reader.convert_file`（唯一分派点）：`suffix ∈ DOCX_SUFFIXES` 时先校验 `docx_mode ∈ DOCX_MODES`，`archive` 走 `_convert_asset(..., CONTENT_TYPE_WORD, DOCX_ASSET_FORMAT.mime)`，`convert` 维持既有 Markdown 转换；
- 模式常量与 MIME 单一真相源：`importers/formats.DOCX_MODES` / `DOCX_MODE_DEFAULT` / `DOCX_ASSET_FORMAT`；
- 批次级校验在 `importer._validate_docx_mode`（analyze / import 共用），非法取值 400。

### 3. 预览渲染入口（唯一）

`plugins/documents/services/preview/office.py`：

```python
def build_spreadsheet_html(data: bytes) -> str: ...   # xlsx → 多工作表表格 HTML
def build_document_html(data: bytes) -> str: ...      # docx → 标题 / 段落 / 列表 / 表格 / 图片 HTML
def build_office_preview(content_type: str, mime: str, data: bytes) -> str: ...  # 分派 + 旧版格式拒绝
```

- 输入仅字节流，不触库；解析异常统一抛 `UnsupportedPreview`，由路由转 400；
- 输出为自包含 HTML（内联 CSS，图片 `data:` URI），不含任何外部资源引用；
- 上限常量集中在模块顶部（C4），截断时追加 `<p class="cn-preview-note">` 提示。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /{wid}/documents/import/files/analyze` | 新增表单字段 `docx_mode`（`convert` 默认 / `archive`），参与预览的 `is_asset` / `format` 计算 |
| `POST /{wid}/documents/import/files` | 同上，`archive` 时 `.docx` 落 `content_type=word` 原件 |
| `GET /{wid}/documents/{doc_id}/asset/preview` | 可预览类型由 `mhtml` 扩为 `mhtml / xlsx / word`；`xlsx` 但 MIME 为 `application/vnd.ms-excel`、`word` 但 MIME 为 `application/msword`（旧版二进制）→ 400；其余类型仍 400 |

### 5. 边界与例外

- 旧版二进制 `.xls` / `.doc`：不解析（`openpyxl` / `python-docx` 不支持），后端 400 + 前端保持下载卡；
- 加密 / 损坏原件：解析抛 `UnsupportedPreview` → 400，前端退化为「原件缺失或无法读取」提示（可下载）；
- 超大表格 / 长文档：按 C4 上限截断并提示，不报错；
- 空文档 / 全空工作表：渲染空态提示，不产出空表；
- 复用导入覆盖策略：`conflict=overwrite` 替换原件（既有 `replace_document_asset` 路径，`word` 与其它原件族一致）。

### 6. 前端

- **格式 / 只读标识单点**：原件族的格式与只读属性统一显示在文档页顶栏**右侧动作区**（紧邻图标按钮组之前的一枚 `{格式} · 只读` 徽标），其后紧跟信息图标按钮，点击弹出「原件信息」气泡（格式 / 大小 / MIME / 原样存档 · 只读口径）；预览区与阅读器内部不再重复任何标识；PPTX 的「放映」入口同样收进右侧动作组（窄屏也在顶栏），预览内容区只放内容本身；
- `docFormat.ts`：`word` → `{ label: 'Word', Icon: FileWordOutlined, color: '#2f54eb', asset: true }`，加入 `DOC_ASSET_CONTENT_TYPES`；
- `DocumentAssetView`：预览分支由「仅 MHTML」抽象为「MHTML / Office」——`previewQuery` 对 `mhtml`、`xlsx`（`.xlsx` 后缀）与 `word` 开启；Office 预览在 `sandbox=""` iframe 中渲染（`data-testid=doc-asset-office`），失败时为下载卡 + 提示；`assetSuffix` 补 docx / xlsx 的 MIME 映射；
- `DocumentImportModal`：新增「Word 原样存档」开关（默认关），切换后重新 `analyze`；导入请求带 `docxMode`；
- `api/documents.ts`：`DocxImportMode` 类型 + `FileImportPayload.docxMode` + 表单字段 `docx_mode`。

### 7. 测试清单

- 判定层（`tests/test_documents_asset_import.py`）：`docx_mode` 分派（convert 仍 markdown / archive 落 word）、非法模式 400、xlsx 预览 HTML（多表 / 表头 / 数值 / 日期）、docx 预览 HTML（标题 / 列表 / 表格 / 图片 `data:`）、截断标记、损坏原件报错、旧版 `.xls` 拒绝；
- 接口层：`archive` 导入后 `content_type=word` 且 `asset` 端点可下载；预览端点响应头（CSP / nosniff / inline）、非预览类型 400、权限与可见性 404、缺失原件 404；
- 前端（`DocumentAssetView.test.tsx`、`DocumentImportModal.test.tsx`、`docFormat.test.ts`）：xlsx / word 走沙箱 iframe、旧版 xls 回落下载卡、Word 开关默认关 / 切换重解析 / 导入带 `docxMode`、`word` 属原件族。

### 8. 分期

| 期 | 范围 |
|---|---|
| P0 | 模型枚举 + 导入模式（formats / reader / importer / router）+ 前端格式映射与导入开关 |
| P1 | 预览渲染（`preview/office.py`）+ 预览端点扩展 + 阅读器分派 + 用例 |
| P2 | 帮助教程 / CONTEXT / CHANGELOG / 真实 `.docx` `.xlsx` 手测 |

## 决策记录

| # | 决策 | 结论 | 被否决项 | 代码落点 |
|---|---|---|---|---|
| D1 | docx 原件取得方式 | 导入模式 `docx_mode`，默认 `convert`（兼容），`archive` 落 `word` 原件 | 默认改 archive（破坏既有 Markdown 编辑链路）；每次预览临时转换（不保留原件、无法下载） | `importers/formats.py`、`reader.py`、`routers/file_import.py` |
| D2 | 渲染位置 | 后端生成自包含 HTML（`openpyxl` / `python-docx`），前端沙箱 iframe | 前端 SheetJS / mammoth（破 bundle 预算、体积与安全面更大）；服务端装 LibreOffice（部署镜像重、转换慢） | `services/preview/office.py`、`DocumentAssetView.tsx` |
| D3 | 内容类型表达 | 新增 `content_type=word` 进原件族集合 | 复用 `docx` 作为 content_type（与既有「渲染族非扩展名」口径不一致） | `models.py` |
| D4 | 旧版 `.xls` / `.doc` | 不预览、保持下载卡（后端 400） | 引入第三方解析库（依赖与体积成本高于收益） | `preview/office.py`、`DocumentAssetView.tsx` |
| D5 | 预览端点 | 扩展现有 `asset/preview`（同一路径、同一权限），按 `content_type` 分派 | 新增 `/asset/html-preview` 等并行端点（权限与安全头要复制一份） | `routers/documents.py` |
| D6 | 有界策略 | 硬上限 + 截断提示（C4 常量集中） | 全量渲染（大表 OOM / 响应过大） | `preview/office.py` |
| D7 | 附件字段范围 | 本期只做文档模块 | 同步做表格附件预览（改动面翻倍，需求未要求） | 需求卡片未决问题③ |

## Consequences

- 收益：Office 一类原件在阅读器内可读，下载不再是用表格 / 文档的唯一路径；`word` 与既有原件族同构，备份 / 权限 / 只读守卫零新增分支；渲染全在服务端，前端无新增依赖与包体积。
- 代价 / 风险：`archive` 模式的 Word 文档失去 Markdown 编辑能力（用户显式选择，默认不变）；预览为「保真但非像素级」渲染（复杂版式、批注、公式、图表不还原）；解析在上传后首次预览时进行（有上限，未做缓存）。

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/services/importers/formats.py`、`src/cndb/plugins/documents/services/importers/reader.py`、`src/cndb/plugins/documents/services/importers/importer.py`、`src/cndb/plugins/documents/routers/file_import.py`、`frontend/src/components/Document/docFormat.ts`、`frontend/src/pages/documents/DocumentImportModal.tsx`、`frontend/src/api/documents.ts` | `tests/test_documents_asset_import.py`、`frontend/src/pages/documents/DocumentImportModal.test.tsx`、`frontend/src/components/Document/docFormat.test.ts` | `c92cb4f2` |
| P1 | 已落地 | `src/cndb/plugins/documents/services/preview/office.py`、`src/cndb/plugins/documents/routers/documents.py`、`frontend/src/pages/documents/DocumentAssetView.tsx` | `tests/test_documents_asset_import.py`、`frontend/src/pages/documents/DocumentAssetView.test.tsx` | `c92cb4f2` |
| P2 | 已落地 | `frontend/src/pages/help/content/tutorials.tsx`、`CONTEXT.md`、`CHANGELOG.md` | `CONTEXT.md`、`CHANGELOG.md` | `c92cb4f2` |

## 交接

- 当前阶段：P0-P2 全期落地（2026-11-03），Word archive 模式与 Excel / Word 在线预览可用。
- 下一步：如需表格附件字段（`file` 字段）的 docx / xlsx 预览，按同一 `preview/office.py` 入口接入新的只读端点与前端弹窗（本期按需求范围未做）。
- 已知坑：`.xls` / `.doc` 旧版二进制不支持预览（后端 400、前端下载卡）；预览不还原批注 / 修订 / 公式 / 图表；解析按上限截断，超大文件只显示前若干行列；`docx_mode` 只在导入端点生效，已导入为 Markdown 的 Word 文档需重新导入才能得到原件。
