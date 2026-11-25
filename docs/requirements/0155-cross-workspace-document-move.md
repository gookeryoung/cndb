# 需求卡片：文档跨工作区移动

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0155（S2：跨权限边界的数据搬迁 + 站内文件迁移 + 分享/待审数据切断）
- 来源 / 提出人：用户（会话 2026-11-25）
- 日期：2026-11-25
- 关联 ADR：`docs/adr/0155-cross-workspace-document-move.md`（Proposed，待评审）

## 需求原句（逐字）

> 文档需实现跨工作区移动

## 可实施约束（C1..C10）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「文档」「移动」 | 新增**把一篇文档从源工作区迁到目标工作区**的能力：移动后文档只在目标工作区可见；源工作区列表 / 目录树 / 检索 / 详情 / 版本 / 导出一律 404（H33 / H17 同口径） | `documents` 插件 | 接口测试：移动后源侧全读路径 404、目标侧可读 |
| C2 | （范围） | P0 只支持**单篇文档**（含原件族 Word/PDF/Excel/PPTX/图片/MHTML）；文件夹子树、回收站中的文档不支持（400）；目标位置固定为目标工作区根目录（P1 再提供目标文件夹选择） | `documents` 插件 | 接口测试：文件夹 / 已删除文档 400 |
| C3 | （权限） | 源工作区需 `WRITE`（owner/editor，与删除文档同口径）且文档对调用者可见；目标工作区需 `WRITE`（owner/editor）且**目标开启 `documents` 模块**；不满足：源不足 403、目标不足 403、不可见 404、目标=源 400 | `documents` 插件 + `workspaces` 能力位 | 接口测试：四类角色 × 目标模块开关矩阵 |
| C4 | （不中断内容） | 移动保留：文档 id、全部版本（版本号 / 时间 / 作者 / 变更说明 / 外存内容）、状态（published/draft/archived）、标题、摘要、大纲、作者、排序以外的元数据 | `documents` 插件 | 接口测试：移动前后版本列表逐条一致、正文一致 |
| C5 | （站内文件） | 文档引用的站内文件（原件 `asset_file_key` + 所有版本正文里的 `file:<key>` + 草稿里的引用）一并从源工作区上传目录搬到目标工作区目录；`file_key` 保持不变（正文无需改写），文件归属行 `FileOwner.workspace_id` 改写为目标 | `files` 插件 + `documents` | 接口测试：移动后目标侧图片/原件可下载（200），源侧文件已不存在；正文 `file:` 引用仍可解析 |
| C6 | （切断跨边界的对外面） | 该文档的**访客分享链接全部撤销**（撤销后统一 404，H34 口径不变）；**open 状态的文档修改申请一律关闭**（备注「文档已移出工作区」、记录处理人），不再可能被合并进目标工作区 | `documents` 插件 | 接口测试：移动后旧分享 404；申请状态 closed |
| C7 | （随行反馈） | 文档级问题清单（`DocumentIssue` + 评论 + 状态事件）随文档迁到目标工作区（`workspace_id` 改写），讨论与状态历史不丢 | `documents` 插件 | 接口测试：移动后目标工作区可读该问题与其评论 |
| C8 | （原子性） | 要么完全落在目标工作区（文档可见、文件可读、源不再可见），要么完全不变；不允许「文档已移动但图片丢」「源删了目标没接住」 | 全链路 | 故障注入测试（文件缺失 / DB 异常）两次都回滚 |
| C9 | （可解释） | 移动结果返回：`document_id` / `target_workspace_id` / 迁移文件数 / 撤销分享数 / 关闭申请数；源、目标各写一条 `core_event`（`documents.move_out` / `documents.move_in`，不含正文） | `documents` + `core.events` | 接口测试：响应字段与事件行 |
| C10 | （存量不变） | 不新增表 / 列，不改既有读写路径；未执行移动时全站行为与升级前逐条一致（H13 / H14 不触发） | 全链路 | 存量用例全绿 |

非目标（本期不做，避免误期）：文件夹子树整体迁移、批量移动、跨工作区「复制」、移动后自动重建 `[[双链]]` 与数据表引用、跨工作区历史审计合并、移动撤销（P1+ 再评估）。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 文档本体（`workspace_id` / `parent_id` / `asset_file_key`） | `src/cndb/plugins/documents/models.py:76` | 移动即改 `workspace_id` 并把 `parent_id` 归零 |
| 2 | 版本与外存内容 | `documents/services/content.py:72`（`external_version_path` 按 **doc id** 落盘） | 保留 doc id → 历史版本零搬迁 |
| 3 | 站内文件（上传目录按工作区分区） | `files/services.py:64`（`resolve_workspace_file`） | `file_key` 不含工作区，跨区复制后同 key 仍可解析 |
| 4 | 全文检索 FTS | `documents/services/search.py`、`content.py:_fts_upsert_sql` | FTS 无 workspace 列，`rowid=doc_id`，过滤走 `documents` 表 |
| 5 | 访客分享 | `documents/models.py:208`（`DocumentShare`） | token 不绑工作区，必须显式撤销 |
| 6 | 修改申请 | `documents/models.py:270`（`DocumentChangeRequest.workspace_id`） | open 申请跨区合并会破坏基准，需关闭 |
| 7 | 文档问题清单 | `documents/models.py:345`（`DocumentIssue.workspace_id`） | 随文档改 `workspace_id` |
| 8 | 个人草稿 / 置顶 | `documents/models.py:233`、`:324` | 保留行（无权限者自然不可见） |
| 9 | 存储用量 / 配额 | `workspaces/services/storage_snapshot.py:157`（`refresh_workspace`） | 两侧标脏并刷新 |
| 10 | 权限判定 | `workspaces/permissions.py:37`（`WorkspaceCapability`）、`workspaces/modules.py::resolve_features` | 复用 `WRITE` + 模块开关，不新增能力位 |
| 11 | 审计 / 事件 | `core/events.py:139`（`record_event`） | 两侧各一条事件 |
| 12 | 备份 / 恢复 | `workspaces/services/backup_io.py` | 无 schema 变更；移动后源工作区备份自然不含该文档 |

## 未决问题

- [x] ① 真移动还是「复制 + 软删源」：**真移动**（保留 doc id 与版本链，外存内容按 doc id 落盘 → 历史版本零搬迁）。
- [x] ② 谁能移动：源 `WRITE` + 目标 `WRITE`，且目标开启文档模块（与「能删除 / 能新建文档」同口径，不新增能力位）。
- [x] ③ 分享链接：**全部撤销**（跨权限边界不静默续期）。
- [x] ④ 待审修改申请：**一律关闭**并记备注与处理人。
- [x] ⑤ 问题清单：**随文档迁移**（讨论与状态历史保留）。
- [x] ⑥ 目标位置：P0 固定根目录；目标文件夹选择与批量移动放 P1。
- [ ] ⑦ 目标工作区配额不足时是否阻断：建议**不阻断**（内部流转，配额仅统计口径），待确认。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] ⑥ / ⑦ 与 P0 范围（单文档、根目录、不含文件夹）确认
