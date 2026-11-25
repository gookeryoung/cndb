# ADR 0155: 文档跨工作区移动（子树 + 多选真移动、文件搬迁、分享保留、申请随行、配额先判）

Status: Accepted
Date: 2026-11-25
Related: `src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/documents/services/search.py`、`src/cndb/plugins/files/services.py`、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/workspaces/modules.py`、`src/cndb/plugins/workspaces/services/storage.py`、`src/cndb/plugins/workspaces/services/storage_snapshot.py`、`src/cndb/core/events.py`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`
需求卡片: `docs/requirements/0155-cross-workspace-document-move.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；C1..C10 引用卡片编号，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「文档」「移动」 | `UPDATE documents_document.workspace_id`（保留 id）→ 源侧所有读路径因 `workspace_id` 过滤而自然 404，不新增可见性分支 |
| C2 | （范围，需求方：单/多/文件夹都支持） | `POST …/move-to-workspace` 接 `document_ids[]`（1..200 根节点）；文件夹按**子树整体**迁移（含其下文档、子文件夹、回收站中的子节点）；根节点在回收站 → 400；目标位置 = 目标工作区任一文件夹或根目录 |
| C3 | （权限，同口径） | 源：`require_capability(WRITE)` + 每个根节点 `get_visible_document_or_404`；目标：`require_capability(WRITE)` + `resolve_features(modules)["documents"]` + 目标父节点必须是目标工作区的未删文件夹 |
| C4 | （不中断内容） | 只改 `workspace_id`、根节点 `parent_id`/`sort_order`、`updated_*`；`DocumentVersion` 行与 `data/docs/{doc_id}/v*.md.gz` **原样保留**（外存路径按 doc id，与工作区无关）；子节点 `parent_id` 不变 |
| C5 | （站内文件） | 扫**整棵子树**：`asset_file_key` + 全部版本正文 + 草稿正文里的 `file:<key>`；逐个 copy 到 `UPLOAD_DIR/{dst}/`（同 key），`FileOwner.workspace_id` 改目标，事务提交后删源文件 |
| C6 | （对外面与待审稿，需求方：分享保留、申请迁移） | `DocumentShare` **不动**（token 继续有效，按文档可见性判定）；`DocumentChangeRequest.workspace_id` → 目标（状态 / 基准 / 提交人 / 评论全保留） |
| C7 | （随行反馈） | 子树内文档的 `DocumentIssue.workspace_id` → 目标（评论 / 事件按 issue 级联，不动） |
| C8 | （原子性） | 顺序固定：**校验 → 配额预判 → 复制文件（失败即整体失败，无 DB 写入）→ 单事务改 DB（全部节点）→ 提交 → 删源文件（失败只告警）**；DB 异常回滚后清理目标侧已复制文件 |
| C9 | （可解释） | 响应 `{document_ids, target_workspace_id, moved_nodes, moved_files, moved_change_requests, moved_bytes}`；`record_event("documents.move_out"/"move_in")` 两侧各一条 |
| C10 | （存量不变 + 配额先判） | 无迁移、无新表 / 新列；不移动时行为逐条不变；`已用 + 本次字节 > 配额` → **413**（与上传同口径，写盘前） |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 文档表以 `workspace_id` 为硬边界，所有读路径按它过滤 | `documents/models.py:79`、`routers/documents.py`、`services/visibility.py` | 「改一列即完成移动」的前提成立 | 确认（C1） |
| 2 | 外存版本内容按 **doc id** 落盘：`data/docs/{doc_id}/v{n}.md.gz` | `documents/services/content.py:72` | 保留 doc id ⇒ 历史版本零搬迁，版本号 / 时间 / 作者全保留 | 确认（C4） |
| 3 | 上传文件按工作区分区：`UPLOAD_DIR/{workspace_id}/<file_key>`，**`file_key` 不含工作区** | `files/services.py:64` | 跨区只需 copy 同 key 文件，正文 `file:<key>` 无需改写（真移动成立的关键前提） | 确认（C5） |
| 4 | FTS5 表 `documents_fts(rowid=doc_id, …)`，工作区过滤走 join `documents` | `documents/services/search.py:52`、`content.py:1021` | 移动后无需重建；仍主动 reindex 一次防脏行 | 确认 |
| 5 | 访客分享 `documents_share.token` 只绑 `document_id`，读取按「已发布 + 文档可见性」 | `documents/models.py:208`、`routers/public.py` | token 不携带工作区 ⇒ **分享可继续生效**，无需改写 | 确认（C6，需求方要求保留） |
| 6 | 修改申请带 `workspace_id` 与 `base_version_number`，合并时按文档与基准校验 | `documents/models.py:270`、`services/change_requests.py` | 版本链不变 ⇒ 基准仍有效；只需 `workspace_id` 改目标 | 确认（C6，需求方要求迁移） |
| 7 | 文档问题清单 `documents_issue.workspace_id` + 评论 + 事件 | `documents/models.py:345` | 不迁移会留下悬空引用 | 新增（C7） |
| 8 | 个人草稿 / 置顶按 `(document_id, user_id)` | `documents/models.py:233`、`:324` | 行保留即可（无目标权限者读不到） | 确认 |
| 9 | 存储用量口径：附件 + 文档外存目录 + 内联正文/草稿 + 数据表行 | `workspaces/services/storage.py:134`、`:79`、`:157` | 迁移字节必须与同一口径对齐，否则 413 判定漂移 | 新增（C10） |
| 10 | 上传已有「写盘前配额预判 + 413」范式 | `tables/routers/files.py:275` | 移动沿用同款判定与文案 | 确认（C10） |
| 11 | 能力位已收敛，文档模块开关由 `resolve_features` 推导 | `workspaces/permissions.py:37`、`workspaces/modules.py:62` | 不新增能力位：移动 = 源 `WRITE` + 目标 `WRITE` + 目标模块开 | 确认（C3） |
| 12 | 事件通道 `core_event` 已有 `record_event` | `core/events.py:139` | 复用，不建新审计表 | 确认（C9） |

**核心缺陷（需求要补的）**：工作区是硬数据边界（ADR 0153 保留），一篇文档**没有跨边界的合法搬迁通道**——用户只能「在目标工作区重建 + 源工作区删除」，版本历史、站内图片、问题讨论全部丢失。

设计目标（不变量）：

- **M1 原子性**：一次请求内的所有节点（含子树）要么全部移动成功，要么完全不变；任何失败不得留下「半移动」文档。
- **M2 权限不放大**：移动不新增可见性通路；源工作区成员移动后对该文档一律 404，目标成员按目标角色可见（H17 / H33 原文不变）。
- **M3 对外面与待审稿随文档走**：访客分享链接保持有效（不撤销、不改 token）；修改申请随文档迁入目标工作区（状态与基准不变）。
- **M4 版本不断链**：文档 id、版本号、版本时间、作者、外存内容路径全部保持。
- **M5 存量不变**：无 schema 变更；不执行移动时行为与升级前逐条一致（H13 / H14 不触发）。
- **M6 配额先判**：迁移字节在写盘前与目标配额比对，超限直接 413，不留任何写入。

> M2 与既有 H15/H17/H33 同轴，M5 属常规回归要求；若评审要求登记，按 `ADR 0155 M1/M3` 补 CONSTRAINTS 条目（H27）。

## Decision

### 1. 数据模型

**无新表、无新列、无迁移**。移动只改现有行：

- `documents_document`：**整棵子树**（根 + 全部后代，含 `is_deleted=1` 的子节点）`workspace_id` → 目标；根节点 `parent_id` → 请求的 `parent_id`（默认 `NULL` = 根目录）、`sort_order` → 目标父节点下最大值 +1（多个根依次递增）；`updated_at` / `updated_by_id` 更新；其余列（`slug`、`content_type`、`asset_file_key`、`status`、`summary`、`toc_json`…）原样；子节点 `parent_id` 不变。
- `documents_issue`：子树内文档的 issue `workspace_id` → 目标（评论 / 事件不动）。
- `files_fileowner`：子树内文档引用到的 `file_key` 行 `workspace_id` → 目标（`document_id` 不变）。
- `documents_changerequest`：子树内申请的 `workspace_id` → 目标（`status` / `stale` / `base_version_number` / `submitted_by` / `review_*` 全保留）。
- `documents_share`：**不动**（token 继续有效）。
- `documents_draft` / `documents_pin`：不动。

### 2. 判定算法（唯一入口）

新服务 `src/cndb/plugins/documents/services/move.py`：

```python
def resolve_move_roots(db, *, source_workspace_id: int, root_ids: list[int], actor: User) -> list[Document]
    # 可见 / 未删 / 去重 / 去嵌套（父与子同时选中时只保留祖先）
