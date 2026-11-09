# ADR 0129: PPTX 后台异步转 PDF 预览（衍生件缓存 + 独立转换容器 + 失败降级）

Status: Accepted
Date: 2026-11-09
Related: `src/cndb/plugins/documents/services/importers/importer.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/workspaces/services/storage.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/core/config.py`、`src/cndb/app.py`、`frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/api/documents.ts`、`deploy/Dockerfile.prod`、`deploy/Dockerfile.base`、`docker-compose.prod.yml`、`docs/adr/0087-docx-xlsx-online-preview.md`、`docs/requirements/0128-pptx-preview-performance.md`
需求卡片: `docs/requirements/0129-pptx-async-pdf-preview.md`（需求原文与约束编号的唯一副本）

> 本 ADR 只新增「PPTX → PDF 衍生预览件」链路；ADR 0025 的原件族只读模型、ADR 0087 的 Office HTML 预览、需求 0128 的前端逐页渲染均保持不变。衍生件是可丢弃缓存，不进入备份、配额与内容版本。
>
> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C12），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「后台异步转 PDF」 | 新增 `documents/services/preview/pptx_pdf.py`：导入提交后把 `content_type=pptx` 的文档 id 入队；进程内单线程消费者执行转换；`GET /asset/pdf` 未就绪返回 202，不阻塞导入 / 打开请求 |
| C2 | 「后台空闲时间转化格式」 | 触发顺序固定为「导入后入队 → 首次打开读取时补入队 → 低频补扫」；补扫只处理缓存缺失且不在进行中的 PPTX，默认 6 小时一次、启动延迟 5 分钟、队列非空不投递 |
| C3 | 「PPTX预览时非常缓慢」 | `DocumentAssetView` 对 `isPptx` 始终先渲染 0128 的 `PptxPreview`；并行请求 PDF 状态，200 后原位替换为 PDF `iframe`，首屏不等待 PDF |
| C4 | （性能验收） | 首张可见时间以 0128 为基线不得回退；转换耗时单独记录（20 页 P95 ≤ 30s、200 页 P95 ≤ 120s，参考机）；样本与结果写入 CHANGELOG / ADR 交接 |
| C5 | （失败降级） | 409（未启用 / 非 PPTX）、413（超限）、422（失败）、503（队列满）统一视为「PDF 不可用」，前端保留客户端预览与下载；`POST /asset/pdf` 提供手动重试 |
| C6 | （原件只读） | 转换只读 `asset_file_key` 指向的文件；不写 `Document`、不产生版本、不改 `content_type`；端点复用 `get_visible_document_or_404` |
| C7 | （有界） | 配置项：`PPTX_PDF_QUEUE_MAX=32`、`PPTX_PDF_TIMEOUT_SECONDS=180`、`PPTX_PDF_MAX_SOURCE_BYTES=104857600`、`PPTX_PDF_RETRY=1`、`PPTX_PDF_CACHE_TTL_DAYS=30`、`PPTX_PDF_CACHE_MAX_BYTES=2147483648` |
| C8 | （安全隔离） | 新增 `pdf-worker` 容器：仅内网、无发布端口、非 root、`read_only`、`tmpfs /tmp`、`cap_drop: ALL`、`no-new-privileges`、`mem_limit` / `pids_limit`、宏安全级别高；API 容器不装 `soffice` |
| C9 | （缓存口径） | 路径 `settings.CACHE_DIR / "document-pdf" / CONVERTER_CACHE_VERSION / str(workspace_id) / f"{asset_file_key}.pdf"`；`.part` 写完后原子替换；覆盖 / 彻底删除时调用失效函数 |
| C10 | （部署与兼容） | `docker-compose.prod.yml` 增加 `pdf-worker` 服务与 `internal: true` 网络；`PPTX_PDF_CONVERTER_URL` 为空即关闭；桌面端 / Windows 无容器时自动降级 |
| C11 | （保真边界） | worker 镜像安装 `fonts-wqy-microhei` 与 `fonts-noto-cjk`；前端提示「服务端 PDF 预览，版式可能与原件有差异」；动画 / 音视频 / 嵌入对象不保证 |
| C12 | （测试与文档） | 新增单测 / 接口 / 备份往返 / 前端 / e2e；CHANGELOG、帮助教程、`CONTEXT.md` 同步；日志字段 `doc_id` / `workspace_id` / `duration_ms` / `result` |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。编号沿用卡片「现状影响面」，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | PPTX 由前端 `PptxPreview` 逐页渲染，无服务端衍生件 | `frontend/src/pages/documents/DocumentAssetView.tsx:181-191`、`frontend/src/pages/documents/PptxPreview.tsx` | 大页数仍需客户端解析，首开受设备性能影响 | 确认（C3） |
| 2 | 原件落盘 key 为 `uuid4().hex + 后缀`，覆盖导入换 key | `src/cndb/plugins/documents/services/importers/importer.py:69-88` | 衍生件可按 key 命名，天然区分版本 | 确认（C9） |
| 3 | 导入在单次请求内完成，无转换后置动作 | `src/cndb/plugins/documents/services/importers/importer.py:346-394` | 需要新增导入后入队钩子 | 新增（C1） |
| 4 | 原件下载 / 预览端点统一走可见性判定 | `src/cndb/plugins/documents/routers/documents.py:718-755`、`:758-812` | 新 PDF 端点复用同一权限入口 | 确认（C6） |
| 5 | `CACHE_DIR` 已存在并在启动时创建 | `src/cndb/core/config.py:85`、`:103` | 可放可重建衍生件，无需新目录约定 | 确认（C9） |
| 6 | 工作区用量只统计上传目录、外存版本与数据库 | `src/cndb/plugins/workspaces/services/storage.py:55-57`、`:123-136` | `CACHE_DIR` 不计入配额 | 确认（C9） |
| 7 | 备份按原件字段导出，不扫描缓存目录 | `src/cndb/plugins/workspaces/services/backup_io.py:540-560` | 衍生件不进备份，恢复也不依赖它 | 确认（C9） |
| 8 | 彻底删除在事务提交后删除原件文件 | `src/cndb/plugins/documents/services/content.py:720-746` | 需在同一位置失效衍生缓存 | 新增（C9） |
| 9 | 应用生命周期已有多条后台线程与停机顺序 | `src/cndb/app.py:41-126` | 可挂转换消费者与补扫线程，并在关闭阶段停止 | 复用（C1/C2） |
| 10 | 治理任务已有「后台线程 + 状态机」范式 | `src/cndb/plugins/tables/services/governance/tasks.py:148-161` | 借用线程模型，但不新增任务表 | 复用（D5） |
| 11 | 生产镜像仅 Python slim + 中文字体，无 LibreOffice | `deploy/Dockerfile.prod:27-63`、`deploy/Dockerfile.base:38-46` | 转换器必须独立部署，避免应用镜像膨胀 | 确认（C8/C10） |
| 12 | ADR 0087 D2 曾以「镜像重、转换慢」否决应用镜像装 LibreOffice | `docs/adr/0087-docx-xlsx-online-preview.md:130` | 本 ADR 用 sidecar 隔离，不推翻 0087 的结论 | 确认（D2） |
| 13 | 前端原件 API 已提供 blob / 文本两种取法 | `frontend/src/api/documents.ts:859-864` | 新增 PDF 状态与 blob 取法即可，无需新依赖 | 确认（C3） |
| 14 | 需求 0128 已交付逐页渲染、模块级加载与原件缓存 | `docs/requirements/0128-pptx-preview-performance.md` | 作为永久回退路径保留，不删除 | 确认（C5） |

