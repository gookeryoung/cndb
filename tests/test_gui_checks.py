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


class _FakeKernel32:
    """kernel32 替身：QueryFullProcessImageNameW / GetExitCodeProcess 可编程.

    以普通函数实例属性暴露（而非绑定方法），使被测代码对其赋值
    ``restype``/``argtypes`` 时与 ctypes 函数指针行为一致。
    """

    def __init__(self, image: str = "", query_ok: bool = True, exit_code: int = 259, exit_ok: bool = True) -> None:
        self._image = image
        self._query_ok = query_ok
        self._exit_code = exit_code
        self._exit_ok = exit_ok
        self.closed: list[int] = []

        def _query(_handle: int, _flags: int, buf, size) -> int:
            if not self._query_ok:
                return 0
            buf.value = self._image
            size._obj.value = len(self._image)
            return 1

        def _exit(_handle: int, ref) -> int:
            if not self._exit_ok:
                return 0
            ref._obj.value = self._exit_code
            return 1

        def _close(handle: int) -> int:
            self.closed.append(handle)
            return 1

        self.QueryFullProcessImageNameW = _query
        self.GetExitCodeProcess = _exit
        self.CloseHandle = _close


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


def test_bind_error_idle(monkeypatch) -> None:
    """端口可 bind 时 bind_error 返回 None（空闲）."""
    monkeypatch.setattr(checks.socket, "socket", lambda *a, **k: _FakeSocket())
    assert checks.bind_error("127.0.0.1", 8000) is None


def test_bind_error_addr_in_use(monkeypatch) -> None:
    """bind 报 WSAEADDRINUSE 时返回 errno 10048."""
    sock = _FakeSocket()

    def _bind(self, _addr: tuple) -> None:
        raise OSError(10048, "Address already in use")

    sock.bind = _bind.__get__(sock)  # type: ignore[method-assign]
    monkeypatch.setattr(checks.socket, "socket", lambda *a, **k: sock)
    assert checks.bind_error("127.0.0.1", 8000) == 10048


def test_bind_error_unknown_errno(monkeypatch) -> None:
    """OSError 无 errno（如测试替身）时映射为 -1."""
    sock = _FakeSocket()
    sock._fail_bind = True
    monkeypatch.setattr(checks.socket, "socket", lambda *a, **k: sock)
    assert checks.bind_error("127.0.0.1", 8000) == -1


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


def test_process_name_win(monkeypatch) -> None:
    """Windows：Win32 API 查询镜像路径并取 basename，句柄用后关闭."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_win_open_process", lambda pid: 4242)
    fake = _FakeKernel32(image=r"C:\Program Files\Python312\python.exe")
    monkeypatch.setattr(checks, "_kernel32", lambda: fake)
    assert checks._process_name(1234) == "python.exe"
    assert fake.closed == [4242]


def test_process_name_win_open_failed(monkeypatch) -> None:
    """Windows：句柄打不开（进程不存在/无权限）返回空串."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_win_open_process", lambda pid: 0)
    assert checks._process_name(32448) == ""


def test_process_name_win_query_failed(monkeypatch) -> None:
    """Windows：QueryFullProcessImageNameW 失败返回空串，句柄仍被关闭."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_win_open_process", lambda pid: 4242)
    fake = _FakeKernel32(query_ok=False)
    monkeypatch.setattr(checks, "_kernel32", lambda: fake)
    assert checks._process_name(32448) == ""
    assert fake.closed == [4242]


def test_pid_alive_win(monkeypatch) -> None:
    """Windows：Win32 退出码 STILL_ACTIVE 判活；查询失败保守判活且句柄已关闭."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_win_open_process", lambda pid: 4242)
    alive = _FakeKernel32(exit_code=259)
    monkeypatch.setattr(checks, "_kernel32", lambda: alive)
    assert checks._pid_alive(32448) is True
    assert alive.closed == [4242]
    dead = _FakeKernel32(exit_code=0)
    monkeypatch.setattr(checks, "_kernel32", lambda: dead)
    assert checks._pid_alive(32448) is False
    broken = _FakeKernel32(exit_ok=False)
    monkeypatch.setattr(checks, "_kernel32", lambda: broken)
    assert checks._pid_alive(32448) is True  # 查询失败保守按存活


