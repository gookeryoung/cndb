# 0174 工作区附件管理面板（S1）

- 编号：0174
- 来源 / 提出人：用户（会话 2026-11-26「先开批次 1」；批次范围见 `BACKLOG.md`）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；文件归属见 `files` 插件）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 先开批次 1。

（批次 1 在 `BACKLOG.md` 中定义为「0174 附件管理面板（工作区附件列表、引用计数、
孤儿体检与回收，复用 `docs gc` 能力）」。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「工作区附件列表」 | `GET /{wid}/documents/attachments?q=&limit=&offset=`：列出 `UPLOAD_DIR/{wid}` 下的文件，字段 `file_key / name / size / uploaded_at / document_id / document_title / orphan`；`q` 按文件名过滤；按上传时间倒序；分页 | `routers/attachments.py`（新）、`services/attachments.py`（新） | 接口单测：分页、搜索、归属文档标题 |
| C2 | 「引用计数」 | 列表返回 `ref_count`：该 `file_key` 在**最新版本正文**与 `asset_file_key` 中被引用的次数（本次扫描范围内）；为避免拖慢列表，列表用 `FileOwner` + `asset_file_key` 直查，正文引用计数放在体检结果里 | 同上 | 单测：正文引用 2 次时体检报告 ref_count=2 |
| C3 | 「孤儿体检」 | `POST /{wid}/documents/attachments/scan`（editor+，只读）：扫描工作区全部未删除文档的最新正文（`file:<key>` 与裸 key）与 `asset_file_key`，输出 `items`（每个附件：ref_count / 是否孤儿 / 大小）+ 合计；孤儿定义 = 文件存在、未被任何正文或原件字段引用、无 `FileOwner` 记录，且上传已满 24h（保护期避免误删编辑中素材） | `services/attachments.py` | 单测：被引用文件不判孤儿；无归属且未引用判孤儿 |
| C4 | 「回收」 | `POST /{wid}/documents/attachments/purge`（**owner**，`dry_run` 默认 true）：仅删除扫描判定为孤儿的文件；二次确认在前端；返回删除数与字节数 | 同上 | 单测：dry_run 不删；apply 只删孤儿、不碰被引用文件 |
| C5 | （安全） | 列表 / 扫描 editor+，回收 owner；不返回文件内容；不暴露其它工作区文件；删除走 `resolve_workspace_file` 路径校验 | 同上 | 单测：viewer 403、跨工作区 404 |
| C6 | （前端） | 文档区二级页「附件」（`/w/:wid/documents/attachments`）：表格（文件名 / 大小 / 归属文档 / 状态 / 时间）+ 搜索 + 「体检」+「回收孤儿」（owner，Popconfirm）；体检结果就地展示孤儿数与可回收字节 | `pages/documents/DocumentAttachmentsPage.tsx`（新）、路由、`api/documents.ts` | 前端单测：列表渲染、搜索、体检展示、owner 才见回收按钮 |
| C7 | （测试 / 文档） | 后端 + 前端单测；CHANGELOG；本卡回填落地结果 | 测试、`CHANGELOG.md` | 定向测试 + `pnpm check` 全绿 |

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 上传目录 | `settings.UPLOAD_DIR / {workspace_id}` | 附件物理位置 |
| 2 | 文件归属 | `files/models.py::FileOwner` | 列表的归属来源 |
| 3 | 原件族字段 | `Document.asset_file_key` | 扫描时的引用来源 |
| 4 | 正文引用 | `file:<key>` / `assets/<key>` | 扫描正则需覆盖站内引用写法 |
| 5 | 二级页签 | `MainLayout.tsx::DOCUMENT_SUBPAGES` | C6 入口 |

## 未决问题

- [x] 是否复用 `documents gc`（2026-11-26 结论）：不复用。`docs gc` 扫的是**外存版本文件**（`data/docs`），
  附件在 `data/uploads` 且需要按工作区隔离；本卡新增工作区级扫描，避免误删历史无归属但被引用的附件。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题有结论

## 落地结果

- 代码落点：`services/attachments.py`（列表 / 体检 / 回收，孤儿=零引用且无 `FileOwner`）、`routers/attachments.py`（`GET ""`、`POST /scan` editor+、`POST /purge` owner，注册在 `/{doc_id}` 之前）；前端 `pages/documents/DocumentAttachmentsPage.tsx` + 文档区二级页「附件」。
- 测试：`tests/test_document_attachments.py` 3 例（列表/搜索/归属、体检与回收不误删、viewer 403）；前端 `DocumentAttachmentsPage.test.tsx` 2 例（体检+回收、viewer 无回收入口）。
- 提交 sha：待提交。