**核心缺陷（需求要补的）**：PPTX 只有「客户端解析渲染」一条预览路径，没有服务端生成、可复用、与设备性能解耦的稳定预览件；因此大文件首开始终受浏览器解析能力限制，也无法把转换成本移到后台。

设计目标（不变量）：

- **I1 原件不变**：转换只读原件，不写 `Document` / 版本 / `asset_file_key`；原件族只读口径不变。
- **I2 缓存可丢弃**：衍生 PDF 是缓存，缺失可重建；不计配额、不进备份、不进内容差异。
- **I3 失败必降级**：转换不可用或失败不得阻断预览；前端始终保留 0128 客户端预览与下载。
- **I4 有界**：并发、队列、源文件大小、转换时长、重试次数、缓存容量与保留期都有硬上限。
- **I5 隔离**：不可信 PPTX 只在独立转换容器解析，容器无外网、非 root、最小权限；API 进程不执行 `soffice`。
- **I6 权限同源**：衍生 PDF 只经带鉴权的文档端点提供，权限判定与 `/asset` 完全一致；不新增裸链接或匿名入口。
- **I7 默认关闭**：`PPTX_PDF_CONVERTER_URL` 为空时行为与 0128 完全一致；桌面端无容器即自动关闭。

> I3 / I5 已按 H27 登记为 `docs/CONSTRAINTS.md` 的 H45 / H46（来源 `ADR 0129 I3/I5`，2026-11-09 人工确认）。

