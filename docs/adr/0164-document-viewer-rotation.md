# ADR 0164: 文档阅读器旋转 / 水平镜像（自动判定 + 手动纠偏）

Status: Implemented（2026-11-26 评审通过，P0-P2 已落地）
Date: 2026-11-26
Related: `frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/api/documents.ts`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/preview/`、ADR 0025（原件族阅读器）、ADR 0129（PPTX 衍生 PDF）
需求卡片: `docs/requirements/0164-document-viewer-rotation.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 只对 PDF 与图片 | `DocumentAssetView` 仅当 `content_type ∈ {pdf, image}` 时渲染方向控件条；其它分支（office / mhtml / pptx 客户端预览 / 下载卡）不渲染 |
| C2 | 右侧并列的手动按钮 | 阅读区右上角浮层 `AssetRotationControls`：`[自动旋转] | [旋转 90°] [水平镜像]` 三个按钮同一行；有 tooltip / aria-label / `data-testid` |
| C3 | 自动旋转默认开启、判定后默认应用 | 纯函数 `detectAutoOrientation()` 决策；默认 `autoEnabled=true`，高置信度才把判定结果作为基线 |
| C4 | 可叠加、可回环、关闭回原始 | 状态 `{rotate: 0/90/180/270, flip: boolean}`；旋转按 90° 取模累加；关自动旋转把状态重置为 `{0,false}` |
| C5 | 不改原件、原生阅读器 | PDF 走新增 `GET …/asset/rotated` 返回派生副本（pypdf 处理，原件字节不动）；iframe 仍是浏览器原生 PDF 阅读器 |
| C6 | 权限 / 只读 / 下载不回归 | 新端点复用 `_require_member` + `get_visible_document_or_404`；图片只做 CSS 变换，下载仍取原件 |
| C7 | 切文档重置 / Chrome 81 / 不加重首屏 | `useEffect` 按 `workspaceId+doc.id` 重置方向；变换用 CSS `rotate` / `scaleX` 与 `<img>` → 无新前端依赖；pypdf 装在后端 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | PDF 用 `<iframe src=objectURL>`，图片用 `<img>`，均无方向控制 | `frontend/src/pages/documents/DocumentAssetView.tsx:204-229` | 横置扫描件无法在应用内摆正 | 确认（C1/C2 主缺口） |
| 2 | 原件只读、下载走 `/asset`，权限 = 成员 + 可见性 | `src/cndb/plugins/documents/routers/documents.py:847-884` | 派生副本必须复用同一权限与「不外露 `asset_file_key`」口径 | 确认（C6） |
| 3 | 后端无 PDF 解析依赖（只有 reportlab 生成 PDF） | `pyproject.toml:40` | 服务端旋转 / 镜像需新增纯 Python 的 pypdf | 新增（C5） |
| 4 | 浏览器已自动应用图片 EXIF 方向与 PDF 页面 `/Rotate` | 浏览器默认行为 | 若再叠加一次 EXIF / `/Rotate` 会「转两次」 | 确认（C3 需显式关闭原生方向，见 D4） |
| 5 | 文档页为 flex 列 + `padding: 12px 24px`，阅读器占满剩余区 | `DocumentAssetView.tsx:321-326` | 控件条用绝对定位浮在阅读区右上角，不挤压阅读器尺寸 | 确认（C2） |

**核心缺陷**：阅读器只负责「把字节显示出来」，没有任何方向语义，也没有判定方向的入口。

设计不变量：

- **I1 原件不可变**：旋转 / 镜像只产生派生副本，`/asset` 返回的原件字节与文件永不改写。
- **I2 单一方向来源**：图片显式关闭浏览器原生 EXIF 自动方向（`image-orientation: none`），PDF 派生副本会把页面既有 `/Rotate` 烘焙进内容后再应用用户旋转 / 镜像；同一页只被「应用一次」方向。
- **I3 判定宁缺毋滥**：只有高置信度（明确元数据，或强长宽比信号）才自动旋转；否则保持原始方向，交给手动按钮。

## Decision

### 1. 数据模型

无新表、无新列、无迁移。方向状态只存在于前端内存（切文档重置），不落库、不进版本。

### 2. 判定算法（唯一入口：前端纯函数）

