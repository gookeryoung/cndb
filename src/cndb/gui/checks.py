"""GUI 服务启动前置检查与修复（环境监视）.

提供跨平台的端口占用检测/清理与前端静态产物就绪检查/构建，
供「启动服务」Tab 在实际拉起 uvicorn 之前调用，避免因端口被占、
静态文件缺失而导致服务无法启动。

设计约束：
- 本模块不依赖 tkinter，可在无显示环境（CI）下单元测试纯逻辑。
- 端口 PID 探测优先使用系统自带命令（无第三方依赖）：
  Windows 用 ``netstat``/``tasklist``/``taskkill``，
  POSIX 用 ``lsof``（回退 ``ss``）/``ps``/``kill``。
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import socket
import subprocess  # nosec B404 - 环境检查需调用内部命令
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# 服务端实际挂载的前端静态目录（与 app.py 中 _STATIC 一致）
APP_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# 源码根目录（fspack 打包后不存在 frontend/，此时跳过自动构建）
ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT_DIR / "frontend"

# 静态主目录可接近的可接受条件（与 app._SPA_READY 判定一致）
_STATIC_REQUIRED = ("index.html", "assets")


def _emit(log: Callable[[str], object] | None, message: str) -> None:
    """把消息交给可选回调；未提供时忽略（安静模式）."""
    if log is not None:
        log(message)


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """执行命令，返回 ``(returncode, stdout, stderr)``；异常视为失败."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec - 命令来自内部常量
        return proc.returncode, (proc.stdout or ""), (proc.stderr or "")
    except OSError:
        return -1, "", ""


# ── 端口占用 ──────────────────────────────────────────────────


@dataclass
class PortStatus:
    """端口占用状态."""

    used: bool = False
    pid: int | None = None
    process_name: str = ""


def bind_error(host: str, port: int) -> int | None:
    """试探绑定端口，失败时返回 ``errno``（未知映射记为 -1），空闲返回 ``None``.

    与 :func:`check_port` 同口径，额外区分占用原因：
    ``10048``（WSAEADDRINUSE 地址被占）与 ``10013``（WSAEACCES 被拒绝，
    常见于 Hyper-V 排除端口段）。
    """
    host = host or "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.bind((host, int(port)))
        return None
    except OSError as exc:
        return exc.errno or -1
    finally:
        with contextlib.suppress(OSError):
            sock.close()


def check_port(host: str, port: int) -> bool:
    """试探端口是否已被占用（可 bind 即视为空闲）.

    Args:
        host: 绑定主机；空串视为 ``127.0.0.1``.
        port: 待检测端口.

    Returns:
        ``True`` 表示端口已被占用，``False`` 表示空闲。
    """
    return bind_error(host, port) is not None


def _find_pid_win(port: int) -> int | None:
    """Windows：解析 ``netstat -ano`` 找出监听该端口的 PID."""
    rc, out, _ = _run(["netstat", "-ano"])
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            local = parts[1]
            # 兼容 IPv4 / 带方括号的 IPv6（如 [::1]:8000）
            if local.rsplit(":", 1)[-1] == str(port):
                with contextlib.suppress(ValueError):
                    return int(parts[-1])
    return None


def _lsof_pid(port: int) -> int | None:
    """POSIX：优先用 ``lsof -t -iTCP:port -sTCP:LISTEN`` 取 PID."""
    if shutil.which("lsof") is None:
        return None
    rc, out, _ = _run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
    if rc != 0:
        return None
    return next((int(t) for t in out.split() if t.isdigit()), None)


def _ss_pid(port: int) -> int | None:
    """POSIX：回退用 ``ss -ltnp`` 解析监听该端口进程的 PID."""
    if shutil.which("ss") is None:
        return None
    rc, out, _ = _run(["ss", "-ltnp"])
    if rc != 0:
        return None
    for line in out.splitlines():
        if f":{port}" not in line:
            continue
        if "LISTEN" not in line.upper():
            continue
        match = re.search(r"pid=(\d+)", line)
        if match:
            with contextlib.suppress(ValueError):
                return int(match.group(1))
    return None


def find_pid_on_port(port: int) -> int | None:
    """查找监听指定端口的进程 PID；未占用或无法探测时返回 ``None``."""
    if sys.platform == "win32":
        return _find_pid_win(port)
    return _lsof_pid(port) or _ss_pid(port)


# tasklist「无匹配任务」提示前缀（中/英文环境）：此时 PID 对应进程不存在
_TASKLIST_NO_TASK = ("信息:", "INFO:")