## Decision

### 1. 数据模型

**零迁移、零新表**。不新增转换任务表，不扩展 `Document` 字段。

- 衍生件路径：`settings.CACHE_DIR / "document-pdf" / CONVERTER_CACHE_VERSION / str(workspace_id) / f"{asset_file_key}.pdf"`；
- `CONVERTER_CACHE_VERSION` 为模块常量（首版 `"lo-1"`），LibreOffice 大版本升级或转换参数变化时递增，旧目录由补扫按 TTL 清理；
- 写入使用同目录 `.part` 临时文件 + `os.replace` 原子替换，避免半成品被读取；
- 状态只存在进程内：`_jobs: dict[int, PdfJobState]`，字段 `status ∈ {queued, running, ready, failed}`、`error_code`、`attempts`、`updated_at`；
- 进程重启后内存状态丢失，`asset_file_key` 对应 PDF 是否存在是唯一权威事实；缺失即由读取路径重新入队。

### 2. 判定与执行入口（唯一）

新增 `src/cndb/plugins/documents/services/preview/pptx_pdf.py`：

```python
def derived_pdf_path(workspace_id: int, asset_file_key: str) -> Path: ...
def ensure_pptx_pdf(workspace_id: int, doc_id: int, *, retry: bool = False, db: Session | None = None) -> PdfJobState: ...
def enqueue_pptx_pdf(workspace_id: int, doc_id: int, *, retry: bool = False, db: Session | None = None) -> PdfJobState: ...
def invalidate_pptx_pdf(workspace_id: int, asset_file_key: str) -> None: ...
def start_pptx_pdf_sweeper() -> None: ...
def stop_pptx_pdf_sweeper() -> None: ...
```

> `db` 为可选会话注入：路由 / 导入在同一事务内复用调用方 Session，后台线程缺省时自行新建；不改变对外语义。

判定顺序（`ensure_pptx_pdf`）：

1. `PPTX_PDF_CONVERTER_URL` 为空 → `disabled`（409 `pdf_preview_disabled`）；
2. 文档不存在 / 不可见 → 由路由先行 404，服务层只接收已校验 id；
3. `content_type != pptx` 或旧版 `.ppt` → `unsupported`（409 `pdf_preview_unsupported`）；
4. 源文件大于 `PPTX_PDF_MAX_SOURCE_BYTES` → `too_large`（413 `pdf_preview_too_large`）；
5. 缓存 PDF 存在且非空 → `ready`；
6. 同文档已有 `queued/running` → 返回现有状态；
7. 队列已满 → `busy`（503 `pdf_preview_busy`）；
8. 失败态在 10 分钟冷却内且未 `retry` → `failed`（422）；
9. 其余入队 → `queued`（202）。

执行器：