def collect_subtree(db, roots: list[Document]) -> list[Document]     # 根 + 全部后代（含回收站子节点）
def collect_file_keys(db, nodes: list[Document]) -> set[str]         # asset + 全版本正文 + 草稿正文
def move_size_bytes(db, nodes: list[Document], file_keys: set[str]) -> int   # 与 workspace_storage_bytes 同口径
def move_nodes_to_workspace(db, *, source_workspace_id, root_ids, target_workspace_id,
                            actor, parent_id=None) -> MoveResult
def move_targets(db, *, source_workspace_id, actor) -> list[MoveTarget]
```

判定顺序（唯一实现，路由只调用）：

1. 源工作区存在且调用者是成员 → 否则 404（不泄露存在性）。
2. 每个根节点对调用者可见 → 否则 404（不区分「不存在」与「无权限」）。
3. 源 `WRITE` → 否则 403（ADR 0047 文案）。
4. `target != source` → 否则 400；目标工作区存在且调用者是成员 → 否则 404。
5. 目标 `WRITE` → 否则 403。
6. 目标 `resolve_features(modules)["documents"]` 为真 → 否则 400。
7. 根节点 `is_deleted` → 400（回收站中的节点先恢复再移动）。
8. `root_ids` 去重、去嵌套；空 / >200 → 400。
9. `parent_id` 为空 = 根目录；非空必须存在、属于目标工作区、`is_folder=1`、`is_deleted=0`。
10. 配额：`snapshot_used(target, lazy=True) + moved_bytes > workspace_quota_bytes(target)` → **413**（文案含已用 / 配额 / 本次大小）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/documents/move-to-workspace` | 新增：body `{document_ids: int[], target_workspace_id, parent_id?}` → `{document_ids, target_workspace_id, moved_nodes, moved_files, moved_change_requests, moved_bytes, missing_files}`；**静态段路由注册在 `/{doc_id}` 之前** |
| `GET  /api/v1/workspaces/{wid}/documents/move-targets` | 新增：可移动目标工作区（`WRITE` + 文档模块开 + 剩余配额），同样注册在 `/{doc_id}` 之前 |

