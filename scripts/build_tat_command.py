#!/usr/bin/env python3
"""把部署配置和部署命令拼成一份可由 TAT 下发的 Shell 脚本。

背景
----
改用 TAT 下发后，原来的三处 scp 同步不复存在，配置得换个方式落地：

* 配置类文件（compose、部署脚本、Dockerfile、nginx、依赖锁定清单）总量是
  几十 KB，打包成 tar.gz + base64 后按分片内联进命令下发落地 —— 不需要对象
  存储中转，也不用额外开端口。
* wheel 是 MB 级，塞进命令会顶爆 TAT 的 64 KiB 上限，改由服务器自己下载并
  校验 sha256。

TAT 的 Content 上限是 64 KiB（且 Content 本身还要对命令再做一次 base64），
单条命令装不下完整载荷，所以拆成多条下发（按 OUTPUT_PATH 前缀编号）：

* 前面每条命令只携带一段 base64 分片（每片 ≤ PAYLOAD_CHUNK_CHARS 字符），
  追加写入 /tmp/cndb-deploy-config.b64；
* 最后一条命令把 .b64 解码为 tar.gz 落盘后执行原部署逻辑。

这样命令模板的体积增长不再挤压载荷空间，只需按分片数多下发几条。

环境变量
--------
VERSION, IMAGE_REPO, WHEEL_URL, WHEEL_NAME, WHEEL_SHA256   必需
WHEEL_MIRROR_URLS, BUILD_BASE_IMAGE, BUILD_PIP_INDEX_URL    可选
CNDB_SOURCES    服务器侧构建源 profile（默认 cn；不继承 GitHub runner 的 global）
PAYLOAD_PATH   默认 /tmp/cndb-deploy-config.tgz
OUTPUT_PATH    默认 /tmp/cndb-deploy-cmd.sh

用法：python scripts/build_tat_command.py
输出：<OUTPUT_PATH 去掉 .sh> -01.sh、-02.sh…（载荷分片）+ -99.sh（部署命令），
按文件名顺序逐条下发（见 .github/workflows/deploy-tencent.yml）。
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

# 载荷 base64 分片大小：单条分片命令 = 分片 + 固定壳约 300 字节，
# base64 后 Content 约 60 KiB，稳定低于 64 KiB 上限。
PAYLOAD_CHUNK_CHARS = 45_000

# 载荷在服务器侧的中转文件（拼接的 base64 文本，落地后解码为 tar.gz）
PAYLOAD_B64_PATH = "/tmp/cndb-deploy-config.b64"
PAYLOAD_TGZ_PATH = "/tmp/cndb-deploy-config.tgz"

# 部署命令文件的后缀编号：数字最大，保证按文件名排序时最后执行
FINAL_COMMAND_SUFFIX = "99"

# 国内镜像重试窗口：发布后镜像同步有分钟级延迟，窗口内按轮重试（每轮间隔若干秒），
# 超窗后才回退跨境官方源。总时长受此窗口约束，不会把部署拖到超时。
MIRROR_WINDOW_SECONDS = 420
MIRROR_RETRY_SLEEP_SECONDS = 20


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"[build] 缺少环境变量 {name}")
    return value


def build_payload_command(chunk: str, index: int, total: int) -> str:
    """拼装一条载荷分片命令：把分片追加到服务器侧的 .b64 中转文件。"""
    op = ">" if index == 1 else ">>"
    lines = [
        "set -Eeuo pipefail",
        f"cat {op} {PAYLOAD_B64_PATH} <<'{PAYLOAD_HEREDOC}'",
        chunk,
        PAYLOAD_HEREDOC,
        f'echo "[deploy] 载荷分片 {index}/{total} 已落地"',
        "",
    ]
    return "\n".join(lines)


def build_command() -> str:
    """拼装最后下发的部署命令（不含载荷，载荷已由前面的分片命令落地）。"""
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
    # 服务器在腾讯云内网，默认国内源；显式写入命令，绝不继承 GitHub runner 的 global。
    server_sources = env("CNDB_SOURCES") or "cn"
    if server_sources not in {"cn", "global", "auto"}:
        raise SystemExit(f"[build] 非法的 CNDB_SOURCES：{server_sources!r}（允许 cn / global / auto）")

    lines: list[str] = [
        "set -Eeuo pipefail",
        "cd /opt/cndb",
        "",
        "# ── 1. 解码并落地部署配置（前面分片命令已拼接好 base64）───────",
        "if ! command -v curl >/dev/null 2>&1; then",
        '  echo "[deploy] 缺少 curl，无法下载 wheel；请先安装 curl" >&2',
        "  exit 1",
        "fi",
    ]
    lines += [
        f"base64 -d {PAYLOAD_B64_PATH} > {PAYLOAD_TGZ_PATH}",
        f"rm -f {PAYLOAD_B64_PATH}",
        f"tar -xzf {PAYLOAD_TGZ_PATH} -C /opt/cndb",
        f"rm -f {PAYLOAD_TGZ_PATH}",
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
        "# 发布刚完成时国内镜像往往还没同步到新版本（同步滞后数分钟），旧逻辑一滞后就",
        "# 直接落到 files.pythonhosted.org（实测跨境仅 ~14KB/s，3MB 要 200s+，且常被",
        "# reset）。这里先在时间窗内按轮重试多家国内镜像（等同步追上），全部落空才用",
        "# 官方源长超时兜底；任一源落盘后都必须过 sha256 校验，校验不过继续换源。",
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
    if mirror_urls:
        lines += [
            # 国内镜像同步新版本有分钟级延迟：发布后立刻部署时，全部镜像可能同时 404，
            # 此时如果直接落到官方源，就会因跨境链路被 reset / 超时而整轮失败（实测
            # 0.4.19 发布 2 分钟后部署即如此）。改为在时间窗内按轮重试镜像，等同步追上来。
            f"MIRROR_DEADLINE=$(( $(date +%s) + {MIRROR_WINDOW_SECONDS} ))",
            "ROUND=0",
            'while [ "$WHEEL_OK" != "1" ] && [ "$(date +%s)" -lt "$MIRROR_DEADLINE" ]; do',
            "  ROUND=$((ROUND + 1))",
            '  if [ "$ROUND" -gt 1 ]; then',
            '    echo "[deploy] 第 ${ROUND} 轮重试（镜像可能仍在同步新版本，等待 '
            f'{MIRROR_RETRY_SLEEP_SECONDS}s）..." >&2',
            f"    sleep {MIRROR_RETRY_SLEEP_SECONDS}",
            "  fi",
            f"  for src in {mirror_list}; do",
            '    [ -n "$src" ] || continue',
            "    try_wheel \"$src\" 45 '--retry 1 --retry-delay 2' && break",
            "  done",
            "done",
        ]
    lines += [
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
        f"CNDB_SOURCES='{server_sources}' \\",
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


def content_estimate(command: str) -> int:
    """TAT Content 按最坏情况（每 3 字节涨到 4 字节）估算 base64 后大小。"""
    return (len(command.encode("utf-8")) + 2) // 3 * 4


def main() -> int:
    payload_path = Path(env("PAYLOAD_PATH", "/tmp/cndb-deploy-config.tgz"))
    output_path = Path(env("OUTPUT_PATH", "/tmp/cndb-deploy-cmd.sh"))

    if not payload_path.is_file():
        raise SystemExit(f"[build] 载荷不存在：{payload_path}")

    payload_b64 = base64.b64encode(payload_path.read_bytes()).decode("ascii")
    chunks = [payload_b64[i : i + PAYLOAD_CHUNK_CHARS] for i in range(0, len(payload_b64), PAYLOAD_CHUNK_CHARS)]

    commands = [build_payload_command(chunk, i + 1, len(chunks)) for i, chunk in enumerate(chunks)]
    commands.append(build_command())

    stem = output_path.with_name(output_path.stem)  # /tmp/cndb-deploy-cmd.sh → /tmp/cndb-deploy-cmd
    output_files: list[Path] = []
    for i, command in enumerate(commands, start=1):
        # 分片按序号 -01、-02…；部署命令固定 -99，保证按文件名排序即下发顺序
        suffix = f"{i:02d}" if i <= len(chunks) else FINAL_COMMAND_SUFFIX
        target = Path(f"{stem}-{suffix}.sh")
        size = content_estimate(command)
        if size >= MAX_CONTENT_BYTES:
            raise SystemExit(
                f"[build] 第 {i} 条命令过大（Content 约 {size} 字节 ≥ {MAX_CONTENT_BYTES}）：{target}"
            )
        target.write_text(command, encoding="utf-8")
        output_files.append(target)

    print(
        f"[build] 载荷 {payload_path.stat().st_size} 字节 → base64 {len(payload_b64)} 字节 → "
        f"{len(chunks)} 条分片命令 + 1 条部署命令"
    )
    for target in output_files:
        print(f"[build] 已生成 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
