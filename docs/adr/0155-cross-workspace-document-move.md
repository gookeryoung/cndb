# ADR 0155: 文档跨工作区移动（真移动 + 文件搬迁 + 对外面切断）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/documents/services/search.py`、`src/cndb/plugins/files/services.py`、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/modules.py`、`src/cndb/plugins/workspaces/services/storage_snapshot.py`、`src/cndb/core/events.py`、`frontend/src/pages/documents/DocumentEditorPage.tsx`
需求卡片: `docs/requirements/0155-cross-workspace-document-move.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；C1..C10 引用卡片编号，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「文档」「移动」 | `UPDATE documents_document.workspace_id`（保留 id）→ 源侧所有读路径因 `workspace_id` 过滤而自然 404，不新增可见性分支 |
| C2 | （范围） | 端点拒 `is_folder` / `is_deleted` / 落地子节点；`parent_id` 置 `NULL`（目标根目录）；P1 再开放 `parent_id` 入参 |
| C3 | （权限） | 源：`require_capability(WRITE)`（与删除文档一致）+ `get_visible_document_or_404`；目标：`require_capability(WRITE)` + `resolve_features(ws.modules)["documents"]`；目标=源 400 |
| C4 | （不中断内容） | 只改 `workspace_id` / `parent_id` / `sort_order` / `updated_*`；`DocumentVersion` 行与 `data/docs/{doc_id}/v*.md.gz` **原样保留**（外存路径按 doc id，与工作区无关） |
| C5 | （站内文件） | `services/move.py::collect_doc_file_keys` 扫 `asset_file_key` + 全部版本正文 + 草稿正文的 `file:<key>`；逐个 `copy` 到 `UPLOAD_DIR/{dst}/`，`FileOwner.workspace_id` 改目标，事务提交后再删源文件 |
| C6 | （切断对外面） | `DocumentShare` → `is_active=False`（保留审计痕迹）；`DocumentChangeRequest(status=open)` → `closed` + `review_comment="文档已移出工作区"` + `reviewed_by_id`/`reviewed_at` |
| C7 | （随行反馈） | `DocumentIssue.workspace_id` 与文档同步改写（评论 / 事件按 issue_id 级联，不动） |
| C8 | （原子性） | 顺序固定：**校验 → 复制文件（失败即整体失败，无 DB 写入）→ 单事务改 DB → 提交 → 删源文件（失败只告警，不影响结果）**；DB 异常回滚后清理已复制的目标文件 |
| C9 | （可解释） | 响应 `{document_id, target_workspace_id, moved_files, revoked_shares, closed_change_requests}`；`record_event("documents.move_out"/"move_in")` 两侧各一条 |
| C10 | （存量不变） | 无迁移、无新表 / 新列；不移动时行为逐条不变 |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 文档表以 `workspace_id` 为硬边界，所有读路径（列表 / 树 / 检索 / 详情 / 版本 / 导出 / 分享 / 修改申请）都按它过滤 | `documents/models.py:79`、`routers/documents.py`、`services/visibility.py` | 「改一列即完成移动」的前提成立；不需要逐路径改代码 | 确认（C1） |
| 2 | 外存版本内容按 **doc id** 落盘：`data/docs/{doc_id}/v{n}.md.gz` | `documents/services/content.py:72` | 保留 doc id 则历史版本零搬迁，版本号 / 时间 / 作者全保留 | 确认（C4） |
| 3 | 上传文件按工作区分区：`UPLOAD_DIR/{workspace_id}/<file_key>`，`file_key` **不含工作区** | `files/services.py:64` | 跨区只需 copy 同 key 文件，正文 `file:<key>` 无需改写（这是选「真移动」的关键前提） | 确认（C5） |
| 4 | 全文检索 FTS5 表 `documents_fts(rowid=doc_id, …)`，工作区过滤走 join `documents` | `documents/services/search.py:52`、`content.py:1021` | 移动后无需重建索引；仍主动 reindex 一次防历史脏行 | 确认 |
| 5 | 访客分享 `documents_share.token` 不携带工作区，读取按文档可见性 | `documents/models.py:208`、`routers/public.py` | 移动后分享会「跟着」文档进入新工作区的权限上下文 → 必须显式撤销 | 新增（C6） |
| 6 | 修改申请带 `workspace_id` 与 `base_version_number`，合并时校验基准 | `documents/models.py:270`、`services/change_requests.py` | 跨区保留 open 申请会产生「目标工作区里出现源工作区的待审稿」 | 新增（C6） |
| 7 | 文档问题清单 `documents_issue.workspace_id` + 评论 + 事件 | `documents/models.py:345` | 不迁移则问题留在源工作区却指向已移走的文档 | 新增（C7） |
| 8 | 个人草稿 / 置顶按 `(document_id, user_id)` | `documents/models.py:233`、`:324` | 保留行即可：无目标工作区权限者读不到，有权限者继续用 | 确认 |
| 9 | 存储用量快照按工作区聚合（含上传文件与正文外存） | `workspaces/services/storage_snapshot.py:157` | 移动后两侧都要刷新，否则配额展示漂移 | 新增 |
| 10 | 能力位已收敛（`READ`/`WRITE`/`EXPORT`/管理面），文档模块开关由 `resolve_features` 推导 | `workspaces/permissions.py:37`、`workspaces/modules.py:62` | 不新增能力位：移动 = 源 `WRITE` + 目标 `WRITE` + 目标模块开 | 确认（C3） |
| 11 | 文档删除只允许单篇 / 不含子树；回收站行 `is_deleted=1` | `routers/documents.py`（`delete` / `purge`） | 移动拒绝回收站行，与删除同口径 | 确认（C2） |
| 12 | 事件通道 `core_event` 已有 `record_event` | `core/events.py:139` | 复用，不建新审计表 | 确认（C9） |

**核心缺陷（需求要补的）**：工作区是硬数据边界（ADR 0153 保留），一篇文档**没有跨边界的合法搬迁通道**——用户只能「在目标工作区重建 + 源工作区删除」，版本历史、站内图片、问题讨论全部丢失。

设计目标（不变量）：

- **M1 原子性**：移动要么完整生效（文档与站内文件都可用、源侧不可见），要么完全不变；任何失败都不得留下「半移动」文档。
- **M2 权限不放大**：移动不新增任何可见性通路；源工作区成员在移动后对该文档一律 404，目标工作区成员按目标角色可见（H17 / H33 原文不变）。
- **M3 不静默外泄**：访客分享链接在移动时**全部撤销**；open 修改申请**全部关闭**；两者都不随文档进入新工作区。
- **M4 版本不断链**：文档 id、版本号、版本时间、作者、外存内容路径全部保持（用户看到的是「同一篇文档换了工作区」，不是副本）。
- **M5 存量不变**：无 schema 变更；不执行移动时全站行为与升级前逐条一致（H13 / H14 不触发）。

> 本 ADR 不新增跨需求长期不变量（M2 与既有 H15/H17/H33 同轴，M5 属常规回归要求），暂不登记 CONSTRAINTS；若评审要求登记，按 `ADR 0155 M1/M3` 补 H 条目（H27）。

## Decision

### 1. 数据模型

**无新表、无新列、无迁移**。移动只改现有行：

- `documents_document`：`workspace_id` → 目标；`parent_id` → `NULL`；`sort_order` → 目标工作区当前根节点最大值 +1；`updated_at` / `updated_by_id` 更新；`is_deleted` 必须为 0（前置校验）。其余列（`slug`、`content_type`、`asset_file_key`、`status`、`summary`、`toc_json`…）原样。
- `documents_issue`：`workspace_id` → 目标（仅该文档的 issue；评论 / 事件不动）。
- `files_fileowner`：该文档引用到的 `file_key` 行 `workspace_id` → 目标（`document_id` 不变）。
- `documents_share`：`is_active=False`（不删行，保留审计与 `view_count`）。
- `documents_changerequest`：`status=open` → `closed`，`review_comment` / `reviewed_by_id` / `reviewed_at` 填写。
- `documents_draft` / `documents_pin`：不动。

### 2. 判定算法（唯一入口）

新服务 `src/cndb/plugins/documents/services/move.py`：

```python
def move_document_to_workspace(
    db: Session, *, source_workspace_id: int, document_id: int,
    target_workspace_id: int, actor: User, parent_id: int | None = None,
) -> MoveResult:            # MoveResult: document_id / target_workspace_id / counts

