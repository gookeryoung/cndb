"""cndb service 子命令 —— Windows 开机自启后台服务管理.

子命令：
- enable    写入 HKCU Run 键（登录后自动启动后台服务，可 --host/--port 固化）
- disable   删除 Run 键（幂等）
- status    查看自启状态与后台服务进程状态
- stop      停止后台服务进程（幂等）
- run       自启入口：无窗口派生 `cndb serve` 子进程后退出（供 Run 键调用）

实现约束：
- 仅依赖标准库（winreg / subprocess），不引入新依赖；
- 注册表与进程探测收敛为窄函数（_read_run_value 等），供单元测试替身替换；
- 仅支持 Windows，其他平台在 service_command 入口统一拦截。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess  # nosec B404 - service 子命令需管理服务子进程，命令均来自内部构造
import sys
from dataclasses import dataclass
from typing import Any

from cndb.core.config import CACHE_DIR, LOG_DIR, _is_frozen
from cndb.gui import checks

# ── 常量 ──────────────────────────────────────────────────────

# HKCU Run 键路径与值名（登录后按值启动，无需管理员权限）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "cndb"

# 后台服务 pid 文件与日志文件（运行时产物归 CACHE_DIR / LOG_DIR）
PID_FILE = CACHE_DIR / "service.pid"
SERVICE_LOG = LOG_DIR / "service.log"

_PORT_RE = re.compile(r"--port (\d+)")


@dataclass
class ServiceStatus:
    """后台服务聚合状态.

    Attributes:
        autostart: Run 键是否已注册开机自启。
        running: pidfile 指向的服务进程是否存活。
        pid: 服务进程 pid（未运行时为 None）。
        port: Run 键命令中固化的端口（未注册时为 None）。
        command: Run 键存储的完整命令行（未注册时为 None）。
    """

    autostart: bool
    running: bool
    pid: int | None = None
    port: int | None = None
    command: str | None = None


# ── 注册表窄封装（测试用替身替换这三个函数即可）──────────────


def _read_run_value() -> str | None:
    """读取 HKCU Run 键中 cndb 条目的命令行；未注册返回 None."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None


def _write_run_value(command: str) -> None:
    """写入/覆盖 HKCU Run 键中 cndb 条目（REG_SZ）."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)


def _delete_run_value() -> None:
    """删除 HKCU Run 键中 cndb 条目；不存在时静默成功."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


# ── 进程探测窄封装 ────────────────────────────────────────────


