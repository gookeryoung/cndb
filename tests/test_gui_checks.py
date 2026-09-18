"""cndb.gui.checks 单元测试.

该模块不依赖 tkinter，可在无显示环境（CI）下测试端口检测、静态产物
就绪检查与自动构建逻辑。所有涉及系统命令/真实端口的分支均通过
monkeypatch 隔离，避免测试受宿主机环境干扰。
"""

from __future__ import annotations

import pytest

from cndb.gui import checks


class _FakeSocket:
    """可注入 bind 行为的假 socket."""

    def __init__(self, family=0, stype=0) -> None:
        self._fail_bind = False

    def settimeout(self, _v: float) -> None:
        pass

    def bind(self, _addr: tuple) -> None:
        if self._fail_bind:
            raise OSError("Address already in use")

    def close(self) -> None:
        pass


class _FakeProc:
    returncode = 0
    stdout = "ok"
    stderr = ""


# ── 端口检测 ─────────────────────────────────────────────────


def test_check_port_idle(monkeypatch) -> None:
    """端口可 bind 时返回 False（空闲）."""
    monkeypatch.setattr(checks.socket, "socket", lambda *a, **k: _FakeSocket())
    assert checks.check_port("127.0.0.1", 8000) is False


def test_check_port_used(monkeypatch) -> None:
    """端口 bind 失败返回 True（占用）."""
    sock = _FakeSocket()
    sock._fail_bind = True
    monkeypatch.setattr(checks.socket, "socket", lambda *a, **k: sock)
    assert checks.check_port("", 8000) is True


def test_find_pid_win_parse(monkeypatch) -> None:
    """Windows netstat 输出解析出监听端口的 PID."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(
        checks,
        "_run",
        lambda cmd: (0, "  TCP    127.0.0.1:8000    0.0.0.0:0    LISTENING    1234\n", ""),
    )
    assert checks.find_pid_on_port(8000) == 1234


def test_find_pid_win_ipv6(monkeypatch) -> None:
    """IPv6 带方括号地址也能正确提取端口."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(
        checks,
        "_run",
        lambda cmd: (0, "  TCP    [::1]:8000              [::]:0         LISTENING    4321\n", ""),
    )
    assert checks.find_pid_on_port(8000) == 4321


def test_lsof_pid(monkeypatch) -> None:
    """lsof 探测到 PID."""
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/bin/lsof" if name == "lsof" else None)
    monkeypatch.setattr(checks, "_run", lambda cmd: (0, "5678\n", ""))
    assert checks._lsof_pid(8000) == 5678


def test_ss_pid(monkeypatch) -> None:
    """ss 输出解析出 pid."""
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/bin/ss" if name == "ss" else None)
    out = (
        'LISTEN 0 511 *:8000 *:* users:(("python3",pid=999,fd=5))\n'
        'LISTEN 0 511 *:9000 *:* users:(("python",pid=111,fd=5))\n'
    )
    monkeypatch.setattr(checks, "_run", lambda cmd: (0, out, ""))
    assert checks._ss_pid(8000) == 999


def test_stop_port_occupant_found(monkeypatch) -> None:
    """找到占用进程并终止，返回提示含 PID."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    killed: list[int] = []
    monkeypatch.setattr(checks, "_kill_pid", killed.append)
    msg = checks.stop_port_occupant(8000)
    assert killed == [1234]
    assert "PID=1234" in msg
    assert "python" in msg


def test_stop_port_occupant_idle(monkeypatch) -> None:
    """端口未被占用时不执行任何终止."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: None)
    killed: list[int] = []
    monkeypatch.setattr(checks, "_kill_pid", killed.append)
    msg = checks.stop_port_occupant(8000)
    assert killed == []
    assert "未检测到占用进程" in msg


def test_port_status_used_without_pid(monkeypatch) -> None:
    """占用但探测不到 PID 时 status 仍标记 used."""
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: None)
    st = checks.port_status(8000)
    assert st.used is True
    assert st.pid is None


def test_port_status_idle(monkeypatch) -> None:
    """空闲端口 status.used 为 False."""
    monkeypatch.setattr(checks, "check_port", lambda host, port: False)
    st = checks.port_status(8000)
    assert st.used is False


# ── 静态产物检查 ─────────────────────────────────────────────


def test_static_status_ready(tmp_path, monkeypatch) -> None:
    """index.html + assets 齐全视为就绪."""
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    monkeypatch.setattr(checks, "APP_STATIC_DIR", tmp_path)
    st = checks.static_status()
    assert st.ready is True
    assert st.missing == []


def test_static_status_missing(monkeypatch, tmp_path) -> None:
    """部分缺失时列出缺失项."""
    monkeypatch.setattr(checks, "APP_STATIC_DIR", tmp_path)
    st = checks.static_status()
    assert st.ready is False
    assert sorted(st.missing) == ["assets", "index.html"]


# ── 自动构建 ─────────────────────────────────────────────────


def test_build_static_success(monkeypatch, tmp_path) -> None:
    """构建成功并把 dist 同步到静态目录."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    dist = frontend / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets").mkdir()
    target = tmp_path / "static"
    monkeypatch.setattr(checks, "APP_STATIC_DIR", target)
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **k: _FakeProc())
    logs: list[str] = []
    result = checks.build_static(log=logs.append, frontend_dir=frontend)
    assert result == target
    assert (target / "index.html").is_file()
    assert any("构建前端" in m for m in logs)


def test_build_static_missing_frontend(monkeypatch, tmp_path) -> None:
    """前端源码缺失时上抛 RuntimeError."""
    target = tmp_path / "static"
    monkeypatch.setattr(checks, "APP_STATIC_DIR", target)
    with pytest.raises(RuntimeError):
        checks.build_static(frontend_dir=tmp_path / "nope")


def test_build_static_npm_missing(monkeypatch, tmp_path) -> None:
    """npm 不可用时上抛 RuntimeError."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError):
        checks.build_static(frontend_dir=frontend)


def test_build_static_build_failed(monkeypatch, tmp_path) -> None:
    """前端构建失败时上抛 RuntimeError 并带错误信息."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/bin/npm")

    class _FailProc:
        returncode = 1
        stdout = ""
        stderr = "rollup failed"

    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **k: _FailProc())
    with pytest.raises(RuntimeError, match="rollup failed"):
        checks.build_static(frontend_dir=frontend)
