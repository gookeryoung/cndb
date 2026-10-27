"""锁定 deploy/ 离线构建与导出脚本的判定口径（ADR 0008 的脚本回归）.

脚本无后端覆盖率口径（`make cov` 只统计 cndb 包），故用**静态检查 + 假 docker 桩**钉住三条不变量：
  · 三个脚本可被 bash 解析（`bash -n`）；
  · `export-image.sh` 在无外网下产出**结构完整**的离线交付包（镜像 tar + 编排 + SHA256SUMS 且校验可过）；
  · `build-image.sh` 默认用**无 registry 前缀**的本地名（C5），且缺少 wheel 时立即失败（不静默）。
"""

from __future__ import annotations

import gzip
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("build-image.sh", "export-image.sh", "deploy.sh", "docker-sources.sh")
BASH = shutil.which("bash")
# Windows 开发机上的 bash 多为 MSYS/Gow 包装器（反斜杠路径不认、subprocess 直接调用恒返回 1），
# 脚本本身是 POSIX sh，CI（Linux）已完整覆盖；此处跳过避免本地门禁假红。
pytestmark = [
    pytest.mark.skipif(BASH is None, reason="需要 bash"),
    pytest.mark.skipif(os.name == "nt", reason="部署脚本回归只在 POSIX bash 下有意义（CI 为 Linux）"),
]


def _repo_copy(tmp_path: Path) -> Path:
    """复制脚本运行所需的仓库子集（deploy/ + compose），避免污染真实工作区."""
    repo = tmp_path / "repo"
    (repo / "dist").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", repo / "deploy")
    shutil.copy(ROOT / "docker-compose.prod.yml", repo / "docker-compose.prod.yml")
    return repo


