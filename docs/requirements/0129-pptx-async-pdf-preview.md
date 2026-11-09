# 需求卡片：PPTX 后台异步转 PDF 预览（衍生件缓存 + 失败降级）

- 编号：0129
- 来源 / 提出人：用户（会话 2026-11-09）
- 日期：2026-11-09
- 关联 ADR：[ADR 0129](../adr/0129-pptx-async-pdf-preview.md)
- 分级：**S2**（新增对外接口、后台转换链路、独立转换容器与部署编排；涉及安全隔离、缓存口径与可观测性）
- 上游需求：需求 0128（PPTX 预览逐页渲染，已完成；其卡片明确「后端异步转 PDF 另立 S2」）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改 ADR 与代码。

## 需求原句（逐字）

> PPTX预览时非常缓慢，请针对性能优化给出建议，能否后台空闲时间转化格式便于预览。

跟进确认（2026-11-09 用户）：

> 请补充后台异步转 PDF 的 S2 方案

## 方案摘要

**目标**：PPTX 导入后由后台异步转换为 PDF 衍生件；用户打开 PPTX 时先看到 0128 的逐页快速预览，PDF 就绪后原位切换为 PDF 阅读器。转换失败、转换器未部署或桌面端无转换容器时，**静默回退**到现有纯前端预览与下载，不出现错误页。

**关键口径**：

- 转换是**事件驱动 + 读取时兜底**：导入提交后入队、首次打开未命中缓存时补入队、可选的周期性空闲补扫只做兜底，不把「服务器空闲」作为主触发。
- 衍生 PDF 放 `CACHE_DIR`，**不进工作区上传目录、不计存储配额、不进备份归档**；原件 PPTX 不改写。
- LibreOffice 只跑在**独立、无外网、非 root 的转换容器**中；API 进程不安装、不调用 `soffice`。
- 转换器地址为空 = 功能关闭，行为与 0128 完全一致（生产 compose 显式开启）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「后台异步转 PDF」 | 导入完成后对 `content_type=pptx` 的文档入队；转换在应用内后台单线程执行，导入 / 打开请求不等待转换完成；未就绪返回 202 与 `Retry-After` | `documents/services/importers/importer.py`、`documents/services/preview/pptx_pdf.py`、`documents/routers/documents.py` | 接口测试：导入后任务入队；GET 未就绪返回 202；请求耗时不受转换阻塞 |
| C2 | 「后台空闲时间转化格式」 | 主触发为「导入后 + 首次打开补入队」；另提供低频空闲补扫（默认 6 小时、启动延迟 5 分钟、队列空闲才入队），补扫只补缺失缓存，不重复转换 | `app.py`、`documents/services/preview/pptx_pdf.py` | 单测：补扫只选缺失且非进行中的 PPTX；关闭开关不启动线程 |
| C3 | 「PPTX预览时非常缓慢」 | 前端打开 PPTX 立即渲染 0128 的逐页预览；PDF 查询并行进行，就绪后原位替换；首屏不得等待 PDF | `frontend/src/pages/documents/DocumentAssetView.tsx`、新增 `pptxPdf.ts` | 前端单测：先出现客户端预览；PDF 就绪后切换；首屏断言不依赖 PDF 响应 |
| C4 | （性能验收） | 同一份 20 / 50 / 200 页样本：首张幻灯片可见时间不高于 0128 基线；PDF 就绪时间单独记录，不作为首屏阻塞项；转换 P95 目标 20 页 ≤ 30s、200 页 ≤ 120s（参考机） | 前端 + 转换链路 | 手测记录 + e2e / 性能用例；发布说明附样本与耗时 |
| C5 | （失败降级） | 转换器未配置、源文件超限、损坏 / 加密、超时、队列满、转换失败：前端保留客户端预览与下载，不弹错误页；提供「重试生成」入口 | `DocumentAssetView.tsx`、`documents.py` | 前端单测覆盖 409 / 413 / 422 / 503；接口测试错误码 |
| C6 | （原件只读） | 原件 PPTX 不被读取以外的任何写入；衍生 PDF 不改变 `content_type`、不进入 Markdown 写路径；权限沿用 `get_visible_document_or_404` | `documents/services/content.py`、`documents/routers/documents.py` | 接口测试：转换前后 `asset_file_key` 不变；保存 / 提交仍 409 |
| C7 | （有界） | 全局同时 1 个转换；队列上限默认 32；源文件上限默认 100MB；转换超时默认 180s；瞬时失败自动重试 1 次；衍生件 TTL 30 天、全局上限 2GiB | `core/config.py`、`pptx_pdf.py`、转换容器 | 单测：队列满 503；超时 422；重试次数；缓存回收 |
| C8 | （安全隔离） | 不可信 PPTX 只在独立转换容器解析：无外网、非 root、只读根文件系统、`tmpfs`、`cap_drop: ALL`、`no-new-privileges`、内存 / 进程数限制、宏安全级别设为高；API 进程不执行 `soffice` | 新增 `deploy/Dockerfile.pdf-worker`、`docker-compose.prod.yml`、`pdf_worker.py` | 部署检查清单；容器内 `/health`；手工上传含宏 / 异常样本验证不执行、不联网 |
| C9 | （缓存口径） | 衍生 PDF 只放 `CACHE_DIR/document-pdf/<version>/<workspace_id>/<asset_key>.pdf`；原子写入；原件覆盖 / 彻底删除时同步失效；孤儿与过期文件由补扫清理 | `core/config.py`、`pptx_pdf.py`、`content.py`、`importer.py` | 单测：路径不落在 `UPLOAD_DIR`；覆盖换 key 后旧缓存删除；彻底删除后缓存删除 |
| C10 | （部署与兼容） | 生产 compose 增加 `pdf-worker` 服务与内部网络；`PPTX_PDF_CONVERTER_URL` 为空时功能关闭；桌面端 / Windows 无容器时自动降级；不改变单机应用镜像体积 | `docker-compose.prod.yml`、`deploy/deploy.sh`、`deploy/.env.prod.example`、`core/config.py` | 部署冒烟；桌面端打开 PPTX 与 0128 行为一致 |
| C11 | （保真边界） | 转换容器内置中文字体（`fonts-wqy-microhei` + `fonts-noto-cjk`）；界面标注「服务端 PDF 预览，版式可能与原件有差异」；动画 / 切换 / 音视频 / 嵌入对象 / 部分 SmartArt 不保证还原 | 转换容器、前端提示文案 | 手测中英文 / 图表 / 艺术字样本；文案核对 |
| C12 | （测试与文档） | 单测 / 接口 / 备份往返 / 前端 / e2e 同轮补齐；CHANGELOG、帮助教程与 `CONTEXT.md` 同步；日志记录文档 id、耗时、结果 | 全仓 | `make flow`；`make check-docs`；帮助教程核对 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | PPTX 目前纯前端逐页渲染，无服务端衍生件 | `frontend/src/pages/documents/DocumentAssetView.tsx:181-191`、`frontend/src/pages/documents/PptxPreview.tsx` | 0128 已优化，但大页数仍受客户端解析限制 |
| 2 | 原件落盘 key 为 UUID + 后缀，覆盖导入会换 key | `src/cndb/plugins/documents/services/importers/importer.py:69-88` | 衍生件可按 key 命名并在换 key 时失效 |
| 3 | 导入编排在单次请求内完成，无转换后置动作 | `src/cndb/plugins/documents/services/importers/importer.py:346-394` | 导入完成后收集 PPTX 文档入队（C1） |
| 4 | 原件下载与预览端点已统一可见性 | `src/cndb/plugins/documents/routers/documents.py:718-755`、`:758-812` | 新端点复用同一权限入口（C6） |
| 5 | 运行时可写缓存目录已存在 | `src/cndb/core/config.py:85`、`:103` | 衍生件放 `CACHE_DIR`（C9） |
| 6 | 工作区用量只统计上传目录、外存版本与数据库 | `src/cndb/plugins/workspaces/services/storage.py:55-57`、`:123-136` | `CACHE_DIR` 天然不计配额（C9） |
| 7 | 备份按原件字段导出，不扫描缓存目录 | `src/cndb/plugins/workspaces/services/backup_io.py:540-560` | 衍生件不进备份（C9） |
| 8 | 彻底删除在事务提交后删除原件文件 | `src/cndb/plugins/documents/services/content.py:720-746` | 同步失效衍生缓存（C9） |
| 9 | 应用内已有后台线程范式 | `src/cndb/app.py:41-126`、`src/cndb/plugins/tables/services/governance/tasks.py:148-161` | 单线程队列与生命周期停机（C1/C2） |
| 10 | 生产镜像仅 Python slim + 中文字体，无 LibreOffice | `deploy/Dockerfile.prod:27-63`、`deploy/Dockerfile.base:38-46` | 转换器放独立容器（C8/C10） |
| 11 | ADR 0087 曾以「镜像重、转换慢」否决应用镜像装 LibreOffice | `docs/adr/0087-docx-xlsx-online-preview.md:130` | 本方案用 sidecar 正面回应，不推翻 0087 |
| 12 | 前端原件 API 已有 blob / 文本两种取法 | `frontend/src/api/documents.ts:859-864` | 新增 PDF 状态与 blob 取法（C3） |
| 13 | 0128 已交付逐页渲染、模块级加载与原件缓存 | `docs/requirements/0128-pptx-preview-performance.md` | 作为回退路径保留，不删改（C3/C5） |

