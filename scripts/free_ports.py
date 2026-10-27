"""结束占用开发端口的旧进程（供 ``make dev`` / ``make free-dev-ports`` 调用）.

用法::

    python scripts/free_ports.py 8772 5173

先 SIGTERM，等待 ``SHUTDOWN_TIMEOUT`` 秒仍未释放则 SIGKILL；Windows 走
``netstat`` + ``taskkill /T /F``。任一端口无法释放时退出码为 1。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL = 0.1
SHUTDOWN_TIMEOUT = 2.0
_TAG = "[dev]"


def _pids_via_proc(port: int) -> set[int]:
    """在 Linux 上通过 /proc 扫描监听 *port* 的进程."""
    inodes: set[str] = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            fields = line.split()
            # fields[3] == "0A" 表示 LISTEN，fields[1] 为本地地址:端口（十六进制）
            if len(fields) < 10 or fields[3] != "0A":
                continue
            if int(fields[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(fields[9])
    if not inodes:
        return set()
    targets = {f"socket:[{inode}]" for inode in inodes}
    pids: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fd_paths = list((entry / "fd").iterdir())
        except OSError:
            continue
        for fd_path in fd_paths:
            try:
                if str(fd_path.readlink()) in targets:
                    pids.add(int(entry.name))
                    break
            except OSError:
                continue
    return pids


def _pids_via_lsof(port: int) -> set[int]:
    """在 macOS / 未提供 /proc 的系统上通过 lsof 查询."""
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
            timeout=SHUTDOWN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {int(token) for token in result.stdout.split() if token.isdigit()}


def _pids_via_netstat(port: int) -> set[int]:
    """在 Windows 上通过 netstat 查询监听 *port* 的进程."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
            timeout=SHUTDOWN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        if fields[3].upper() != "LISTENING" or not fields[1].endswith(f":{port}"):
            continue
        if fields[4].isdigit():
            pids.add(int(fields[4]))
    return pids


def pids_on_port(port: int) -> set[int]:
    """返回在 *port* 上监听的进程 PID 集合."""
    if sys.platform == "win32":
        pids = _pids_via_netstat(port)
    elif Path("/proc/net").is_dir():
        pids = _pids_via_proc(port)
    elif shutil.which("lsof"):
        pids = _pids_via_lsof(port)
    else:
        pids = set()
    pids.discard(os.getpid())
    return pids


def _terminate(pid: int, *, force: bool = False) -> None:
    try:
        if sys.platform == "win32":
            _ = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=SHUTDOWN_TIMEOUT,
            )
        else:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{_TAG} 无法结束进程 {pid}: {exc}", file=sys.stderr)


def _wait_released(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pids_on_port(port):
            return True
        time.sleep(POLL_INTERVAL)
    return False


def free_port(port: int) -> bool:
    """结束占用 *port* 的进程，成功释放返回 True."""
    pids = pids_on_port(port)
    if not pids:
        print(f"{_TAG} 端口 {port}: 可用")
        return True
    print(f"{_TAG} 端口 {port}: 结束占用进程 {sorted(pids)}")
    for pid in pids:
        _terminate(pid)
    if _wait_released(port, SHUTDOWN_TIMEOUT):
        print(f"{_TAG} 端口 {port}: 已释放")
        return True
    remaining = pids_on_port(port)
    if remaining:
        print(f"{_TAG} 端口 {port}: 未响应 SIGTERM，强制结束 {sorted(remaining)}")
        for pid in remaining:
            _terminate(pid, force=True)
        if _wait_released(port, SHUTDOWN_TIMEOUT):
            print(f"{_TAG} 端口 {port}: 已释放")
            return True
    print(f"{_TAG} 端口 {port} 仍被占用", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: python scripts/free_ports.py <port> [port ...]", file=sys.stderr)
        return 2
    ports = [int(arg) for arg in argv]
    print(f"{_TAG} 检查开发端口占用...")
    ok = True
    for port in ports:  # 逐个尝试，避免前一个失败导致后面的端口漏检
        ok = free_port(port) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