def _fake_docker(tmp_path: Path, *, inspect_ok: bool = True) -> tuple[Path, Path]:
    """造一个假 docker：inspect 默认恒成功、save 产假 tar、其余记录调用后成功返回.

    ``inspect_ok=False`` 用来模拟「本地无依赖基础镜像」，逼出真实 build 调用。
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    shim = bin_dir / "docker"
    image_rc = 0 if inspect_ok else 1
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'cmd="$1"; shift || true\n'
        'case "$cmd" in\n'
        f"  image) exit {image_rc} ;;\n"
        '  save) printf "FAKE-IMAGE-TAR" ; exit 0 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return bin_dir, log


def _env(tmp_path: Path, bin_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}", "HOME": str(tmp_path)}
    env.update(extra or {})
    return env


class TestSyntax:
    @pytest.mark.parametrize("name", SCRIPTS)
    def test_bash_syntax_ok(self, name: str) -> None:
        result = subprocess.run([BASH, "-n", str(ROOT / "deploy" / name)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def _resolve_sources(extra: dict[str, str] | None = None) -> dict[str, str]:
    """调用唯一源解析入口，把 KEY=VALUE 输出解析成 dict."""
    env = {
        "PATH": f"{Path('/usr/bin')}:{Path('/bin')}",
        "HOME": "/tmp",
    }
    env.update(extra or {})
    result = subprocess.run(
        [BASH, "deploy/docker-sources.sh", "print"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


class TestDockerSources:
    def test_auto_defaults_to_cn_outside_github(self) -> None:
        values = _resolve_sources()
        assert values["CNDB_SOURCES_RESOLVED"] == "cn"
        assert values["BASE_IMAGE"].startswith("docker.m.daocloud.io/")
        assert values["APT_MIRROR_HOST"] == "mirrors.cloud.tencent.com"
        assert values["PIP_INDEX_URL"] == "https://mirrors.cloud.tencent.com/pypi/simple"
        assert values["UV_DEFAULT_INDEX"] == "https://mirrors.cloud.tencent.com/pypi/simple"
        assert values["NPM_REGISTRY"] == "https://registry.npmmirror.com"

    def test_github_actions_defaults_to_global(self) -> None:
        values = _resolve_sources({"GITHUB_ACTIONS": "true"})
        assert values["CNDB_SOURCES_RESOLVED"] == "global"
        assert values["BASE_IMAGE"] == "python:3.12-slim"
        assert values["APT_MIRROR_HOST"] == ""
        assert values["PIP_INDEX_URL"] == "https://pypi.org/simple"
        assert values["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"
        assert values["NPM_REGISTRY"] == "https://registry.npmjs.org/"

    def test_explicit_profile_beats_github_detection(self) -> None:
        values = _resolve_sources({"GITHUB_ACTIONS": "true", "CNDB_SOURCES": "cn"})
        assert values["CNDB_SOURCES_RESOLVED"] == "cn"

    def test_invalid_profile_fails_loudly(self) -> None:
        result = subprocess.run(
            [BASH, "deploy/docker-sources.sh", "detect"],
            cwd=ROOT,
            env={"PATH": f"{Path('/usr/bin')}:{Path('/bin')}", "HOME": "/tmp", "CNDB_SOURCES": "fast"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "允许 auto / cn / global" in result.stderr

    def test_single_overrides_beat_profile(self) -> None:
        values = _resolve_sources(
            {
                "BUILD_BASE_IMAGE": "registry.example/python:3.13-slim",
                "BUILD_PIP_INDEX_URL": "https://pip.example/simple",
                "CNDB_APT_MIRROR": "",
                "CNDB_NGINX_IMAGE": "registry.example/nginx:custom",
                "CNDB_NPM_REGISTRY": "https://npm.example/",
            }
        )
        assert values["CNDB_SOURCES_RESOLVED"] == "cn"
        assert values["BASE_IMAGE"] == "registry.example/python:3.13-slim"
        assert values["PIP_INDEX_URL"] == "https://pip.example/simple"
        # 显式空串 = 明确使用官方 Debian 源，不能被国内 profile 覆盖
        assert values["APT_MIRROR_HOST"] == ""
        assert values["NGINX_IMAGE"] == "registry.example/nginx:custom"
        assert values["NPM_REGISTRY"] == "https://npm.example/"


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

    def _build(self, tmp_path: Path, extra: dict[str, str]) -> str:
        repo = _repo_copy(tmp_path)
        (repo / "dist" / "requirements.lock.txt").write_text("fastapi==1.0\n", encoding="utf-8")
        (repo / "dist" / "cndb-0.3.0-py3-none-any.whl").write_bytes(b"whl")
        # inspect 失败 → 触发依赖基础镜像真实构建，才能看到源参数
        bin_dir, log = _fake_docker(tmp_path, inspect_ok=False)
        result = subprocess.run(
            [BASH, "deploy/build-image.sh", "0.3.0"],
            cwd=repo,
            env=_env(tmp_path, bin_dir, extra),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return log.read_text(encoding="utf-8")

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

    def test_local_build_uses_cn_profile(self, tmp_path: Path) -> None:
        calls = self._build(tmp_path, {})
        assert "--build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim" in calls
        assert "--build-arg APT_MIRROR_HOST=mirrors.cloud.tencent.com" in calls
        assert "--build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple" in calls

    def test_global_profile_uses_official_sources(self, tmp_path: Path) -> None:
        calls = self._build(tmp_path, {"CNDB_SOURCES": "global"})
        assert "--build-arg BASE_IMAGE=python:3.12-slim" in calls
        assert "--build-arg APT_MIRROR_HOST= --build-arg PIP_INDEX_URL=https://pypi.org/simple" in calls


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
        bin_dir, log = _fake_docker(tmp_path)
        env = _env(tmp_path, bin_dir)

        result = self._export(env, repo)

        assert result.returncode == 0, result.stderr
        calls = log.read_text(encoding="utf-8")
        # 本地默认 cn：nginx 镜像走国内代理
        assert "save docker.m.daocloud.io/library/nginx:1.27-alpine" in calls
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

    def test_global_profile_exports_official_nginx(self, tmp_path: Path) -> None:
        repo = _repo_copy(tmp_path)
        bin_dir, log = _fake_docker(tmp_path)

        result = self._export(_env(tmp_path, bin_dir, {"CNDB_SOURCES": "global"}), repo)

        assert result.returncode == 0, result.stderr
        assert "save nginx:1.27-alpine" in log.read_text(encoding="utf-8")

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
