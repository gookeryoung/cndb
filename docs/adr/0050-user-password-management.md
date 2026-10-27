# ADR 0050: 用户自助修改密码与管理员重置他人密码

Status: Implemented（已评审，2026-10-27；同日人工确认 P0-P2 全期落地）
Date: 2026-10-27
Related: `src/cndb/plugins/accounts/routers/auth.py`、`src/cndb/plugins/accounts/routers/users.py`、`src/cndb/plugins/accounts/services/users.py`、`src/cndb/plugins/accounts/services/sessions.py`、`src/cndb/plugins/accounts/services/user_bulk.py`、`src/cndb/core/events.py`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/pages/admin/UsersPage.tsx`
需求卡片: `docs/requirements/0050-user-password-management.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「用户修改密码」 | 后端复用既有 `POST /api/v1/accounts/auth/password`（校验当前密码 + 新密码 6–128 + 新旧不同）；前端在个人设置新增「安全」页签承载改密表单 |
| C2 | 「用户修改密码」 | 后端既有逻辑已做 `token_version` +1 + `revoke_all`；前端成功后调用 `logout()` 清本地态并 `navigate('/login')`，提示用新密码重新登录 |
| C3 | 「管理员修改其他用户密码」 | 新增 `POST /api/v1/accounts/users/{user_id}/password`：仅超管；新密码可选，缺省由服务端 `generate_password(12)` 生成；响应仅返回本次生成的密码；成功后目标 `token_version` +1 + `revoke_all(reason="password_reset_by_admin")` |
| C4 | 「管理员修改其他用户密码」 | 服务层入口即校验 `target.id == actor.id` → `UserAdminError("不能重置自己的密码…")`，路由映射 400；管理员改自己只能走 C1 的个人设置 |
| C5 | 隐含（审计与事件） | 新增审计动作 `password_reset`，detail 仅 `{generated, revoked_sessions}`；复用 `record_audit` 自动写入 `user.password_reset` 事件；`_USER_ACTION_SUMMARY` 与前端 `ACTION_LABELS` 补中文摘要 |
| C6 | 隐含（权限边界与零回归） | 管理端点复用 `_require_superuser`；自助端点保持「仅当前登录用户本人」；不改用户编辑 / 导入导出 / 登录注册的请求与响应契约 |
| C7 | 隐含（密码不落明文） | 两条路径都只调 `User.set_password`（bcrypt）；手工输入的新密码不回显，自动生成的密码只在该次管理端点响应中出现一次；审计 / 事件 / 列表 / 导出均无密码字段 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论并补 `文件:行号`：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 自助改密后端已完整实现：校验当前密码 → 更新哈希 → `token_version` +1 → `revoke_all(reason="password_changed")` → 写事件 | `src/cndb/plugins/accounts/routers/auth.py:331-365` | 后端能力可直接复用，无需改判定 | 确认 |
| 2 | 自助改密请求体已定义 `current_password` + `new_password`（6–128） | `src/cndb/plugins/accounts/schemas/auth.py:90-96` | 密码规则沿用 | 确认 |
| 3 | 前端 API 封装存在，但全仓无页面调用 | `frontend/src/api/auth.ts:31-33` | 用户看不到入口，能力不可达 | 确认 |
| 4 | 个人设置已有四个页签，Modal 由 MainLayout 挂载 | `frontend/src/pages/settings/SettingsModal.tsx:373-390`、`frontend/src/layouts/MainLayout.tsx:637` | 「安全」页签有稳定挂载点 | 确认 |
| 5 | 页签 key 为封闭联合类型 | `frontend/src/store/ui.ts:10` | 需扩 `SettingsTab`，否则无法定位新页签 | 确认 |
| 6 | 用户管理页桌面表格与移动卡片只有「编辑 / 日志」两个操作，编辑弹窗无密码字段 | `frontend/src/pages/admin/UsersPage.tsx:470-475,775-807`、`frontend/src/pages/admin/UsersPage.tsx:583-594` | 管理员无重置入口 | 确认 |
| 7 | 用户编辑请求体不含密码，且只处理资料 / 角色 / 状态 | `src/cndb/plugins/accounts/schemas/users.py:32-46`、`src/cndb/plugins/accounts/services/users.py:142-200` | 不能通过编辑接口捎带密码（也不应这样做） | 确认 |
| 8 | 用户管理服务层已有 `record_audit`（审计失败不阻断主操作）与事件流接入 | `src/cndb/plugins/accounts/services/users.py:63-108` | 重置密码可复用同一审计 / 事件通道 | 确认 |
| 9 | 操作日志动作标签与 `DiffSummary` 未覆盖重置密码 | `frontend/src/pages/admin/UsersPage.tsx:32-40,78-128` | 重置后日志会显示原始动作名且详情为空 | 确认 |
| 10 | 会话吊销已有 `revoke_all`，支持原因字符串与批量失效 | `src/cndb/plugins/accounts/services/sessions.py:97-108` | 两条改密路径共用同一吊销入口 | 确认 |
| 11 | 现成随机初始密码生成器（12 位、排除易混淆字符） | `src/cndb/plugins/accounts/services/user_bulk.py:98-102` | 管理员重置默认密码直接复用，避免第二套生成规则 | 确认 |
| 12 | 既有改密测试覆盖会话失效与事件，未覆盖前端入口；用户管理测试无重置密码用例 | `tests/test_auth_session.py:143-181`、`tests/test_core_events.py:259-274`、`tests/test_users_management.py` | 需新增接口与前端用例，既有用例作为回归基线 | 确认 |
| 13 | CLI 已有 `users edit -p` 重置能力 | `src/cndb/cli/users/commands.py:206-215` | 不在本次 API / 前端范围，保持不动 | 排除 |

