#!/usr/bin/env python3
"""把部署配置和部署命令拼成一份可由 TAT 下发的 Shell 脚本。

背景
----
改用 TAT 下发后，原来的三处 scp 同步不复存在，配置得换个方式落地：

* 配置类文件（compose、部署脚本、Dockerfile、nginx、依赖锁定清单）总量只有
  二十多 KB，直接内联进命令最省事 —— 打成 tar.gz 再 base64，一次下发即落地，
  不需要对象存储中转，也不用额外开端口。
* wheel 是 MB 级，塞进命令会顶爆 TAT 的 64 KiB 上限，改由服务器自己下载并
  校验 sha256。

TAT 的 Content 上限是 64 KiB（且 Content 本身还要对命令再做一次 base64），
所以这里显式预检：超限直接失败并说明怎么拆，而不是等云端返回一个难读的错误。

环境变量
--------
VERSION, IMAGE_REPO, WHEEL_URL, WHEEL_NAME, WHEEL_SHA256   必需
WHEEL_MIRROR_URLS, BUILD_BASE_IMAGE, BUILD_PIP_INDEX_URL    可选
PAYLOAD_PATH   默认 /tmp/cndb-deploy-config.tgz
OUTPUT_PATH    默认 /tmp/cndb-deploy-cmd.sh

用法：python scripts/build_tat_command.py
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# TAT Content 的硬上限（base64 后的命令文本）
MAX_CONTENT_BYTES = 64 * 1024

# 载荷 heredoc 的定界符：不能与命令里任何一行重复
PAYLOAD_HEREDOC = "CNDB_DEPLOY_PAYLOAD_EOF"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"[build] 缺少环境变量 {name}")
    return value


def build_command(payload_b64: str) -> str:
    """拼装下发到实例的命令。"""
    version = require("VERSION")
    image_repo = require("IMAGE_REPO")
    wheel_url = require("WHEEL_URL")
    wheel_name = require("WHEEL_NAME")
    wheel_sha256 = require("WHEEL_SHA256")
    mirror_urls = env("WHEEL_MIRROR_URLS").split()
    # 镜像地址直接拼进 shell，先做一次白名单校验，避免空格/引号/命令替换字符
    for url in mirror_urls:
        if not url.startswith("https://") or any(ch.isspace() or ch in "'\"$`\\" for ch in url):
            raise SystemExit(f"[build] 非法的 PyPI 镜像地址：{url!r}")
    build_base_image = env("BUILD_BASE_IMAGE")
    build_pip_index_url = env("BUILD_PIP_INDEX_URL")

    lines: list[str] = [
        "set -Eeuo pipefail",
        "cd /opt/cndb",
        "",
        "# ── 1. 落地部署配置（替代原 scp 同步）────────────────────────────",
        "if ! command -v curl >/dev/null 2>&1; then",
        '  echo "[deploy] 缺少 curl，无法下载 wheel；请先安装 curl" >&2',
        "  exit 1",
        "fi",
    ]
    lines.append(f"base64 -d > /tmp/cndb-deploy-config.tgz <<'{PAYLOAD_HEREDOC}'")
    lines.append(payload_b64)
    lines.append(PAYLOAD_HEREDOC)
    lines += [
        "tar -xzf /tmp/cndb-deploy-config.tgz -C /opt/cndb",
        "rm -f /tmp/cndb-deploy-config.tgz",
        "chmod +x deploy/*.sh 2>/dev/null || true",
        'echo "[deploy] 部署配置已解包"',
        "",
        "# ── 2. 服务器布局与 .env 校验（原 Bootstrap 步骤）──────────────",
        "mkdir -p /opt/cndb/backups",
        "if [ ! -f .env ]; then",
        '  echo "[deploy] 错误：/opt/cndb/.env 不存在。首次部署请先执行 bash deploy/bootstrap-server.sh" >&2',
        "  exit 1",
        "fi",
        "if grep -q 'CHANGE_ME' .env; then",
        '  echo "[deploy] 错误：JWT_SECRET 仍是占位值，用 openssl rand -hex 32 生成后填入 .env" >&2',
        "  exit 1",
        "fi",
        "",
        "# ── 3. 取 wheel（原 scp 同步构建产物）──────────────────────────",
        "# 发布刚完成时国内镜像往往还没同步到新版本，旧逻辑只有「腾讯镜像 → 官方源」",
        "# 两跳，镜像一滞后就落到 files.pythonhosted.org（实测跨境仅 ~14KB/s，3MB 要",
        "# 200s+）。这里改为「多个国内镜像快速失败 → 官方源长超时兜底」，任一源落盘",
        "# 后都必须过 sha256 校验，校验不过继续换源。",
        "mkdir -p dist",
        "WHEEL_OK=0",
        "try_wheel() {",
        '  src="$1" max_time="$2" retry_opts="$3"',
        '  echo "[deploy] 下载 wheel: $src"',
        "  # shellcheck disable=SC2086  # retry_opts 需要按空格拆成多个参数",
        '  if curl -fsSL --connect-timeout 15 --max-time "$max_time" $retry_opts \\',
        f"      -o 'dist/{wheel_name}' \"$src\"; then",
        "    # 落盘后立刻校验：镜像可能返回不完整/陈旧文件，",
        "    # 校验失败要切下一个源，而不是直接判死整个部署。",
        f"    if echo '{wheel_sha256}  dist/{wheel_name}' | sha256sum -c - >/dev/null 2>&1; then",
        "      WHEEL_OK=1",
        '      echo "[deploy] wheel 校验通过"',
        "      return 0",
        "    fi",
        '    echo "[deploy] 该源文件校验失败，尝试下一个" >&2',
        "  else",
        '    echo "[deploy] 该源不可用，尝试下一个" >&2',
        "  fi",
        "  return 1",
        "}",
        "",
    ]
    # 没有可用镜像时生成空串占位，让循环体里的 [ -n "$src" ] 兜住
    mirror_list = " ".join(f"'{url}'" for url in mirror_urls) or "''"
    lines += [
        f"for src in {mirror_list}; do",
        '  [ -n "$src" ] || continue',
        "  try_wheel \"$src\" 90 '' && break",
        "done",
        'if [ "$WHEEL_OK" != "1" ]; then',
        '  echo "[deploy] 国内镜像均未命中，回退 PyPI 官方源（跨境可能较慢）..." >&2',
        f"  try_wheel '{wheel_url}' 900 '--retry 2 --retry-delay 3' || true",
        "fi",
        'if [ "$WHEEL_OK" != "1" ]; then',
        f'  echo "[deploy] 错误：dist/{wheel_name} 下载或校验失败（国内镜像与官方源均不可用）" >&2',
        "  exit 1",
        "fi",
        f"echo '{wheel_sha256}  dist/{wheel_name}' | sha256sum -c -",
        "",
        "# ── 4. 服务器端构建并部署（内置备份/健康探测/失败回滚）────────",
        f"IMAGE_REPO_OVERRIDE='{image_repo}' \\",
        "SERVER_BUILD=1 \\",
        f"BUILD_BASE_IMAGE='{build_base_image}' \\",
        f"BUILD_PIP_INDEX_URL='{build_pip_index_url}' \\",
        f"./deploy/deploy.sh '{version}'",
        "",
        "# ── 5. 部署后复查（外部视角二次确认）──────────────────────────",
        'echo "--- 容器状态 ---"',
        "docker ps --filter name=cndb --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}'",
        'echo "--- 健康端点 ---"',
        "curl -fsS http://127.0.0.1:8000/api/health || { echo '[deploy] 健康端点不可达' >&2; exit 1; }",
        'echo ""',
        f'echo "[deploy] 全部完成：{version}"',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    payload_path = Path(env("PAYLOAD_PATH", "/tmp/cndb-deploy-config.tgz"))
    output_path = Path(env("OUTPUT_PATH", "/tmp/cndb-deploy-cmd.sh"))

    if not payload_path.is_file():
        raise SystemExit(f"[build] 载荷不存在：{payload_path}")

    payload_b64 = base64.b64encode(payload_path.read_bytes()).decode("ascii")
    command = build_command(payload_b64)
    raw = command.encode("utf-8")

    # 命令还要被 TAT 再 base64 一次，按最坏情况（每 3 字节涨到 4 字节）估算
    content_bytes = (len(raw) + 2) // 3 * 4
    print(
        f"[build] 载荷 {payload_path.stat().st_size} 字节 → base64 {len(payload_b64)} 字节\n"
        f"[build] 命令 {len(raw)} 字节 → TAT Content 约 {content_bytes} 字节"
        f"（上限 {MAX_CONTENT_BYTES}）"
    )
    if content_bytes >= MAX_CONTENT_BYTES:
        raise SystemExit(
            f"[build] 命令过大（Content 约 {content_bytes} 字节 ≥ {MAX_CONTENT_BYTES}）。\n"
            "  TAT 单条命令装不下，需要拆成两条：先下发配置载荷并落盘，再下发执行命令。\n"
            "  若只是配置体积增长，优先剔除不参与部署的文件（如 deploy/nginx/extra 的示例）。"
        )

    output_path.write_text(command, encoding="utf-8")
    print(f"[build] 已生成 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
