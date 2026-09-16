# 注册入口收窄 + cndb users CLI + 批量导入 Spec

> Status: ALIGNED
> Author: gookeryoung
> Last updated: 2026-09-16

## Background

cndb 当前公开注册端点 `/api/v1/auth/register` 后端已静默降级（非 `user` 角色自动转为 `user`），但前端仍完整展示四角色 Radio 选择器，造成用户认知混乱。同时系统缺少运维侧批量创建/删除用户的入口——超级管理员创建用户只能走 API `admin-register`，删用户无任何官方途径，批量导入更无工具。

本次改动将注册入口彻底收窄为"只允许普通用户"，并在服务端 `cndb` CLI 上补齐 `users` 子命令，覆盖单条创建/删除、删除前工作区检查、csv/xlsx 批量导入三个场景。

## In scope

- 前端移除注册页面的角色选择 UI（`RegisterPage.tsx` 去掉 `role` Form.Item + `ROLE_OPTIONS`）
- 后端 `RegisterRequest` schema 移除 `role` 字段，公开注册端点不再接受/处理角色参数
- `cndb users create`：交互式创建单个用户，可指定 `--username --password [--role] [--email] [--nickname] [--is-superuser]`，默认为 `user` 角色
- `cndb users delete <username|id>`：删除前列出该用户作为 **OWNER** 的所有工作区，列出该用户的成员关系数；`--cascade` 级联删除 OWNER 工作区（及子表数据）；不传 `--cascade` 时拒绝删除
- `cndb users import <file>`：从 csv 或 xlsx 批量导入用户，支持字段 `username / password / email / nickname / role`，逐行处理、冲突跳过、生成统计报告
- `cndb users list [--role] [--active]`：列出用户，可按角色/激活状态筛选

## Out of scope

- 用户级别的 CRUD 管理后台（前端管理页面不在本次范围内，CLI 是本次唯一运维入口）
- 用户自行删除自己的账号（需要单独的"注销"端点，另项规划）
- 跨用户的批量**删除** CLI（只有批量**创建**，批量删除高风险暂不开放）
- 审计日志集成（删除操作的审计记录走现有审计插件，本次不新增）
- 工作区 OWNER 转移 CLI（`--transfer-to` 暂不提供，v2 再做；当前只能级联删除或拒绝）

## Assumptions

1. **OWNER 判定**：以 `WorkspaceMember.role == OWNER` 为准，不以 `Workspace.created_by_id` 为准（两者多数情况下一致，但 OWNER 字段经过转移后仍保留，created_by_id 不更新）。
2. **级联删除安全**：删 OWNER 工作区会通过 SQLAlchemy `cascade="all, delete-orphan"` 递归删除关联的 DataTable / Field / Record / Link / ImportTask 等，且不可逆。CLI 必须显式 `--cascade` 才执行。
3. **非 OWNER 工作区**：用户作为普通 MEMBER 的工作区通过 `WorkspaceMember.user_id CASCADE` 自动清理关联行，不影响工作区本身。
4. **created_by_id**：外键定义为 `ONDELETE SET NULL`，删除用户后该字段自动置空，无副作用。
5. **批量导入角色**：CLI import 允许指定任意角色（含三员 + user），因为 CLI 是运维侧操作，调用者已具备服务端文件系统访问权限，等价于超级管理员。
6. **批量导入失败策略**：逐行处理；`username` 冲突、`role` 非法、密码过短等均跳过并记录；全量不回滚；最后一行汇总 `N 成功 / M 跳过 / K 失败` + 失败详情（行号 + 原因）。
7. **CSV 密码列**：留空时自动生成 12 位随机密码（字母+数字），在最终报告中打印；CLI 不主动强制"下次登录改密码"——这是独立功能（password reset），本次不做。
8. **xlsx 支持**：项目依赖已包含 `openpyxl>=3.1.5`，直接用；csv 用标准库 `csv`。表头字段用 `headers.lower().strip()` 做宽松匹配（`Role` / `role` / "用户角色" 等都可识别）。
9. **CLI 权限**：`cndb users` 子命令是**本地运维工具**，不走 API 鉴权——直接操作数据库，只要 `DATABASE_URL` 可用即可。不要求登录态。

