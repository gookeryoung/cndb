# 文档编辑流程与权限控制

> 适用范围：`documents`、`change_requests` 插件中「文档」相关的读写、草稿、修改申请、协作者授权、发布与分享。
> 后端入口 `src/cndb/plugins/documents/`，前端入口 `frontend/src/pages/documents/`。
> 本文以代码为准，描述当前实现（非规划）。

---

## 1. 角色与通用开关

工作区成员角色从高到低三级（`src/cndb/plugins/workspaces/models.py` 的 `WorkspaceRole`）：

| 角色 | 说明 |
|---|---|
| `owner` | 工作区所有者：设置、成员管理、文档可见性管理的最高权限 |
| `editor` | 编辑者：可写文档/数据，受 `allow_edit` 开关影响 |
| `viewer` | 查看者：只读；写文档正文一律转「修改申请」 |

判定函数：`get_member_role(user, workspace, db)`（`workspaces/permissions.py`，非成员返回 `None`）。

**工作区级开关 `Workspace.allow_edit`**（默认 `true`，注释「是否允许成员（EDITOR 及以下）编辑数据」）：关闭后，`editor` 的正文保存也转为修改申请。

**文档可见性管理员 `is_document_admin`**：超级用户或该工作区 `OWNER`，可看到全部状态的文档（含他人草稿），用于审阅与清理。

---

## 2. 文档状态与可见性

`Document.status ∈ {draft, published, archived}`（默认 `draft`），`is_folder` 区分文档与文件夹。

**可见性规则**（`documents/services/visibility.py`，`PUBLIC_STATUSES = (published,)`）：

| status | 谁可见 |
|---|---|
| `published` | 该工作区**全部成员**（成员身份已在路由层校验） |
| `draft` | **创建者本人** + 工作区 `OWNER` / 超管 + **被显式授权的协作者** |
| `archived` | 同 `draft`（已下线内容不再向普通成员扩散） |

设计取舍：

- **不可见即 404**（而非 403）：不泄露「存在这样一份草稿」；`get_visible_document_or_404` 是统一入口。
- 结构文件夹不单独授权：只要其**任一可见后代**可见，就补链展示祖先（`visible_ancestor_ids`），避免目录树出现孤儿节点。
- 读取收口：列表 / 目录树 / 全文检索 / 详情 / 版本 / 差异 / 导出 / 反链 / 回收站 / 文档问题清单全部按同一可见性条件过滤，避免逐端点各写一遍导致遗漏。检索走 `services/search.py`，SQL 条件为 `is_deleted=0 AND (status=published OR created_by=me OR 已授权)`。
- 文档树缓存**按用户隔离**，写请求 / 协作者授权后失效（`invalidate_document_tree_cache`）。

---

## 3. 写模式分派（双轨制）

文档正文写入与数据表同源分派，三态（`documents/services/change_requests.py`）：

| 写模式 | 判定 | 效果 |
|---|---|---|
| `direct` | `owner` 恒直编；`editor` 且 `allow_edit` 开启 | 直接落库为新版本 |
| `change_request` | `viewer`，或 `allow_edit` 关闭的 `editor` | 生成待审修改申请（正文不落库） |
| `denied` | 非工作区成员 | 403 |

- `resolve_write_mode(db, workspace_id, user)`：工作区级判定。
- `resolve_document_write_mode(db, workspace_id, doc_id, user)`：在工作区策略上**叠加文档级 `editor` 授权**——被创建者/所有者授予 `editor` 的协作者可直编该文档，但**仅对未发布文档生效**（`document_permissions.is_editor_granted` 内部判断），已发布内容仍走 `allow_edit` / 修改申请流程，避免绕过审核。

---

## 4. 编辑流程

### 4.1 个人草稿（保存与提交解耦）

产品语义：**保存只写草稿，提交才生效**。表 `documents_draft`，每位用户对每篇文档至多一份，**仅本人可读写，管理员也看不到他人草稿**（`documents/services/drafts.py`）。

| 动作 | 端点 | 行为 |
|---|---|---|
| 读草稿 | `GET /{wid}/documents/{doc_id}/draft` | 无草稿或草稿与最新版本一致时返回 `draft=null` |
| 保存草稿 | `PUT /{wid}/documents/{doc_id}/draft` | 只写草稿表；与最新版本一致时**删除草稿**并返回 `draft=null` |
| 丢弃草稿 | `DELETE /{wid}/documents/{doc_id}/draft` | 幂等 |
| 显式提交 | `POST /{wid}/documents/{doc_id}/submit` | 直编落库为新版本，否则生成修改申请 |