### 4. 边界与例外

1. **目标=源** → 400（`源工作区与目标工作区相同`）。
2. **根节点在回收站** → 400；`document_ids` 空 / >200 / 含非本工作区 id → 400 或 404（不可见统一 404）。
3. **目标工作区未启用文档模块** → 400。
4. **站内文件缺失**：跳过并计入 `missing_files` 返回，不阻断移动（与导出降级同口径）。
5. **文件复制失败**（磁盘满 / 权限）：整体失败，DB 未改动。
6. **DB 提交失败**：回滚 + 清理目标侧已复制文件（不留孤儿）。
7. **分享保持有效**：token 与 `is_active` 不动；移动后仍按「已发布 + 文档可见性」判定（H34 不变）。
8. **修改申请并发评审**：事务内先 `UPDATE … WHERE document_id IN (子树) AND status='open'` 改 `workspace_id`，与评审写入串行。
9. **草稿**：行保留（不迁移、不删除）；源成员在目标无权限时读不到，目标成员按个人草稿继续可用。
10. **配额**：迁移字节（站内文件 + 外存目录 + 内联正文 + 草稿）计入目标；写盘前预判，不足 → 413 并提示差额（M6）。
11. **原件族文档**：`asset_file_key` 同样搬迁，`content_type` / `asset_mime` 不变。
12. **幂等**：重复提交同一请求，第二次因「文档已不在源工作区」→ 404，不产生副作用。