新增 `frontend/src/pages/documents/assetOrientation.ts`：

```ts
export interface Orientation { rotate: 0 | 90 | 180 | 270; flip: boolean }
export interface AutoOrientationResult { orientation: Orientation; confident: boolean; reason: string }

detectAutoOrientation(input: {
  kind: 'image' | 'pdf'
  exifOrientation: number | null       // 图片：EXIF Orientation 1..8
  pageAspects: Array<{ rotate: number; width: number; height: number }> | null  // PDF：页面 /Rotate + MediaBox
  viewport: { width: number; height: number }
}): AutoOrientationResult
```

判定顺序（高 → 低）：

1. **图片 EXIF（高置信度）**：Orientation 2/4/5/7 同时给出 `flip=true`，1..8 映射为标准 `(rotate, flip)`。
2. **PDF 声明的页面方向**：所有页 `/Rotate` 一致且非 0 → 浏览器已按该方向显示，结果取 `{0,false}`（标记「已按页面方向标记显示」）。
3. **长宽比兜底（高置信度才自动）**：仅当页面 / 图片是横置（`w/h ∈ [1.15, 1.5]`，覆盖 A4 横置 1.414 与 4:3 照片 1.333，排除 16:9 演示页 1.78 与方图）**且**阅读区是竖置时，自动顺时针 90°。其余情况 `confident=false`，不自动旋转。
4. 无依据 → `{0,false}`，不自动旋转。

