# 0172 文档复制副本（S1）

- 编号：0172
- 来源 / 提出人：用户（会话 2026-11-26「先开批次 1」；批次范围见 `BACKLOG.md`）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；权限口径 H33/H64，文件归属见 `files` 插件）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 先开批次 1。

（批次 1 在 `docs/requirements/BACKLOG.md` 中定义为「0172 文档复制副本（文档 / 文件夹子树，
标题「原名 副本」递增；复制最新正文、元数据、标签；版本链可选）」。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「文档 / 文件夹子树」 | `POST /{wid}/documents/{id}/duplicate`：文档复制为同级副本；文件夹递归复制整棵子树（层级与顺序保留） | `routers/documents.py`、`services/content.py` | 单测：文件夹 2 层子树复制后节点数 / parent 关系一致 |
| C2 | 「标题「原名 副本」递增」 | 根节点标题默认 `原名 副本`，同工作区重名时递增为 `副本 2` / `副本 3`；子节点标题原样保留（同名不影响） | `services/content.py` | 单测：连续复制三次标题分别为 副本 / 副本 2 / 副本 3 |
| C3 | 「复制最新正文、元数据、标签」 | 每个节点取 `latest_version + load_content` 作为新文档 v1 正文；复制 `status / content_type / sort_order / tag_ids`；**不复制版本链**（新文档只有 v1），不复制置顶、分享、问题、修改申请 | `services/content.py` | 单测：版本数为 1、标签一致、置顶/分享不复制 |
| C4 | （原件族） | 原件族文档（pdf/image/xlsx/pptx/mhtml/word）复制文件字节为新 `file_key`（uuid + 原后缀）并登记 `FileOwner(document_id=新 id)`；源文件缺失时该节点降级为普通 Markdown 空文档并记 `errors`？**否**：直接 400，整体不落库 | `files/services.py`、`services/content.py` | 单测：新 key ≠ 源 key、内容字节一致、归属指向新文档 |
| C5 | （权限） | 仅 owner/editor（`require_editor`）可复制；源文档须可见（H33）；目标 `parent_id` 须为同工作区文件夹；配额不预判（复制后用量由快照统计） | `routers/documents.py` | 单测：viewer 403、跨工作区 404、父节点非文件夹 409 |
| C6 | （前端） | 文档列表 / 文件夹行操作加「创建副本」；成功后刷新列表并提示新标题，不自动跳转 | `DocumentsPage.tsx`、`api/documents.ts` | 前端单测：点击后调用端点且列表刷新 |
| C7 | （测试 / 文档） | 后端接口 + service 单测、前端单测；CHANGELOG 增条目；本卡回填落地结果 | 测试、`CHANGELOG.md` | `make check-fast` / 定向测试全绿 |

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 创建文档 | `services/content.py::create_document` | 复制的唯一落库入口（保证元数据/版本/标签一致） |
| 2 | 最新正文 | `services/content.py::latest_version` / `load_content` | 分级存储，需按原样读出 |
| 3 | 文件归属 | `files/services.py::record_owner` / `resolve_workspace_file` | 原件族复制 |
| 4 | 行操作菜单 | `frontend/src/pages/documents/DocumentsPage.tsx` | C6 入口 |
| 5 | 文档接口封装 | `frontend/src/api/documents.ts` | `duplicate` |

## 未决问题

- [x] 版本链是否复制（2026-11-26 结论）：不复制，只保留最新正文为新文档 v1；需要历史请用导出/备份。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题有结论

## 落地结果

- 代码落点：`services/content.py::duplicate_document` / `_duplicate_node`（递归子树、标题递增、最新正文、标签、原件文件复制）、`routers/documents.py::POST /{doc_id}/duplicate`、`schemas.DocumentDuplicateRequest`；前端 `api/documents.ts::duplicate` + 行操作「创建副本」。
- 测试：`tests/test_documents_duplicate.py` 6 例（正文/标签/v1、标题递增、文件夹子树、跨区 404、viewer 403、原件文件新 key）；前端 `DocumentsPageDuplicate.test.tsx` 1 例。相关 70 例全绿。
- 已知边界：逐节点 `create_document` 落库，极端失败会留下部分副本（无跨节点事务）；需要严格原子时后续再收口。
- 提交 sha：52403b88。