def test_pid_alive_win_open_failed(monkeypatch) -> None:
    """Windows：句柄打不开时按最后错误码判定（87=不存在判死，其余保守判活）."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_win_open_process", lambda pid: 0)
    monkeypatch.setattr(checks.ctypes, "get_last_error", lambda: 87)
    assert checks._pid_alive(32448) is False
    monkeypatch.setattr(checks.ctypes, "get_last_error", lambda: 5)
    assert checks._pid_alive(32448) is True


def test_stop_port_occupant_found(monkeypatch) -> None:
    """找到占用进程并终止，返回提示含 PID."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    killed: list[int] = []
    monkeypatch.setattr(checks, "_kill_pid", killed.append)
    monkeypatch.setattr(checks, "check_port", lambda host, port: False)
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


def test_kill_pid_stale_pid_not_found_is_success(monkeypatch) -> None:
    """netstat 残留已死 PID 时 taskkill 报「没有找到进程」不视为失败（回归）.

    场景：停止服务后 netstat 短暂残留 LISTENING 条目，启动前清理对
    不存在的 PID 执行 taskkill 失败会阻断启动，尽管端口实际已释放。
    """
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_run", lambda cmd: (1, "", '错误: 没有找到进程 "32448"。'))
    checks._kill_pid(32448)  # 不应抛错


def test_kill_pid_not_found_english_locale(monkeypatch) -> None:
    """英文环境 taskkill「not found」报错同样视为进程已不存在."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_run", lambda cmd: (1, "", 'ERROR: The process "32448" not found.'))
    checks._kill_pid(32448)  # 不应抛错


def test_kill_pid_denied_raises(monkeypatch) -> None:
    """非「进程不存在」类失败（如拒绝访问）仍上抛 RuntimeError."""
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_run", lambda cmd: (1, "", "错误: 拒绝访问。"))
    with pytest.raises(RuntimeError, match="拒绝访问"):
        checks._kill_pid(32448)


def test_kill_pid_posix_no_such_process(monkeypatch) -> None:
    """POSIX kill 报「No such process」视为终止成功."""
    monkeypatch.setattr(checks.sys, "platform", "posix")
    monkeypatch.setattr(checks, "_run", lambda cmd: (1, "", "kill: (1234) - No such process"))
    checks._kill_pid(1234)  # 不应抛错


def test_kill_tree_windows_taskkill_tree(monkeypatch) -> None:
    """kill_tree 在 Windows 走 taskkill /F /T 整树终止（供 GUI 停止服务用）."""
    cmds: list[list[str]] = []
    monkeypatch.setattr(checks.sys, "platform", "win32")
    monkeypatch.setattr(checks, "_run", lambda cmd: cmds.append(cmd) or (0, "", ""))
    checks.kill_tree(1234)
    assert cmds == [["taskkill", "/PID", "1234", "/F", "/T"]]


def test_stop_port_occupant_stale_pid_port_idle(monkeypatch) -> None:
    """残留已死 PID 且端口实际已空闲：不执行终止，提示记录已失效."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 32448)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: False)
    killed: list[int] = []
    monkeypatch.setattr(checks, "_kill_pid", killed.append)
    monkeypatch.setattr(checks, "check_port", lambda host, port: False)
    msg = checks.stop_port_occupant(8000)
    assert killed == []
    assert "PID=32448" in msg
    assert "已失效" in msg


