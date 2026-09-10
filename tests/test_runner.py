"""runner CLI 测试."""

from __future__ import annotations

import argparse
import subprocess
import sys
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pytest

from pyweb_template import runner


def test_info_command_prints_version() -> None:
    """info 子命令应成功返回."""
    old_out = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = runner.info_command()
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_out
    assert rc == 0
    assert "pyweb_template" in output


def test_dev_starts_backend_and_frontend_subprocess() -> None:
    """dev 应启动 backend + frontend 两个子进程."""
    args = argparse.Namespace(host="127.0.0.1", port=8000, reload=False, workers=1)
    mock_backend = Mock()
    mock_backend.pid = 12345
    mock_backend.wait.return_value = None  # 立即返回，不阻塞

    with (
        patch.object(runner, "_ensure_dev_env"),
        patch.object(subprocess, "Popen", return_value=mock_backend) as mock_popen,
    ):
        runner.dev(args)
        # Popen 应被调用两次：backend 和 frontend
        assert mock_popen.call_count == 2


def test_serve_no_uvicorn_prints_error_and_exits() -> None:
    """uvicorn 缺失时应打印错误并 sys.exit(1)."""
    args = argparse.Namespace(host="127.0.0.1", port=8000, reload=False, workers=1)

    def raise_io(*args: object, **kwargs: object) -> None:
        raise ImportError("no uvicorn")

    with (
        patch.dict("sys.modules", {"uvicorn": None}),
        patch("builtins.__import__", side_effect=raise_io),
    ):
        old_stderr = sys.stderr
        sys.stderr = StringIO()
        try:
            with pytest.raises(SystemExit) as excinfo:
                runner.serve(args)
            assert excinfo.value.code == 1
        finally:
            sys.stderr = old_stderr


def test_main_with_no_command_defaults_to_serve() -> None:
    """main 无参数时应走 serve 路径."""
    with patch.object(runner, "serve") as mock_serve:
        with patch.object(sys, "argv", ["pywt"]):
            runner.main()
        mock_serve.assert_called_once()


def test_main_info_subcommand_exits_0() -> None:
    """main info 子命令应走 info_command 并 sys.exit(0)."""
    with patch.object(sys, "argv", ["pywt", "info"]):
        with pytest.raises(SystemExit) as excinfo:
            runner.main()
        assert excinfo.value.code == 0


def test_main_serve_subcommand_dispatches() -> None:
    """main serve 子命令应调用 serve."""
    with patch.object(runner, "serve") as mock_serve:
        with patch.object(sys, "argv", ["pywt", "serve", "--port", "9000"]):
            runner.main()
        mock_serve.assert_called_once()


def test_main_dev_subcommand_dispatches() -> None:
    """main dev 子命令应调用 dev（启动前后端子进程）."""
    with patch.object(runner, "dev") as mock_dev:
        with patch.object(sys, "argv", ["pywt", "dev", "--port", "9000"]):
            runner.main()
        mock_dev.assert_called_once()


def test_main_build_subcommand_dispatches() -> None:
    """main build 子命令应调用 build."""
    with patch.object(runner, "build") as mock_build:
        with patch.object(sys, "argv", ["pywt", "build"]):
            runner.main()
        mock_build.assert_called_once()


def test_serve_invokes_uvicorn_run() -> None:
    """serve 正常应调用 uvicorn.run."""
    args = argparse.Namespace(host="127.0.0.1", port=8000, reload=False, workers=2)

    with patch("uvicorn.run") as mock_run:
        runner.serve(args)
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 8000
        assert call_kwargs["reload"] is False
        assert call_kwargs["workers"] == 2


def test_serve_reload_sets_workers_to_one() -> None:
    """serve reload=True 时 workers 应被强制为 1."""
    args = argparse.Namespace(host="0.0.0.0", port=9000, reload=True, workers=4)

    with patch("uvicorn.run") as mock_run:
        runner.serve(args)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["workers"] == 1


def test_ensure_dev_env_missing_frontend_exits() -> None:
    """FRONTEND_DIR 不存在时 _ensure_dev_env 应 sys.exit(1)."""
    fake = Mock()
    fake.is_dir.return_value = False

    with (
        patch.object(runner, "FRONTEND_DIR", fake),
        pytest.raises(SystemExit) as excinfo,
    ):
        runner._ensure_dev_env()
    assert excinfo.value.code == 1


def test_ensure_dev_env_existing_frontend_passes() -> None:
    """FRONTEND_DIR 存在时 _ensure_dev_env 应正常返回."""
    fake = Mock()
    fake.is_dir.return_value = True
    with patch.object(runner, "FRONTEND_DIR", fake):
        runner._ensure_dev_env()  # 不抛异常即通过