关键规则：

- **基准版本 `base_version_number`**：记录开始编辑时所基于的版本（0 = 空文档）；保存时 `base > 最新版本` 返回 400。
- **未修改不可提交**：正文与最新版本一致时返回 409（`code=no_changes`），前端据此禁用「保存 / 提交」按钮。
- **提交时基准过期**：直编路径若 `base < 最新版本` 返回 409（`code=stale_version`），要求刷新后重新编辑，避免覆盖他人已保存的修改。

### 4.2 保存路径（保留的「保存即提交」兼容入口）

`PUT /{wid}/documents/{doc_id}/content`（`routers/documents.py`）：

- 先按 `resolve_write_mode` + 文档级 `editor` 授权分派；
- `change_request`：调用 `create_request` 生成申请，返回 **202 + 申请载荷（含 DIFF）**，正文不落库，并清理个人草稿；
- `direct`：`update_content` 落库为新版本（乐观锁：`base_updated_at` 失配返回 409），并清理个人草稿。

### 4.3 版本写入（`services/content.py#update_content`）

- `enforce_role`：路由层默认校验工作区写权限；仅「已单独特判过文档级 editor 授权」的内部提交路径（`submit_draft`）传 `False`。
- 正文与最新版本哈希一致时不创建新版本。
- 落库会刷新元数据（作者 / 摘要 / 目录）并同步 FTS5 索引。
- 并发保存（同 `version_number` 唯一约束竞争）转 409（`code=doc_version_conflict`）。
- **新版本落地后**：同文档其它 `open` 修改申请自动置 `stale`（`mark_open_requests_stale`）。

### 4.4 前端交互（`frontend/src/pages/documents/DocumentEditorPage.tsx`）

- **查看 / 编辑双模式**（`doc-mode-switch`）：默认模式 = 有个人草稿或未发布（`draft`）文档 → **编辑**；已发布 / 归档且无草稿 → **查看**。
- **保存草稿**：`Ctrl+S` / 「保存草稿」按钮，只调 `PUT /draft`，不产生版本、不触发审核。
- **切换查看模式**：若有未保存到草稿的改动，先自动落草稿（不提交、不影响版本）。
- **未保存 / 未提交提示**：`hasUnsaved`（与已保存内容比）→ 顶部「未保存」；`hasChanges`（与最新版本比）→ 决定保存 / 提交按钮可用性。
- **提交修改**：弹确认框（`doc-submit-summary` 可填变更说明）。直编 → 生成新版本并回查看模式；转申请 → 提示已提交审核、正文回到当前发布版。
- **发布 / 转为草稿**：工具栏 `doc-publish-toggle`（后端 `PATCH /{doc_id}` 改 `status` 需 **editor+**）。
- **修改申请入口**：工具栏徽标显示本文件待审核条数，抽屉展开列表 + 内容 DIFF。

---

## 5. 修改申请生命周期

表 `documents_change_request`（`documents/services/change_requests.py`）。状态 `open` / `merged` / `closed`。

| 操作 | 端点（`/{wid}/document-change-requests`） | 权限 |
|---|---|---|
| 列表 | `GET ""`（`document_id` / `scope` = open/merged/closed/mine/all） | 工作区成员；仅列「我能看见的文档」的申请 |
| 手动发起 | `POST ""` | 成员 |
| 详情 | `GET /{id}`（含 DIFF 与待审正文） | 成员 + 文档可见 |
| 通过 | `POST /{id}/merge` | **owner / editor** |
| 驳回 / 关闭 | `POST /{id}/close` | **owner / editor 或提交人本人** |
| 刷新基准 | `POST /{id}/update-base` | **仅提交人本人** |
| 删除草稿 | `DELETE /{id}` | **提交人本人或 owner；仅 `open`** |

关键规则：

- `proposed_content` 只存待审全文，**不写 `document_versions`**；`merge` 通过后才生成新版本。
- `base_version_number` 为内容基准；文档版本前进后其余 `open` 申请置 `stale`（卡片显示「基准已过期」）。
- `merge` 时若 `current != base` → 置 `stale` 并返回 409（`code=document_change_request_stale`），要求先刷新基准或重新提交。
- `merge` / 读取均受**文档可见性**约束：看不见该文档（含他人草稿）的人无法读到它的申请（404）。
- `close` / `delete` 仅对 `open` 申请生效；已 `merged` / `closed` 的申请保留作处理留痕。