## 未决问题（已确认）

- [x] ① 转换目标格式：**PDF**；优先服务端渲染，不选图片序列（体积大、分页 / 文本选择差）。
- [x] ② 转换时机：**导入后异步 + 首次打开读取时补入队 + 低频空闲补扫**；不以「服务器空闲」为唯一触发。
- [x] ③ 转换器位置：**独立 `pdf-worker` 容器**；API 进程不装 LibreOffice，不推翻 ADR 0087 D2。
- [x] ④ 衍生件存储：`CACHE_DIR`，按 `asset_file_key` 命名；不进上传目录、不计配额、不进备份。
- [x] ⑤ 任务状态：**进程内状态 + 缓存文件存在性**，不新增任务表、不做迁移；重启后缺失缓存由读取时补入队。
- [x] ⑥ 失败策略：前端始终先渲染 0128 客户端预览；PDF 失败静默回退，提供手动重试。
- [x] ⑦ 保真口径：非像素级；中文字体替代、动画 / 音视频 / 嵌入对象不保证。
- [x] ⑧ 公开分享页：本期不接入 PDF 衍生件，保持现有行为。
- [x] ⑨ 缓存治理：TTL 30 天 + 全局 2GiB + 孤儿清理；覆盖 / 彻底删除即时失效。
- [x] ⑩ 重试口径：瞬时失败自动重试 1 次；失败态保留 10 分钟，用户可 POST 手动重试。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认（S2 需人工确认后进入 ADR 评审；2026-11-09 用户确认「标 Accepted 并开始 P0」）
