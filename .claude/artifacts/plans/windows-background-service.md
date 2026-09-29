# Windows 开机自启后台服务 Implementation Plan

> Status: APPROVED
> Source: .trae/req/req-16-开机自启后台服务.md
> Mode: default
> Iterations: 1 / 3
> Author: dev-plan consensus loop
> Last updated: 2026-09-29

## Requirements summary

Windows 用户开机登录后 cndb 服务自动在后台运行（无窗口），浏览器直接访问管理界面，无需手动开 GUI 或 CLI。开关提供 CLI（`cndb service enable|disable|status|stop`）与 GUI「启动服务」页签复选框双入口，共用同一实现。

## Acceptance criteria

继承 spec AC-1 ~ AC-9（见 .trae/req/req-16-开机自启后台服务.md），验证方式见 Verification steps。

## RALPLAN-DR

### Principles

- 最小代码：复用现有 `serve()` 与 `gui/checks.py`，不为后台模式另起服务实现
- spec In scope 边界：不做系统服务/托盘/守护重启/非 Windows 自启
- CLI 是开关逻辑单一真相源，GUI 只做薄调用
- 可测试性优先：注册表与进程操作收敛为可 monkeypatch 的窄函数

### Decision drivers

- fspack frozen 与源码两种运行形态都要能定位入口可执行文件
- 无管理员权限（HKCU 而非 HKLM）
- 标准库优先（winreg/subprocess），不引入新依赖（暂停条件约束）

### Viable options

**Option A（选定）：HKCU Run 键 + 间接启动入口**
- Run 键 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 值 `cndb` → `"<exe>" service run --host H --port P`；`service run` 以 `CREATE_NO_WINDOW | DETACHED_PROCESS` 派生 `"<exe>" serve ...`（stdout/stderr 重定向到 `~/.cndb/logs/service.log`），写 pidfile 后父进程立即退出
- 改动文件：`src/cndb/cli/service.py`（新建）、`src/cndb/cli/main.py`、`src/cndb/gui/main_window.py`、`tests/test_cli_service.py`（新建）
- Pros：winreg 标准库可读写可测试；无权限要求；间接启动彻底解决控制台窗口；与 dev 子命令既有 taskkill/Popen 模式一致
- Cons：需维护 pidfile；「父进程退出、子进程存活」对用户不可见（靠 status 命令弥补）

**Option B：计划任务 schtasks onlogon**
- `schtasks /create /sc onlogon /tn cndb /tr <命令>` 注册登录触发任务
- Pros：不碰注册表；触发器语义更显式
- Cons：**被否决（invalidation rationale）**——schtasks 无标准库 API、输出本地化文本解析脆弱、测试只能 mock 子进程字符串；且 console 程序经计划任务启动仍可能闪现窗口，同样需要间接启动兜底，复杂度严格高于 Option A 而收益为空

### Implementation steps

1. **新建 `src/cndb/cli/service.py`**，包含：
   - `_exe_command()`：frozen（`cndb.core.config._is_frozen()`）返回 `[sys.executable]`，源码态返回 `[sys.executable, "-m", "cndb.cli.main"]`（main.py L357 已有 `__main__` 分发）
   - `_run_key()` / `_read_run_value()` / `_write_run_value()` / `_delete_run_value()`：winreg 窄封装（HKCU\...\Run，值名 `cndb`），供测试 monkeypatch
   - `_pid_file()`：`cndb.core.config.CACHE_DIR / "service.pid"`；`_pid_alive(pid)`：psutil 不可用则退化为 `tasklist` 查询（Windows）
   - `enable(host, port)`：写 Run 键（覆盖更新，AC-1）
   - `disable()`：删 Run 键，键不存在静默成功（AC-2）
   - `status()`：聚合「自启已启用 + 后台进程存活 + 监听端口」，端口检测复用 `cndb.gui.checks.port_status`
   - `stop()`：读 pidfile → `taskkill /T /F /PID`（与 cli/main.py L118 同模式）→ 删 pidfile；进程已死/文件缺失幂等成功（AC-4）
   - `run(host, port)`：单实例预检（pidfile 存活**或**端口占用则拒绝，AC-5）→ `subprocess.Popen` 派生 serve，`creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS`，stdout/stderr 追加重定向到 `LOG_DIR / "service.log"`（AC-3/7），写 pidfile 后退出
   - `register_service_subparser(sub)`：argparse 注册 enable（`--host/--port`，默认 0.0.0.0/8000，AC-9）/disable/status/stop/run 五个子命令；非 win32 平台各入口统一走 `_require_windows()` 报错退出码 1（AC-8）
2. **改 `src/cndb/cli/main.py`**：
   - L3-10 模块 docstring 子命令清单追加 `service`
   - L320-322 附近在 `register_users_subparser(sub)` 之后调用 `register_service_subparser(sub)`（users.py L 注册模式同款）
   - L344-351 分发链追加 `elif args.command == "service"` 分支
