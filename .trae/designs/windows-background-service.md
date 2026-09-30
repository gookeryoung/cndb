# Windows 开机自启后台服务设计

> 来源：`.trae/req/req-16-开机自启后台服务.md`
> 状态：已实现（`[x]`），对应 commit 见 git log

## 接口定义

CLI 子命令（`cndb service <sub>`，注册于 [src/cndb/cli/service.py](file:///f:/Dev/cndb/src/cndb/cli/service.py) `register_service_subparser`，分发 `service_command`）：

- `cndb service enable [--host H] [--port P]`：写 HKCU Run 键（默认 0.0.0.0:8000）；已存在则覆盖更新；返回写入的命令行。
- `cndb service disable`：删除 Run 键条目；不存在时幂等成功。
- `cndb service status`：输出自启状态 / 后台进程状态 / 固化端口。
- `cndb service stop`：终止后台进程并清理 pidfile；无实例时幂等成功。
- `cndb service run [--host H] [--port P]`：自启入口（Run 键调用）：无窗口派生 `serve` 子进程后父进程退出；已有实例或端口占用时返回 1 拒绝。

公共 API（供 GUI 调用）：

- `enable(host: str, port: int) -> str` / `disable() -> None` / `autostart_enabled() -> bool`
- `collect_status() -> ServiceStatus`（dataclass：autostart/running/pid/port/command）
- `run(host: str, port: int) -> int`（0 成功 / 1 拒绝）
- `stop() -> bool`（是否实际终止存活进程）

GUI 入口（[src/cndb/gui/main_window.py](file:///f:/Dev/cndb/src/cndb/gui/main_window.py) `ServeTab`）：启动配置区「开机自启(后台)」复选框（仅 `sys.platform == "win32"` 渲染），勾选态回显 `autostart_enabled()` 实际注册表状态；`toggle_autostart` 勾选时按 Host/Port 输入框当前值 `enable`，取消时 `disable`，异常弹 `messagebox.showerror` 并在 finally 回滚为实际状态。ServeConfig 不新增字段——Run 键本身即持久状态。

## 数据模型

- Run 键：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，值名 `cndb`，REG_SZ，内容为 `"<exe>" service run --host <H> --port <P>`（`subprocess.list2cmdline` 生成）。
- 入口命令：frozen（fspack 安装版，`_is_frozen()`）为 `[sys.executable]`；源码态为 `[sys.executable, "-m", "cndb.cli.main"]`。
- pidfile：`<DATA_DIR>/cache/service.pid`，内容为服务进程 pid 十进制字符串。
- 服务日志：`<DATA_DIR>/logs/service.log`，子进程 stdout/stderr 以 `ab` 追加重定向。
- 无数据库 schema 变更，无迁移。

## 算法与流程

- enable：`build_run_command` → `_write_run_value`（CreateKeyEx + SetValueEx）。
- run 单实例保护（双重校验，任一命中即拒绝）：① pidfile 存在且 `_pid_alive(pid)` 为真；② `cndb.gui.checks.port_status(port, host).used` 为真（checks 无 tkinter 依赖，可从 CLI 复用；host 须与服务绑定地址一致，Windows 下 wildcard 绑定被占时 specific-IP 仍可绑定成功）。
- run 派生：`subprocess.Popen([*_exe_command(), "serve", ...], stdin=DEVNULL, stdout=SERVICE_LOG.open("ab"), stderr=STDOUT, creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)`，随后写 pidfile、打印确认并退出；非 Windows 不传 creationflags。
- `_pid_alive`：委托 `cndb.gui.checks._pid_alive`——Windows 用 Win32 API（`OpenProcess`+`GetExitCodeProcess`）判定，不调用 `tasklist` 子进程（该命令在部分会话环境启动即失败 0xc0000142 并弹系统模态错误框）；句柄打不开时按最后错误码区分：PID 不存在（ERROR_INVALID_PARAMETER）判死，权限不足等保守判活。POSIX 用 `os.kill(pid, 0)`（ProcessLookupError→False，PermissionError→True）。
- stop：读 pidfile → 存活则 `taskkill /T /F /PID`（POSIX `os.kill(pid, 15)`）→ 删 pidfile。pidfile 缺失或 pid 已死均幂等。
- `stop_port_occupant`（checks，GUI 启动前端口清理）：按镜像名强杀兜底——当 netstat 归属 PID 已死但端口仍被继承句柄占用，或终止记录 PID 后端口仍未释放时，枚举镜像名前缀为 python/uvicorn/node 的存活进程（Windows 用 Toolhelp 快照，不依赖 tasklist，规避 0xc0000142 模态框；POSIX 用 `ps`），排除自身与记录 PID 后逐一 `taskkill/kill`，轮询确认端口释放；未释放（或无可终止对象）时按残留条目归因提示。

## 异常处理

- 非 Windows 平台：`service_command` 入口统一拦截，stderr 提示「仅支持 Windows」并以退出码 1 结束。
- winreg 所有操作仅捕 `FileNotFoundError`（读/删未注册条目视为 None/幂等）；其余 OSError（如杀软拦截）向上抛出，CLI 直接失败、GUI 弹窗并回滚勾选态。
- `read_pid` 捕 `(FileNotFoundError, ValueError)` 返回 None（pidfile 残留/损坏视为无实例）。
- 退出码约定：run 拒绝=1、缺子命令=2、平台不支持=1。

## 依赖项描述

- 仅依赖标准库（winreg 延迟导入于函数体内，保证模块在非 Windows 可导入）；不新增第三方依赖。
- 复用 `cndb.core.config`（CACHE_DIR/LOG_DIR/_is_frozen）与 `cndb.gui.checks.port_status`。
- 跨模块不变量：`service.py` 是 CLI 与 GUI 开关的唯一真相源，禁止旁路直写注册表；GUI 关闭不影响后台服务进程（二者生命周期独立）。
- 与 fix-09 局域网绑定约定一致：enable 默认 0.0.0.0，`--host 127.0.0.1` 可仅本机访问。

## 勾选清单

- [x] CLI service 子命令（enable/disable/status/stop/run）
- [x] HKCU Run 键读写窄封装与幂等语义
- [x] 无窗口间接启动 + pidfile 单实例保护
- [x] GUI ServeTab 开机自启复选框
- [x] 单元测试（tests/test_cli_service.py，21 用例）
- [x] 非 Windows 平台拦截
