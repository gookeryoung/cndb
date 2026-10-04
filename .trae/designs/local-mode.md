# local-mode（仅本地单机模式）

需求来源：计划 `.claude/artifacts/plans/local-mode.md`（commit 90f026d，ADR 详见其 Review trail）；`.trae/req/` 无对应需求文件，来源为用户会话内确认的路线 A（单机模式开关）。

## 开关语义

- `Settings.LOCAL_MODE: bool = False`，环境变量别名 `LOCAL_MODE` / `CNDB_LOCAL_MODE`（`AliasChoices`）。
- `False`（默认）时全链路与现网行为一致，既有测试零改动。
- 安全不变量：LOCAL_MODE 与非回环绑定硬性互斥——所有启动入口（CLI serve / service run / GUI Popen / service enable）在启用单机模式时校验 host ∈ {127.0.0.1, localhost, ::1}，否则拒绝启动。

## 接口定义

- `GET /api/v1/accounts/auth/auth-mode`（无认证）→ `AuthModeResponse {"mode": "local" | "jwt"}`，schema 放 `plugins/accounts/schemas/auth.py`。不复用 `/api/health`（运维探针语义不污染）。
- `get_current_user`（api/deps.py）顶部 LOCAL_MODE 分支：忽略 Authorization 头（含同机旧 token，一律归属本地用户——docstring 明示），返回 `_get_local_user(db)`，不再走 AUTH_ENABLED / 401 路径。
- LOCAL_MODE=True 时以下入口返回 403：
  - `POST /auth/register`（detail「单机模式已禁用注册」）、`POST /auth/login`（detail「单机模式已禁用登录」）
  - 公开分享 `GET /public/share/{slug}` 与表单提交 `POST /public/forms/{slug}`——统一在 `_get_public_view` 顶部拦截（两个路由都经过该函数）
  - `POST /wechat-auth/login`——可用条件改为 `WECHAT_AUTH_ENABLED 且非 LOCAL_MODE`
- `cndb serve` 新增 `--local` flag；`--host` default 改为 None：`host = args.host or ("127.0.0.1" if args.local else "0.0.0.0")`。`--local` 或 `settings.LOCAL_MODE` 为真时校验回环并置进程内 `settings.LOCAL_MODE = True`（uvicorn.run 字符串导入共享本进程单例）；非回环报错退出。裸 `cndb` 直启行为不变（补 `args.local = False`）。
- `cndb service enable/run` 新增 `--local`：enable 的 Run 键命令注入 `--local`；run() 派生 serve 子进程前设 `os.environ["CNDB_LOCAL_MODE"]="1"` 并向 serve 传 `--local`（双通道，serve 侧统一校验兜底）。

## 数据模型

- 内置本地用户（惰性 get-or-create，`deps._get_local_user`）：`username='local'`、`nickname='本地用户'`、`is_superuser=True`、`role`/`is_active` 走模型默认、`hashed_password=secrets.token_urlsafe(32)`（不可知，login 已 403 不校验）。审计归属该行，不引入无 User 行的匿名对象。
- `ServeConfig.local_mode: bool = True`（GUI 勾选默认开），序列化进 gui.json `serve.local_mode`；旧配置缺键经 `_apply_section` 回退默认 True。

## 算法与流程

- `_get_local_user`：先查后建；commit 撞 `IntegrityError`（多 worker 并发首建）时 rollback 回退重查，重查必命中；首次创建 `logger.info` 留痕。
- 前端免登录链路：`refresh` 无 token 分支先 `fetchAuthMode()`——local 则无头调 `authApi.me()` 填充 user（后端忽略头）；jwt 维持现状（置 loading=false）。ProtectedRoute / axios 拦截器零改动。
- 防循环双保险：MainLayout 在 `authMode==='local'` 时隐藏「退出登录」菜单项；store `logout` 在 local 模式下改为重新 `refresh()`（不产生 401 循环）。LoginPage 在 local 模式 effect 重定向 `returnTo` 并隐藏注册入口。

## 异常处理

- CLI 回环校验失败：`print` 原因到 stderr + `sys.exit(1)`。
- 模式内 403 detail 统一「单机模式已禁用<行为>」格式。
- `_get_local_user` IntegrityError 回退后重查仍为 None 属理论边界（并发+删户），直接 raise 不吞。

## 依赖项描述

- `core/config.py`（settings 单例）：deps / auth / public / wechat / cli / gui 全部依赖其 LOCAL_MODE 值；测试用 `monkeypatch.setattr(settings, ...)` 配对回滚。
- gui → cli.service.enable(local) 传递勾选态；gui Popen 前 `os.environ["CNDB_LOCAL_MODE"]` 置 "1"/"0"（"0" 防残留）。
- 前端类型 `AuthModeResponse` 与后端 schema 同步（FastAPI 为类型真理源）。

## 验证

- [x] tests/test_local_mode.py：me 无头 200 幂等、auth-mode 双模式、403 矩阵、业务冒烟、IntegrityError 回退替身
- [x] CLI serve host 推导与回环拒绝分支
- [x] GUI ServeConfig roundtrip、service build_run_command --local
- [x] LOCAL_MODE=False 回归：auth-mode 返回 jwt、无头 me 401（并入同一文件）
- [x] make check 全绿（95% cov 门禁 + ruff format + 前端 tsc/vitest）
