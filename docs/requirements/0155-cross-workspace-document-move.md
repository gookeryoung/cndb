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
| C2 | （范围） | 支持**单篇 / 多篇 / 文件夹**：文件夹按**子树整体**迁移（含其下文档、子文件夹与回收站中的子节点）；单次最多 200 个根节点；目标位置可选目标工作区的**任一文件夹或根目录**；回收站中的根节点（`is_deleted=1`）拒绝（400） | `documents` 插件 | 接口测试：单篇 / 多篇 / 文件夹子树 / 指定目标文件夹 / 根节点已删 400 |
| C3 | （权限） | **同口径**：源工作区需 `WRITE`（owner/editor，与删除文档一致）且每个根节点对调用者可见；目标工作区需 `WRITE`（owner/editor）且开启 `documents` 模块；不满足：源不足 403、目标不足 403、不可见 404、目标=源 400、目标父节点非法 400 | `documents` 插件 + `workspaces` 能力位 | 接口测试：四类角色 × 目标模块开关矩阵 |
| C4 | （不中断内容） | 移动保留：文档 id、全部版本（版本号 / 时间 / 作者 / 变更说明 / 外存内容）、状态（published/draft/archived）、标题、摘要、大纲、作者、排序以外的元数据 | `documents` 插件 | 接口测试：移动前后版本列表逐条一致、正文一致 |
| C5 | （站内文件） | **整棵子树**引用的站内文件（原件 `asset_file_key` + 所有版本正文里的 `file:<key>` + 草稿里的引用）一并从源工作区上传目录搬到目标工作区目录；`file_key` 保持不变（正文无需改写），`FileOwner.workspace_id` 改写为目标 | `files` 插件 + `documents` | 接口测试：移动后目标侧图片/原件可下载（200），源侧文件已不存在；正文 `file:` 引用仍可解析 |
| C6 | （对外面与待审稿） | **分享链接继续生效**（不撤销：token 指向文档本身，移动后按新工作区的文档可见性判定，旧链接依旧可访问已发布文档）；**修改申请随文档迁移**（`workspace_id` 改写为目标，状态 / 基准版本 / 提交人 / 评论全部保留，目标工作区 owner/editor 可继续评审） | `documents` 插件 | 接口测试：移动后旧分享 token 仍 200；申请 status 不变且出现在目标工作区列表 |
| C7 | （随行反馈） | 文档级问题清单（`DocumentIssue` + 评论 + 状态事件）随文档迁到目标工作区（`workspace_id` 改写），讨论与状态历史不丢 | `documents` 插件 | 接口测试：移动后目标工作区可读该问题与其评论 |
| C8 | （原子性） | 一次请求内的所有节点（含子树）**要么全部移动成功，要么完全不变**；不允许「部分节点移动」「文档已移动但图片丢」；配额不足在**写盘之前**阻断 | 全链路 | 故障注入测试（文件缺失 / DB 异常 / 配额不足）均无残留 |
| C9 | （可解释） | 移动结果返回：根节点 id 列表 / `target_workspace_id` / 迁移节点数 / 迁移文件数 / 迁移修改申请数 / 计入字节数；源、目标各写一条 `core_event`（`documents.move_out` / `documents.move_in`，不含正文） | `documents` + `core.events` | 接口测试：响应字段与事件行 |
| C10 | （存量不变 + 配额） | 不新增表 / 列，不改既有读写路径；未执行移动时全站行为与升级前逐条一致；**配额提前阻断**：目标工作区「已用 + 本次迁移字节 > 配额」时直接 413 并提示差额（与上传同一口径） | 全链路 | 存量用例全绿；配额不足 413 且无任何写入 |

非目标（本期不做，避免误期）：跨工作区「复制」（只做移动）、移动后自动重建 `[[双链]]` 与数据表引用、跨工作区审计合并、移动撤销（P1+ 再评估）。

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
- [x] ② 谁能移动：**同口径** —— 源 `WRITE` + 目标 `WRITE`，且目标开启文档模块（不新增能力位）。
- [x] ③（需求方回复）**分享链接继续生效**，不撤销。
- [x] ④（需求方回复）**修改申请随文档迁移**，不关闭。
- [x] ⑤ 问题清单：**随文档迁移**（讨论与状态历史保留）。
- [x] ⑥（需求方回复）**单文件 / 多文件 / 文件夹都支持**；目标可选工作区内任一文件夹或根目录。
- [x] ⑦（需求方回复）配额**提前阻断并提示**（413，写盘前判定）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方已确认 P0 范围（单/多/文件夹）、权限同口径、分享继续生效、申请迁移、配额提前阻断