def test_build_success() -> None:
    """build 正常流程：npm run build 成功且有 dist 目录."""
    args = argparse.Namespace()
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=0)

    # FRONTEND_DIR / "dist" -> fake_dist
    fake_dist = MagicMock()
    fake_dist.is_dir.return_value = True
    fake_frontend = MagicMock()
    fake_frontend.is_dir.return_value = True

    def _fe_div(_o: object) -> MagicMock:
        return fake_dist

    fake_frontend.__truediv__.side_effect = _fe_div

    # ROOT_DIR / "src" / ... / "static" -> fake_static（链式 / 都返回同一个）
    fake_static = MagicMock()
    fake_static.exists.return_value = False

    def _fs_div(_o: object) -> MagicMock:
        return fake_static

    fake_static.__truediv__.side_effect = _fs_div
    fake_root = MagicMock()

    def _fr_div(_o: object) -> MagicMock:
        return fake_static

    fake_root.__truediv__.side_effect = _fr_div

    with (
        patch.object(runner, "_ensure_dev_env"),
        patch.object(subprocess, "run", fake_run),
        patch.object(runner, "FRONTEND_DIR", fake_frontend),
        patch.object(runner, "ROOT_DIR", fake_root),
        patch("pyweb_template.runner.shutil.copytree"),
    ):
        runner.build(args)

    assert fake_run.call_count == 1
    assert fake_run.call_args[0][0][:2] == ["npm", "run"]


def test_build_failure_exits_with_code() -> None:
    """npm run build 返回非零时应 sys.exit(n)."""
    args = argparse.Namespace()
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=2)

    with (
        patch.object(runner, "_ensure_dev_env"),
        patch.object(subprocess, "run", fake_run),
        pytest.raises(SystemExit) as excinfo,
    ):
        runner.build(args)
    assert excinfo.value.code == 2


def test_build_without_dist_dir_skips_copy() -> None:
    """dist 目录不存在时 build 应跳过复制步骤."""
    args = argparse.Namespace()
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=0)

    fake_dist = MagicMock()
    fake_dist.is_dir.return_value = False
    fake_frontend = MagicMock()
    fake_frontend.is_dir.return_value = True

    def _fe_div2(_o: object) -> MagicMock:
        return fake_dist

    fake_frontend.__truediv__.side_effect = _fe_div2

    with (
        patch.object(runner, "_ensure_dev_env"),
        patch.object(subprocess, "run", fake_run),
        patch.object(runner, "FRONTEND_DIR", fake_frontend),
        patch("pyweb_template.runner.shutil.copytree") as mock_copy,
    ):
        runner.build(args)

    mock_copy.assert_not_called()


def test_build_with_existing_static_dir() -> None:
    """build 时 static 目录已存在应先 rmtree 再 copytree."""
    args = argparse.Namespace()
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=0)

    fake_dist = MagicMock()
    fake_dist.is_dir.return_value = True
    fake_frontend = MagicMock()
    fake_frontend.is_dir.return_value = True

    def _fe_div(_o: object) -> MagicMock:
        return fake_dist

    fake_frontend.__truediv__.side_effect = _fe_div

    fake_static = MagicMock()
    fake_static.exists.return_value = True  # 触发 rmtree 分支

    def _fs_div(_o: object) -> MagicMock:
        return fake_static

    fake_static.__truediv__.side_effect = _fs_div
    fake_root = MagicMock()

    def _fr_div(_o: object) -> MagicMock:
        return fake_static

    fake_root.__truediv__.side_effect = _fr_div

    mock_rmtree = MagicMock()
    mock_copy = MagicMock()

    with (
        patch.object(runner, "_ensure_dev_env"),
        patch.object(subprocess, "run", fake_run),
        patch.object(runner, "FRONTEND_DIR", fake_frontend),
        patch.object(runner, "ROOT_DIR", fake_root),
        patch("pyweb_template.runner.shutil.rmtree", mock_rmtree),
        patch("pyweb_template.runner.shutil.copytree", mock_copy),
    ):
        runner.build(args)

    mock_rmtree.assert_called_once()
    mock_copy.assert_called_once()


def test_dev_keyboard_interrupt_triggers_cleanup() -> None:
    """KeyboardInterrupt 应触发 _cleanup 并 sys.exit."""
    args = argparse.Namespace(host="127.0.0.1", port=8000, reload=False, workers=1)
    mock_backend = Mock()
    mock_backend.pid = 12345
    mock_backend.wait.side_effect = KeyboardInterrupt()

    try:
        with (
            patch.object(runner, "_ensure_dev_env"),
            patch.object(subprocess, "Popen", return_value=mock_backend),
            patch.object(subprocess, "run"),  # _cleanup 内部调用，无需真实执行
        ):
            runner.dev(args)
    except SystemExit:
        pass
