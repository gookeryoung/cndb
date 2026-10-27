"""锁定 ``scripts/free_ports.py`` 的判定口径与 ``make dev`` 的端口释放接线.

``make dev`` 若漏掉端口释放，会重现「后端 Errno 98 但前端已起」的半启动状态，
故用单测钉住端口发现、优雅 / 强制结束、失败退出码与 Makefile 前置依赖。
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "free_ports.py"
_MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"


def _load_module():
    spec = importlib.util.spec_from_file_location("free_ports", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


free_ports = _load_module()


class TestPidsOnPort:
    def test_win32_uses_netstat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports.sys, "platform", "win32")
        monkeypatch.setattr(free_ports, "_pids_via_netstat", lambda port: {4321})
        assert free_ports.pids_on_port(8772) == {4321}

    def test_proc_branch_discards_own_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports.sys, "platform", "linux")
        monkeypatch.setattr(free_ports.Path, "is_dir", lambda self: True)
        monkeypatch.setattr(free_ports, "_pids_via_proc", lambda port: {111, os.getpid()})
        assert free_ports.pids_on_port(8772) == {111}

    def test_lsof_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports.sys, "platform", "darwin")
        monkeypatch.setattr(free_ports.Path, "is_dir", lambda self: False)
        monkeypatch.setattr(free_ports.shutil, "which", lambda name: "/usr/sbin/lsof")
        monkeypatch.setattr(free_ports, "_pids_via_lsof", lambda port: {222})
        assert free_ports.pids_on_port(5173) == {222}

    def test_without_proc_or_lsof_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports.sys, "platform", "darwin")
        monkeypatch.setattr(free_ports.Path, "is_dir", lambda self: False)
        monkeypatch.setattr(free_ports.shutil, "which", lambda name: None)
        assert free_ports.pids_on_port(5173) == set()


class TestParsers:
    def test_lsof_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            free_ports.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="12\n34\nabc\n"),
        )
        assert free_ports._pids_via_lsof(8772) == {12, 34}

    def test_lsof_missing_tool_is_treated_as_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*args, **kwargs):
            raise OSError("lsof not found")

        monkeypatch.setattr(free_ports.subprocess, "run", _raise)
        assert free_ports._pids_via_lsof(8772) == set()

    def test_lsof_timeout_is_treated_as_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="lsof", timeout=1)

        monkeypatch.setattr(free_ports.subprocess, "run", _raise)
        assert free_ports._pids_via_lsof(8772) == set()

    def test_netstat_output_filters_listen_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stdout = "\n".join(
            (
                "  Proto  Local Address          Foreign Address        State           PID",
                "  TCP    0.0.0.0:8772           0.0.0.0:0              LISTENING       4321",
                "  TCP    127.0.0.1:8877         0.0.0.0:0              LISTENING       9999",
                "  TCP    0.0.0.0:8772           1.2.3.4:52000          ESTABLISHED     5555",
                "  UDP    0.0.0.0:8772           *:*                                    6666",
            )
        )
        monkeypatch.setattr(
            free_ports.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout),
        )
        assert free_ports._pids_via_netstat(8772) == {4321}

    def test_netstat_failure_is_treated_as_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*args, **kwargs):
            raise OSError("netstat missing")

        monkeypatch.setattr(free_ports.subprocess, "run", _raise)
        assert free_ports._pids_via_netstat(8772) == set()


class TestWaitReleased:
    def test_returns_true_when_port_is_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: set())
        assert free_ports._wait_released(8772, 0.5) is True

    def test_returns_false_when_timeout_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: {111})
        assert free_ports._wait_released(8772, 0) is False


class TestTerminate:
    def test_posix_sends_term_then_kill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[tuple[int, int]] = []
        monkeypatch.setattr(free_ports.sys, "platform", "linux")
        monkeypatch.setattr(free_ports.os, "kill", lambda pid, sig: sent.append((pid, sig)))

        free_ports._terminate(111)
        free_ports._terminate(111, force=True)

        assert sent == [(111, signal.SIGTERM), (111, signal.SIGKILL)]

    def test_win32_uses_taskkill_tree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(free_ports.sys, "platform", "win32")
        monkeypatch.setattr(
            free_ports.subprocess,
            "run",
            lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(returncode=0),
        )

        free_ports._terminate(4321)

        assert calls == [["taskkill", "/PID", "4321", "/T", "/F"]]

    def test_kill_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _fail(pid: int, sig: int) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(free_ports.sys, "platform", "linux")
        monkeypatch.setattr(free_ports.os, "kill", _fail)

        free_ports._terminate(111)

        assert "无法结束进程 111" in capsys.readouterr().err


class TestFreePort:
    def test_port_already_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: set())
        assert free_ports.free_port(8772) is True

    def test_terminates_and_waits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        terminated: list[tuple[int, bool]] = []
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: {111})
        monkeypatch.setattr(free_ports, "_terminate", lambda pid, force=False: terminated.append((pid, force)))
        monkeypatch.setattr(free_ports, "_wait_released", lambda port, timeout: True)

        assert free_ports.free_port(8772) is True
        assert terminated == [(111, False)]

    def test_escalates_to_sigkill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        terminated: list[tuple[int, bool]] = []
        waits = iter((False, True))
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: {111})
        monkeypatch.setattr(free_ports, "_terminate", lambda pid, force=False: terminated.append((pid, force)))
        monkeypatch.setattr(free_ports, "_wait_released", lambda port, timeout: next(waits))

        assert free_ports.free_port(8772) is True
        assert terminated == [(111, False), (111, True)]

    def test_reports_failure_when_still_listening(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports, "pids_on_port", lambda port: {111})
        monkeypatch.setattr(free_ports, "_terminate", lambda pid, force=False: None)
        monkeypatch.setattr(free_ports, "_wait_released", lambda port, timeout: False)

        assert free_ports.free_port(8772) is False


class TestMain:
    def test_requires_ports(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert free_ports.main([]) == 2
        assert "用法" in capsys.readouterr().err

    def test_all_ports_freed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(free_ports, "free_port", lambda port: True)
        assert free_ports.main(["8772", "5173"]) == 0

    def test_checks_every_port_and_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []

        def _free(port: int) -> bool:
            seen.append(port)
            return port == 5173

        monkeypatch.setattr(free_ports, "free_port", _free)
        assert free_ports.main(["8772", "5173"]) == 1
        assert seen == [8772, 5173]


class TestMakefileWiring:
    def test_dev_depends_on_free_dev_ports(self) -> None:
        makefile = _MAKEFILE.read_text(encoding="utf-8")
        assert "dev: free-dev-ports" in makefile
        assert "DEV_PORTS ?= $(DEV_PORT) 5173" in makefile
        assert "scripts/free_ports.py $(DEV_PORTS)" in makefile
