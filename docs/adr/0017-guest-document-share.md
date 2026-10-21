# ADR 0017: 文档游客级只读分享（匿名分享链接）

Status: Accepted（已评审）
Date: 2026-10-21
Related: `src/cndb/plugins/documents/routers/public.py`、`src/cndb/plugins/documents/routers/share.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/files/services.py`、`src/cndb/plugins/tables/routers/files.py`、`frontend/src/App.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/components/Document/DocumentImage.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`docs/adr/0003-view-visibility-permission-model.md`
需求卡片: `docs/requirements/0017-guest-document-share.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 增加游客级权限 | 游客 = 匿名分享链接：URL 携带 `token` 即可读取，不新增 `WorkspaceRole.GUEST`，不要求注册 / 登录 / 加入工作区。公开端点继续放在 `routers/public.py`，不挂 `Depends(get_current_user)`；前端公开路由放在 `ProtectedRoute` 之外（D1 / D7） |
| C2 | 仅查看的访问 | 匿名路由只注册 `GET`（正文 / meta / 图片）；不存在任何匿名写方法。`DocumentShare.permission` 对匿名访问**不产生写权限**，仅为存量字段兼容（D3） |
| C3 | 便于共享文档 | 一个 `token` 只解析一个 `document_id`；公开响应使用**显式白名单**（标题 / 正文 / 更新时间），不含目录树、工作区成员、标签、其它文档；公开图片端点还要求 `FileOwner.document_id == share.document_id`（D2 / D5 / D6） |
| C4 | 共享文档给他人浏览 | 创建分享沿用 `share.py` 的「仅 `published` 可创建（否则 409）」；匿名读取统一经 `resolve_public_share` 复核 `is_active / expires_at / is_deleted / status`，取消发布、归档、回收站、撤销后立即 404（D4） |
| C5 | 便于共享文档 | 撤销沿用 `DELETE /{doc_id}/share/{share_id}`；每次成功取正文后 `view_count` 原子 +1（`view_count = view_count + 1`），`meta` 与密码校验失败不计（D4） |
| C6 | 便于共享文档 | 分享管理入口放在文档编辑器「更多」菜单：仅 `owner` / `editor` 渲染，viewer 不显示且后端仍由 `require_editor` 拒绝（403）；弹层提供创建 / 复制链接 / 访问次数 / 撤销（D8） |
| C7 | 共享文档给他人浏览 | 新增 `/public/share/:token` 独立路由与公开页，覆盖加载 / 密码 / 不存在或已失效三态；不请求任何工作区鉴权接口，不触发登录跳转与令牌过期提示（D7） |
| C8 | 增加游客级权限 | 公开响应白名单剔除 `created_by_id / updated_by_id / workspace_id / parent_id / tag_ids / version_count / visibility` 等内部字段；分享列表只回显 `has_password`，永不返回 `password_hash`（D5） |
| C9 | 增加游客级权限 | 不新增密码 / 有效期创建入口；既有 `password_hash` / `expires_at` 字段与校验保留，历史密码分享仍可在公开页输入密码访问；不新增迁移（D8 / D9） |
| C10 | 增加游客级权限 | 游客能力只覆盖文档：不恢复表 / 视图匿名分享（ADR 0003 D5），公开图片端点也只接受归属该文档的附件，不放宽表 `READ` 与视图可见性（D6） |
| C11 | 仅查看的访问 | `resolve_public_share` 对未知 token、已撤销、已过期、文档已删除 / 未发布一律抛 `NotFoundError`（404，统一文案），不区分「链接不存在」与「已失效」（D4） |