3. **改 `src/cndb/gui/main_window.py` ServeTab**：
   - `_build_layout` L327-346 启动配置区新增一行：`开机自启(后台)` Checkbutton（BooleanVar 初值取 `service.status()` 的自启项，win32 才显示该行，grid 包裹以 `grid_remove`/`grid` 控制可见性）
   - 新增回调 `_toggle_autostart()`：勾选 → `service.enable(self.host_var, self.port_var)`；取消 → `service.disable()`；结果写 `app.log_queue`，失败弹 `messagebox.showerror` 并回滚勾选态（AC-6）
   - ServeConfig/`save_settings`（settings.py L58-100）**不改**：Run 键本身即持久状态，复选框回显走 `status()` 查询
4. **新建 `tests/test_cli_service.py`**：
   - Fake Registry fixture 替身 `_read/_write/_delete_run_value`；参数化 enable/disable/status 幂等与覆盖更新
   - `run()` 用 mock Popen 断言 creationflags 含 CREATE_NO_WINDOW、stdout/stderr 指向 service.log、pidfile 写入
   - `stop()` 对 pidfile 缺失/进程已死两分支幂等断言
   - 非 win32 分支：monkeypatch `sys.platform` 断言非零退出（AC-8 在 CI Linux 上可执行）
5. **设计文件同步**：新建 `.trae/designs/windows-background-service.md`（接口定义/数据模型[Run 键+pidfile]/算法流程/异常处理/依赖项），实现完成即 `[x]`

### Workspace setup

- 实施前运行 `git status --short` + `git branch --show-current`（本 plan 编写时：clean + main）
- 按项目既有约定直接在 main 工作（memory 显示本项目历来直接 main 提交，不使用 worktree），不新建 worktree；实施前若工作区变脏，先核对暂存区按文件分批 add，不混轮次

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| 杀软拦截注册表写 / detached 派生 | enable 失败明确报错并提示手动放行；不静默吞异常 |
| frozen 与源码入口路径解析错误 | `_exe_command()` 双形态分别覆盖，测试对两分支断言 |
| pidfile 残留（断电/强杀） | `_pid_alive` 校验存活，死 pid 视为无实例 |
| 后台服务不可见导致用户困惑 | status 命令 + GUI 复选框回显 + 启动日志落 service.log |
| 非 Windows 误用 | `_require_windows()` 统一拦截，exit 1 + 提示文案 |

## Verification steps

- AC-1/2：`uv run pytest tests/test_cli_service.py -k enable_or_disable`；本机 `uv run cndb service enable && reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v cndb` 后 disable 复查
- AC-3/7：本机 `uv run cndb service run`，确认无窗口、`Get-Content ~/.cndb/logs/service.log` 有 uvicorn 启动记录、浏览器可访问
- AC-4/5：连跑两次 `service run` 断言第二次拒绝；`service stop` 后端口释放；再 stop 幂等
- AC-6：GUI 勾选后 `reg query` 与 CLI enable 结果一致（人工验证，tkinter 不进自动化）
- AC-8：CI Linux 环境跑 `test_cli_service.py::test_non_windows_rejected`
- 全量门禁：`make check`（收尾 + commit 前）

## ADR

- **Decision**: 登录自采用 HKCU Run 键 + `service run` 间接无窗口派生 serve 子进程，开关收敛在 `cndb/cli/service.py` 单模块，GUI 薄调用
- **Drivers**: 标准库可测试性（winreg 优于 schtasks 文本解析）、无管理员权限、fspack 双形态入口、间接启动根治控制台窗口
- **Alternatives considered**: Option B schtasks 计划任务 — rejected（无 API、本地化输出脆弱、仍需间接启动，严格劣于 A）；Windows 系统服务/托盘 — spec 明确 out of scope
- **Why chosen**: 同等功能下改动面最小（1 新模块 + 2 处薄改 + 1 测试文件），零新依赖，全部逻辑可用替身单测
- **Consequences**: 后台进程独立于 GUI 生命周期（GUI 关闭服务仍在）；新增 pidfile/日志两个运行时文件归 CACHE_DIR/LOG_DIR；service.py 是 CLI/GUI 唯一真相源，后续改动不得旁路
- **Follow-ups**: 服务进程崩溃自动守护（不做）；非 Windows 自启（不做）；`--include-config` 类需求出现时再评估

## Review trail

- Planner draft v1: Option A favored，Option B 列为真候选后 invalidation
- Architect challenge v1: steelman「pidfile 不可靠，应改用端口探测作唯一真相」→ 采纳为双重校验（pid 存活 **或** 端口占用都判有实例）；tension「GUI 复选框状态持久化在 ServeConfig vs 查询 Run 键」→ 取查询 Run 键（单一事实源，避免两处状态漂移）
- Critic verdict v1: APPROVED，reservations：① `_pid_alive` 在无 psutil 时走 tasklist 子进程，高频调用偏慢——status 一次性调用可接受，但未来若做轮询需换 OpenProcess；② GUI 复选框勾选失败回滚依赖异常路径，tkinter 事件序需人工验证；③ AC-3 的「重新登录」环节无法自动化，属人工验收项已在 Verification 标注
- Final iterations: 1 / 3