def _process_name(pid: int) -> str:
    """查询进程可执行文件名；探测失败或进程不存在时返回空串."""
    if sys.platform == "win32":
        rc, out, _ = _run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        line = out.strip()
        if rc == 0 and line and not line.startswith(_TASKLIST_NO_TASK):
            return line.split()[0]
        return ""
    rc, out, _ = _run(["ps", "-p", str(pid), "-o", "comm="])
    return out.strip() if rc == 0 else ""


def _pid_alive(pid: int) -> bool:
    """判断进程是否存活；探测失败时保守按存活处理（不放过可终止对象）."""
    if sys.platform == "win32":
        rc, out, _ = _run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        if rc != 0:
            return True
        line = out.strip()
        return bool(line) and not line.startswith(_TASKLIST_NO_TASK)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


# 终止占用进程后等待内核释放端口的上限与轮询间隔
_PORT_RELEASE_TIMEOUT = 2.0
_PORT_RELEASE_INTERVAL = 0.2


def _pid_gone_message(err: str) -> bool:
    """判断终止命令的报错是否为「进程已不存在」.

    netstat 在进程刚退出后会短暂残留 LISTENING 条目（归属已死 PID），
    据此对不存在的进程执行 taskkill/kill 会报「没有找到进程」，
    该情况视为终止成功而非失败。
    """
    lowered = err.lower()
    return "没有找到进程" in err or "no such process" in lowered or "not found" in lowered


def _kill_pid(pid: int) -> None:
    """终止进程（Windows 强制带子进程，POSIX 优雅 SIGTERM）.

    「进程已不存在」（如 netstat 残留条目）视为终止成功，不抛错。
    """
    if sys.platform == "win32":
        rc, _, err = _run(["taskkill", "/PID", str(pid), "/F", "/T"])
    else:
        rc, _, err = _run(["kill", str(pid)])
    if rc != 0 and not _pid_gone_message(err):
        raise RuntimeError(f"未能终止进程 PID={pid}: {err.strip() or '无权限'}")


def kill_tree(pid: int) -> None:
    """终止进程及其全部子进程（供 GUI「停止服务」整树终止 uvicorn worker/reload 子进程）."""
    _kill_pid(pid)


def port_status(port: int, host: str = "127.0.0.1") -> PortStatus:
    """返回端口占用详情：是否占用 + 占用进程 PID/名称.

    Args:
        port: 待检测端口。
        host: 与服务实际绑定地址一致的检测主机；Windows 下 wildcard
            绑定被占时 specific-IP 仍可绑定成功，检测口径必须与服务
            一致，否则会出现「检查空闲但启动失败」的矛盾结论。
    """
    if not check_port(host, port):
        return PortStatus(used=False)
    pid = find_pid_on_port(port)
    return PortStatus(used=True, pid=pid, process_name=_process_name(pid) if pid else "")


def _port_entries(port: int) -> list[tuple[str, int | None]]:
    """列出该端口的全部 TCP 条目 ``(state, pid)``；探测失败返回空列表.

    Windows 解析 ``netstat -ano``；POSIX 回退 ``ss -tan``（无 PID 列）。
    """
    if sys.platform == "win32":
        rc, out, _ = _run(["netstat", "-ano"])
        if rc != 0:
            return []
        entries: list[tuple[str, int | None]] = []
        for line in out.splitlines():
            parts = line.split()
            # TCP 行五列：协议/本地/远端/状态/PID；只匹配本地端口
            if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].rsplit(":", 1)[-1] == str(port):
                pid: int | None = None
                with contextlib.suppress(ValueError):
                    pid = int(parts[-1])
                entries.append((parts[3].upper(), pid))
        return entries
    if shutil.which("ss") is None:
        return []
    rc, out, _ = _run(["ss", "-tan"])
    if rc != 0:
        return []
    entries = []
    for line in out.splitlines()[1:]:  # 首行为表头
        parts = line.split()
        if len(parts) >= 4 and parts[3].rsplit(":", 1)[-1] == str(port):
            entries.append((parts[0].upper(), None))
    return entries


# Windows bind 被拒绝（WSAEACCES）：常见于 Hyper-V/排除端口段
_WSAEACCES = 10013