决策结论只在「决策记录」写一次。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」编号，ADR 新发现项从 13 起编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 匿名读取端点已存在：`GET /{token}` 与带密码 `POST /{token}`，前缀 `/api/v1/documents/share` | `src/cndb/plugins/documents/routers/public.py:24`、`:46`、`:72` | 无需新建路由前缀，只需收敛判定与响应 | 确认 |
| 2 | 分享管理端点已存在：创建 / 列表 / 撤销，均需登录 + `require_editor` | `src/cndb/plugins/documents/routers/share.py:30`、`:66`、`:86` | 后端管理能力可复用，缺口在前端入口 | 确认 |
| 3 | `DocumentShare` 已有 `token / permission / password_hash / expires_at / view_count / is_active` | `src/cndb/plugins/documents/models.py:187-206` | 游客只读所需字段齐备，无需加列 | 确认 |
| 4 | 前端分享 API 已封装 `shares / createShare / revokeShare`，但全仓无调用方 | `frontend/src/api/documents.ts:621-630` | 直接复用，补分享弹层 | 确认 |
| 5 | 前端无 `/public` 分享访问路由；`/public` 前缀仅在令牌过期提示中被排除 | `frontend/src/App.tsx:72-133`、`:165-167` | 需新增独立公开路由，且不落在 `ProtectedRoute` 内 | 确认 |
| 6 | 创建分享要求文档 `published`，草稿 / 归档返回 409 | `src/cndb/plugins/documents/routers/share.py:45-46` | 直接复用为「仅已发布可分享」 | 确认 |
| 7 | 匿名读取校验 `status == published`，取消发布后既有链接 404 | `src/cndb/plugins/documents/routers/public.py:58-59`、`:89-90` | 语义正确，收敛进统一判定 | 确认 |
| 8 | 取文档时排除软删除（`is_deleted == False`） | `src/cndb/plugins/documents/services/content.py:87-96` | 公开读取复用同一取数，回收站文档自然 404 | 确认 |
| 9 | `require_editor` 是写操作（含分享管理）的权限来源 | `src/cndb/plugins/documents/services/content.py:131` | 分享入口沿用，不新增角色或权限位 | 确认 |
| 10 | 未登录访问受保护路由统一跳 `/login?return_to=...` | `frontend/src/components/ProtectedRoute.tsx:19-22` | 公开页必须注册在守卫外，否则游客被弹去登录 | 确认 |
| 11 | 既有测试覆盖创建限制、密码、过期、撤销 | `tests/test_document_visibility.py:213`、`:220`；`tests/test_documents_plugin.py:374`；`tests/test_cov_documents_extra.py:769` | 可复用夹具扩游客读取与计数；过期断言需从 403 改 404 | 确认 |
| 12 | 编辑器「更多」菜单集中次级入口；页面已取 `current_user_role` | `frontend/src/pages/documents/DocumentEditorPage.tsx:660-680`、`:136` | 分享入口落点明确，角色门控有现成数据 | 确认 |
| 13 | 附件下载需登录 + 工作区成员 + 归属校验 | `src/cndb/plugins/tables/routers/files.py:335-354` | 公开页正文里的站内图片无法匿名加载 | 新增 |
| 14 | 前端站内图片统一经 axios 带鉴权取 blob | `frontend/src/hooks/useFileObjectUrl.ts:38-42`、`frontend/src/components/Document/DocumentImage.tsx:14-17` | 公开页不能复用该链路，需免登录图片 URL | 新增 |
| 15 | 公开响应直接复用内部详情序列化，仅剔除 `created_by_id` / `updated_by_id` | `src/cndb/plugins/documents/services/content.py:1036-1067`、`routers/public.py:63-68` | 仍暴露 `workspace_id / parent_id / tag_ids / version_count / status` 等，不符合单文档最小披露 | 新增 |
| 16 | 过期分享返回 403（可反推 token 曾存在）；`meta` 不校验文档状态与软删 | `src/cndb/plugins/documents/routers/public.py:37-42`、`:113-120` | 泄露存在性；已下线 / 已删文档的标题仍可读到 | 新增 |

**核心缺陷（需求要补的）**：现有匿名分享只有「半条链路」——后端读接口在，但响应按内部详情序列化、公开图片没有免登录入口、前端既无访问页也无管理入口，且过期 / 失效口径不统一，无法作为可交付的游客只读能力。

设计目标（不变量）：

