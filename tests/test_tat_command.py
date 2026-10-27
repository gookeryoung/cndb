"""锁定 TAT 下发命令里的服务器侧构建源 profile（不继承 GitHub runner 的 global）."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    payload = tmp_path / "payload.tgz"
    payload.write_bytes(b"payload")
    output = tmp_path / "cmd.sh"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "VERSION": "0.3.0",
        "IMAGE_REPO": "ccr.example/pydev/cndb",
        "WHEEL_URL": "https://pypi.org/packages/aa/cndb-0.3.0.whl",
        "WHEEL_NAME": "cndb-0.3.0-py3-none-any.whl",
        "WHEEL_SHA256": "0" * 64,
        "PAYLOAD_PATH": str(payload),
        "OUTPUT_PATH": str(output),
    }
    env.update(extra)
    return subprocess.run(
        [sys.executable, "scripts/build_tat_command.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestTatCommandSources:
    def test_server_defaults_to_cn(self, tmp_path: Path) -> None:
        result = _run(tmp_path)

        assert result.returncode == 0, result.stderr
        command = (tmp_path / "cmd.sh").read_text(encoding="utf-8")
        assert "CNDB_SOURCES='cn'" in command
        # GitHub runner 的环境不会被抄进服务器命令
        assert "CNDB_SOURCES='global'" not in command

    def test_explicit_profile_is_passed_through(self, tmp_path: Path) -> None:
        result = _run(tmp_path, CNDB_SOURCES="global")

        assert result.returncode == 0, result.stderr
        assert "CNDB_SOURCES='global'" in (tmp_path / "cmd.sh").read_text(encoding="utf-8")

    def test_invalid_profile_fails_loudly(self, tmp_path: Path) -> None:
        result = _run(tmp_path, CNDB_SOURCES="fast")

        assert result.returncode != 0
        assert "非法的 CNDB_SOURCES" in result.stderr

    @pytest.mark.parametrize("profile", ["cn", "global"])
    def test_command_still_fits_tat_limit(self, tmp_path: Path, profile: str) -> None:
        result = _run(tmp_path, CNDB_SOURCES=profile)

        assert result.returncode == 0, result.stderr
        assert "上限 65536" in result.stdout


class TestTatWheelFallback:
    """镜像同步滞后时按轮重试，而不是立刻掉到跨境官方源。"""

    def test_mirrors_retry_in_window_before_official(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            WHEEL_MIRROR_URLS="https://mirror.example/packages/aa/cndb.whl",
        )

        assert result.returncode == 0, result.stderr
        command = (tmp_path / "cmd.sh").read_text(encoding="utf-8")
        # 有重试窗口与轮次，且窗口在官方源兜底之前结束
        assert "MIRROR_DEADLINE=" in command
        assert command.index('while [ "$WHEEL_OK" != "1" ]') < command.index("回退 PyPI 官方源")
        # 官方源仍在镜像全部落空后兜底
        assert "https://pypi.org/packages/aa/cndb-0.3.0.whl" in command

    def test_no_mirrors_skips_retry_loop(self, tmp_path: Path) -> None:
        result = _run(tmp_path)

        assert result.returncode == 0, result.stderr
        command = (tmp_path / "cmd.sh").read_text(encoding="utf-8")
        # 没有镜像时不生成重试循环，否则会空转整个重试窗口
        assert "MIRROR_DEADLINE=" not in command
        assert "回退 PyPI 官方源" in command