**核心缺陷（需求要补的）**：自助改密的**后端**已存在但**前端不可达**；管理员**完全没有**重置他人密码的端点与入口，且缺少对应的审计动作。

设计目标（不变量）：

- **I1 密码规则单一**：两条路径都只接受 6–128 位密码、只落 bcrypt 哈希；自动生成沿用 12 位既有生成器（C1/C3/C7）。
- **I2 改密即失效**：任一改密 / 重置成功后，目标用户的既有 access token 与全部刷新令牌立即失效（`token_version` +1 + `revoke_all`）（C2/C3）。
- **I3 权限边界**：自助端点只作用于当前用户；管理端点只允许超级管理员，且拒绝作用于操作人自己（C4/C6）。
- **I4 秘密不回显**：手工输入的新密码永不出现在响应 / 日志 / 事件；自动生成的密码只在该次响应返回一次（C7）。
- **I5 存量契约不变**：既有自助端点响应 `{ok, revoked_sessions}`、用户编辑 / 导入导出 / 登录注册接口均不改形状（C6）。
- **I6 审计一致**：管理员重置必须尝试写 `accounts_userauditlog` 与 `core_event`，口径沿用既有「尽力而为、不阻断主操作」；detail 不含密码或哈希（C5）。

## Decision

### 1. 数据模型

无（零迁移、零新表新列；`token_version` 与 `RefreshToken` 均为存量结构）。

### 2. 判定算法（唯一入口）

**自助改密**：不改判定，沿用 `auth.py:change_password`。

**管理员重置**：新增服务层入口 `src/cndb/plugins/accounts/services/users.py`：

```python
def reset_user_password(
    db: Session,
    *,
    actor: User,
    target: User,
    new_password: str | None = None,
) -> tuple[str | None, int]:
    """管理员重置他人密码（不含自助路径）。

    返回 (generated_password | None, revoked_sessions)。
    校验顺序：actor==target → UserAdminError；否则缺省 generate_password(12)。
    """
```

顺序：

```
0. target.id == actor.id → UserAdminError（路由映射 400）
1. plain = new_password or generate_password(12)
2. target.set_password(plain)            # bcrypt
3. target.token_version += 1
4. commit
5. revoked = session_service.revoke_all(db, target.id, reason="password_reset_by_admin")
6. record_audit(action="password_reset", detail={"generated": new_password is None, "revoked_sessions": revoked})
7. return (plain if new_password is None else None, revoked)
```

路由层 `src/cndb/plugins/accounts/routers/users.py` 继续用 `_require_superuser` 门控；目标用户不存在沿用 `get_user_or_none` → 404；`UserAdminError` 沿用 `_map_user_admin_error` → 400。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/accounts/auth/password` | 不改（既有自助改密；仅补前端调用与测试） |
| `POST /api/v1/accounts/users/{user_id}/password` | 新增：管理员重置他人密码，仅超级管理员 |

请求 / 响应（`src/cndb/plugins/accounts/schemas/users.py`）：

```python
class UserPasswordResetRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    new_password: str | None = Field(default=None, min_length=6, max_length=128,
                                     description="留空则由服务端生成 12 位随机密码")

class UserPasswordResetResponse(BaseModel):
    ok: bool
    generated_password: str | None = Field(default=None, description="仅自动生成时返回一次")
    revoked_sessions: int