## Solution

### 1. 前端注册页收窄

文件：`frontend/src/pages/auth/RegisterPage.tsx`

- 删掉 `ROLE_OPTIONS` 常量、`RegisterFormValues.role` 字段、Radio.Group Form.Item、role hint Text
- 删掉 `initialValues={{ role: ... }}` 中的 role 键
- 删掉 role 相关 TS 类型引用（`UserRole`）
- 注释更新为"公开注册 → 仅普通用户；三员账号由超级管理员通过 `cndb users create --role xxx` 创建"

不做：API 层面强制拒绝 `role` 参数（后端 `RegisterRequest` 会移掉 role，传了会 pydantic 校验报错，正好是预期行为）。

### 2. 后端 RegisterRequest 去 role

文件：`src/cndb/plugins/accounts/schemas/auth.py`

- `RegisterRequest` 删除 `role` 字段（默认 user 已在 User 模型里）
- 删除 `PUBLIC_REGISTERABLE_ROLES` 常量（不再需要降级逻辑）
- `AdminRegisterRequest` 独立保留 role 必填（管理员创建不受影响）

文件：`src/cndb/plugins/accounts/routers/auth.py`

- `register()` 端点去掉 role 降级逻辑块，简化为"确保唯一 → 建 User → set_password → commit"

### 3. cndb users CLI

新建模块（建议路径 `src/cndb/cli_users.py`，保持 `__init__.py` 纯净），在 `runner.py` 注册子命令。

```
cndb users create
  -u, --username   必填
  -p, --password   留空则自动生成 12 位
  -e, --email      可选
  -n, --nickname   可选
  -r, --role       默认 user，可选 system_admin / security_admin / audit_admin / user
  --superuser      设置 is_superuser=True（危险操作，打印 WARNING）

cndb users delete
  <username|id>    必填
  --cascade        级联删除该用户作为 OWNER 的工作区（危险操作）
  --yes            跳过二次确认（供脚本调用）

cndb users import
  <file>           csv 或 xlsx，按后缀或 magic 自动识别
  --dry-run        只做校验、不实际写入
  --encoding       csv 编码，默认 utf-8（fallback gbk）

cndb users list
  -r, --role       可选，按角色筛选
  --active         只列出 is_active=True
  --inactive       只列出 is_active=False
```

**删除流程细节**：

```
cndb users delete gookeryoung

[info] 查找用户 gookeryoung ... found (id=7, role=system_admin, is_superuser=True)
[warn] 目标用户是 superuser，继续前请确认
[info] 查询 OWNER 工作区: 3 个
  - #12 生产数据 (tables=8, members=12)
  - #25 测试工作区 (tables=2, members=3)
  - #31 临时工作区 (tables=0, members=1)
[info] 查询成员关系: 7 条（将通过外键自动清理）
[warn] 未传 --cascade，拒绝删除。该用户拥有 3 个工作区。
      加 --cascade 将级联删除上述工作区（不可逆）。
```

加 `--cascade` 后要求 `--yes` 或交互确认 `[y/N]`，然后打印删除汇总。

**批量导入表头宽松映射**：

| 内部字段 | 接受的表头（不区分大小写、前后空格） |
|---|---|
| username | username / 用户名 / login |
| password | password / 密码 / pwd |
| email | email / 邮箱 |
| nickname | nickname / 昵称 / display_name |
| role | role / 角色 / user_role |

### 4. db Session 获取

CLI 不走 FastAPI `get_db` Depends，直接 `from cndb.core.database import SessionLocal` 打开一个 session，命令结束时关闭。环境初始化沿用 `cndb.core.config.settings`（会自动读 `DATABASE_URL` 等）。

## Edge cases & risks