def collect_doc_file_keys(db: Session, doc: Document) -> set[str]   # asset + 全版本正文 + 草稿正文
def preview_move(db, *, source_workspace_id, document_id, target_workspace_id, actor) -> MovePreview
```

权限与资格判定顺序（唯一实现，路由只调用）：

1. 源工作区存在且调用者是成员 → 否则 404（不泄露存在性）。
2. 文档对调用者可见（`visibility.get_visible_document_or_404`）→ 否则 404。
3. 源 `WRITE` → 否则 403（ADR 0047 文案）。
4. `target != source` → 否则 400；目标工作区存在且调用者是成员 → 否则 404。
5. 目标 `WRITE` → 否则 403。
6. 目标 `resolve_features(modules)["documents"]` 为真 → 否则 400（`目标工作区未启用文档模块`）。
7. `is_folder` 或 `is_deleted` → 400。
8. `parent_id`（P0 仅允许 `None`；P1 校验目标节点存在、属于目标工作区、是文件夹、未删除）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/documents/{doc_id}/move-to-workspace` | 新增：body `{target_workspace_id, parent_id?}`，返回 `{document_id, target_workspace_id, moved_files, revoked_shares, closed_change_requests}` |
| `GET  /api/v1/workspaces/{wid}/documents/{doc_id}/move-targets` | 新增：返回可移动目标工作区（`WRITE` 且有文档模块），供前端弹窗列举（避免前端猜权限） |