前端：`ChangeRequestCard.tsx`（通过 / 驳回 / 刷新基准 / 删除草稿 + 内容 DIFF）、`DocumentChangeRequestsDrawer.tsx`（单文档视角，按钮按 `role` 与提交人身份显示）、`DocumentsChangeRequestsPage.tsx`（工作区级列表）。

---

## 6. 文档级协作者授权

表 `documents_permission`（`(document_id, user_id) -> role`），用于把**未发布草稿**开放给指定同事（`documents/services/document_permissions.py`）。

| 角色 | 效果 |
|---|---|
| `viewer` | 可读该文档（含 `draft` / `archived`）；写入仍按工作区策略（viewer → 修改申请） |
| `editor` | 可读 + 可**直接编辑**该文档内容；**仅对未发布文档生效**（已发布仍按工作区 `allow_edit` / 修改申请） |

- **管理权限 `can_manage`**：文档创建者 / 工作区 `OWNER` / 超管。`require_can_manage` 用于授权与撤销。
- **被授权者**：必须是该工作区成员；不能给自己授权；文档创建者本身已可见，无授权。
- 端点：`GET /{doc_id}/permissions`（能看见该文档的成员均可读名单）、`POST`（授权）、`DELETE /{doc_id}/permissions/{user_id}`（撤销）。
- 授权后：失效文档树缓存并**通知被授权者**（best-effort）。
- 前端：`DocumentCollaboratorsModal.tsx`（选择工作区成员 + 「只读 / 可编辑」）。

---

## 7. 分享与公开访问

- **仅已发布文档可创建分享**：`POST /{wid}/documents/{doc_id}/share` 要求 **editor+**，且 `status == published`，否则 409（避免把未发布内容放给外部）。支持密码与过期时间。
- **匿名访问**（`routers/public.py`，无需登录）：`GET /api/v1/documents/share/{token}`（有密码返回 401 提示）、`POST`（校验密码）、`GET /{token}/meta`。
- **未发布即失效**：草稿 / 归档文档，或「分享后取消发布」的文档，其分享链接访问一律 404（`分享链接已失效`）；撤销的链接同样失效。
- 访问计数累加；返回体脱敏去除 `created_by_id` / `updated_by_id`。

---

## 8. 权限矩阵（文档相关动作）

| 动作 | owner | editor | viewer | 备注 |
|---|---|---|---|---|
| 查看已发布文档 | ✅ | ✅ | ✅ | 全部成员 |
| 查看草稿 / 归档 | ✅ | 仅创建者或被授权者 | 仅创建者或被授权者 | 创建者本人始终可见；owner 全量 |
| 创建文档 / 文件夹 | ✅ | ✅ | ❌ | `require_editor` |
| 保存个人草稿 | ✅ | ✅ | ✅ | 仅本人可读写，需能看见该文档 |
| 直接落库新版本 | ✅ | 需 `allow_edit`；或被授予文档级 `editor`（仅未发布） | ❌ | |
| 生成 / 发起修改申请 | ✅ | ✅ | ✅ | 成员即可 |
| 通过修改申请 | ✅ | ✅ | ❌ | `_require_reviewer` |
| 驳回 / 关闭申请 | ✅ | ✅ | 提交人本人 | |
| 刷新基准 | 提交人本人 | 提交人本人 | 提交人本人 | 仅 `open` |
| 删除草稿（申请） | ✅ 或提交人本人 | 提交人本人 | 提交人本人 | 仅 `open` |
| 管理协作者 | ✅（含超管） | 仅文档创建者 | 仅文档创建者 | `can_manage` |
| 发布 / 转为草稿 | ✅ | ✅ | ❌ | `PATCH /{doc_id}` 需 editor+ |
| 创建分享 | ✅ | ✅ | ❌ | 且仅已发布 |
| 软删除 / 恢复 / 彻底删除 / 回滚 / 断链修复 | ✅ | ✅ | ❌ | editor+ |
| 导出（md/docx/pdf） | ✅ | ✅ | ✅ | 工作区成员即可 |

> 说明：编辑器前端「发布」按钮不区分角色（`editable` 恒为 true，方便 viewer 走 202 提交路径），真正的权限由后端 `PATCH` / 分享端点的 `require_editor` 兜底。

---

