# ADR 0025: 文档多格式上传（PDF / Office / 图片原样存档）与按格式区分图标

Status: Accepted
Date: 2026-10-24
Related: `plugins/documents/models.py`、`plugins/documents/services/importers/`、`plugins/documents/services/content.py`、`plugins/documents/routers/file_import.py`、`plugins/documents/routers/documents.py`、`plugins/files/services.py`、`frontend/src/pages/documents/`、`docs/adr/0010-document-file-import.md`
需求卡片: `docs/requirements/0025-document-asset-formats.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 需支持 PDF 等格式文件上传 | 导入白名单新增 `.pdf`、`.xlsx/.xls`、`.pptx/.ppt`、`.png/.jpg/.jpeg/.gif/.webp/.svg/.bmp`（用户确认的格式范围）；md / docx / html 沿用 ADR 0010 的转换通道。 |
| C2 | …上传 | 新格式**原样存档**：原件写入工作区上传目录，`Document` 记录 `asset_file_key` / `asset_mime` / `content_type`；正文区以阅读器呈现（PDF 浏览器原生渲染、图片直出、Office 给下载卡），不进入 Markdown 编辑器。 |
| C3 | 在文档树等地方 | 新增 `frontend/src/pages/documents/docFormat.ts` 作为唯一映射；文档树、文档列表、回收站、工作区搜索统一取用。 |
| C4 | 为不同格式配置不同的图标 | 映射同时给「图标形状 + 配色」（PDF 红 / Word 蓝 / Excel 绿 / PPT 橙 / 图片紫 / Markdown 蓝灰 / 未知灰），不只靠颜色区分。 |
| C5 | 功能增强…（健壮性） | 沿用 ADR 0010 的批次上限、逐条隔离、冲突三策略、`require_editor`；新增原件读取端点走文档可见性校验（不做「持 key 即可读」的裸链接）；原件文档禁写正文。 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状核对（以代码为准，标注 `文件:行号`）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 导入白名单仅 `.md/.markdown/.docx/.html/.htm`，其余扩展名进 `skipped` | `importers/reader.py:26-30`、`:90-98` | PDF / 图片 / Office 一律被拒 | 确认（C1 主缺口） |
| 2 | `content_type` 取值只有 `markdown` / `folder`，创建时硬编码 | `models.py:43-44`、`services/content.py:254` | 无法表达「节点是一份 PDF」 | 确认（C2/C4 依据） |
| 3 | 正文一律存 `DocumentVersion.content`（文本），>2MB 走 gzip 外存 | `services/content.py:211-240` | 二进制不能进版本正文（gzip 文本通道） | 确认（需独立原件存储） |
| 4 | 附件落盘与归属校验已具备（`file_key` → 表/行/文档） | `plugins/files/services.py:40-124`、`plugins/tables/routers/files.py:216-300` | 原件可复用同一目录与权限模型 | 复用 |
| 5 | 树 / 列表文档图标恒为 `FileTextOutlined` | `DocumentTree.tsx:376`、`DocumentsPage.tsx:729` | 所有格式看起来一样 | 确认（C3/C4 落点） |
| 6 | 编辑器页任何非文件夹文档都走 Markdown 编辑 / 预览 | `DocumentEditorPage.tsx:1106-1174` | 原件文档没有可用的阅读形态 | 确认（需阅读器分支） |
| 7 | 文档可见性校验已有（未发布 → 仅创建者/所有者） | `services/visibility.py`、`plugins/files/services.py:88-108` | 原件读取可直接挂上同一口径 | 复用 |
| 8 | 彻底删除已清理版本 / 标签 / 分享 / FTS / 外存目录 | `services/content.py:610-658` | 原件文件需要一并清理，否则残留占配额 | 新增（补清理） |

**核心缺陷**：文档模块只能承载「Markdown 正文」，非文本格式既进不来（白名单）也存不下（正文是文本版本），因此现象上「所有文档一个图标」。

设计不变量：

- **I1 正文格式单一不变**：可转换格式（md / docx / html）仍统一转 Markdown，`content_type=markdown`；新增格式**不改动** Markdown 通道。
- **I2 原件只读**：`content_type` 属原件族（pdf / image / xlsx / pptx）的文档不参与 Markdown 写路径（保存草稿 / 提交 / 回滚一律 409），保证「原件即事实」。
- **I3 权限同源**：原件读走文档可见性（未发布草稿对非创建者 404），与正文同口径。
- **I4 逐条隔离**：沿用 ADR 0010，单个文件超限 / 损坏只跳过该条，整批继续。
- **I5 图标单一映射**：前端只有一处格式 → (图标, 颜色, 标签) 表，各处调用，禁止就地写死。

## Decision

### 1. 数据模型（扩展列，无新表）

`documents_document` 新增两列：

| 列 | 类型 | 语义 |
|---|---|---|
| `asset_file_key` | `String(255) NULL` | 原件在工作区上传目录中的文件名（`uuid + 原扩展名`）；NULL = 普通 Markdown 文档 |
| `asset_mime` | `String(128) NOT NULL DEFAULT ''` | 原件 MIME（`application/pdf` / `image/png` / …），预览与下载的 `Content-Type` |

`content_type` 扩展取值（渲染族，不是扩展名全集）：

| 取值 | 含义 | 图标 |
|---|---|---|
| `markdown` | 原生 Markdown，或 docx / html 转换而来 | Markdown 蓝灰 |
| `folder` | 文件夹 | 文件夹（沿用） |
| `pdf` | PDF 原件 | PDF 红 |
| `image` | 图片原件（png/jpg/gif/webp/svg/bmp 同族） | 图片紫 |
| `xlsx` | Excel 原件（xlsx/xls） | Excel 绿 |
| `pptx` | PPT 原件（pptx/ppt） | PPT 橙 |

具体扩展名不落库（`asset_mime` 已能区分 `image/png` 与 `image/jpeg`），避免为展示引入枚举膨胀。

迁移：`add_document_asset_columns`，仅两列，无索引、无数据回填（历史文档 `asset_file_key=NULL` 即 Markdown）。

### 2. 格式注册表（唯一分派点）

新增 `plugins/documents/services/importers/formats.py`：

```python
@dataclass(frozen=True)
class AssetFormat:
    content_type: str   # pdf / image / xlsx / pptx
    mime: str           # application/pdf、image/png、…
    label: str          # 预览文案用（PDF / 图片 / Excel / PowerPoint）