### 5. 迁移

无。无 schema 变更；存量零迁移。备份 / 恢复路径不变（移动后源工作区备份自然不含该文档）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API | `frontend/src/api/documents.ts` | 新增 `moveToWorkspace(wid, payload)`、`moveTargets(wid)` |
| 组件 | `frontend/src/pages/documents/MoveDocumentModal.tsx`（新增） | 目标工作区 + 目标文件夹（可选，懒加载该工作区文档树）+ 影响说明（节点数 / 含子树 / 配额余量 / 「分享链接继续有效」「修改申请随文档迁移」「双链与数据表引用不会自动修复」）+ 提交态；无可用目标时展示原因；413 展示后端 detail |
| 页面 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 「更多」菜单新增「移动到工作区」（owner/editor 可见，文件夹亦可）；成功后跳转目标工作区 |
| 页面 | `frontend/src/pages/documents/DocumentsPage.tsx` | 多选批量操作新增「移动到工作区」（与「移动 / 删除」并列），复用同一弹窗 |

样式遵循 H24 / H25 / H29（token 取值、1px 中性线、无裸数值），弹层随文档页 lazy chunk（H31）。

### 7. 测试清单

**判定层（单测）**
- `collect_subtree`：根 + 后代（含回收站子节点）、去嵌套、去重。
- `collect_file_keys`：asset + 多版本正文 + 草稿合并去重、非法 key 过滤。
- `move_size_bytes`：与 `workspace_storage_bytes` 口径一致（文件 + 外存目录 + 内联正文/草稿）。
- 资格判定逐条：源非成员 404 / 节点不可见 404 / 源 viewer 403 / 目标=源 400 / 目标非成员 404 / 目标 viewer 403 / 模块关闭 400 / 根节点在回收站 400 / 目标父节点非法 400 / 空 ids 400 / >200 400。

**接口层**
- 正常移动（单篇 / 多篇 / 文件夹子树 / 指定目标文件夹）：源侧列表 / 树 / 检索 / 详情 / 版本 / 导出全 404；目标侧均有；`document_id` 与版本列表逐条一致；子树 `parent_id` 结构完整。
- 站内文件：移动后目标侧 `GET /{doc}/asset` 与正文图片可 200，源工作区上传目录不再存在该文件；`FileOwner.workspace_id` 已改写。
- 分享继续生效：移动后旧 token 仍 200（已发布文档）；草稿文档访问仍 404（H34 口径）。
- 修改申请迁移：`workspace_id` 变目标、`status` / `base_version_number` 不变，且出现在目标工作区申请列表；源工作区列表不再出现。
- 问题清单：随文档迁移，目标工作区可列出该 issue 与评论。
- 原件族（PDF / Word 存档）移动后仍可预览 / 下载。
- 配额不足：**413** 且无任何写入（源文档仍在、目标无新增文件）。
- 幂等：重复请求第二次 404。
- 审计：两侧 `core_event` 各一条，不含正文。

**迁移 / 备份**
- 无迁移；`make test` 存量用例全绿（H13 不触发）。
- 备份往返：移动后的目标工作区备份含该文档与文件，源工作区备份不含。