- 模块级 `queue.Queue(maxsize=PPTX_PDF_QUEUE_MAX)` + 单个 daemon 线程，首次入队时惰性启动；
- 每个任务新建独立 SQLAlchemy Session，重新读取文档并再次比对 `asset_file_key`（防止排队期间被覆盖）；
- 读取原件字节 → 调用 `pdf_converter.convert_pptx_to_pdf()` → 校验响应以 `%PDF-` 开头 → 原子写入缓存；
- 瞬时错误（超时 / worker 5xx / 连接失败）自动重试 1 次，仍失败则 `failed`；损坏、加密、非 PPTX 等永久错误不重试；
- 日志固定字段：`doc_id`、`workspace_id`、`asset_file_key`、`duration_ms`、`result`、`error_code`（不记录文件内容）。

入队钩子：

- `importer.import_files` 在批次结束后，对本次保存的 `content_type == pptx` 文档调用 `enqueue_pptx_pdf`，整体 `try/except` 包住，入队失败不影响导入结果；
- `GET /asset/pdf` 读取时若缓存缺失，调用 `ensure_pptx_pdf` 补入队；
- 补扫线程在 `app.lifespan` 启动：默认启动延迟 300s、周期 21600s、仅当队列空闲时投递；`PPTX_PDF_SWEEP_INTERVAL_SECONDS=0` 或转换器未配置时不启动；
- 同一线程顺带清理：删除孤儿缓存（工作区 / 文档 / 原件已不存在）、超过 TTL 的文件；全局缓存超过 `PPTX_PDF_CACHE_MAX_BYTES` 时按最旧 mtime 淘汰。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{workspace_id}/documents/{doc_id}/asset/pdf` | 新增。命中缓存返回 200 PDF；未就绪返回 202；未启用 / 非 PPTX 409；超限 413；失败 422；队列满 503；权限 / 原件缺失沿用 404 |
| `POST /{workspace_id}/documents/{doc_id}/asset/pdf` | 新增。手动请求 / 重试转换；幂等：已就绪 200、进行中 202、其余同上；不返回文件字节 |

响应口径：

- `200`：`Content-Type: application/pdf`、`Content-Disposition: inline`、`X-Content-Type-Options: nosniff`、`Cache-Control: private, max-age=3600`、`ETag: "pptxpdf-<asset_file_key>-<CONVERTER_CACHE_VERSION>"`；`If-None-Match` 命中返回 304；
- `202`：JSON `{"status": "queued|running", "retry_after": 2}` + `Retry-After: 2`；
- `409`：`{"code": "pdf_preview_disabled|pdf_preview_unsupported", "detail": "..."}`；
- `413`：`{"code": "pdf_preview_too_large"}`；
- `422`：`{"code": "pdf_conversion_failed", "detail": "..."}`；
- `503`：`{"code": "pdf_preview_busy"}` + `Retry-After: 5`。

不新增公开分享端点；公开分享页维持现有行为（卡片未决问题⑧）。

### 4. 边界与例外

1. 旧版二进制 `.ppt`：不转换，409 `pdf_preview_unsupported`，前端保持下载卡 / 客户端能力判定。
2. 转换器未部署（桌面端、Windows、未配置 URL）：409 `pdf_preview_disabled`，前端静默使用 0128 客户端预览。
3. 损坏 / 加密 / 密码保护 PPTX：worker 返回永久错误，422；前端回退，提供「重试生成」。
4. 源文件超限：入队前 413，不发送到 worker；前端回退。
5. 转换超时：worker 杀掉子进程，422；自动重试 1 次仍失败则进入 10 分钟冷却。
6. 队列满：503，不无限排队；前端回退，稍后打开 / 手动重试再入队。
7. 进程重启：内存状态丢失；缓存存在即 200，缺失则读取时重新入队。
8. 原件覆盖导入：`asset_file_key` 变化；旧缓存由 `_drop_previous_asset` 同步删除，新 key 重新转换。
9. 彻底删除 / 工作区删除：`_remove_asset_files` 同步删除衍生缓存；补扫兜底清理孤儿。
10. 单进程假设：当前生产为单 uvicorn 进程，进程内队列成立；未来多 worker 需改为文件锁或外部队列，属已知限制。
11. 并发转换：全局 1 个；每个任务使用独立 `-env:UserInstallation` 临时 profile，避免 LibreOffice 用户配置锁冲突。
12. 公开分享 / 游客：不提供衍生 PDF；维持现有页面能力。

### 5. 迁移

无数据库迁移、无备份协议变更。

- 衍生件位于 `CACHE_DIR`，`backup_io` 不扫描该目录，备份归档不新增条目；
- 恢复旧备份不依赖衍生件，首次打开时重新生成；
- `tests/test_workspace_backup_*.py` 增加断言：备份归档中不存在 `document-pdf` 路径，恢复前后业务数据一致；
- `workspace_storage_bytes` 不统计 `CACHE_DIR`，配额口径不变（H14 / H13 均不触发新增）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 状态机 / API | `frontend/src/pages/documents/pptxPdf.ts`（新增） | `fetchPptxPdf` 返回 `ready(blob) / pending / disabled / failed / busy`；统一解析 200 / 202 / 409 / 413 / 422 / 503；轮询退避 2s → 3s → 5s，最多 60s，页面隐藏或组件卸载即停止 |
| API 封装 | `frontend/src/api/documents.ts` | 新增 `assetPdf`（blob）与 `requestAssetPdf`（POST，`validateStatus` 接受 200/202/409/413/422/503） |
| 阅读器 | `frontend/src/pages/documents/DocumentAssetView.tsx` | `isPptx` 分支始终先渲染现有 `PptxPreview`；并行查询 PDF；`ready` 后用 objectURL + `iframe`（`data-testid="doc-asset-pptx-pdf"`）原位替换；`pending` 仅显示右下角轻量「正在生成高清预览」提示；`disabled/failed/busy` 不提示错误，保留客户端预览 |
| 回退 | `frontend/src/pages/documents/PptxPreview.tsx` | 不改；继续作为 PDF 不可用时的唯一回退渲染器 |
| 顶栏 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 仅补「服务端 PDF 预览，版式可能与原件有差异」的信息气泡文案；下载入口不变 |

约束：

- 不新增前端依赖，不引入 PDF.js；200 时复用现有 PDF `iframe` 渲染方式；
- PDF objectURL 在切换 / 卸载时 `revokeObjectURL`；
- 不以 `loading` 状态覆盖客户端预览，避免 0128 的首屏收益被 PDF 等待抵消。

### 7. 测试清单

**判定层（单测，`tests/test_pptx_pdf_preview.py`）**：

- 缓存路径含版本 / 工作区 / asset key；不落在 `UPLOAD_DIR`；
- `disabled / unsupported / too_large / ready / queued / busy / failed` 七种判定顺序；
- 同文档双请求只产生一个任务（单飞）；不同文档按队列串行；
- 瞬时错误重试 1 次、永久错误不重试、失败态 10 分钟冷却；
- 覆盖换 key 失效旧缓存、彻底删除失效缓存、TTL / 孤儿 / 容量淘汰；
- 客户端：URL 为空、超时、worker 4xx/5xx、非 PDF 响应、响应超限；
- worker：伪造 `soffice` 成功 / 超时 / 非零退出 / 缺输出文件，token 校验与请求大小上限。

**接口层（`tests/test_pptx_pdf_preview_api.py`）**：

- 未登录 / 非成员 / 不可见文档 404；非 PPTX 409；未配置 409；超限 413；
- `GET` 首次 202 → 转换完成后 200，校验 `Content-Type` / `Content-Disposition` / `nosniff` / `Cache-Control` / `ETag` / 304；
- `POST` 手动重试；队列满 503；失败 422；原件缺失 404；
- 导入一批 PPTX + 非 PPTX：仅 PPTX 入队；
- 转换前后 `asset_file_key` / `content_type` / 版本数不变；保存 / 提交仍 409（H19）；
- 配额统计不含衍生件；备份归档不含 `document-pdf`。

**迁移 / 备份**：零迁移；`make test` 全量通过；备份往返断言见第 5 节。

**前端单测（`DocumentAssetView.test.tsx`、`pptxPdf.test.ts`）**：

- PPTX 打开先出现客户端预览；PDF 202 期间仍可见客户端预览；就绪后切换为 PDF `iframe`；
- 409 / 413 / 422 / 503 均保留客户端预览，不出现 `doc-asset-error`；
- 轮询在卸载后停止；`ready` 后不再轮询；PDF objectURL 被释放；
- 非 PPTX 文档行为不变；放映、下载、标记笔不受影响。

**e2e（`frontend/tests/e2e/critical/pptx-async-pdf.spec.ts`）**：

- 未配置转换器：导入 PPTX → 打开 → 客户端预览可用、无错误页；
- 通过路由拦截模拟 202 → 200：先客户端预览，后切换 PDF；
- 模拟 422：保持客户端预览，点击重试后重新请求。

**性能记录**：20 / 50 / 200 页样本，记录首张可见时间、PDF 就绪时间、转换耗时、内存峰值；首张可见时间不得高于 0128 基线。

### 8. 部署与运维

1. 新增 `deploy/Dockerfile.pdf-worker`：
   - `FROM ${BASE_IMAGE}`（复用 `Dockerfile.base`，避免重复装 Python 依赖）；
   - `apt-get install --no-install-recommends libreoffice-impress fonts-wqy-microhei fonts-noto-cjk`；
   - 创建非 root 用户，复制 `dist/*.whl` 安装；
   - 入口 `python -m cndb.plugins.documents.services.preview.pdf_worker`，监听 `0.0.0.0:8100`；
   - 仅提供 `GET /health` 与 `POST /convert`，`POST` 校验 `Authorization: Bearer <token>` 与 `Content-Length`。
2. `docker-compose.prod.yml` 新增：
   - `pdf-worker` 服务：不发布端口、仅加入 `cndb-internal`（`internal: true`）、`read_only: true`、`tmpfs: /tmp:size=512m`、`cap_drop: ALL`、`security_opt: no-new-privileges:true`、`mem_limit: 1g`、`pids_limit: 256`、`restart: unless-stopped`；
   - `app` 服务增加 `cndb-internal` 网络与环境变量 `PPTX_PDF_CONVERTER_URL=http://pdf-worker:8100`、`PPTX_PDF_CONVERTER_TOKEN=${PPTX_PDF_CONVERTER_TOKEN}`；
   - 顶层 `networks.cndb-internal.internal: true`。
3. `deploy/deploy.sh`：把 `Dockerfile.pdf-worker` 纳入构建 / 推送 / 指纹与镜像保留；worker 镜像 tag 与应用版本同源。
4. `deploy/.env.prod.example`：新增 `CNDB_PDF_WORKER_IMAGE`、`PPTX_PDF_CONVERTER_TOKEN`（`openssl rand -hex 32`）、`PPTX_PDF_CONVERTER_URL`（默认指向 compose 服务名）。
5. 应用镜像（`Dockerfile.prod`）不新增 LibreOffice；桌面端 / Windows 不部署 worker，URL 留空即关闭。
6. 观测：worker 访问日志只记录请求 id、源大小、耗时、结果；API 日志记录第 2 节字段；`/api/health` 不依赖 worker（worker 挂掉只影响 PDF 预览，不影响应用健康）。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 配置项 + `pptx_pdf.py` 缓存 / 队列 / 状态 + `pdf_converter.py` 客户端 + 两个端点 + 导入钩子 + 单测 / 接口测试 | 低（默认关闭，零回归） |
| **P1** | `pdf_worker.py` + `Dockerfile.pdf-worker` + compose / deploy / env + 前端渐进式 PDF 切换 + 前端测试 | 中（部署编排与容器权限） |
| **P2** | 空闲补扫 + 缓存 GC + 日志 / 验收指标 + e2e + 帮助教程 / CONTEXT / CHANGELOG + 性能记录 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 后台异步生成 PDF 衍生件，前端渐进式替换 | 大页数 PPTX 的瓶颈在客户端解析；服务端一次转换可复用，且不改变原件 | 纯前端继续优化（0128 已做，收益见顶）；每次打开实时转换（重复成本高、阻塞请求） | `pptx_pdf.py`、`DocumentAssetView.tsx` |
| D2 | 转换器位置 | 独立 `pdf-worker` 容器，API 进程不装 LibreOffice | 应用镜像保持 slim；不可信文件隔离；正面回应 ADR 0087 D2 的「镜像重」否决项 | 应用镜像内装 LibreOffice（镜像 +数百 MB，攻击面进 API）；纯 Python 转换库（PPTX 版式还原不足） | `deploy/Dockerfile.pdf-worker`、`docker-compose.prod.yml` |
| D3 | 触发时机 | 导入后入队 + 首次打开补入队 + 低频空闲补扫 | 用户导入后最可能立即打开；读取时兜底覆盖重启 / 漏投；补扫只做兜底 | 只在「服务器空闲」时转换（不可预期、首开仍慢）；只在打开时转换（首次仍等待） | `importer.py`、`documents.py`、`app.py` |
| D4 | 衍生件存储 | `CACHE_DIR`，按 `asset_file_key` 命名，原子写入 | 可丢弃、可重建；不进配额 / 备份；key 唯一且覆盖会变 | 存 `UPLOAD_DIR`（计配额、进备份、需归属登记）；存数据库 BLOB（体积与备份成本高） | `pptx_pdf.py`、`core/config.py` |
| D5 | 任务状态 | 进程内状态 + 缓存文件存在性；零迁移 | 状态可丢，文件可重建；避免为缓存引入持久化任务表与备份协议 | 新增任务表（迁移 + H14 备份纳入 + 清理逻辑）；Redis / 外部队列（单机部署过度设计） | `pptx_pdf.py` |
| D6 | API 形态 | `GET .../asset/pdf` 读取时补入队 + `POST .../asset/pdf` 手动重试 | 前端只需一个读取入口；GET 的入队是幂等副作用；POST 提供显式重试 | 独立 `/conversion-jobs` 资源（前端多一次往返、状态模型变重）；只在导入时转换（重启 / 漏投无兜底） | `documents.py` |
| D7 | 并发与有界 | 全局 1 并发、队列 32、超时 180s、重试 1 次、源文件 100MB | LibreOffice 内存 / CPU 重；单机部署必须防止并发打满 | 每请求并发转换（易被大文件拖垮）；无上限队列（内存与延迟失控） | `pptx_pdf.py`、`pdf_converter.py` |
| D8 | 安全隔离 | 独立容器无外网、非 root、只读根、tmpfs、cap_drop、资源限制、宏安全高 | 不可信 PPTX 可能含宏 / 解析漏洞；最小权限 + 无外网降低影响 | 在 API 容器内 `subprocess soffice`（逃逸即拿到数据库 / 密钥）；有外网 worker（可被用作出口） | `Dockerfile.pdf-worker`、`docker-compose.prod.yml`、`pdf_worker.py` |
| D9 | 字体与保真 | 安装 microhei + Noto CJK；明确非像素级 | 覆盖常用中文字形；PPTX 复杂版式无法完全还原 | 声称像素级还原（无法保证）；不装 CJK 字体（中文变方框） | `Dockerfile.pdf-worker`、前端提示 |
| D10 | 失败降级 | 始终先渲染 0128 客户端预览；PDF 失败静默回退；提供手动重试 | 预览可用性优先；不能因转换链路回退 0128 的收益 | 失败显示错误页（阻断阅读）；自动无限重试（放大故障） | `DocumentAssetView.tsx`、`pptxPdf.ts` |
| D11 | 缓存治理 | 覆盖 / 彻底删除即时失效；TTL 30 天、全局 2GiB、孤儿清理 | 缓存不能无限增长；失效必须跟随原件生命周期 | 永不清理（磁盘耗尽）；只靠 TTL（覆盖后旧件仍占空间） | `pptx_pdf.py`、`content.py`、`importer.py` |
| D12 | 公开分享 | 本期不接入；维持现有行为 | 分享链路有独立权限与匿名边界，需求未要求；避免扩大安全面 | 同步开放公开 PDF（需新增匿名端点与滥用防护，超出本期） | `documents/routers/public.py`（不改） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：大页数 PPTX 首开不再依赖客户端解析完成；PDF 可复用、可分页、可文本选择；转换失败不影响现有预览；应用镜像不膨胀；衍生件不占配额 / 备份。
- **负向**：多一个容器与部署编排；LibreOffice 转换保真度有限；单机增加 CPU / 内存峰值（受 1 并发与资源限制约束）；进程内状态在重启后需重新生成。
- **风险与缓解**：LibreOffice 解析不可信文件 → 独立无外网容器 + 最小权限 + 超时；缓存增长 → TTL + 容量淘汰 + 孤儿清理；队列拥塞 → 有界队列 + 503 快速降级；字体缺失 → 固定镜像字体并手测中英文样本。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 原件族只读 | `Document` / `ASSET_CONTENT_TYPES` | PPTX 仍只读；衍生 PDF 不改变原件模型 | ADR 0025 |
| Office 预览方式 | `preview/office.py` / `DocumentAssetView` | docx / xlsx 继续走 HTML；PPTX 新增 PDF 衍生件，不改 0087 的 HTML 路径 | ADR 0087 |
| LibreOffice 位置 | 部署镜像 | 0087 否决「应用镜像装 LibreOffice」；本 ADR 改为独立 sidecar，结论不冲突 | ADR 0087 D2 |
| 前端 PPTX 回退 | `PptxPreview.tsx` | 0128 的逐页渲染保留为永久回退，不删除 | 需求 0128 |
| 备份与配额 | `backup_io` / `storage.py` | 衍生件不进入备份、不计配额 | ADR 0075 / 0024 |
| 前端体积门禁 | `bundle-budget` | 不新增前端重型依赖，PDF 复用 `iframe` | ADR 0116 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/preview/pptx_pdf.py`、`src/cndb/plugins/documents/services/preview/pdf_converter.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/importers/importer.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/core/config.py` | `tests/test_pptx_pdf_preview.py`、`tests/test_pptx_pdf_preview_api.py` | 待提交 |
| P1 | 未开始 | `src/cndb/plugins/documents/services/preview/pdf_worker.py`、`deploy/Dockerfile.pdf-worker`、`docker-compose.prod.yml`、`deploy/deploy.sh`、`deploy/.env.prod.example`、`frontend/src/pages/documents/pptxPdf.ts`、`frontend/src/pages/documents/DocumentAssetView.tsx`、`frontend/src/api/documents.ts` | `frontend/src/pages/documents/DocumentAssetView.test.tsx`、`frontend/src/pages/documents/pptxPdf.test.ts`、`tests/test_pptx_pdf_worker.py` | — |
| P2 | 未开始 | `src/cndb/app.py`、`src/cndb/plugins/documents/services/content.py`、`frontend/src/pages/help/content/tutorials.tsx`、`CONTEXT.md`、`CHANGELOG.md` | `frontend/tests/e2e/critical/pptx-async-pdf.spec.ts`、`tests/test_workspace_backup_*.py` | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：S2 实施（P0 已落地，P1 / P2 未开始）
- 已完成：需求卡片 0129、本 ADR（Accepted）、H45 / H46 登记；P0 配置项 + 缓存 / 队列 / 状态 + 转换客户端 + 两个端点 + 导入 / 覆盖 / 彻底删除钩子 + 单测 / 接口测试
- 下一步：P1 做 `pdf_worker.py` + `Dockerfile.pdf-worker` + compose / deploy / env + 前端渐进式 PDF 切换 + 前端测试；P2 做空闲补扫 / GC / e2e / 文档与性能记录
- 已知坑：单进程队列假设；`CONVERTER_CACHE_VERSION` 升级后旧目录由 P2 补扫清理；LibreOffice 字体 / 复杂版式还原有限；桌面端无 worker 必须降级；`CACHE_DIR` 不备份，换机后首次打开需重新生成；旧版 `.ppt` 不转换
- 最近一次全绿：`make check-fast` + `make test`（6768 passed, 3 skipped）@ 2026-11-09
