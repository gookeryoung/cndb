# local-mode（仅本地单机模式）Implementation Plan

> Status: APPROVED
> Source: user request（路线 A：单机模式开关，经 AskUserQuestion 确认：免登录自动单用户、网络特性模式内禁用、交付重点为数据安全默认 + GUI 一键启动体验）
> Mode: --deliberate（涉鉴权改造，自动升级）
> Iterations: 2 / 3
> Author: zhou
> Last updated: 2026-10-03

## Requirements summary

cndb 当前为多用户网络平台定位，本地单机使用存在登录摩擦与 0.0.0.0 默认暴露两大问题。本计划新增 `LOCAL_MODE` 单开关：免登录自动单用户（内置本地用户）、强制仅回环绑定、模式内禁用公开分享/注册/微信登录入口；现有多用户与部署能力全保留，开关关闭即完全回到现网行为。

## Acceptance criteria

- AC-1: `LOCAL_MODE=True` 时，无 Authorization 头 `GET /api/v1/accounts/auth/me` 返回 200 与内置本地用户（幂等，重复调用同一 id）
- AC-2: 无认证 `GET /api/v1/accounts/auth/auth-mode` 返回 `{"mode":"local"}`；`LOCAL_MODE=False` 时返回 `{"mode":"jwt"}`
- AC-3: `LOCAL_MODE=True` 时 `POST /auth/register`、`POST /auth/login`、`GET /api/v1/public/share/{slug}`、`POST /wechat-auth/login` 均返回 403
- AC-4: `cndb serve --local --host 0.0.0.0` 立即报错退出；`cndb serve --local`（未显式 host）绑定 127.0.0.1
- AC-5: cndbw 勾选「单机模式」启动后，浏览器打开直达工作区列表（无 /login 跳转）；取消勾选重启后回到登录流程
- AC-6: `LOCAL_MODE=False`（默认）下既有全部测试零改动通过（现网行为完全不变）
- AC-7: `make check` 全绿（含 95% 覆盖门禁、ruff format、前端 tsc/vitest）

## RALPLAN-DR

### Principles

1. **开关而非分支**：所有新行为由 `settings.LOCAL_MODE` 单开关控制，False 时全链路与现状逐字节一致，不删任何既有能力
2. **最小代码**：复用既有资产——public 路由无认证先例、`CNDB_DATA_DIR` 环境变量通道模式、GUI settings 序列化、`get_optional_user` 形态
3. **安全不变量**：local 模式与网络暴露硬性互斥——非回环绑定直接拒绝启动，而非仅改默认值
4. **单一真相源**：auth 模式由后端下发（auth-mode 端点），前端只消费不推断
5. **审计可归因**：本地操作归属内置用户行（username='local'），不引入无 User 行的匿名对象（避免破坏 user_id NOT NULL 外键遍布的数据层）

### Decision drivers

1. 开箱即用体验：零登录摩擦（用户确认免登录，决定性）
2. 安全默认：不存在局域网匿名超管暴露面（用户勾选交付重点，决定性）
3. 现有能力零破坏：多用户/等保/Docker 部署不动（用户确认模式内禁用而非移除）
4. 维护成本：改动收敛于 `deps.py` 单点 + 前端 store 单分支

### Viable options

**Option A1: 匿名→本地用户映射 + auth-mode 端点探测**（chosen）
- 思路：后端 `get_current_user` 在 LOCAL_MODE 时返回惰性 get-or-create 的内置 local 用户；新增无认证 auth-mode 端点；前端 refresh 无 token 时探测，local 则无头调 `me` 填充 user
- 改动文件：`api/deps.py`、`core/config.py`、`plugins/accounts/routers/auth.py`、`plugins/tables/routers/public.py`、`plugins/wechat_auth/routers/login.py`、`cli/main.py`、`cli/service.py`、`gui/settings.py`、`gui/main_window.py`、`frontend/src/api/auth.ts`、`frontend/src/api/types.ts`、`frontend/src/store/auth.ts`、`frontend/src/pages/auth/LoginPage.tsx`、`frontend/src/layouts/MainLayout.tsx`
- Pros: ProtectedRoute/axios 拦截器/RBAC 数据层零改动（user 正常填充）；无 token 生命周期问题（永不过期）；审计归属明确
- Cons: 前端冷加载多一次 auth-mode 探测请求；「用户」语义上是内置账号