def _run_cmd(cmd: list[str]) -> tuple[int, str]:
    """执行系统命令返回 ``(returncode, stdout)``；OSError 视为失败."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec - 命令来自内部常量
        return proc.returncode, proc.stdout or ""
    except OSError:
        return -1, ""


def _pid_alive(pid: int) -> bool:
    """判断进程是否存活.

    委托 ``cndb.gui.checks`` 的 Win32 实现：Windows 不再调用 tasklist 子进程
    （规避其 DLL 初始化失败 0xc0000142 时弹出的系统模态错误框）；
    POSIX 用 ``os.kill(pid, 0)`` 探测（权限不足视为存活，进程不存在视为死亡）。
    """
    return checks._pid_alive(pid)


# ── 核心操作 ──────────────────────────────────────────────────


def _exe_command() -> list[str]:
    """返回当前运行形态的 cndb 入口命令前缀.

    frozen（fspack 安装版）直接用可执行文件本身；源码态经
    ``python -m cndb.cli.main`` 进入（main.py 有 ``__main__`` 分发）。
    """
    if _is_frozen():
        return [sys.executable]
    return [sys.executable, "-m", "cndb.cli.main"]


def build_run_command(host: str, port: int) -> str:
    """构造写进 Run 键的命令行字符串（登录时由系统执行）."""
    cmd = [*_exe_command(), "service", "run", "--host", host, "--port", str(port)]
    return subprocess.list2cmdline(cmd)


def enable(host: str, port: int) -> str:
    """注册开机自启（已存在则覆盖更新）.

    Args:
        host: 服务绑定地址。
        port: 服务端口。

    Returns:
        写入的命令行字符串。
    """
    command = build_run_command(host, port)
    _write_run_value(command)
    return command


def disable() -> None:
    """取消开机自启；Run 键不存在时幂等成功."""
    _delete_run_value()


def autostart_enabled() -> bool:
    """Run 键是否已注册 cndb 开机自启."""
    return _read_run_value() is not None


def read_pid() -> int | None:
    """读取 pidfile 中的服务进程 pid；文件缺失或内容非法返回 None."""
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def collect_status() -> ServiceStatus:
    """聚合自启与后台进程状态，供 CLI status 与 GUI 回显共用."""
    command = _read_run_value()
    pid = read_pid()
    port: int | None = None
    if command and (match := _PORT_RE.search(command)):
        port = int(match.group(1))
    return ServiceStatus(
        autostart=command is not None,
        running=pid is not None and _pid_alive(pid),
        pid=pid,
        port=port,
        command=command,
    )


def run(host: str, port: int) -> int:
    """自启入口：无窗口派生 ``cndb serve`` 子进程后本进程立即退出.

    单实例保护：pidfile 进程存活或端口已被占用时拒绝启动。
    子进程 stdout/stderr 追加重定向到 SERVICE_LOG。

    Args:
        host: 服务绑定地址。
        port: 服务端口。

    Returns:
        退出码：0 成功派生；1 因已有实例/端口占用拒绝。
    """
    status = collect_status()
    if status.running:
        print(f"[info] 后台服务已在运行 (PID {status.pid})，跳过重复启动")
        return 1

    from cndb.gui.checks import port_status

    if port_status(port, host).used:
        print(f"[info] 端口 {port} 已被占用，跳过重复启动")
        return 1

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": SERVICE_LOG.open("ab"),
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    cmd = [*_exe_command(), "serve", "--host", host, "--port", str(port)]
    proc = subprocess.Popen(cmd, **kwargs)  # nosec - 命令来自内部构造，无用户可控输入
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(f"[ok] 后台服务已启动 (PID {proc.pid})，日志: {SERVICE_LOG}")
    return 0


def stop() -> bool:
    """停止后台服务进程并清理 pidfile（幂等）.

    Returns:
        是否实际终止了存活进程（False 表示本来就没有运行实例）。
    """
    pid = read_pid()
    stopped = False
    if pid is not None and _pid_alive(pid):
        if sys.platform == "win32":
            _run_cmd(["taskkill", "/T", "/F", "/PID", str(pid)])
        else:
            os.kill(pid, 15)
        stopped = True
    with_pid_file = PID_FILE.exists()
    if with_pid_file:
        PID_FILE.unlink()
    return stopped


# ── CLI 入口 ─────────────────────────────────────────────────


def register_service_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb service` 子命令组."""
    p_service = sub.add_parser("service", help="Windows 开机自启后台服务（enable/disable/status/stop/run）")
    service_sub = p_service.add_subparsers(dest="service_cmd")

    p_enable = service_sub.add_parser("enable", help="启用开机自启（后台服务）")
    p_enable.add_argument("--host", default="0.0.0.0", help="服务绑定地址（默认 0.0.0.0）")
    p_enable.add_argument("--port", type=int, default=8000, help="服务端口（默认 8000）")

    service_sub.add_parser("disable", help="取消开机自启")
    service_sub.add_parser("status", help="查看自启与后台服务状态")
    service_sub.add_parser("stop", help="停止后台服务进程")

    p_run = service_sub.add_parser("run", help="自启入口：派生无窗口后台服务（由 Run 键调用）")
    p_run.add_argument("--host", default="0.0.0.0", help="服务绑定地址（默认 0.0.0.0）")
    p_run.add_argument("--port", type=int, default=8000, help="服务端口（默认 8000）")


def service_command(args: argparse.Namespace) -> None:
    """分发 `cndb service <sub>`；仅支持 Windows."""
    if sys.platform != "win32":
        print("[error] service 子命令仅支持 Windows 平台", file=sys.stderr)
        sys.exit(1)

    cmd = getattr(args, "service_cmd", None)
    if cmd == "enable":
        command = enable(args.host, args.port)
        print(f"[ok] 已启用开机自启: {command}")
    elif cmd == "disable":
        disable()
        print("[ok] 已取消开机自启")
    elif cmd == "status":
        st = collect_status()
        print(f"  自启状态: {'已启用' if st.autostart else '未启用'}")
        print(f"  后台服务: {'运行中 (PID ' + str(st.pid) + ')' if st.running else '未运行'}")
        if st.port is not None:
            print(f"  固化端口: {st.port}")
    elif cmd == "stop":
        if stop():
            print("[ok] 后台服务已停止")
        else:
            print("[info] 后台服务未在运行")
    elif cmd == "run":
        sys.exit(run(args.host, args.port))
    else:
        print("[error] 缺少 service 子命令，可用: enable / disable / status / stop / run", file=sys.stderr)
        sys.exit(2)


__all__ = [
    "PID_FILE",
    "RUN_KEY_PATH",
    "RUN_VALUE_NAME",
    "SERVICE_LOG",
    "ServiceStatus",
    "autostart_enabled",
    "build_run_command",
    "collect_status",
    "disable",
    "enable",
    "read_pid",
    "register_service_subparser",
    "run",
    "service_command",
    "stop",
]
