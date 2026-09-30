"""cndb.cli.service 单元测试.

注册表操作用内存字典替身替换窄封装函数；进程探测与子进程派生
用 monkeypatch 替换，不在测试中真正写注册表或拉起服务。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from cndb.cli import service


class FakeRegistry:
    """winreg 替身：内存字典模拟 HKCU Run 键的 cndb 条目."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> FakeRegistry:
    """把三个注册表窄函数替换为内存字典实现."""
    reg = FakeRegistry()

    monkeypatch.setattr(service, "_read_run_value", lambda: reg.values.get(service.RUN_VALUE_NAME))
    monkeypatch.setattr(service, "_write_run_value", lambda cmd: reg.values.__setitem__(service.RUN_VALUE_NAME, cmd))
    monkeypatch.setattr(service, "_delete_run_value", lambda: reg.values.pop(service.RUN_VALUE_NAME, None))
    return reg


@pytest.fixture
def fake_paths(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """pidfile 与日志文件重定向到临时目录."""
    monkeypatch.setattr(service, "PID_FILE", tmp_path / "service.pid")
    monkeypatch.setattr(service, "SERVICE_LOG", tmp_path / "service.log")


# ── enable / disable / autostart_enabled ─────────────────────


def test_enable_writes_run_key(fake_registry: FakeRegistry) -> None:
    """enable 写入含 service run 与固化端口的命令行."""
    command = service.enable("0.0.0.0", 8772)

    assert fake_registry.values[service.RUN_VALUE_NAME] == command
    assert "service run" in command
    assert "--port 8772" in command
    assert service.autostart_enabled()


def test_enable_overwrites_existing(fake_registry: FakeRegistry) -> None:
    """重复 enable 覆盖更新而非报错."""
    service.enable("0.0.0.0", 8000)
    service.enable("127.0.0.1", 9000)

    command = fake_registry.values[service.RUN_VALUE_NAME]
    assert "--host 127.0.0.1" in command
    assert "--port 9000" in command


def test_disable_removes_and_idempotent(fake_registry: FakeRegistry) -> None:
    """disable 删除条目；重复 disable 不报错."""
    service.enable("0.0.0.0", 8000)
    service.disable()
    assert not service.autostart_enabled()
    service.disable()
    assert not service.autostart_enabled()


def test_build_run_command_quotes_frozen_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    """命令行构造经 list2cmdline，frozen 态仅含可执行文件本身."""
    monkeypatch.setattr(service, "_exe_command", lambda: [r"C:\Program Files\cndb\cndb.exe"])
    command = service.build_run_command("0.0.0.0", 8000)

    assert command.startswith('"C:\\Program Files\\cndb\\cndb.exe"')
    assert "service run --host 0.0.0.0 --port 8000" in command


def test_exe_command_frozen_vs_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """frozen 用可执行文件，源码态经 python -m cndb.cli.main."""
    monkeypatch.setattr(service, "_is_frozen", lambda: True)
    assert service._exe_command() == [sys.executable]

    monkeypatch.setattr(service, "_is_frozen", lambda: False)
    assert service._exe_command() == [sys.executable, "-m", "cndb.cli.main"]


# ── collect_status / read_pid ────────────────────────────────


def test_collect_status_all_off(fake_registry: FakeRegistry, fake_paths: None) -> None:
    """未注册且无 pidfile 时全部为关闭态."""
    st = service.collect_status()

    assert st.autostart is False
    assert st.running is False
    assert st.pid is None
    assert st.port is None


def test_collect_status_running(
    fake_registry: FakeRegistry, fake_paths: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注册 + pidfile 存活时 running 为真，端口从命令行解析."""
    monkeypatch.setattr(service, "_pid_alive", lambda pid: True)
    service.enable("0.0.0.0", 8772)
    service.PID_FILE.write_text("4242", encoding="utf-8")

    st = service.collect_status()

    assert st.autostart is True
    assert st.running is True
    assert st.pid == 4242
    assert st.port == 8772


def test_read_pid_invalid_content(fake_paths: None, tmp_path: Any) -> None:
    """pidfile 内容非法时返回 None."""
    service.PID_FILE.write_text("not-a-pid", encoding="utf-8")

    assert service.read_pid() is None


# ── run（自启入口）───────────────────────────────────────────


class _FakePopen:
    """subprocess.Popen 替身：记录调用参数，返回固定 pid."""

    calls: dict[str, Any] = {}
    pid = 4242

    def __init__(self, cmd: list[str], **kwargs: Any) -> None:
        type(self).calls = {"cmd": cmd, **kwargs}


@pytest.mark.skipif(sys.platform != "win32", reason="creationflags 仅 Windows 语义")
def test_run_spawns_detached_and_writes_pidfile(
    fake_registry: FakeRegistry, fake_paths: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正常路径：无窗口派生 serve、日志重定向、写 pidfile."""
    monkeypatch.setattr("cndb.gui.checks.port_status", lambda port, host="127.0.0.1": type("P", (), {"used": False})())
    monkeypatch.setattr(service.subprocess, "Popen", _FakePopen)

    rc = service.run("0.0.0.0", 8000)

    assert rc == 0
    call = _FakePopen.calls
    assert call["cmd"][-5:] == ["serve", "--host", "0.0.0.0", "--port", "8000"]
    assert call["creationflags"] == (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    assert getattr(call["stdout"], "name", "").endswith("service.log")
    assert service.PID_FILE.read_text(encoding="utf-8") == "4242"


def test_run_rejects_when_pid_alive(
    fake_registry: FakeRegistry,
    fake_paths: None,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pidfile 进程存活时拒绝重复启动."""
    monkeypatch.setattr(service, "_pid_alive", lambda pid: True)
    service.PID_FILE.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(
        service.subprocess,
        "Popen",
        lambda *a: pytest.fail("不应派生子进程"),  # type: ignore[arg-type,return-value]
    )

    rc = service.run("0.0.0.0", 8000)

    assert rc == 1
    assert "已在运行" in capsys.readouterr().out


def test_run_rejects_when_port_used(
    fake_registry: FakeRegistry, fake_paths: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """端口被占用时拒绝启动（单实例双重校验）."""
    monkeypatch.setattr("cndb.gui.checks.port_status", lambda port, host="127.0.0.1": type("P", (), {"used": True})())

    rc = service.run("0.0.0.0", 8000)

    assert rc == 1
    assert "已被占用" in capsys.readouterr().out


# ── stop ─────────────────────────────────────────────────────


def test_stop_missing_pidfile_idempotent(fake_paths: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """pidfile 缺失时幂等成功且不调用 taskkill."""
    monkeypatch.setattr(
        service,
        "_run_cmd",
        lambda cmd: pytest.fail("不应调用 taskkill"),  # type: ignore[arg-type,return-value]
    )

    assert service.stop() is False


def test_stop_kills_process_and_removes_pidfile(
    fake_paths: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存活进程被 taskkill 终止并清理 pidfile."""
    service.PID_FILE.write_text("4242", encoding="utf-8")
    killed: list[list[str]] = []
    monkeypatch.setattr(service, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(service, "_run_cmd", lambda cmd: killed.append(cmd) or (0, ""))
    monkeypatch.setattr(service.sys, "platform", "win32")

    assert service.stop() is True
    assert killed and "4242" in killed[0]
    assert not service.PID_FILE.exists()


def test_stop_dead_pid_removes_pidfile_only(fake_paths: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """pid 已死时仅清理 pidfile，不调用 taskkill（幂等）."""
    service.PID_FILE.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(service, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(
        service,
        "_run_cmd",
        lambda cmd: pytest.fail("进程已死不应 taskkill"),  # type: ignore[arg-type,return-value]
    )
    monkeypatch.setattr(service.sys, "platform", "win32")

    assert service.stop() is False
    assert not service.PID_FILE.exists()


def test_stop_posix_race_condition_no_crash(fake_paths: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """POSIX：_pid_alive 返回 True 但进程在 os.kill 前退出（竞态窗口），幂等处理不崩溃.

    覆盖 service.stop() 对 ProcessLookupError 的处理——历史版本在这种竞态下会抛出
    ProcessLookupError 终止调用方；修复后改为返回 False 并清理 pidfile。
    """
    service.PID_FILE.write_text("9999", encoding="utf-8")
    monkeypatch.setattr(service, "_pid_alive", lambda pid: True)
    # 不 monkeypatch sys.platform，让代码走 POSIX 的 os.kill 分支
    assert service.stop() is False  # ProcessLookupError 被捕获
    assert not service.PID_FILE.exists()


# ── CLI 分发 ─────────────────────────────────────────────────


def _namespace(service_cmd: str | None) -> Any:
    """构造 service_command 分发所需的 argparse.Namespace."""
    import argparse

    return argparse.Namespace(command="service", service_cmd=service_cmd)


def test_service_command_non_windows_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """非 Windows 平台统一拦截，非零码退出."""
    monkeypatch.setattr(service.sys, "platform", "linux")

    with pytest.raises(SystemExit, match="1"):
        service.service_command(_namespace("status"))

    assert "仅支持 Windows" in capsys.readouterr().err


def test_service_command_missing_sub(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Windows 下缺少子命令提示用法并以退出码 2 结束."""
    monkeypatch.setattr(service.sys, "platform", "win32")

    with pytest.raises(SystemExit, match="2"):
        service.service_command(_namespace(None))


def _make_registry_parser() -> Any:
    """构造含 service 组的顶层 parser（走真实注册链路）."""
    import argparse

    parser = argparse.ArgumentParser(prog="cndb")
    sub = parser.add_subparsers(dest="command")
    service.register_service_subparser(sub)
    return parser


@pytest.mark.parametrize(
    ("argv", "expected_cmd", "expected_port"),
    [
        (["service", "enable", "--port", "8772"], "enable", 8772),
        (["service", "disable"], "disable", 8000),
        (["service", "status"], "status", None),
        (["service", "stop"], "stop", None),
        (["service", "run", "--host", "127.0.0.1"], "run", 8000),
    ],
)
def test_register_service_subparser(argv: list[str], expected_cmd: str, expected_port: int | None) -> None:
    """argparse 注册链路：子命令与默认值解析正确."""
    args = _make_registry_parser().parse_args(argv)

    assert args.command == "service"
    assert args.service_cmd == expected_cmd
    assert getattr(args, "port", 8000) == (expected_port if expected_port is not None else 8000)