**Option A2: 启动签发非过期 token + 前端自动登录**
- 思路：公开端点返回本地用户的非过期 JWT，前端自动获取并走既有 login 持久化链路
- invalidate rationale: 引入「非过期 JWT」新语义违背 `JWT_EXPIRE_MINUTES` 既有契约；token 仍需持久化与失效边界处理；多一个公开端点扩大攻击面——复用收益小于新增复杂度

**Option A3: 前端旁路登录（user 保持 null）**
- 思路：ProtectedRoute 在 local 模式直接渲染 children
- invalidate rationale: 数据层普遍直接访问 `current_user.id`（`workspaces.py:74`、`tables.py:117`），user=null 引发 500；MainLayout 用户菜单等大量组件依赖 user——不可行

**本地用户身份子设计**：`username='local'`、`nickname='本地用户'`、`is_superuser=True`、`role='user'`、`hashed_password=secrets.token_urlsafe(32)`（不可知，login 已 403）；get-or-create 先查后建 + IntegrityError 回退重查（多 worker/并发首建防线）。

## Implementation steps

后端（行为核心）：

1. `src/cndb/core/config.py:145` — Settings 类 `AUTH_ENABLED` 后新增 `LOCAL_MODE: bool = False`（docstring 注明：单机模式、强制回环绑定、与 AUTH_ENABLED 的关系）
2. `src/cndb/api/deps.py:41-59` — 新增 `_get_local_user(db)`（get-or-create username='local'，IntegrityError 回退重查，首次创建 logger.info）；`get_current_user` L62-97 顶部插入 LOCAL_MODE 分支：直接返回本地用户、忽略 Authorization 头、不再 401
3. `src/cndb/plugins/accounts/routers/auth.py` — 新增无认证路由 `GET /auth-mode` 返回 `{"mode": "local"|"jwt"}`（response_model 加 `AuthModeResponse`，schema 放 accounts 的 schemas 模块）；`register` L67、`login` L138 入口加 `settings.LOCAL_MODE → 403`（detail：「单机模式已禁用注册/登录」）；`me` L161-166 不动（get_current_user 已返回本地用户）
4. `src/cndb/plugins/tables/routers/public.py:18-26` — `_get_public_view` 顶部加 `settings.LOCAL_MODE → 403`（分享路由统一过此函数；实施时确认表单提交路由 L139 是否同路，例外则单独补）
5. `src/cndb/plugins/wechat_auth/routers/login.py:61-62` — 可用条件改为 `WECHAT_AUTH_ENABLED 且非 LOCAL_MODE`

CLI / 服务（安全不变量落地）：

6. `src/cndb/cli/main.py:253-257` — `serve` 子命令加 `--local` flag；`--host` default 改 None；`serve()` L90-101 内：`host = args.host or ("127.0.0.1" if args.local else "0.0.0.0")`；`args.local` 或 `settings.LOCAL_MODE` 为真时校验 host 属于 {127.0.0.1, localhost, ::1}，非回环直接报错退出；`--local` 时 in-process `settings.LOCAL_MODE = True`（uvicorn.run 字符串导入共享本进程单例）；裸 `cndb` L332-337 行为不变（help 文本同步更新）
7. `src/cndb/cli/service.py:267,275` — `enable()` 扩展 local 参数：自启命令注入 `CNDB_LOCAL_MODE=1`，并校验 host 回环

GUI（一键启动）：

8. `src/cndb/gui/settings.py:30-36` — `ServeConfig` 加 `local_mode: bool = True`；`to_dict` L73-78 补该键（`_apply_section` 自动兼容旧配置缺失回退默认）
9. `src/cndb/gui/main_window.py` — ServeTab 加「单机模式」Checkbutton（说明文字：免登录、仅本机访问）；`start_server` L495-503：勾选时 host 强制 127.0.0.1（非回环输入弹提示并锁定）、Popen 前 `os.environ["CNDB_LOCAL_MODE"]="1"`（取消勾选置 "0"，防残留）；`toggle_autostart` L613-634：local_mode 传入 `enable()`；`persist` L663-668 补存 local_mode；`open_browser` L655-661 不动（免登录后自然直达工作区）