| Category | Notes |
|---|---|
| Boundary conditions | 删用户时最后一个 OWNER 工作区——级联删；批量导入 role 非法（写了 `administrator`）——该行跳过并在报告中说明；csv 无 password 列——该行自动生成密码 |
| Failure modes | `cndb users create` 时 username 冲突 → 直接报错退出，不创建；`import` 中途数据库连接断开 → 已提交的行保留（逐行 commit），剩余行失败并汇总 |
| Risks | `cndb users delete --cascade` 是不可逆操作，必须有交互确认 + `--yes` 才绕过 |
| Mitigation | `--cascade` 强制配合 `--yes` 或交互式 y/N；import 支持 `--dry-run` 预演；所有 CLI 操作打印操作前/后的统计数据 |

## Acceptance criteria

- AC-1 前端注册页面不包含任何角色选择 UI（Radio.Group / role Form.Item / ROLE_OPTIONS）
- AC-2 前端注册请求 payload 不包含 role 字段；`AdminRegisterRequest` 在 `/auth/admin-register` 路径中正常工作
- AC-3 `RegisterRequest` schema 不含 role 字段，公开注册端点 `/auth/register` 提交含 role 的 JSON 会触发 pydantic 校验错误（422）
- AC-4 `cndb users create -u alice -p xxx` → 创建 role=user 普通用户；`-r system_admin` → 创建系统管理员
- AC-5 `cndb users create -u alice -p`（空密码）→ 自动生成 12 位密码并打印
- AC-6 `cndb users delete <user>`（用户是 3 个工作区 OWNER）→ CLI 列出 3 个工作区并拒绝删除，提示加 `--cascade`
- AC-7 `cndb users delete <user> --cascade --yes` → 级联删除 OWNER 工作区 + 清理成员关系 + 用户本身，并打印汇总
- AC-8 `cndb users import users.csv`（csv 含 10 行，2 行 username 冲突，1 行 role 非法，7 行合法）→ 输出 `ok=7 skipped=2 failed=1` 并逐行说明原因
- AC-9 `cndb users import users.xlsx`（openpyxl 依赖已在 pyproject.toml）→ 正常解析 xlsx 并按 AC-8 输出
- AC-10 `cndb users import --dry-run users.csv` → 只打印解析/校验报告，不写入数据库
- AC-11 `cndb users list` → 打印用户表格，支持 `--role` / `--active` / `--inactive` 筛选
- AC-12 所有新增 CLI 子命令和函数有 pytest 覆盖，`make check`（ruff + pyrefly + pytest-cov）全绿

## Open questions

- `--transfer-to`（转移 OWNER 给其他用户）本次不做，是否在迭代记录中标记 v2 待办？**已在 Out of scope 声明，标记 v2**

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| User | ORM (accounts_user) | id, username, role, is_superuser, is_active | 多对多 Workspace（通过 WorkspaceMember） |
| Workspace | ORM (workspaces_workspace) | id, name, created_by_id | 一对多 DataTable；多对多 User |
| WorkspaceMember | ORM (workspaces_workspacemember) | workspace_id, user_id, role | 关联 User ↔ Workspace |
| cndb users CLI | argparse 子命令组 | create / delete / import / list | 调用 accounts / workspaces ORM 直接操作 DB |

## Interview metadata

- Mode: dev-spec (--spec-only)
- Waves: 1
- Final ambiguity: 26.5%
- Status: EARLY_EXIT_BY_RECOMMENDATION（歧义已低于 default 退出线 30%，剩余用合理默认锚定）

### Clarity breakdown

| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.8 | 0.40 | 0.32 |
| Scope | 0.7 | 0.25 | 0.175 |
| AC | 0.6 | 0.25 | 0.15 |
| Context | 0.9 | 0.10 | 0.09 |

### 关键决策（本次 spec 内）

1. 删除边界：只处理 OWNER 工作区，通过 `--cascade` 级联删除
2. batch import 失败策略：逐行 + 不回滚 + 冲突跳过 + 报告汇总
3. CLI 不走 API 鉴权，直接操作 DB（运维侧工具，等价超级管理员）
4. role 宽松匹配（表头不区分大小写 + 别名）