def _residue_message(port: int, host: str, prefix: str) -> str:
    """端口未释放时的归因提示：区分存活监听、TIME_WAIT 残留与系统保留端口."""
    entries = _port_entries(port)
    live = [pid for state, pid in entries if "LISTEN" in state and pid is not None and _pid_alive(pid)]
    if live:
        pids = "、".join(f"PID={p}" for p in live)
        return f"{prefix}；端口仍被存活进程监听（{pids}），请再次终止或手动结束该进程"
    if entries and all("TIME_WAIT" in state for state, _ in entries):
        return f"{prefix}；残留连接处于 TIME_WAIT 等待状态（通常 1-4 分钟内自动释放），可稍后重新检查"
    if bind_error(host, port) == _WSAEACCES:
        return f"{prefix}；端口被系统保留（如 Hyper-V 排除端口段），建议更换服务端口"
    detail = "；".join(state + (f"/PID={pid}" if pid is not None else "") for state, pid in entries)
    suffix = f"（残留条目: {detail}）" if detail else ""
    return f"{prefix}；未发现可终止的存活进程{suffix}，其监听句柄可能仍被其他进程持有，请稍后重新检查"


def stop_port_occupant(port: int, host: str = "127.0.0.1") -> str:
    """停止占用指定端口的进程.

    Args:
        port: 待清理端口。
        host: 与服务实际绑定地址一致的检测主机（用于停止后确认端口释放）。

    Returns:
        面向用户的提示消息（无论是否真的有进程被终止都会返回便于展示的文案）。
    """
    pid = find_pid_on_port(port)
    if pid is None:
        return f"端口 {port} 暂未检测到占用进程，可直接启动"
    name = _process_name(pid)
    display = f"PID={pid}" + (f" ({name})" if name else "")
    if not _pid_alive(pid):
        # netstat 残留已死 PID（句柄可能被其他进程继承）：无可终止对象，按残留状态归因
        if not check_port(host, port):
            return f"端口 {port} 的占用记录 {display} 已失效，端口实际已空闲，可直接启动"
        return _residue_message(port, host, f"占用端口 {port} 的记录 {display} 对应进程已不存在")
    _kill_pid(pid)
    # 内核释放端口存在短暂延迟；轮询确认直至可绑定或超时
    deadline = time.monotonic() + _PORT_RELEASE_TIMEOUT
    while check_port(host, port) and time.monotonic() < deadline:
        time.sleep(_PORT_RELEASE_INTERVAL)
    if check_port(host, port):
        return _residue_message(port, host, f"已终止占用端口 {port} 的进程 {display}，但端口仍未释放")
    return f"已停止占用端口 {port} 的进程 {display}"


# ── 前端静态产物 ─────────────────────────────────────────────


@dataclass
class StaticStatus:
    """前端静态产物状态."""

    ready: bool = False
    missing: list[str] = field(default_factory=list)


def static_dir() -> Path:
    """返回服务实际挂载的前端静态目录（``src/cndb/static``）."""
    return APP_STATIC_DIR


def static_status() -> StaticStatus:
    """检查静态产物是否就绪（index.html + assets 目录完整）."""
    missing = [name for name in _STATIC_REQUIRED if not (APP_STATIC_DIR / name).exists()]
    ready = not missing and APP_STATIC_DIR.is_dir()
    return StaticStatus(ready=ready, missing=missing)


def build_static(log: Callable[[str], object] | None = None, *, frontend_dir: Path | None = None) -> Path:
    """构建前端产物并同步到服务静态目录.

    Args:
        log: 可选日志回调，收到构建进度消息。
        frontend_dir: 覆盖前端源码目录（便于测试注入临时目录）。

    Returns:
        同步后的静态目录 ``Path``。

    Raises:
        RuntimeError: 前端源码缺失、构建失败或产物不完整时。
    """
    frontend = frontend_dir or FRONTEND_DIR
    if not (frontend / "package.json").is_file():
        raise RuntimeError(f"未找到前端源码目录 frontend/（期望位置: {frontend}），无法自动构建")
    if not shutil.which("npm"):
        raise RuntimeError("未找到 npm 可执行文件，无法自动构建前端")

    _emit(log, "[build] 构建前端...")
    cmd = ["npm", "run", "build"]
    kwargs: dict[str, object] = {"cwd": str(frontend), "capture_output": True, "text": True}
    if sys.platform == "win32":
        kwargs["shell"] = True
    proc = subprocess.run(cmd, check=False, **kwargs)  # type: ignore[arg-type]  # nosec - 命令来自内部常量
    if proc.returncode != 0:
        tail = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "").strip()
        raise RuntimeError(f"前端构建失败: {tail}" if tail else "前端构建失败")

    dist = frontend / "dist"
    if not dist.is_dir() or not (dist / "index.html").is_file():
        raise RuntimeError("前端构建产物 dist/ 缺失或不完整")

    if APP_STATIC_DIR.exists():
        shutil.rmtree(APP_STATIC_DIR)
    shutil.copytree(dist, APP_STATIC_DIR)
    _emit(log, f"[ok] 前端产物已同步到 {APP_STATIC_DIR}")
    return APP_STATIC_DIR