CONVERTIBLE_SUFFIXES = (".md", ".markdown", ".docx", ".html", ".htm")   # ADR 0010 通道
ASSET_FORMATS: dict[str, AssetFormat] = {".pdf": …, ".png": …, ".xlsx": …, ".pptx": …}
SUPPORTED_SUFFIXES = CONVERTIBLE_SUFFIXES + tuple(ASSET_FORMATS)
```

`reader.convert_file` 按注册表分派：可转换 → 原有转换器；原件族 → 返回 `ImportedDoc(asset=True, content_type=…, mime=…)`（正文为空、标题取文件名）；都不命中 → `UnsupportedImport`（进 `skipped`）。

原件体积上限单列 `MAX_ASSET_BYTES = 32MB`（图片 / PDF 通常大于 8MB 文本上限），批次总量仍守 128MB。

### 3. 落盘与写入

- 原件写 `settings.UPLOAD_DIR/{workspace_id}/{uuid4}{ext}`，与编辑器插图同目录同命名规则；登记 `FileOwner(document_id=…)`，使下载 / 删除跟随文档权限。
- `content.create_document` 增加可选入参 `content_type` / `asset_file_key` / `asset_mime`：原件族跳过 Markdown 元数据解析（摘要 / TOC）与正文规整，仍创建 1 个空版本（版本号连续性与回滚口径不破），`content_size` = 原件字节数，FTS 只索引标题。
- 冲突 `overwrite`：原件族替换原件（删旧文件 + 旧 `FileOwner`，写新 key），不产生新版本；`skip` / `rename` 语义与文本一致。
- 彻底删除（purge）：原件文件与 `FileOwner` 一并清理（I2 / 现状 #8）。

### 4. 只读守卫与 API

| 端点 | 变更 |
|---|---|
| `POST /{wid}/documents/import/files/analyze` | 预览项新增 `format` / `is_asset`，`skipped` 口径不变 |
| `POST /{wid}/documents/import/files` | 接受新增扩展名；统计新增 `assets`（原样存档数） |
| `GET /{wid}/documents/{doc_id}/asset` | **新增**：流式返回原件，`?download=true` 走 attachment；权限 = 工作区成员 + 文档可见性（I3）；`content_type` 非原件族 → 404 |
| `PUT /{wid}/documents/{id}/content`、`/draft`、`/submit`、`/rollback` | 原件族 → 409 `doc_read_only`（I2） |

响应体新增 `asset_mime`（`DocumentOut` / `_serialize_document`），前端据此选阅读器形态；`asset_file_key` **不外露**（避免绕过端点直取文件）。

### 5. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 格式映射 | `components/Document/docFormat.ts`（新增，跨页共享：树 / 列表 / 回收站 / 搜索都取自这里） | `DOC_FORMAT_META`：`content_type → {label, Icon, color}`；`isAssetDoc()`、`formatMeta()`；图标用 antd `FilePdfOutlined` / `FileWordOutlined` / `FileExcelOutlined` / `FilePptOutlined` / `FileImageOutlined` / `FileMarkdownOutlined` / `FileTextOutlined` |
| 文档树 | `DocumentTree.tsx` | 文档节点图标改由 `formatMeta()` 提供（文件夹逻辑不变） |
| 列表 / 回收站 / 搜索 | `DocumentsPage.tsx`、`TrashDrawer.tsx`、`GlobalSearch.tsx` | 同上，统一取映射（搜索结果由后端补 `content_type`） |
| 原件阅读器 | `pages/documents/DocumentAssetView.tsx`（新增） | 拉取 blob → PDF `<iframe>`（objectURL）/ 图片 `<img>` / 其它下载卡；顶部格式标签、大小、下载按钮；失败态「原件缺失，请重新上传」 |
| 编辑器页 | `DocumentEditorPage.tsx` | `isAssetDoc(doc.content_type)` 时：隐藏查看/编辑切换、保存/提交、图片/插入表格/AI 等编辑入口，正文区替换为阅读器；保留标签、分享、删除 |
| 导入弹窗 | `DocumentImportModal.tsx` | `accept` 扩展；预览表增「格式」列并标注「原样存档」；文案说明新的可导入范围 |
| API | `api/documents.ts` | `FILE_IMPORT_ACCEPT` 扩展；新增 `assetBlob()`（`responseType: 'blob'`） |

### 6. 边界与例外

1. **原件缺失**：`asset_file_key` 指向的文件被外部清理 → 端点 404，前端阅读器显示「原件缺失」而非空白。
2. **SVG 安全**：SVG 以 `image/svg+xml` 直接内联渲染存在脚本执行面，前端用 `<img>`（不执行脚本）而非 `<object>`；`Content-Disposition: inline` 时补 `Content-Security-Policy: sandbox` 头。
3. **超限**：原件 >32MB 只跳过该条（I4）；批次总量超限仍 400。
4. **格式猜错**：`asset_mime` 由扩展名推定（`mimetypes`），不读文件头；猜不到时退回 `application/octet-stream`（下载而非内联）。
5. **搜索**：原件族只按标题命中（正文为空），不引入 OCR / 文本抽取（本 ADR 范围外）。
6. **旧数据**：`asset_file_key=NULL` 的文档全部按 Markdown 处理，无兼容分支。
7. **同名 Markdown 文档不被原件覆盖**：`overwrite` 策略下若同名节点不是原件族，按改名处理（保留两份）——避免把可编辑正文替换成只读原件、丢失历史正文。
8. **工作区备份**：备份导出只含文档树与 Markdown 正文，不含原件字节（与既有附件同现状）；恢复后原件族节点会显示「原件缺失」，需重新导入原件。

### 7. 测试清单

**判定层**

- 格式注册表：扩展名 → (content_type, mime) 全量覆盖；未知扩展名仍 `UnsupportedImport`；
- `convert_file`：原件族返回 `asset=True`、正文空、标题取文件名；md/docx/html 行为不变（回归既有用例）。

**接口层**（`tests/test_documents_asset_import.py`）

- 导入 pdf / png / xlsx：`content_type`、`asset_mime`、`content_size` 正确，`GET /asset` 字节与原件一致；
- `analyze` 预览：原件项 `is_asset=true`、`format` 正确，且不落库；
- 冲突：`overwrite` 替换原件且旧文件被删；`skip` 不写新文件；
- 权限：viewer 导入 403；非成员 403；未发布草稿的原件对非创建者 404；
- 只读：`PUT content` / `PUT draft` / `POST submit` 对原件族 409；
- 越界：`GET /asset` 对 Markdown 文档 404；`?download=true` 带 attachment；
- purge：彻底删除后原件文件消失、`FileOwner` 清除。

**前端**

- `docFormat.test.ts`：每个 `content_type` 有唯一 (图标, 颜色, 标签)；未知类型回退灰色文件图标；
- `DocumentTree.test.tsx`：PDF / 图片节点渲染对应图标（形状 + 颜色断言）；
- `DocumentAssetView.test.tsx`：PDF 走 iframe、图片走 img、其它走下载卡；加载失败显示「原件缺失」；
- `DocumentImportModal.test.tsx`：`accept` 含新扩展名；预览表标注「原样存档」。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 模型 + 格式注册表 + 导入落库** | 两列迁移、`formats.py`、reader/importer 分派、create_document 入参、只读守卫 | 低 |
| **P1 原件端点 + 清理** | `GET /asset`（inline / attachment）、purge 清理原件、权限用例 | 中（SVG/MIME 安全） |
| **P2 前端图标 + 阅读器** | `docFormat.ts` 接入四处 + `DocumentAssetView` + 编辑器页分支 + 导入弹窗 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 非文本格式的处理方式 | **原样存档 + 内置预览**，不抽文本转 Markdown | 用户 2026-10-24 确认；PDF / Office 抽取必失真（版式、图表），且「按格式区分图标」以格式为节点属性更自然 | ① 全部抽文本转 md（丢版式、图标回到单一）；② 原件 + 摘要双存（存储与实现翻倍，收益低） | `importers/formats.py`、`Document.asset_file_key` |
| D2 | 格式范围 | **PDF + Office（xlsx/xls/pptx/ppt）+ 图片（png/jpg/jpeg/gif/webp/svg/bmp）**；txt / csv 不纳入 | 用户 2026-10-24 选择；文本类需求不明确，且已有 md 通道可覆盖纯文本场景 | 仅 PDF（覆盖不足）/ 再加 txt、csv（语义与 md 通道重叠，先不做） | `ASSET_FORMATS` |
| D3 | `content_type` 粒度 | **按渲染族存**（pdf / image / xlsx / pptx），具体扩展名放 `asset_mime` | 图标与阅读器形态只依赖渲染族；避免枚举随扩展名膨胀 | 每个扩展名一个 content_type（前端映射表爆炸） | `models.py`、`docFormat.ts` |
| D4 | 原件存储位置 | **复用工作区上传目录 + `FileOwner` 归属** | 已有落盘与权限校验（现状 #4），无需新存储层 | 存进版本正文（文本通道，不可行）/ 新建对象存储表（过度设计） | `importer._UploadStore` |
| D5 | 原件可编辑性 | **只读**：写正文 / 草稿 / 提交 / 回滚一律 409 | 原件是事实来源，Markdown 编辑无对应语义（I2） | 允许编辑「同名 Markdown 覆盖」（语义混乱，破坏原件） | `content.py` 守卫 |
| D6 | 原件鉴权 | **端点 + 文档可见性**，不外露 `asset_file_key` | 与正文同口径（I3）；裸链接等于绕过草稿可见性 | 直接返回静态文件路径（capability URL 泄漏） | `routers/documents.py` |
| D7 | 图标配色 | **格式专属色 + 不同形状** | 用户 2026-10-24 确认；形状差异保证色弱可辨 | 统一品牌色（辨识度低） | `docFormat.ts` |
| D8 | PDF 预览形态 | **浏览器原生 iframe（objectURL）**，不引入 pdf.js | 零依赖、体积小；需求是「能看」而非「批注」 | 引入 pdf.js（+300KB 且需 worker 配置） | `DocumentAssetView.tsx` |

门禁：本表无「待定」，D1/D2/D7 已于 2026-10-24 由需求方拍板，`Status` 置 `Accepted`。

## Consequences

- **正向**：文档模块从「只会 Markdown」扩展到「多格式文件柜」，PDF / Office / 图片可直接进树、按格式辨识、原样取回；原件复用既有落盘与权限，未引入新存储层；图标映射单点维护，后续加格式只改一个表。
- **负向**：
  1. 原件族文档不可编辑、不可全文检索正文（只有标题可搜），需在 UI 明示「仅预览 / 可下载」。
  2. 原件占工作区存储配额，32MB 上限与配额校验叠加时用户可能同时撞两个限额，报错文案需可区分。
  3. SVG 内联渲染有脚本执行面，用 `<img>` + CSP sandbox 兜底，但仍需安全用例守住。
- **风险与缓解**：MIME 猜错 → 猜不到退回 `application/octet-stream` 走下载；原件丢失 → 端点 404 + 阅读器显式失败态，不静默空白。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 模型 + 格式注册表 + 导入落库 | 已落地 | `src/cndb/plugins/documents/services/importers/formats.py`、`src/cndb/plugins/documents/services/importers/reader.py`、`src/cndb/plugins/documents/services/importers/importer.py`、`src/cndb/plugins/documents/models.py`、`src/cndb/alembic/versions/d0c1b2a3f4e5_add_document_asset_columns.py` | `tests/test_documents_asset_import.py` | 2a8ff3fd |
| P1 原件端点 + 清理 | 已落地 | `src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/files/services.py` | `tests/test_documents_asset_import.py` | 2a8ff3fd |
| P2 前端图标 + 阅读器 | 已落地 | `frontend/src/components/Document/docFormat.ts`、`frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/DocumentImportModal.tsx` | `frontend/src/components/Document/docFormat.test.ts`、`frontend/src/pages/documents/DocumentAssetView.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 2a8ff3fd |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 均已落地并提交（`2a8ff3fd`），功能完结
- 已完成：格式注册表（PDF / Office / 图片）与原件落盘、两列迁移、原件端点（inline / attachment、SVG sandbox）、只读守卫（正文 / 草稿 / 提交 / 回滚 409）、purge 清理原件；前端格式映射（树 / 列表 / 回收站 / 搜索）+ 阅读器（PDF iframe / 图片 img / Office 下载卡）+ 编辑器页只读分支 + 导入弹窗扩展
- 测试：后端 `tests/test_documents_asset_import.py` 28 例（注册表 / 分派 / 预览 / 导入 / 冲突 / 权限 / 下载 / 只读 / 清理）；前端 4 个文件（格式映射 / 阅读器 / 树图标 / 编辑器只读分支）与导入弹窗回归
- 已知坑：`importers` 包名不能用 `import`（Python 保留字）；原件端点用 `FileResponse` 流式返回（不整块读入内存）；迁移链挂在 `c9f1a2b3d4e5`（工作区存储快照）之后，同步提交时不要漏
- 下一步：无（功能已完结）
