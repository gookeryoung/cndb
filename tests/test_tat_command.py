"""锁定 TAT 下发命令里的服务器侧构建源 profile（不继承 GitHub runner 的 global）."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path: Path, *, payload_bytes: bytes = b"payload", **extra: str) -> subprocess.CompletedProcess[str]:
    payload = tmp_path / "payload.tgz"
    payload.write_bytes(payload_bytes)
    output = tmp_path / "cmd.sh"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        # Windows 管道默认用 locale（GBK）编码输出，强制 UTF-8 保证两端一致
        "PYTHONIOENCODING": "utf-8",
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
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _output_files(tmp_path: Path) -> list[Path]:
    """按文件名顺序返回生成的命令文件（分片在前，部署命令 -99 在后）。"""
    return sorted(tmp_path.glob("cmd-*.sh"))


def _final_command(tmp_path: Path) -> str:
    files = _output_files(tmp_path)
    assert files, "未生成任何命令文件"
    return files[-1].read_text(encoding="utf-8")


class TestTatCommandSources:
    def test_server_defaults_to_cn(self, tmp_path: Path) -> None:
        result = _run(tmp_path)

        assert result.returncode == 0, result.stderr
        command = _final_command(tmp_path)
        assert "CNDB_SOURCES='cn'" in command
        # GitHub runner 的环境不会被抄进服务器命令
        assert "CNDB_SOURCES='global'" not in command

    def test_explicit_profile_is_passed_through(self, tmp_path: Path) -> None:
        result = _run(tmp_path, CNDB_SOURCES="global")

        assert result.returncode == 0, result.stderr
        assert "CNDB_SOURCES='global'" in _final_command(tmp_path)

    def test_invalid_profile_fails_loudly(self, tmp_path: Path) -> None:
        result = _run(tmp_path, CNDB_SOURCES="fast")

        assert result.returncode != 0
        assert "非法的 CNDB_SOURCES" in result.stderr

    @pytest.mark.parametrize("profile", ["cn", "global"])
    def test_every_command_fits_tat_limit(self, tmp_path: Path, profile: str) -> None:
        result = _run(tmp_path, CNDB_SOURCES=profile)

        assert result.returncode == 0, result.stderr
        assert "1 条部署命令" in (result.stdout or "")
        # 每条命令（含最后一条）都必须在 TAT 的 64 KiB Content 上限内
        for f in _output_files(tmp_path):
            assert len(f.read_text(encoding="utf-8").encode("utf-8")) <= 48 * 1024


class TestTatPayloadChunking:
    """载荷按分片拆成多条命令，避免单条超出 TAT 64 KiB 上限。"""

    def test_chunks_reassemble_to_payload_base64(self, tmp_path: Path) -> None:
        payload_bytes = bytes(range(256)) * 300  # 约 75 KB，超过单条上限，必然分片
        result = _run(tmp_path, payload_bytes=payload_bytes)

        assert result.returncode == 0, result.stderr
        files = _output_files(tmp_path)
        assert len(files) >= 3  # ≥2 条分片 + 1 条部署命令
        # 分片命令按序追加，拼接后应还原出完整载荷的 base64
        import re

        chunks: list[str] = []
        for f in files[:-1]:
            text = f.read_text(encoding="utf-8")
            match = re.search(r"<<'CNDB_DEPLOY_PAYLOAD_EOF'\n(.+)\nCNDB_DEPLOY_PAYLOAD_EOF", text, re.DOTALL)
            assert match, f"分片命令缺少 heredoc：{f.name}"
            chunks.append(match.group(1))
        assert base64.b64decode("".join(chunks)) == payload_bytes
        # 部署命令不再内联载荷，只负责解码落地
        final = _final_command(tmp_path)
        assert "base64 -d /tmp/cndb-deploy-config.b64 > /tmp/cndb-deploy-config.tgz" in final
        assert "CNDB_DEPLOY_PAYLOAD_EOF" not in final


class TestTatWheelFallback:
    """镜像同步滞后时按轮重试，而不是立刻掉到跨境官方源。"""

    def test_mirrors_retry_in_window_before_official(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            WHEEL_MIRROR_URLS="https://mirror.example/packages/aa/cndb.whl",
        )

        assert result.returncode == 0, result.stderr
        command = _final_command(tmp_path)
        # 有重试窗口与轮次，且窗口在官方源兜底之前结束
        assert "MIRROR_DEADLINE=" in command
        assert command.index('while [ "$WHEEL_OK" != "1" ]') < command.index("回退 PyPI 官方源")
        # 官方源仍在镜像全部落空后兜底
        assert "https://pypi.org/packages/aa/cndb-0.3.0.whl" in command

    def test_no_mirrors_skips_retry_loop(self, tmp_path: Path) -> None:
        result = _run(tmp_path)

        assert result.returncode == 0, result.stderr
        command = _final_command(tmp_path)
        # 没有镜像时不生成重试循环，否则会空转整个重试窗口
        assert "MIRROR_DEADLINE=" not in command
        assert "回退 PyPI 官方源" in command
