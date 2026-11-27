"""Terminate stale processes holding the dev ports (called by ``make dev`` / ``make free-dev-ports``).

Usage::

    python scripts/free_ports.py 8772 5173

Sends SIGTERM first, then SIGKILL if the port is still held after ``SHUTDOWN_TIMEOUT`` seconds;
on Windows it uses ``netstat`` + ``taskkill /T /F``. Exit code is 1 when any port cannot be
released.
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
    """Scan /proc for processes listening on *port* (Linux)."""
    inodes: set[str] = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            fields = line.split()
            # fields[3] == "0A" means LISTEN, fields[1] is the local address:port (hex)
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
    """Query with lsof on macOS / systems without /proc."""
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
    """Query with netstat for processes listening on *port* (Windows)."""
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
    """Return the set of PIDs listening on *port*."""
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
        print(f"{_TAG} cannot terminate process {pid}: {exc}", file=sys.stderr)


def _wait_released(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pids_on_port(port):
            return True
        time.sleep(POLL_INTERVAL)
    return False


def free_port(port: int) -> bool:
    """Terminate the process on *port*; return True once the port is free."""
    pids = pids_on_port(port)
    if not pids:
        print(f"{_TAG} port {port}: free")
        return True
    print(f"{_TAG} port {port}: terminating {sorted(pids)}")
    for pid in pids:
        _terminate(pid)
    if _wait_released(port, SHUTDOWN_TIMEOUT):
        print(f"{_TAG} port {port}: released")
        return True
    remaining = pids_on_port(port)
    if remaining:
        print(f"{_TAG} port {port}: no response to SIGTERM, force killing {sorted(remaining)}")
        for pid in remaining:
            _terminate(pid, force=True)
        if _wait_released(port, SHUTDOWN_TIMEOUT):
            print(f"{_TAG} port {port}: released")
            return True
    print(f"{_TAG} port {port} is still in use", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python scripts/free_ports.py <port> [port ...]", file=sys.stderr)
        return 2
    ports = [int(arg) for arg in argv]
    print(f"{_TAG} checking dev port usage...")
    ok = True
    for port in ports:  # try one by one so an early failure does not skip the remaining ports
        ok = free_port(port) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