```

### 4. 边界与例外

1. 目标不存在：404「用户不存在」（不泄露更多信息）。
2. 目标为操作人自己：400「不能重置自己的密码，请在个人设置中修改（需校验当前密码）」。
3. 非超级管理员（含 security_admin / audit_admin）：403（复用 `_require_superuser` 文案）。
4. `new_password` 长度不在 6–128：422（Pydantic 约束，与注册 / 自助改密一致）。
5. 目标用户已停用：允许重置（为后续重新启用保留自助恢复路径），但仍吊销其全部会话。
6. 自动生成失败 / 生成器异常：按 500 处理，不写审计、不改密码（`generate_password` 仅用标准库 `secrets`，无网络依赖）。
7. 审计写入失败：仅告警，不回滚已提交的密码重置（I6，沿用 `record_audit` 口径）。
8. 自助端点的错误语义（当前密码错误 / 新旧相同 / 未认证）保持不变。

### 5. 迁移

无（零新表新列；`token_version` 已存在）。因此无 alembic 迁移、无备份格式变化、无旧备份兼容新增。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页签类型 | `frontend/src/store/ui.ts` | `SettingsTab` 增加 `'security'` |
| 个人设置 | `frontend/src/pages/settings/SettingsModal.tsx` | 新增「安全」页签与 `PasswordPanel`：当前密码 / 新密码 / 确认新密码（6–128、两次一致、新旧不同）；成功后 `logout()` + 关闭弹窗 + `navigate('/login')` |
| 管理页 | `frontend/src/pages/admin/UsersPage.tsx` | 桌面操作列与移动卡片增加「重置密码」；弹窗二选一「自动生成（默认）/ 手工输入」；提交前 `modal.confirm` 提示目标全部会话将失效；自动生成成功后在弹窗内一次性展示并可复制 |
| 操作日志 | `frontend/src/pages/admin/UsersPage.tsx` | `ACTION_LABELS` 增加 `password_reset: '重置密码'`；`DiffSummary` 增加重置分支（是否自动生成 / 吊销会话数，不展示密码） |
| API 封装 | `frontend/src/api/auth.ts`、`frontend/src/api/types/accounts.ts` | 新增 `resetUserPassword`、`UserPasswordResetRequest/Response`；审计动作类型联合补充 `password_reset` |

自助改密成功后强制退出：调用既有 `useAuthStore.logout()`（服务端会话已吊销，本地登出仍生效），再跳转 `/login`。

### 7. 测试清单

**判定层（单测）**：

- `reset_user_password` 手工密码：返回 `None`，`target.check_password(新密码)` 为真、旧密码为假，`token_version` +1。
- `reset_user_password` 缺省密码：返回 12 位随机串，长度 / 字符集符合 `generate_password`，且可用该串登录。
- 重置自己：抛 `UserAdminError` 且密码 / `token_version` 均不变。
- 审计：`password_reset` 记录存在，detail 仅 `generated` / `revoked_sessions`，不含密码或哈希。

**接口层**：

- 自助改密：沿用并补强 `test_auth_session.py`（错误旧密码 400、新旧相同 400、成功后旧 access 401 / 旧 refresh 401 / 新密码可登录）。
- 管理重置（自动生成）：200，`generated_password` 非空；目标旧 access / refresh 失效；新密码可登录。
- 管理重置（手工）：200，`generated_password` 为 null；响应体不含手工密码。
- 权限矩阵：普通用户 / security_admin / audit_admin 调用管理端点 403。
- 超管重置自己 400；目标不存在 404；新密码过短 422。
- 审计查询：重置后可按 `action=password_reset` 查到记录，detail 无密码；事件流出现 `user.password_reset`。
- 既有 `tests/test_users_management.py`、`tests/test_users_import_export.py`、`tests/test_auth_*` 全绿。

**迁移 / 备份**：无（零迁移；备份不涉及密码明文格式变化）。

**前端单测**：

- `SettingsModal.test.tsx`：页签数量 / 顺序含「安全」；表单校验（两次不一致、长度不足、与当前密码相同）；成功后调用 `logout` 并跳转登录。
- `UsersPage.test.tsx`：桌面 / 移动端均有「重置密码」入口；自动生成路径提交空密码并展示一次性密码；手工路径提交密码；二次确认文案含会话失效提示；日志抽屉渲染「重置密码」及详情。

**e2e（前端）**：`frontend/tests/e2e/critical/user-password.spec.ts` —— 用管理 API 创建临时用户，验证：①临时用户登录后经个人设置改密，被强制退回登录页且旧密码不可登录；②管理员在用户管理页重置该用户密码，自动生成密码可登录；用例结束禁用临时用户（或删除）避免污染。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端管理重置端点 + 服务层 + schema + 审计 / 事件 + 接口与单测；补强自助改密回归测试 | 低 |
| **P1** | 前端个人设置「安全」页签 + 自助改密强制退出 + 前端单测 | 低 |
| **P2** | 前端用户管理重置入口 / 一次性密码展示 / 日志标签 + e2e + 文档回填 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 自助改密复用既有端点，只补前端；管理员重置新增独立端点 | 后端自助链路已含令牌失效与事件，重复实现会分叉口径（卡片 Q1） | 改用户编辑接口捎带密码（职责混杂、审计语义不清） | `auth.py:331`、`users.py` 新增端点 |
| D2 | 自助改密的前端落点 | 个人设置新增「安全」页签 | 与资料 / 主题等设置同层，入口稳定；避免挤进只读资料表单 | 放进用户资料页签（表单语义混杂）、顶栏独立弹窗（重复挂载） | `SettingsModal.tsx`、`ui.ts:10` |
| D3 | 管理重置的密码来源 | 默认服务端生成 12 位随机密码并仅返回一次；允许手工输入 | 卡片 Q5；复用 `generate_password`，避免第二套规则 | 仅手工输入（弱密码风险高）、仅随机（管理员无法指定） | `users.py`、`user_bulk.py:98` |
| D4 | 管理重置的权限与自我限制 | 仅超管；拒绝作用于操作人自己 | 卡片 Q2；自行重置可绕过当前密码核身 | 允许超管重置自己（核身缺失）、允许 security_admin（超出既有用户管理门控） | `routers/users.py`、`services/users.py` |
| D5 | 改密后的会话策略 | 两条路径统一 `token_version` +1 + `revoke_all` | 卡片 Q3；与既有自助改密一致，防止旧会话继续可用 | 仅吊销刷新令牌（存量 access 仍可用）、仅递增代次（刷新令牌仍可续期） | `auth.py:349-352`、`services/users.py` |
| D6 | 审计与事件 | 新动作 `password_reset`，事件 `user.password_reset`，detail 仅 `{generated, revoked_sessions}` | 卡片 Q7；复用既有 `record_audit` 与 `core_event`，保持跨插件可追溯 | 复用 `update` 动作（无法区分敏感操作）、记录重置原因（卡片 Q7 明确不要） | `services/users.py:63-108`、`core/events.py:53-62` |
| D7 | 是否强制目标用户下次登录改密 | 本期不做 | 卡片 Q6；超出原句范围，无独立标记字段 | 新增 `must_change_password` 列（需迁移与全链路拦截，范围外） | — |
| D8 | 迁移策略 | 零迁移 | 所需字段均已存在 | 新增密码历史表 / 强制改密列（无需求支撑） | — |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：用户可自助改密并立即踢掉旧会话；管理员可在 UI 内重置他人密码，敏感操作进入统一审计 / 事件流。
- **负向**：管理端点响应包含一次性生成密码，前端需明确「只显示一次」的交互约束；新增一个敏感写端点，需要持续关注权限与日志口径。
- **风险与缓解**：自动生成密码可能被管理员误关弹窗而丢失——UI 在结果展示层提供复制按钮并提示可再次重置；会话被吊销可能造成用户困惑——登录页提示「密码已变更，请用新密码登录」。

## 与既有 ADR 的关系

无。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/accounts/services/users.py`、`src/cndb/plugins/accounts/routers/users.py`、`src/cndb/plugins/accounts/schemas/users.py`、`src/cndb/core/events.py` | `tests/test_users_management.py` | `82d9a539` |
| P1 | 已落地 | `frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/store/ui.ts`、`frontend/src/api/auth.ts`、`frontend/src/api/types/accounts.ts` | `frontend/src/pages/settings/SettingsModal.test.tsx` | `82d9a539` |
| P2 | 已落地 | `frontend/src/pages/admin/UsersPage.tsx` | `frontend/src/pages/admin/UsersPage.test.tsx`、`frontend/tests/e2e/critical/user-password.spec.ts` | `82d9a539` |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，`Status` 已置 `Implemented`（实现合入 `82d9a539`，2026-10-27 人工确认）
- 已完成：管理重置端点 + 服务层 + schema + 审计 / 事件 + 接口测试；个人设置「安全」页签 + 强制重新登录；用户管理重置入口 / 一次性密码展示 / 日志标签；e2e 用例已编写
- 下一步：无（本期范围已完成）；e2e 交由 CI 执行
- 已知坑：自助改密端点已存在，勿重复新增；管理重置不得复用 `PATCH /users/{id}`；自动生成的密码只在本次响应中出现一次，审计 detail 不得落密码或哈希；e2e 需 Chromium 系统依赖（本机缺 `libatk-1.0.so.0`，未能在本机跑通，交给 CI）
- 最近一次全绿：`make check-fast`、`make test`、`make cov`、`make frontend-coverage`（2026-10-27）