前端只调用这两个新端点；不使用既有 `PATCH /{doc_id}`（该端点只处理同工作区元数据）。

### 4. 边界与例外

1. **目标=源** → 400（`源工作区与目标工作区相同`）。
2. **文件夹 / 回收站文档 / 落地子节点** → 400（P0 范围）。
3. **目标工作区未启用文档模块** → 400。
4. **站内文件缺失**（磁盘上找不到被引用文件）：跳过该文件并计入 `missing_files` 返回，**不阻断移动**（与导出侧的降级口径一致：缺文件不该让整篇文档搬不走）。
5. **文件复制失败**（磁盘满 / 权限）：整体失败 500（or 409），DB 未改动。
6. **DB 提交失败**：回滚 + 清理已复制到目标目录的文件（避免目标工作区残留孤儿文件）。
7. **陈旧分享**：已过期的分享也一并置 `is_active=False`（幂等）。
8. **修改申请并发评审**：移动前先按 `document_id + status=open` 加锁式更新（`UPDATE … WHERE status='open'`），与评审写入串行，避免「移动后刚被合并」。
9. **草稿**：源工作区成员仍可在目标工作区无权限 → 草稿行保留但读不到；不迁移、不删除。
10. **配额**：移动计入目标工作区用量、从源工作区扣除；**超配额不阻断**（内部资源流转，配额是统计与提示口径，P0 确认项 ⑦）。
11. **原件族文档**：`asset_file_key` 同样走文件搬迁，`content_type` / `asset_mime` 不变。
12. **幂等**：重复提交同一移动请求，第二次因「文档已不在源工作区」→ 404，不产生副作用。

### 5. 迁移

无。无 schema 变更；存量数据零迁移。备份 / 恢复路径不变（移动后源工作区备份自然不含该文档，符合预期）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API | `frontend/src/api/documents.ts` | 新增 `moveToWorkspace(wid, docId, targetWorkspaceId)`、`moveTargets(wid, docId)` |
| 页面 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 顶栏「更多」菜单新增「移动到工作区」（owner/editor 且非文件夹可见）；弹窗列可移动目标（含模块/角色说明），二次确认文案明确「分享链接将失效、待审修改申请将关闭、源工作区成员将无法再访问」；成功后 `navigate` 到目标工作区文档页并提示 |
| 组件 | `frontend/src/pages/documents/MoveDocumentModal.tsx`（新增） | 目标选择 + 影响说明 + 提交态；无可用目标时展示原因（无编辑权限 / 未开文档模块） |