辅助函数（同样纯逻辑、单测覆盖）：`rotateBy(current, 90)`（取模回环）、`toggleFlip(state)`、`sameOrientation(a, b)`。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/documents/{doc_id}/asset/orientation` | **新增**。仅 `content_type=pdf`；pypdf 读取每页 `/Rotate` 与 MediaBox，返回 `{pages: [{rotate,width,height}], uniform_rotate, uniform_aspect, page_count}`；非 PDF → 404，原件缺失 → 404；权限同 `/asset`。 |
| `GET /{wid}/documents/{doc_id}/asset/rotated?rotate=0\|90\|180\|270&flip=false\|true` | **新增**。仅 `content_type=pdf`；返回 `application/pdf` 派生副本（inline，`nosniff`）；参数越界 → 422；非 PDF → 404；原件缺失 → 404；解析失败 → 422 `pdf_unreadable`。`rotate=0&flip=false` 也允许（返回等价副本，前端正常情况下不会请求）。 |

派生副本实现（新模块 `services/preview/pdf_rotation.py`）：

1. `PdfReader` → `PdfWriter`，逐页处理；
2. `page.transfer_rotation_to_content()` 先把页面既有 `/Rotate` 烘焙进内容流（I2）；
3. `page.rotate(rotate)` 再 `transfer_rotation_to_content()` 应用用户旋转；
4. `flip=true` 时用 `Transformation().scale(-1, 1)` + 平移页宽的变换矩阵镜像内容；
5. 结果写 `BytesIO` 返回；输入 / 输出体积沿用原件 32MB 上限口径，超过即 422。

进程内 LRU 缓存：键 `(doc.id, asset_file_key, rotate, flip)`，总字节上限 64MB；`asset_file_key` 变化（覆盖上传）天然换键，无需失效逻辑。

### 4. 边界与例外

1. **加密 / 损坏 PDF**：pypdf 抛错 → 422 `pdf_unreadable`，前端提示「该 PDF 无法旋转」并恢复上一次可用方向，不吞成空白。
2. **混合页面方向**：`uniform_rotate=false` 且 `uniform_aspect='mixed'` → 不做自动旋转，只保留手动。
3. **超大页数**：不做硬性页数上限（原件已限 32MB）；旋转请求超时由前端 `AbortSignal` 中止并提示。
4. **图片 EXIF 解析失败**：视为无元数据，走长宽比兜底。
5. **SVG 图片**：无 EXIF，按长宽比兜底；镜像 / 旋转用 CSS，不影响下载。
6. **PPTX 衍生 PDF**：按 PDF 分支处理（同为 iframe），不做单独实现。
7. **并发切换**：旋转请求带 `AbortSignal`，切文档 / 连续点击只保留最后一次；旧副本 objectURL 及时 `revokeObjectURL`。
8. **只读口径**：方向状态不持久化，刷新 / 重开回到自动判定结果。

### 5. 迁移

无（无数据模型变更）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 判定纯函数 | `frontend/src/pages/documents/assetOrientation.ts`（新增） | EXIF 解析（JPEG APP1）、`(rotate, flip)` 映射、长宽比兜底、累积辅助函数 |
| 控件条 | `frontend/src/pages/documents/AssetRotationControls.tsx`（新增） | 自动旋转开关 + 旋转 90° + 水平镜像；右侧浮层；`data-testid` / tooltip |
| 阅读器 | `frontend/src/pages/documents/DocumentAssetView.tsx` | PDF / 图片分支包一层相对容器 + 控件条；PDF 拉 orientation，方向非默认时请求派生副本并替换 iframe `src`；图片 `<img style={{ transform, imageOrientation: 'none' }}>` 并按旋转后的包围盒计算尺寸 |
| API | `frontend/src/api/documents.ts` | 新增 `assetOrientation()`、`assetRotated()`（blob，带 `signal`） |
| 样式 | `frontend/src/index.css` | `cn-asset-rotate-bar` 浮层（token 取色 / 间距，满足 H24/H25/H29） |

图片尺寸处理：用 `ResizeObserver` 量阅读区，按「旋转后包围盒 + contain」计算 `<img>` 的 `width/height`，避免 90°/270° 时被裁切或溢出；`transform-origin: center`。

### 7. 测试清单

**判定层（单测）**：`assetOrientation.test.ts` —— EXIF 1..8 映射（含镜像值 2/4/5/7）；无 EXIF 的横置图 + 竖置阅读区 → 自动 90°；方图 / 16:9 / 竖置图不自动；PDF `/Rotate` 非 0 → 基线 0 且 confident；PDF 横置 1.414 + 竖阅读区 → 90°；混合方向不自动；旋转 4 次回环；flip 开关往返。

**接口层**（`tests/test_document_asset_rotation.py`）：rotate 90/180/270 后派生页 MediaBox / 内容坐标正确（用 reportlab 生成带文字的样本 PDF 断言）；flip 后内容 x 坐标镜像；`asset/orientation` 返回页面信息；非 PDF 404；参数越界 422；损坏 PDF 422；缺原件 404；非成员 403、未发布草稿对非创建者 404；缓存命中（同参数第二次不重新解析，可用 monkeypatch 计数）；原件字节前后一致（I1）。

**前端组件 / 页面**：`DocumentAssetView.test.tsx` —— PDF / 图片出现控件条且其它格式不出现；点击旋转触发 `assetRotated` 且 iframe `src` 更新；自动旋转默认开启并显示正确方向；关闭自动旋转回到原始；切换文档重置；图片 `transform` 断言；旋转失败提示与回退。

**e2e**：不做新增（该交互依赖原生 PDF 插件，浏览器内断言不稳定），由单测 + 组件测试覆盖。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 后端派生副本** | pypdf 依赖、`pdf_rotation.py`、`/asset/orientation` 与 `/asset/rotated`、权限与异常、接口测试 | 中（第三方 PDF 解析健壮性、镜像矩阵正确性） |
| **P1 前端判定 + 控件** | `assetOrientation.ts`、`AssetRotationControls`、图片变换与尺寸、单测 | 低 |
| **P2 PDF 接入 + 回退** | 方向状态、派生副本请求 / 缓存、加载态、失败回退、文档切换重置、组件测试 | 中（请求时序与 objectURL 生命周期） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 覆盖范围 | **PDF + 图片** | 2026-11-26 用户确认；扫描件与照片共用一套交互 | 仅 PDF（图片扫描件同样横置，覆盖不足） | `DocumentAssetView.tsx` |
| D2 | 「反转」语义 | **水平镜像翻转** | 2026-11-26 用户确认 | 逆时针 90° / 180° / 垂直镜像 | `assetOrientation.ts`、`pdf_rotation.py` |
| D3 | PDF 旋转实现 | **后端 pypdf 生成派生副本** | 2026-11-26 用户确认；保留浏览器原生阅读器（文字选择 / 搜索 / Chrome 81 兼容） | 前端 pdf.js（自建工具栏、+300KB、旧内核风险）；CSS 旋转 iframe（阅读器工具栏与滚动条一起转） | `pdf_rotation.py`、`routers/documents.py` |
| D4 | 自动方向判定 | **元数据优先 + 长宽比兜底，仅高置信度自动** | 2026-11-26 用户确认；不做 OCR，避免误判 | 仅元数据（无元数据的横置扫描件永远不自动）；按阅读区强制旋转（会把正常版式转歪） | `assetOrientation.ts` |
| D5 | 图片原生 EXIF 方向 | **显式 `image-orientation: none`，由本功能单点应用** | 浏览器默认会自动应用 EXIF，不关闭会「转两次」（I2） | 依赖浏览器默认方向（不同内核行为不一致，且无法与手动叠加） | `DocumentAssetView.tsx`、`index.css` |
| D6 | 旋转状态是否持久化 | **不持久化，切文档重置** | 需求未提出；原件只读、方向属临时查看偏好 | 写 localStorage（多份文档互相污染、与「不改原件」口径混淆） | `DocumentAssetView.tsx` |
| D7 | 派生存量缓存 | **进程内 LRU（64MB，键含文件 key 与角度）** | 反复调整方向时避免重复解析大 PDF；键含文件 key 天然失效 | 磁盘缓存（清理 / 并发写复杂度）；不缓存（每次 32MB 重新解析） | `pdf_rotation.py` |
| D8 | 自动旋转开关的默认值 | **默认开启** | 2026-11-26 用户原句「需要旋转的判断正确的方向后默认自动旋转」 | 默认关闭（与需求相悖） | `DocumentAssetView.tsx` |

门禁：本表无「待定」，四项选型已由需求方于 2026-11-26 拍板，评审通过后 `Status` 置 `Accepted`。

## Consequences

- **正向**：PDF / 图片阅读补齐方向控制；判定与手动纠偏闭环，横置扫描件可自助摆正；原件与权限口径完全不变；派生副本缓存后重复调整成本低。
- **负向**：
  1. 新增后端依赖 pypdf（纯 Python，体积与安全面小但需锁版本与安全清单）；
  2. PDF 旋转每次方向变化有一次服务端往返，超大 PDF 首次旋转有可感知延迟；
  3. 无 OCR，纯图片且无 EXIF / 长宽比不明显时只能手动纠正。
- **风险与缓解**：镜像矩阵方向写反 → 用带文字坐标的样本 PDF 做几何断言；pypdf 解析不可信 PDF 抛错 → 统一 422 且前端回退到上一次可用方向，不白屏；并发点击 → `AbortSignal` + 只保留最后一次结果。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/preview/pdf_rotation.py`、`src/cndb/plugins/documents/routers/documents.py`、`pyproject.toml`（pypdf） | `tests/test_document_asset_rotation.py` | `9fe1980` |
| P1 | 已落地 | `frontend/src/pages/documents/assetOrientation.ts`、`frontend/src/pages/documents/AssetRotationControls.tsx`、`frontend/src/pages/documents/RotatableImage.tsx`、`frontend/src/index.css` | `frontend/src/pages/documents/assetOrientation.test.ts`、`frontend/src/pages/documents/RotatableImage.test.tsx` | `9fe1980` |
| P2 | 已落地 | `frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/api/documents.ts` | `frontend/src/pages/documents/DocumentAssetView.test.tsx` | `9fe1980` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 均已落地，功能完结
- 已完成：pypdf 派生副本模块（旋转 / 镜像 / 进程内 LRU）、`/asset/orientation` 与 `/asset/rotated` 端点（权限 / 异常 / 参数校验）；前端判定纯函数与 EXIF 解析、右侧方向控件条、可旋转图片舞台、PDF 派生副本接入与失败回退、切文档重置
- 下一步：无（如需 OCR 级方向识别另立 ADR）
- 已知坑：浏览器默认已应用 EXIF 与 PDF `/Rotate`，必须按 I2 关闭 / 烘焙，避免双重方向；pypdf 7 要求页面先挂在 `PdfWriter(clone_from=...)` 上再改，直接改 `PdfReader` 的页会抛 `DeprecationError`；镜像矩阵与页面既有旋转的叠加顺序由几何断言守住
- 最近一次全绿：`make check-fast` 全绿、`make test` 7721 passed、前端方向相关 46 例通过（2026-11-26，`9fe1980`）