- **I1 单一判定入口**：所有匿名端点（正文、密码入口、meta、图片）必须调用同一个 `resolve_public_share(db, token)`，不得各自复制激活 / 过期 / 状态判断。
- **I2 单文档边界**：`token` 只能解析出它对应的那一篇文档；响应与图片都不得带出工作区、目录、成员或其它资源。
- **I3 只读**：匿名路由面只有 `GET`（密码入口为 `POST` 但语义仍是「换取读取」）；`permission` 字段不给匿名访问者任何写能力。
- **I4 即时失效且不泄露存在性**：撤销、过期、取消发布、归档、软删、未知 token 一律 404，响应文案一致。
- **I5 最小披露**：公开响应字段用白名单固定，不随内部序列化演进被动扩张。
- **I6 免登录前端**：公开页不进入 `ProtectedRoute`，不请求工作区鉴权接口，不弹令牌过期提示、不跳 `/login`。
- **I7 存量兼容**：不改 `documents_share` 结构与既有密码 / 过期语义，存量分享与历史备份不受影响。

## Decision

### 1. 数据模型

无新增表 / 列 / 迁移。继续使用 `documents_share`：

| 字段 | 本设计语义 |
|---|---|
| `token` | 唯一凭据（`secrets.token_urlsafe(32)`），一个 token 对应一个 `document_id` |
| `permission` | 存量字段，匿名访问**忽略**；不因 `editor` 值开放任何写方法 |
| `password_hash` | 可选；有值时匿名读取需先经 `POST /{token}` 校验，之后才返回正文 |
| `expires_at` | 可选；过期后按 I4 返回 404（不再返回 403） |
| `view_count` | 成功取正文时原子 +1；`meta` 与密码失败不计 |
| `is_active` | 撤销即置 `false`，所有匿名入口按 I4 返回 404 |

公开响应不复用内部详情序列化，新增白名单序列化（见 §2）。文件夹分享：后端行为不变（历史 token 仍可按标题读取、无正文），前端不提供文件夹分享入口。

### 2. 判定算法（唯一入口）

新增模块级私有入口（与四个匿名端点同处 `routers/public.py`，避免跨层循环依赖）：

```python
def resolve_public_share(db: Session, token: str) -> tuple[DocumentShare, Document]:
    """匿名分享唯一判定入口；任何失败一律 404，不区分原因。"""
    share = db.execute(
        select(DocumentShare).where(
            DocumentShare.token == token,
            DocumentShare.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if share is None:
        raise NotFoundError("分享链接不存在或已失效")
    if share.expires_at is not None:
        expires = share.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        if expires < dt.datetime.now(dt.UTC):
            raise NotFoundError("分享链接不存在或已失效")
    doc = db.execute(
        select(Document).where(
            Document.id == share.document_id,
            Document.is_deleted == False,  # noqa: E712
            Document.status == DOC_STATUS_PUBLISHED,
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("分享链接不存在或已失效")
    return share, doc
```

判定顺序固定：**token 存在且激活 → 未过期 → 文档未软删且已发布**；任一不满足即 404。`meta`、正文、密码入口、图片端点全部先调用该函数，禁止单独查 `DocumentShare`。

公开响应白名单：

```python
def serialize_public_document(db: Session, doc: Document) -> dict[str, Any]:
    data: dict[str, Any] = {"title": doc.title, "updated_at": doc.updated_at}
    if not doc.is_folder:
        data["content"] = load_content(latest_version(db, doc.id), doc)
    return data
```

计数使用原子更新，避免并发读改写丢失：

```python
db.execute(update(DocumentShare).where(DocumentShare.id == share.id).values(view_count=DocumentShare.view_count + 1))
```

公开图片访问判定（与文档判定串联）：

1. `resolve_public_share(db, token)` 通过；
2. `owner = files_service.owner_of(db, file_key)` 必须存在，且 `owner.workspace_id == doc.workspace_id`、`owner.document_id == doc.id`（无归属记录的历史文件一律拒绝）；
3. 扩展名必须落在**栅格图片白名单**（`.png/.jpg/.jpeg/.gif/.bmp/.webp/.ico/.tiff`）；`svg/html/xml` 等可脚本化类型 404；
4. 物理路径统一经新增的 `files_service.resolve_workspace_file(workspace_id, file_key)` 解析（沿用现 `_file_path` 的 `..` / 分隔符 / 前缀校验），`tables/routers/files.py` 的 `_file_path` 改为调用它，保持单一路径校验实现。