前端（免登录链路）：

10. `frontend/src/api/types.ts` + `frontend/src/api/auth.ts` — 新增 `AuthModeResponse` 类型与 `fetchAuthMode()`（FastAPI 为类型真理源，两侧同步）
11. `frontend/src/store/auth.ts:27-51` — AuthState 加 `authMode: 'local'|'jwt'|null`；`refresh` 无 token 分支：先 `fetchAuthMode()`，local 则调 `authApi.me()`（无有效 token，LOCAL_MODE 后端忽略头）填充 user，jwt 则维持现状（置 loading=false）；`logout` 在 local 模式下改为重新 refresh（语义自洽，防循环）——或按 MainLayout 隐藏入口双保险
12. `frontend/src/pages/auth/LoginPage.tsx` — `authMode==='local'` 时 effect 重定向 `/`；注册入口（如有，实施时确认）隐藏
13. `frontend/src/layouts/MainLayout.tsx:161` — local 模式下用户菜单隐藏「退出登录」项

## Workspace setup

- 实施前运行 `git status --short` 与 `git branch --show-current`（当前：干净 / main）。
- 本计划涉及 14+ 文件（后端/CLI/GUI/前端/测试），且当前在 main 分支：**推荐创建 worktree**（`git worktree add -b codex/local-mode ../cndb-local-mode`），实施开始前需用户确认。
- 若用户选择直接在 main 干：保证每轮迭代结束 `make check` 绿后再 commit。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| local 模式跑在 0.0.0.0 → 局域网匿名超管暴露 | CLI `serve()` 校验（覆盖 --local flag 与 env 两种来源）+ GUI 勾选时锁定回环 + `cli/service.py` enable() 校验，四入口全覆盖 |
| `_get_local_user` 并发首建撞 unique 约束（uvicorn workers>1） | 先查后建 + IntegrityError 回退重查；测试覆盖幂等 |
| 老用户升级 GUI 后 host 被锁 127.0.0.1 行为突变 | 界面说明文字 + 启动日志「单机模式已启用（仅本机可访问）」+ README 升级说明；取消勾选即恢复 |
| 前端 token=null 时 axios 拦截器注入异常头 | 实施时确认 `client.ts` 拦截器 null 处理；LOCAL_MODE 后端忽略头，无害兜底 |
| settings 单例在测试间污染 | pytest fixture monkeypatch set/teardown 强制配对；GUI/CLI 测试各自隔离 env |
| gui.json 旧配置无 local_mode 键 → 静默切换 | `_apply_section` 回退 True 属产品定位预期；GUI 日志显式输出一行切换提示 |

## Verification steps

- AC-1/2/3: 运行新增 `tests/test_local_mode.py`（pytest，fixture 临时库 + monkeypatch）
- AC-4: CLI 单测覆盖 `serve --local --host 0.0.0.0` 错误分支与默认 host 推导
- AC-5: 手动路径——cndbw 勾选启动 → 浏览器直达工作区；取消勾选重启 → 回登录页（e2e 可选补）
- AC-6: `make check` 既有测试套零改动全绿
- AC-7: `make check`（95% cov 门禁 + ruff format + 前端 tsc/vitest，注意 make 需 disable sandbox 运行）

## Pre-mortem

1. **Scenario**: 局域网团队升级 cndbw 后「服务失联」——同事访问 8000 全部超时。
   **Trigger**: GUI 升级后首次启动，local_mode 默认 True 锁定 127.0.0.1。
   **Mitigation**: ServeTab 说明文字 + 启动日志明示 + README 升级须知；取消勾选即恢复局域网+登录模式。
2. **Scenario**: 匿名超管暴露——用户手动 `set CNDB_LOCAL_MODE=1` 后 `cndb serve --host 0.0.0.0`，同网段任意设备免登录全权操作。
   **Trigger**: 环境变量与显式 host 组合，绕过 GUI 锁定。
   **Mitigation**: `serve()` 内统一校验（不区分 LOCAL_MODE 来源是 flag/env/直赋值），非回环绑定拒绝启动并输出原因。
