# 需求卡片：游客级文档分享（免登录只读）

- 编号：0017（与 ADR `docs/adr/0017-*.md` 同号）
- 来源 / 提出人：产品需求（用户口述）
- 日期：2026-10-21
- 关联 ADR：`docs/adr/0017-guest-document-share.md`（Implemented）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 增加游客级权限，能够用于仅查看的访问，便于共享文档给他人浏览。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 增加游客级权限 | 游客 = **免登录匿名分享链接**：URL 携带 `token` 即可访问，不新增 `WorkspaceRole.GUEST`，不要求游客注册、登录或加入工作区 | `plugins/documents`、`frontend` 公开页 | 后端匿名端点无 `Depends(get_current_user)`；前端公开路由不经 `ProtectedRoute` |
| C2 | 仅查看的访问 | 游客对分享目标**只有读取**：匿名入口仅暴露读取方法，不存在正文编辑、评论、问题、修改申请、版本回滚等写路径 | `plugins/documents/routers/public.py` | 匿名写请求返回 404/405；接口清单审计无写方法 |
| C3 | 便于共享文档 | 分享粒度 = **单篇文档**：一个 `token` 只对应一个 `document_id`，不得借此读取目录树、其他文档、工作区信息或成员信息 | `documents_share`、`routers/public.py` | 用 token 无法枚举其它资源；响应仅含单文档载荷 |
| C4 | 共享文档给他人浏览 | 仅**已发布**（`published`）文档可创建分享；草稿/归档创建返回 409；取消发布、归档、移入回收站后既有链接立即失效（404） | `routers/share.py`、`routers/public.py`、`services/visibility.py` | 复用并扩展现有可见性测试；状态变更后链接 404 |
| C5 | 便于共享文档 | 分享链接可**随时撤销**：撤销后匿名访问 404；成功访问计数 `view_count + 1` | `routers/share.py`、`routers/public.py` | 撤销后 GET 404；访问计数递增 |
| C6 | 便于共享文档 | 分享管理入口在文档编辑器：**owner/editor** 可创建、复制链接、查看访问次数、撤销；viewer 不显示入口且后端拒绝 | `frontend/.../DocumentEditorPage.tsx`、`routers/share.py` | 前端单测按角色门控；viewer 调用后端 403 |
| C7 | 共享文档给他人浏览 | 新增免登录访问页（公开路由），展示标题与只读正文；未登录访问不得跳转登录页、不触发令牌过期提示；覆盖加载 / 链接不存在 / 已失效三态 | `frontend/src/App.tsx`、公开页组件 | 前端单测 + e2e：未登录直达分享 URL 可读 |
| C8 | 增加游客级权限 | 最小披露：匿名响应剔除 `created_by_id` / `updated_by_id`，不得包含成员、权限、工作区其他资源；分享列表只回显 `has_password`，不返回密码哈希 | `routers/public.py`、`routers/share.py` | 响应字段断言；无敏感字段 |
| C9 | 增加游客级权限 | 本轮**不新增**密码与有效期 UI 或必填校验；既有 `password_hash` / `expires_at` 字段与校验逻辑保留（兼容历史分享），不删除、不改语义 | `documents_share`、`routers/public.py` | 迁移不改列；历史分享仍可访问 |
| C10 | 增加游客级权限 | 游客权限**只作用于文档**：不复活表/视图匿名分享（ADR 0003 D5），不放宽表 `READ` 与视图可见性 | `plugins/tables` | 回归：表/视图公开分享端点仍 404 |
| C11 | 仅查看的访问 | 非法或已失效 token 一律 404，不泄露「链接是否存在 / 文档是否存在」 | `routers/public.py` | 随机 token / 已撤销 token / 已删除文档 → 404 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 匿名分享读取端点 | `src/cndb/plugins/documents/routers/public.py:24` | 已有 `GET /api/v1/documents/share/{token}`、`/{token}/meta` 与密码校验 |
| 2 | 分享管理端点 | `src/cndb/plugins/documents/routers/share.py:30` | 已有创建 / 列表 / 撤销，均需登录 + `require_editor` |
| 3 | 分享数据模型 | `src/cndb/plugins/documents/models.py:187` | `token` / `permission` / `password_hash` / `expires_at` / `view_count` / `is_active` 已齐备 |
| 4 | 前端分享 API 封装 | `frontend/src/api/documents.ts:621` | 已有 `shares / createShare / revokeShare`，但全仓无调用方 |
| 5 | 前端公开页与路由 | `frontend/src/App.tsx:72` | 无分享访问路由；`App.tsx:157`、`App.tsx:167` 已预留 `/public` 前缀但未注册 |
| 6 | 仅发布可分享 | `src/cndb/plugins/documents/routers/share.py:45` | 草稿/归档创建分享返回 409 |
| 7 | 取消发布后链接失效 | `src/cndb/plugins/documents/routers/public.py:58`、`:89` | 匿名读取校验 `status == published` |
| 8 | 软删文档过滤 | `src/cndb/plugins/documents/services/content.py:87` | `get_document_or_404` 排除 `is_deleted` |
| 9 | editor 门槛 | `src/cndb/plugins/documents/services/content.py:131` | 管理分享的权限来源 |
| 10 | 登录拦截 | `frontend/src/components/ProtectedRoute.tsx:19` | 未登录统一跳 `/login`，公开页需绕开 |
| 11 | 既有分享测试 | `tests/test_document_visibility.py:30`、`tests/test_documents_plugin.py:8`、`tests/test_cov_documents_extra.py:773` | 覆盖创建限制、密码、过期、失效；需补游客读取与撤销计数 |
| 12 | 编辑器操作区 | `frontend/src/pages/documents/DocumentEditorPage.tsx:657` | 「更多」菜单是分享入口的候选落点 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（2026-10-21 已与需求方确认）

- [x] 游客身份形态 → **匿名分享链接**（不引入工作区 guest 角色，不要求注册登录）。
- [x] 游客可见范围 → **仅被分享的单篇文档**（不含文档区、数据表或工作区级浏览）。
- [x] 游客可执行动作 → **完全只读**（不可评论、提问题、提交修改申请）。
- [x] 分享管控项 → **可随时撤销 + 访问计数 + 仅已发布文档可分享**；本轮不做密码与有效期入口。
- [x] 与表/视图匿名分享的关系 → **不扩展**：ADR 0003 D5 的移除结论保持，本需求只覆盖文档。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-21）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