样式遵循 H24 / H25 / H29（token 取值、1px 中性线、无裸数值），弹层随文档页 lazy chunk（H31）。

### 7. 测试清单

**判定层（单测）**
- `collect_doc_file_keys`：asset + 多版本正文 + 草稿合并去重、非法 key 过滤。
- 资格判定 8 步逐条（源非成员 404 / 文档不可见 404 / 源 viewer 403 / 目标=源 400 / 目标非成员 404 / 目标 viewer 403 / 模块关闭 400 / 文件夹 400）。

**接口层**
- 正常移动：源侧列表 / 树 / 检索 / 详情 / 版本 / 导出全 404；目标侧均有；`document_id` 与版本列表逐条一致。
- 站内文件：移动后目标侧 `GET /{doc}/asset` 与正文图片可 200，源工作区上传目录不再存在该文件；`FileOwner.workspace_id` 已改写。
- 分享撤销：移动后旧 token 访问 404；`is_active=False`。
- 修改申请：open → closed，`review_comment` 为「文档已移出工作区」。
- 问题清单：随文档迁移，目标工作区可列出该 issue 与评论。
- 原件族（PDF / Word 存档）移动后仍可预览 / 下载。
- 目标工作区配额不足：仍成功（P0 口径）。
- 幂等：重复请求第二次 404。
- 审计：两侧 `core_event` 各一条，不含正文。

**迁移 / 备份**
- 无迁移；`make test` 存量用例全绿（H13 不触发）。
- 备份往返：移动后的目标工作区备份含该文档与文件，源工作区备份不含。

**前端单测**
- 无编辑权限 / 无可用目标时的入口隐藏与空态文案；二次确认文案含三项影响；提交成功后跳转目标工作区；失败展示后端 detail。

**e2e（前端）**
- 文档页 → 更多 → 移动到工作区 → 选目标 → 确认 → 落在目标工作区文档页，源工作区列表不再显示该文档。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `services/move.py` + 两个端点 + 文件搬迁 + 分享/申请切断 + 事件 + 单测/接口测试 | 中（跨工作区数据搬迁，靠「无 schema 变更 + 原子顺序」控风险） |
| **P1** | 前端入口与弹窗、目标文件夹选择、批量移动（多选文档） | 中 |
| **P2** | 移动撤销（记录 `moved_from_workspace_id` 轻量字段）/ 双链与数据表引用的跨区重解析评估 | 低（可选，待需求） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 移动语义 | **真移动**（保留 doc id、版本链、外存内容），不是「复制 + 软删源」 | 外存版本按 doc id 落盘、`file_key` 不含工作区 → 真移动代价低于复制；用户心智是「同一篇文档换位置」 | 复制 + 软删源（版本号 / 时间 / 问题讨论丢失，且源工作区留垃圾）；新建 + 重放版本（成本高、易出现版本号断档） | `services/move.py` |
| D2 | 权限口径 | 源 `WRITE` + 目标 `WRITE` + 目标开文档模块 | 与「能删文档 / 能建文档」同口径，不新增能力位（ADR 0153） | 仅 owner 可移动（过严，编辑者日常就在整理文档）；目标仅 owner 可接收（同上）；新增 `MOVE` 能力位（无必要，语义与 WRITE 重合） | `move.py` + `workspaces/permissions.py` |
| D3 | 目标位置 | P0 固定目标根目录，`parent_id` 置空 | 目标文件夹树结构 / 同名策略需要额外确认，先保证主链路 | 同步带 `parent_id`（源父节点在目标不存在，语义混乱）；自动重建同名文件夹（跨区结构映射规则未定） | `move.py`、`P1` |
| D4 | 分享链接 | **全部撤销**（`is_active=False`，不删行） | 分享是「对外」通道，跨权限边界必须失效（H34 同轴）；保留行便于审计与访问计数 | 保留分享（等于把源工作区批准的对外链接带进目标工作区的权限上下文）；删除行（丢审计痕迹） | `move.py` |
| D5 | 修改申请 | open → closed，备注「文档已移出工作区」 | 待审稿的基准版本属于源工作区上下文，跨区合并会产生越权写入 | 迁移申请（提交人无目标工作区权限，且 `base_version_number` 语义失效）；删除申请（丢用户劳动，无痕迹） | `move.py` |
| D6 | 问题清单 | 随文档迁移 | 讨论与状态历史是文档的一部分，留下会成为悬空引用 | 留在源工作区（指向已移走的文档）；删除（丢历史） | `move.py` |
| D7 | 站内文件策略 | 复制到目标工作区目录（同 `file_key`），提交后删源文件；缺失文件跳过并计数 | `file_key` 不含工作区 → 正文 `file:` 引用无需改写（避免了「改写全部历史版本正文」的高风险操作） | 改写正文为新区径（要动全部历史版本 + 草稿，风险与成本都高）；共享全局文件目录（破坏工作区目录隔离与配额统计） | `move.py`、`files/services.py` |
| D8 | 配额 | 不阻断（只统计） | 内部资源流转，不应因统计口径卡住业务 | 超配额拒绝（用户无法整理文档，且配额本为提示口径） | `move.py` |
| D9 | 配额/统计刷新 | 两侧 `storage_snapshot` 标脏并刷新 | 不刷新会让两侧用量与实际文件分布不一致 | 惰性等下一次全量刷新（期间展示错误） | `move.py` |
| D10 | 前端入口 | 文档页「更多 → 移动到工作区」+ 目标弹窗（后端返回可移动目标），二次确认列三项影响 | 一次性破坏性操作，必须在动作前把「分享失效 / 待审关闭 / 源成员失联」说清楚 | 列表页批量入口（P1）；直接输入目标 id（易误操作） | `MoveDocumentModal.tsx`、`DocumentEditorPage.tsx` |