3. **Scenario**: 存量库切 local 模式后审计归属混乱——历史操作归 admin/demo，新操作全归「本地用户」。
   **Trigger**: 已有多用户库首次以 local 模式启动。
   **Mitigation**: 接受为单机定位的合理语义；`_get_local_user` 首建 logger.info 留痕；README 说明。无法接受时用户关闭 local 模式即回多用户审计。

## Expanded test plan

- **Unit**: `_get_local_user` 幂等/字段断言/IntegrityError 回退（替身注入撞约束场景）；`ServeConfig.local_mode` 序列化 roundtrip；CLI host 推导与回环校验纯函数分支
- **Integration**: local 模式行为矩阵——无头 me 200、auth-mode `{"mode":"local"}`、register/login/share/wechat 403、业务链冒烟（创建工作区→建表→写行 200）；`LOCAL_MODE=False` 回归（auth-mode `jwt`、无头 me 401）
- **E2E**（可选，最后轮）: local 模式启动 → 首页直达工作区列表无 /login 跳转；GUI 取消勾选 → 回登录流程
- **Observability**: 本地用户首建 logger.info；`serve --local` 启动日志一行「单机模式：127.0.0.1 免登录」；auth-mode 端点访问不记敏感信息

## ADR

- **Decision**: 新增 `LOCAL_MODE` 单开关——无认证请求映射到惰性创建的内置本地用户（is_superuser）、强制回环绑定（四入口校验）、模式内 403 禁用注册/登录/分享/微信；前端经 auth-mode 端点探测后免登录填充用户态。
- **Drivers**: 开箱即用体验与安全默认（决定性）；现有能力零破坏（用户明确要求模式内禁用而非移除）
- **Alternatives considered**: A1 匿名映射（chosen）；A2 非过期 token（rejected：新语义+攻击面+复杂度）；A3 前端旁路 user=null（rejected：数据层 500）；复用 /api/health 下发 auth_mode（rejected：污染运维探针语义）；路线 B 最小收紧（rejected：不解决登录摩擦）；路线 C 简化产品线（rejected：不可逆删除既有能力）
- **Why chosen**: 前端与数据层全链路对 user 的既有假设零破坏，改动收敛于 deps.py 单点；无 token 生命周期问题；安全不变量可被四入口校验硬性保证。
- **Consequences**: 正——本地开箱即用、默认不暴露局域网、现网模式完全不变；负——新增双模式测试矩阵（已收敛为差异面测试）、登录页/注册在 local 模式不可达、审计归属统一为内置用户。
- **Follow-ups**: fspack 打包发布流程打通（用户本次未选）；e2e local 模式全链路用例；虚拟机宿主机访问场景（局域网模式）文档补充；`_force_release_by_name` 等既有运维路径与 local 模式的交互说明。

## Review trail

- Planner draft v1: Option A1（匿名映射 + 复用 /api/health 下发 auth_mode）；安全仅到「默认 127.0.0.1」层
- Architect challenge v1: steelman「health 语义污染」→ 改独立 auth-mode 端点；tension「安全不变量 vs 灵活性」→ 回环硬校验；tension「测试矩阵 vs 覆盖门禁」→ 差异面测试
- Critic verdict v1: REVISE — health 复用不当（P1）、安全不变量非硬性（P1）、并发首建无防线（P1）
- Planner draft v2: 采纳全部修正——独立 auth-mode 端点、四入口回环校验、IntegrityError 回退、观测日志
- Critic verdict v2: APPROVED with 3 reservations（见下）
- Final iterations: 2 / 3

### Critic reservations（APPROVED 保留项）

1. `get_current_user` 在 LOCAL_MODE 下完全忽略 Authorization 头——同机持有旧 token 的请求也会归属本地用户；接受，但 docstring 必须明示该语义
2. IntegrityError 回退是多 worker 下的必要防线，不可在实施中以「SQLite 写锁串行」为由省略
3. gui.json 存量用户静默切换仅靠文档兜底偏弱，GUI 日志必须输出显式切换提示行