**前端单测**
- 无编辑权限 / 无可用目标时的入口隐藏与空态文案；影响说明含「分享继续有效 / 申请随文档迁移 / 引用不自动修复」；多选批量入口；提交成功后跳转 / 刷新；413 展示后端 detail。

**e2e（前端）**
- 文档页 → 更多 → 移动到工作区 → 选目标 → 确认 → 落在目标工作区文档页，源工作区列表不再显示；列表页多选两篇 → 批量移动 → 目标侧出现两篇。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `services/move.py`（子树 / 多选 / 文件 / 申请迁移 / 配额预判）+ 两个端点 + 事件 + 单测 / 接口测试 | 中（跨区搬迁，靠「无 schema 变更 + 原子顺序 + 配额先判」控风险） |
| **P1** | 前端弹窗 + 单篇 / 批量入口 + 目标文件夹选择 + e2e | 中 |
| **P2** | 移动撤销（轻量记录来源工作区）/ 双链与数据表引用的跨区重解析评估 | 低（可选，待需求） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 移动语义 | **真移动**（保留 doc id、版本链、外存内容），不是「复制 + 软删源」 | 外存版本按 doc id 落盘、`file_key` 不含工作区 → 真移动代价低于复制；用户心智是同一篇文档换位置 | 复制 + 软删源（版本号 / 时间 / 讨论丢失，源工作区留垃圾）；新建 + 重放版本（成本高、版本号断档） | `services/move.py` |
| D2 | 权限口径 | 源 `WRITE` + 目标 `WRITE` + 目标开文档模块 | 与「能删文档 / 能建文档」同口径，不新增能力位 | 仅 owner 可移动（过严）；新增 `MOVE` 能力位（与 WRITE 重合） | `move.py` + `workspaces/permissions.py` |
| D3 | 移动范围与目标位置 | 单篇 / 多篇 / 文件夹（子树整体）；`document_ids[]` 1..200；目标可选任一层文件夹或根目录 | 需求方明确要求三种都支持；子树整体迁移避免「文件夹搬走、内容留下」 | 只支持单篇（需求方否决）；不带子树（数据不完整）；自动重建来源路径（跨区映射规则未定） | `move.py` |
| D4 | 分享链接 | **保持有效**（token / `is_active` 不动） | 需求方要求；token 只绑 doc id，移动后仍按文档可见性判定（H34 不变） | 全部撤销（需求方否决：外部读者链接突然失效）；换新 token（同理失效） | `move.py`（不改动） |
| D5 | 修改申请 | **随文档迁移**（`workspace_id` 改写，状态 / 基准 / 提交人 / 评论保留） | 需求方要求；版本链不变 ⇒ `base_version_number` 语义仍有效 | 全部关闭（需求方否决：待审稿被丢弃）；删除（丢用户劳动） | `move.py` |
| D6 | 问题清单 | 随文档迁移 | 讨论与状态历史属于文档 | 留在源工作区（悬空引用）；删除（丢历史） | `move.py` |
| D7 | 站内文件策略 | 复制到目标工作区目录（同 `file_key`），提交后删源文件；缺失文件跳过计数 | `file_key` 不含工作区 ⇒ 正文无需改写（避免改写全部历史版本正文的高风险操作） | 改写正文为新区径（要动全部版本 + 草稿）；共享全局文件目录（破坏分区与配额） | `move.py`、`files/services.py` |
| D8 | 配额 | **写盘前预判并阻断**：`已用 + 本次 > 配额` → 413，文案含已用 / 配额 / 本次大小 | 需求方要求提前阻断；超配额写入会让目标用量失真且难回收 | 不阻断（需求方否决）；写盘后回滚（浪费 IO、可能残留） | `move.py` |
| D9 | 统计刷新 | 两侧 `storage_snapshot` 标脏并刷新 | 不刷新会让两侧用量与实际文件分布不一致 | 惰性等下一次全量刷新（期间展示错误） | `move.py` |
| D10 | 前端入口 | 文档页「更多 → 移动到工作区」+ 文档列表多选「移动到工作区」，共用同一弹窗；二次确认列影响 | 移动是破坏性操作，动作前必须把「搬什么、什么会变、什么不会」说清 | 只做单篇入口（需求方要求多文件）；直接输入目标 id（易误操作） | `MoveDocumentModal.tsx`、`DocumentEditorPage.tsx`、`DocumentsPage.tsx` |
| D11 | 子树与回收站 | 子树内 `is_deleted=1` 的子节点一并迁移（树完整，目标回收站可见）；**根节点**在回收站则 400 | 需求方要求文件夹整体迁移；拆开迁会留「文件夹走了、删掉的还在源」 | 丢弃回收站子节点（丢数据）；连回收站一起拒绝（用户需先清空） | `move.py` |