## Consequences

- **正向**：文档第一次可以在工作区之间整体搬迁，版本历史、站内图片、问题讨论全部保留；源工作区不残留半成品；对外通道（分享 / 待审稿）在边界处被明确切断。
- **负向**：新增一条跨工作区写路径，需要严格的事务 / 文件顺序与失败回滚；`[[双链]]` 与 `{{table:…}}` 数据表引用属于工作区内语义，移动后会断（本期不自动修复，需在文档与前端提示中说明）。
- **风险与缓解**：文件搬迁是最大不确定项 → 先复制后提交 DB、失败清理、缺失文件降级计数；跨区误操作 → 二次确认 + 后端返回可移动目标（前端不猜权限）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 跨工作区只读共享 | `workspace_link`（ADR 0154） | 只读引用，不搬迁数据 | ADR 0154 |
| 跨工作区文档搬迁 | 本 ADR | 写路径，一次性移动所有权与文件 | ADR 0155 |
| 工作区硬边界与能力位 | `resolve_capabilities`（ADR 0153） | 移动只消费既有 `WRITE`，不新增能力位 | ADR 0153 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | `src/cndb/plugins/documents/services/move.py`、`src/cndb/plugins/documents/routers/documents.py` | `tests/test_document_cross_workspace_move.py` | — |
| P1 | 未开始 | `frontend/src/pages/documents/MoveDocumentModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/pages/documents/MoveDocumentModal.test.tsx` | — |

## 交接（会话结束更新）

- 当前阶段：方案评审（Proposed，等待人工确认 P0 范围、配额口径与「分享/申请切断」策略）
- 已完成：需求卡片 0155、本 ADR、现状核对（文档边界 / 外存内容 / 文件分区 / FTS / 分享 / 申请 / 问题清单 / 配额 / 能力位）
- 下一步：确认后按 P0（后端服务 + 端点 + 测试）→ P1（前端入口 + 弹窗 + e2e）实现
- 已知坑：① 外存版本按 doc id 落盘是「真移动」成立的关键，若将来改为按工作区分区需同步改本方案；② `file_key` 不含工作区，复制后同 key 可解析，**不要**顺手把 key 改成带工作区前缀（会破坏全部历史版本正文的 `file:` 引用）；③ 分享撤销后旧链接必须 404，前端提示文案要与 H34 口径一致；④ 移动后 `[[双链]]` / `{{table:}}` 引用会断，需在确认弹窗中提示「引用不会自动修复」
- 最近一次全绿：未开始实现