所有匿名成功响应加 `Cache-Control: no-store`，图片加 `X-Content-Type-Options: nosniff`；撤销 / 取消发布后浏览器不会继续用缓存展示旧内容。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/documents/share/{token}` | 修改：改用 `resolve_public_share`；过期从 403 改 404；响应改白名单；`no-store` |
| `POST /api/v1/documents/share/{token}` | 修改：同样判定；保留 bcrypt 密码校验；成功后白名单响应 + 计数；`no-store` |
| `GET /api/v1/documents/share/{token}/meta` | 修改：同样判定（修复已下线 / 已删文档仍回标题）；只返回 `{title, has_password}`；不计数；`no-store` |
| `GET /api/v1/documents/share/{token}/files/{file_key}` | 新增：免登录图片读取，按 §2 判定；仅栅格图片；404 不泄露归属 |
| `POST /{workspace_id}/documents/{doc_id}/share` | 不变：登录 + `require_editor`；非 `published` 返回 409 |
| `GET /{workspace_id}/documents/{doc_id}/share` | 不变：登录 + `require_editor`；只回显 `has_password` |
| `DELETE /{workspace_id}/documents/{doc_id}/share/{share_id}` | 不变：登录 + `require_editor`；置 `is_active = False` |

### 4. 边界与例外

1. **统一 404 文案**：未知 token、撤销、过期、草稿 / 归档、软删文档统一为「分享链接不存在或已失效」，不区分原因（I4）。
2. **密码分享**：有 `password_hash` 时 `GET` 返回 403 + `code=share_password_required`（这是「有效但需凭据」，不是失效）；密码正确后才返回正文并计数。密码哈希永不出现在任何响应。
3. **文件夹**：历史文件夹分享仅返回标题、无 `content`；前端分享入口只对非文件夹文档展示。
4. **`permission=editor`**：匿名访问仍只读；不新增任何匿名写端点，写请求由路由层自然返回 405 / 404。
5. **已发布内容更新**：分享始终指向最新版本正文，编辑已发布文档后访客刷新即见新内容；无快照锁定。
6. **外部图片**：Markdown 中的 `http(s)` 图片由浏览器直连第三方，后端不代理；公开页对外部图片加 `referrerpolicy="no-referrer"`，避免含 token 的页面 URL 经 Referer 泄露。
7. **站内图片**：只通过公开图片端点读取，且归属必须是当前分享文档；未登记归属的历史附件不可匿名读取（返回 404，页面显示图片加载失败）。
8. **数据表动态引用 / 双向链接**：公开页不传 `workspaceId`、不传 `onWikilink`，因此不渲染实时数据表、不做跨文档跳转，避免借公开页读取其它资源。
9. **表 / 视图匿名分享**：保持 ADR 0003 D5 的移除结论；`/api/v1/public/share/{slug}` 仍必须 404，公开图片端点也不能读取表附件。
10. **访问计数**：一次页面加载中 `meta` 不计数、正文只请求一次（前端用 `useQuery`，不做轮询），刷新页面计为新一次浏览。

### 5. 迁移

无。`documents_share` 与全部所需字段已在既有迁移 `f0a1b2c3d4e5_add_documents_plugin.py` 中建立，本次不改表结构，因此不新增 alembic 迁移、无 downgrade、存量零迁移。

工作区备份导出只含文档正文 / 元数据，不含 `documents_share`（外部链接不跨工作区迁移），本设计不改备份格式；备份往返用例无需新增。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 路由 | `frontend/src/App.tsx` | 新增 `lazy(() => import('@/pages/public/PublicSharePage'))` 与 `<Route path="/public/share/:token" element={<PublicSharePage />} />`，放在 `ProtectedRoute` 之外 |
| 公开页 | `frontend/src/pages/public/PublicSharePage.tsx`（新增） | 读取 `token`；`meta` → 正文三态（加载 / 需密码 / 不存在或已失效）；只读渲染标题、更新时间与正文；独立简洁布局，无工作区导航 |
| 公开 API | `frontend/src/api/publicShare.ts`（新增） | `meta(token)`、`content(token)`、`contentWithPassword(token, password)`、`fileUrl(token, fileKey)`；复用 `api` 实例（无 token 时不带 Authorization），`fileUrl` 返回 `/api/v1/documents/share/{token}/files/{fileKey}` |
| 预览复用 | `frontend/src/components/Document/MarkdownPreview.tsx` | 新增可选 `publicFileBase?: string`，透传给 `DocumentImage`；不传 `workspaceId` 时不渲染数据表引用 |
| 图片 | `frontend/src/components/Document/DocumentImage.tsx` | 新增 `publicFileBase?: string`：有值时直接 `<img src={base + '/' + fileKey}>`（免登录），不走 `useFileObjectUrl`；外部图片在公开模式加 `referrerPolicy="no-referrer"` |
| 分享弹层 | `frontend/src/pages/documents/DocumentShareModal.tsx`（新增） | 仅 `owner` / `editor` 打开；列表展示创建时间 / 状态 / 访问次数；「创建链接」在非 `published` 时禁用并提示；复制 `origin + /public/share/{token}`；撤销二次确认 |
| 入口 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 在顶栏 / 「更多」菜单增加「分享」项，`myRole` 为 `owner` / `editor` 且非文件夹时展示，打开分享弹层 |
| API 出口 | — | 不并入 `frontend/src/api/index.ts`：公开页直接 `import publicShareApi from '@/api/publicShare'`，与工作区鉴权 API 出口隔离，游客链路不混入登录态资源域 |

### 7. 测试清单

**判定层（单测）**：`tests/test_document_public_share.py`（新增）

- `resolve_public_share`：有效 token + 已发布 → 通过；未知 token / 撤销 / 过期 / 草稿 / 归档 / 软删 → 一律 404；文件夹 → 通过且无 `content`。
- 公开序列化白名单：响应键恰为 `{title, content, updated_at}`（文件夹为 `{title, updated_at}`），不含 `workspace_id / parent_id / tag_ids / version_count / created_by_id / updated_by_id / visibility`。
- 密码：无密码分享 `GET` 200；有密码 `GET` 403 + `share_password_required`；错误密码 403；正确密码 200；密码哈希不出现在任何响应。
- 计数：成功正文请求 +1；`meta` 不 +1；密码失败不 +1；并发两次成功请求合计 +2。
- 只读：对 `/{token}` 发 `PUT/PATCH/DELETE` → 405；匿名路由清单不存在写方法。
- 公开图片：归属本文档 → 200 + `nosniff`；归属其它文档 / 其它工作区 / 无归属记录 → 404；`svg/html` → 404；路径穿越 `../` → 400/404；分享撤销或文档下线后 → 404。
- 回归：`/api/v1/public/share/{slug}` 仍 404（ADR 0003 D5）。

**接口层**：

- 创建分享：owner / editor 成功；viewer 403；草稿 / 归档 409；非成员 404 / 403。
- 列表：只含 `has_password`，无 `password_hash`；撤销后 `is_active=false`，匿名读取 404。
- `meta`：已发布文档返回标题与 `has_password`；取消发布 / 归档 / 软删后 404。
- 既有 `tests/test_cov_documents_extra.py::test_expired_share` 由 403 改为 404（I4 口径变更）。

**迁移 / 备份**：无新增迁移；`documents_share` 不在备份格式内，备份往返用例不改。

**前端单测**：

- `frontend/src/pages/public/PublicSharePage.test.tsx`：加载态；成功渲染标题 / 正文；404 显示「链接不存在或已失效」；密码分享先渲染密码框，提交正确密码后渲染正文；公开页不发起工作区接口、不跳 `/login`。
- `frontend/src/pages/documents/DocumentShareModal.test.tsx`：owner / editor 可创建；draft 时创建按钮禁用并提示；viewer 不渲染入口；复制链接格式；撤销后列表状态更新；访问次数展示。
- `frontend/src/components/Document/DocumentImage.test.tsx` / `MarkdownPreview.test.tsx`：`publicFileBase` 时图片直接用公开 URL、不调用 axios；不传 `workspaceId` 时数据表引用不渲染为实时表。

**e2e（前端）**：`frontend/tests/e2e/critical/document-public-share.spec.ts`（新增）

- owner 发布文档 → 编辑器创建分享 → 复制链接；
- 无登录态的新上下文直达 `/public/share/{token}` → 正文可见、URL 仍为公开页（未被 `/login` 重定向）；
- 撤销分享 → 同一链接显示「链接不存在或已失效」；
- 取消发布 → 同一链接失效。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端：`resolve_public_share` 单入口、白名单序列化、过期 404、原子计数、公开图片端点 + `resolve_workspace_file` 复用 | 中（图片端点涉及路径与归属校验，需重点测路径穿越） |
| **P1** | 前端：公开路由 + `PublicSharePage` + `publicShareApi` + `MarkdownPreview` / `DocumentImage` 公开图片支持 | 中（需确保不触发鉴权与过期提示） |
| **P2** | 前端：分享弹层与编辑器入口（角色门控、创建 / 复制 / 计数 / 撤销）+ e2e 与回归 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 游客身份形态（整体方案选型） | **匿名分享链接**：token 即凭据，不新增工作区角色 | 游客不应进入工作区成员体系；链接可按篇分发、可撤销，攻击面最小 | ① 新增 `WorkspaceRole.GUEST`：需注册 / 加成员，且会获得工作区级可见面；② 公开工作区 / 文档区：范围远超「共享一篇文档」 | `documents_share`、`routers/public.py`、`/public/share/:token` |
| D2 | 游客可见范围 | **仅 token 对应的一篇文档**；图片也按 `document_id` 归属收口 | 单文档粒度可验证、可撤销；不引入目录 / 成员 / 其它资源读取 | 工作区级匿名浏览（会泄露未分享内容与成员信息） | `resolve_public_share`、公开图片判定 |
| D3 | 游客可执行动作 | **完全只读**；`permission` 字段对匿名访问无效 | 匿名写无法审计到具体用户，评论 / 修改申请也需身份；只读面最小 | 允许匿名评论 / 提问 / 提交修改申请（需引入匿名身份与滥用治理） | `routers/public.py` 仅 GET；无匿名写端点 |
| D4 | 失效与存在性口径 | 撤销 / 过期 / 取消发布 / 归档 / 软删 / 未知 token **统一 404**；成功响应 `no-store` | 不泄露 token 是否曾存在；撤销需立即生效，缓存会削弱「随时撤销」 | 过期返回 403 + 明确文案（泄露存在性）；允许浏览器缓存（撤销后仍可见） | `resolve_public_share`、响应头 |
| D5 | 公开响应字段 | **显式白名单** `{title, content, updated_at}`，文件夹无 `content` | 内部详情序列化会随功能演进而扩张，白名单可锁住最小披露 | 复用 `serialize_document` 再 pop 敏感字段（新增字段会默认外泄） | `serialize_public_document` |
| D6 | 正文站内图片 | 新增 `GET /share/{token}/files/{file_key}`：免登录、**归属本文档**、仅栅格图片、路径校验单源 | 不开放图片则公开页大面积裂图；按归属收口可防止借 token 读取工作区其它附件 | ① 复用需登录下载端点（游客无法加载）；② 放开整个工作区文件目录（越权读取表附件） | `routers/public.py`、`files/services.py`、`tables/routers/files.py` |
| D7 | 前端访问形态 | 独立 `/public/share/:token` 路由，置于 `ProtectedRoute` 之外；不传 `workspaceId` / `onWikilink` | 游客不能进入登录态；不请求工作区接口才能保证不跳登录、不弹过期提示 | 复用编辑器页并加只读开关（仍会拉工作区 / 版本 / 修改申请等鉴权接口） | `App.tsx`、`PublicSharePage.tsx`、`MarkdownPreview.tsx` |
| D8 | 分享管理入口与存量密码 / 有效期 | 入口仅 `owner` / `editor`；创建固定 `viewer`；**不新增**密码 / 有效期 UI，但公开页支持历史密码分享输入 | 与既有 `require_editor` 一致；C9 要求保留存量语义，不能把历史密码分享变成死链 | ① 给 viewer 也显示入口（后端必 403，徒增困惑）；② 移除密码 / 过期字段（破坏存量分享） | `share.py`、`DocumentShareModal.tsx`、`DocumentEditorPage.tsx`、`PublicSharePage.tsx` |
| D9 | 数据模型与迁移 | **零迁移**，复用 `documents_share` 现有字段 | 字段已齐备，加列只会增加发布风险；`permission` 保留兼容 | 新增 `share_type` / `is_public` 等列（冗余且需迁移） | `plugins/documents/models.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：文档可以免登录分享给外部浏览者，且范围严格收敛到单篇已发布文档；撤销 / 下线即时生效；分享管理、访问计数与图片读取都有明确落点，游客面没有写入口。
- **负向**：公开读取从「内部序列化」改为独立白名单，后续若要在公开页展示新字段需显式加白；公开图片端点新增一条对外路径，需要持续守住归属与扩展名白名单；前端多一个独立页面与弹层，测试面扩大。
- **风险与缓解**：token 出现在 URL 中，可能经浏览器历史 / Referer 泄露 —— 页面不记录到工作区导航、外部图片禁用 Referer；公开响应 `no-store`，撤销后不依赖缓存失效；图片端点只按文档归属放行，避免成为工作区文件遍历入口。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 表 / 视图匿名分享 | `/api/v1/public/share/{slug}`、视图分享端点 | 保持**彻底移除**，本 ADR 不恢复；游客能力只覆盖文档 | ADR 0003 D5 |
| 文档可见性 | `status=draft/published/archived` | 游客只能读 `published`，取消发布 / 归档立即失效；不改变成员可见性口径 | ADR 0003、`services/visibility.py` |
| 文档写权限 | 双轨制写入（直编 / 修改申请） | 匿名访客不进入任何写路径，不生成修改申请 | 既有文档双轨制 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/routers/public.py`、`src/cndb/plugins/files/services.py`、`src/cndb/plugins/tables/routers/files.py` | `tests/test_document_public_share.py` | `feaebb9c` |
| P1 | 已落地 | `frontend/src/pages/public/PublicSharePage.tsx`、`frontend/src/api/publicShare.ts`、`frontend/src/App.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/components/Document/DocumentImage.tsx` | `frontend/src/pages/public/PublicSharePage.test.tsx`、`frontend/src/components/Document/DocumentImage.test.tsx`、`frontend/src/components/Document/MarkdownPreview.test.tsx` | `feaebb9c` |
| P2 | 进行中 | `frontend/src/pages/documents/DocumentShareModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/pages/documents/DocumentShareModal.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx`；e2e `frontend/tests/e2e/critical/document-public-share.spec.ts` 待补 | `feaebb9c` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 已落地；P2 代码与单测已落地，**e2e 用例待补**（`frontend/tests/e2e/critical/document-public-share.spec.ts`）
- 已完成：后端 `resolve_public_share` 单入口判定、公开响应白名单、过期统一 404、原子 `view_count`、免登录图片端点与 `resolve_workspace_file` 路径校验单源；前端公开路由与 `PublicSharePage`（三态，兼容历史密码分享）、`publicShareApi`、`MarkdownPreview` / `DocumentImage` 公开图片、`DocumentShareModal` 与编辑器入口（owner/editor 且非文件夹）；后端与前端相关单测全绿
- 下一步：补 `document-public-share.spec.ts`（匿名 context 直达 `/public/share/{token}`、撤销与取消发布后失效），跑通后把 P2 置「已落地」并把 `Status` 定稿 `Implemented`、同步索引 / CHANGELOG
- 已知坑：过期分享的既有测试断言已随 I4 从 403 改为 404；公开图片必须按 `FileOwner.document_id` 收口，不能只校验工作区；前端公开页不得传 `workspaceId`，否则会触发工作区接口与鉴权链路；`publicShareApi` 未并入 `frontend/src/api/index.ts`（公开页直接 import，避免游客链路混入鉴权资源域）
- 最近一次全绿：2026-10-22 `make check-fast` 通过；`pytest tests/test_document_public_share.py tests/test_cov_documents_extra.py` 155 passed；前端 `PublicSharePage` / `DocumentShareModal` / `DocumentImage` / `MarkdownPreview` / `DocumentEditorPage` 单测 86 passed