## Consequences

- **正向**：单篇 / 多篇 / 整棵文件夹可在工作区之间整体搬迁，版本历史、站内图片、问题讨论、待审修改申请全部保留；对外分享链接不中断；源工作区不残留半成品；配额在写盘前把关。
- **负向**：新增一条跨工作区写路径（支持子树批量），事务 / 文件顺序 / 配额预判都必须严格；`[[双链]]` 与 `{{table:…}}` 引用属于工作区语义，移动后会断（本期不自动修复，前端提示）。
- **风险与缓解**：文件搬迁是最大不确定项 → 先复制后提交、失败清理、缺失文件降级计数；跨区误操作 → 二次确认 + 后端返回可移动目标与配额余量。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 跨工作区只读共享 | `workspace_link`（ADR 0154） | 只读引用，不搬迁数据 | ADR 0154 |
| 跨工作区文档搬迁 | 本 ADR | 写路径，一次性移动所有权与文件（保留分享与待审稿） | ADR 0155 |
| 工作区硬边界与能力位 | `resolve_capabilities`（ADR 0153） | 只消费既有 `WRITE`，不新增能力位 | ADR 0153 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/move.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/schemas/__init__.py` | `tests/test_document_cross_workspace_move.py` | 见「交接」回填 |
| P1 | 已落地 | `frontend/src/pages/documents/MoveDocumentModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/api/documents.ts` | `frontend/src/pages/documents/MoveDocumentModal.test.tsx`、`frontend/src/pages/documents/DocumentsPage.test.tsx`、`frontend/tests/e2e/critical/document-move-workspace.spec.ts` | 见「交接」回填 |

## 交接（会话结束更新）

- 当前阶段：P0 + P1 全部落地（2026-11-25，本地提交待推送）
- 已完成：需求卡片 0155、本 ADR、现状核对（文档边界 / 外存内容 / 文件分区 / FTS / 分享 / 申请 / 问题清单 / 配额口径 / 能力位）
- 下一步：人工验收后 `make push`（H4 / H6）；P2（移动撤销 / 双链跨区重解析）按需单独立项
- 已知坑：① 外存版本按 doc id 落盘是「真移动」成立的关键；② `file_key` 不含工作区，复制后同 key 可解析，**不要**把 key 改成带工作区前缀（会破坏全部历史版本正文的 `file:` 引用）；③ 分享**不撤销**：token 仍指向文档，移动后按新工作区文档可见性判定（H34 不变），不要顺手加 workspace 过滤；④ 移动后 `[[双链]]` / `{{table:}}` 会断，需在弹窗提示；⑤ 子树迁移要连回收站子节点一起搬（根节点在回收站则 400）；⑥ 配额口径必须与 `workspace_storage_bytes` 完全一致，否则 413 判定会漂移
- 最近一次全绿：后端 7529 passed（含新增 20 例）、前端 `MoveDocumentModal` 7 例 + `DocumentsPage`/`DocumentEditorPage` 回归全绿、e2e `document-move-workspace.spec.ts` 3 passed、`bundle-budget` 在预算内 @ 本地 2026-11-25