## 9. 端点速查

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/{wid}/documents` | GET | 成员 | 列表（按可见性过滤；支持 `parent/status/tag`） |
| `/{wid}/documents` | POST | editor+ | 创建文档 / 文件夹（`status` 默认 draft） |
| `/{wid}/documents/tree` | GET | 成员 | 目录树（按用户隔离缓存） |
| `/{wid}/documents/search` | GET | 成员 | FTS5 全文检索（按可见性过滤） |
| `/{wid}/documents/{doc_id}` | GET | 成员 + 可见 | 详情（不含正文） |
| `/{wid}/documents/{doc_id}` | PATCH | editor+ | 改元数据（标题 / 状态 / 移动 / 排序 / 标签） |
| `/{wid}/documents/{doc_id}` | DELETE | editor+ | 软删除（文件夹递归） |
| `/{wid}/documents/{doc_id}/content` | GET | 成员 + 可见 | 详情 + 最新正文 + `draft` + `write_mode` |
| `/{wid}/documents/{doc_id}/content` | PUT | 成员（分派） | 保存（直编落库 / 202 转申请） |
| `/{wid}/documents/{doc_id}/draft` | GET/PUT/DELETE | 成员 + 可见 | 个人草稿（仅本人） |
| `/{wid}/documents/{doc_id}/submit` | POST | 成员（分派） | 显式提交 |
| `/{wid}/documents/{doc_id}/permissions` | GET/POST | 可见 / 创建者或 owner | 协作者名单 / 授权 |
| `/{wid}/documents/{doc_id}/permissions/{user_id}` | DELETE | 创建者或 owner | 撤销 |
| `/{wid}/documents/{doc_id}/share` | POST/GET | editor+ / 仅已发布 | 创建 / 列表 |
| `/{wid}/documents/{doc_id}/share/{share_id}` | DELETE | editor+ | 撤销 |
| `/{wid}/documents/{doc_id}/versions`、`/diff`、`/rollback`、`/backlinks` | GET/POST | 成员 + 可见（rollback / 断链修复 editor+） | 版本 / 差异 / 回滚 / 反链 |
| `/{wid}/documents/{doc_id}/export` | GET | 成员 | md / docx / pdf |
| `/{wid}/document-change-requests` | GET/POST | 成员 | 列表 / 发起 |
| `/{wid}/document-change-requests/{id}` | GET/DELETE | 成员+可见 / 提交人或 owner | 详情（含 DIFF）/ 删除草稿 |
| `/{wid}/document-change-requests/{id}/merge` | POST | owner/editor | 通过 |
| `/{wid}/document-change-requests/{id}/close` | POST | owner/editor 或提交人 | 驳回 / 关闭 |
| `/{wid}/document-change-requests/{id}/update-base` | POST | 提交人本人 | 刷新基准 |
| `/api/v1/documents/share/{token}` | GET/POST | 匿名 | 分享访问（仅已发布） |

---

## 10. 前端入口与组件

| 组件 | 职责 |
|---|---|
| `pages/documents/DocumentEditorPage.tsx` | 查看/编辑双模式、草稿保存、提交、发布、待审徽标 |
| `pages/documents/DocumentChangeRequestsDrawer.tsx` | 单文档视角待审列表 + 审核 |
| `pages/documents/ChangeRequestCard.tsx` | 申请卡片：状态 / 基准 / DIFF / 通过·驳回·刷新基准·删除草稿 |
| `pages/documents/DocumentsChangeRequestsPage.tsx` | 工作区级修改申请列表（二级导航） |
| `pages/documents/DocumentCollaboratorsModal.tsx` | 协作者授权（只读 / 可编辑） |
| `pages/documents/DocumentTree.tsx` | 目录树：状态图标（草稿 / 已发布 / 归档）、可见性标记 |
| `pages/documents/DocumentsPage.tsx` | 列表：状态筛选、`仅自己可见 / 共享 / 已发布` 标记 |
| `api/documents.ts` | 上述端点的前端封装（`saveDraft` / `submit` / `changeRequests` / `mergeChangeRequest` 等） |

---

## 11. 相关文件索引

- 可见性：`src/cndb/plugins/documents/services/visibility.py`
- 个人草稿：`src/cndb/plugins/documents/services/drafts.py`
- 文档级授权：`src/cndb/plugins/documents/services/document_permissions.py`
- 修改申请：`src/cndb/plugins/documents/services/change_requests.py`
- 内容与版本：`src/cndb/plugins/documents/services/content.py`
- 模型：`src/cndb/plugins/documents/models.py`（`Document` / `DocumentVersion` / `DocumentDraft` / `DocumentChangeRequest` / `DocumentPermission` / `DocumentShare`）
- 路由：`src/cndb/plugins/documents/routers/{documents,change_requests,share,public}.py`
- 术语表：`CONTEXT.md`（文档修改申请、文档双轨制写入、文档问题清单等词条）
