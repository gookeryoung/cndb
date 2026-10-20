"""锁定 deploy/ 离线构建与导出脚本的判定口径（ADR 0008 的脚本回归）.

脚本无后端覆盖率口径（`make cov` 只统计 cndb 包），故用**静态检查 + 假 docker 桩**钉住三条不变量：
  · 三个脚本可被 bash 解析（`bash -n`）；
  · `export-image.sh` 在无外网下产出**结构完整**的离线交付包（镜像 tar + 编排 + SHA256SUMS 且校验可过）；
  · `build-image.sh` 默认用**无 registry 前缀**的本地名（C5），且缺少 wheel 时立即失败（不静默）。
"""

from __future__ import annotations

import gzip
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("build-image.sh", "export-image.sh", "deploy.sh")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="需要 bash")


def _repo_copy(tmp_path: Path) -> Path:
    """复制脚本运行所需的仓库子集（deploy/ + compose），避免污染真实工作区."""
    repo = tmp_path / "repo"
    (repo / "dist").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", repo / "deploy")
    shutil.copy(ROOT / "docker-compose.prod.yml", repo / "docker-compose.prod.yml")
    return repo


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    """造一个假 docker：inspect 恒成功、save 产假 tar、其余记录调用后成功返回."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    shim = bin_dir / "docker"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'cmd="$1"; shift || true\n'
        'case "$cmd" in\n'
        "  image) exit 0 ;;\n"
        '  save) printf "FAKE-IMAGE-TAR" ; exit 0 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return bin_dir, log


def _env(tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    return {"PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}", "HOME": str(tmp_path)}


class TestSyntax:
    @pytest.mark.parametrize("name", SCRIPTS)
    def test_bash_syntax_ok(self, name: str) -> None:
        result = subprocess.run([BASH, "-n", str(ROOT / "deploy" / name)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


class TestBuildImage:
    def test_missing_wheel_fails_fast(self, tmp_path: Path) -> None:
        repo = _repo_copy(tmp_path)
        (repo / "dist" / "requirements.lock.txt").write_text("fastapi==1.0\n", encoding="utf-8")
        bin_dir, _ = _fake_docker(tmp_path)

        result = subprocess.run(
            [BASH, "deploy/build-image.sh", "0.3.0"],
            cwd=repo,
            env=_env(tmp_path, bin_dir),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "请先执行 make build" in result.stderr
        assert "缺少 dist/cndb-0.3.0-*.whl" in result.stderr

    def test_defaults_to_local_tag(self, tmp_path: Path) -> None:
        repo = _repo_copy(tmp_path)
        (repo / "dist" / "requirements.lock.txt").write_text("fastapi==1.0\n", encoding="utf-8")
        (repo / "dist" / "cndb-0.3.0-py3-none-any.whl").write_bytes(b"whl")
        bin_dir, log = _fake_docker(tmp_path)

        result = subprocess.run(
            [BASH, "deploy/build-image.sh", "0.3.0"],
            cwd=repo,
            env=_env(tmp_path, bin_dir),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = log.read_text(encoding="utf-8")
        # 未设 IMAGE_REPO → 用无 registry 前缀的本地名（ADR 0008 C5）
        assert "build -f deploy/Dockerfile.prod --build-arg BASE_IMAGE=cndb-base:deps-" in calls
        assert "-t cndb:0.3.0" in calls


class TestExportImage:
    def _export(self, env: dict[str, str], repo: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, "deploy/export-image.sh", "0.3.0"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_bundle_structure_and_checksums(self, tmp_path: Path) -> None:
        repo = _repo_copy(tmp_path)
        bin_dir, _ = _fake_docker(tmp_path)
        env = _env(tmp_path, bin_dir)

        result = self._export(env, repo)

        assert result.returncode == 0, result.stderr
        out = repo / "dist" / "offline" / "cndb-0.3.0-offline"
        for name in (
            "cndb-0.3.0-image.tar.gz",
            "nginx-image.tar.gz",
            "docker-compose.prod.yml",
            "SHA256SUMS",
            "OFFLINE-README.txt",
        ):
            assert (out / name).is_file(), f"交付包缺少 {name}"
        assert (out / "deploy" / "deploy.sh").is_file()

        # 交付包内脚本须带执行位：离线机用法是 `./deploy/deploy.sh`（仓库内为 644）
        shipped = out / "deploy" / "deploy.sh"
        assert shipped.stat().st_mode & stat.S_IXUSR, "交付包内 deploy/deploy.sh 缺少执行位"

        # 镜像 tar 是经 gzip 压缩的真实产物
        with gzip.open(out / "cndb-0.3.0-image.tar.gz") as fh:
            assert fh.read() == b"FAKE-IMAGE-TAR"

        # 校验清单可过（离线机 `sha256sum -c` 的实际口径）
        check = subprocess.run(
            ["sha256sum", "-c", "SHA256SUMS"],
            cwd=out,
            capture_output=True,
            text=True,
            check=False,
        )
        assert check.returncode == 0, check.stdout + check.stderr

        assert (repo / "dist" / "offline" / "cndb-0.3.0-offline-bundle.tar.gz").is_file()

    def test_missing_app_image_fails(self, tmp_path: Path) -> None:
        repo = _repo_copy(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "docker"
        # inspect 失败 → 视为本地无应用镜像
        shim.write_text('#!/usr/bin/env bash\n[[ "$1" == "image" ]] && exit 1\nexit 0\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

        result = self._export(_env(tmp_path, bin_dir), repo)

        assert result.returncode != 0
        assert "本地无应用镜像 cndb:0.3.0" in result.stderr