def test_stop_port_occupant_stale_pid_residue(monkeypatch) -> None:
    """残留已死 PID 且端口仍不可绑定：按残留状态归因而非谎报已停止.

    场景：netstat 残留 LISTENING 条目归属已死 PID，监听句柄被其他进程
    继承持有，taskkill 对死 PID 是空操作，端口无法释放。
    """
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 32448)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(checks, "_port_entries", lambda port: [("LISTENING", 32448)])
    monkeypatch.setattr(checks, "bind_error", lambda host, port: 10048)
    msg = checks.stop_port_occupant(8000)
    assert "已不存在" in msg
    assert "未发现可终止的存活进程" in msg
    assert "LISTENING/PID=32448" in msg


def test_stop_port_occupant_residue_live_listener(monkeypatch) -> None:
    """终止后端口仍被其他存活进程监听时，提示其 PID 而非笼统失败."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(checks, "_kill_pid", lambda pid: None)
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(checks, "_port_entries", lambda port: [("LISTENING", 999)])
    msg = checks.stop_port_occupant(8000)
    assert "PID=999" in msg
    assert "存活" in msg


def test_stop_port_occupant_residue_time_wait(monkeypatch) -> None:
    """终止后仅剩 TIME_WAIT 残留连接时，提示自动释放等待."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(checks, "_kill_pid", lambda pid: None)
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(
        checks,
        "_port_entries",
        lambda port: [("TIME_WAIT", 1234), ("TIME_WAIT", None)],
    )
    msg = checks.stop_port_occupant(8000)
    assert "TIME_WAIT" in msg
    assert "自动释放" in msg


def test_stop_port_occupant_residue_access_denied(monkeypatch) -> None:
    """bind 被拒绝（errno 10013）时提示系统保留端口段并建议换端口."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(checks, "_kill_pid", lambda pid: None)
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(checks, "_port_entries", lambda port: [])
    monkeypatch.setattr(checks, "bind_error", lambda host, port: 10013)
    msg = checks.stop_port_occupant(8000)
    assert "系统保留" in msg
    assert "更换服务端口" in msg


def test_stop_port_occupant_port_still_busy(monkeypatch) -> None:
    """终止后端口仍不可绑定时，走残留归因提示而非谎报成功."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(checks, "_kill_pid", lambda pid: None)
    monkeypatch.setattr(checks, "check_port", lambda host, port: True)
    monkeypatch.setattr(checks, "_port_entries", lambda port: [("TIME_WAIT", None)])
    monkeypatch.setattr(checks, "_PORT_RELEASE_TIMEOUT", 0.0)
    msg = checks.stop_port_occupant(8000)
    assert "仍未释放" in msg


def test_stop_port_occupant_polls_until_released(monkeypatch) -> None:
    """终止后端口短暂未释放时轮询等待，释放后返回成功提示."""
    monkeypatch.setattr(checks, "find_pid_on_port", lambda port: 1234)
    monkeypatch.setattr(checks, "_process_name", lambda pid: "python")
    monkeypatch.setattr(checks, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(checks, "_kill_pid", lambda pid: None)
    results = [True, True, False]

    def _fake_check(host: str, port: int) -> bool:
        return results.pop(0) if results else False

    monkeypatch.setattr(checks, "check_port", _fake_check)
    sleeps: list[float] = []
    monkeypatch.setattr(checks.time, "sleep", sleeps.append)
    msg = checks.stop_port_occupant(8000)
    assert "仍未释放" not in msg
    assert len(sleeps) == 2


def test_port_status_host_passthrough(monkeypatch) -> None:
    """port_status 把 host 透传给 check_port（与服务绑定地址同口径检测）."""
    seen: list[tuple[str, int]] = []

    def _fake_check(host: str, port: int) -> bool:
        seen.append((host, port))
        return False

    monkeypatch.setattr(checks, "check_port", _fake_check)
    checks.port_status(8000, host="0.0.0.0")
    assert seen == [("0.0.0.0", 8000)]


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
