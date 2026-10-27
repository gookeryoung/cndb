#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 离线交付包导出（联网机器执行，接 build-image.sh 之后）
#
# 把已构建/已存在的本地镜像 docker save 成压缩 tar，连同 compose、deploy 脚本与
# .env 模板、SHA256SUMS 校验清单一起打成离线交付包，供无外网服务器解包即部署：
#   build-image.sh（本地构建）→ export-image.sh（导出交付包）→ scp/U盘 → 离线机
#   解包 → sha256sum -c → OFFLINE=1 ./deploy/deploy.sh <version>
#
# 用法：
#   ./deploy/export-image.sh 0.3.0
#   IMAGE_REPO=ccr.ccs.tencentyun.com/pydev/cndb ./deploy/export-image.sh 0.3.0   # 与构建时保持一致
#   WITH_NGINX=0 ./deploy/export-image.sh 0.3.0        # 不导出 nginx 反代镜像
#   CNDB_SOURCES=global ./deploy/export-image.sh 0.3.0 # nginx 镜像走官方源
#   OUTPUT_DIR=/tmp/pkg ./deploy/export-image.sh 0.3.0
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

log()  { printf '\033[0;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '\033[0;32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[0;33m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '\033[0;31m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker"

# ── 构建源（唯一解析入口）──────────────────────────────────────────
# 只影响 nginx 镜像的拉取来源；应用镜像来自本地，不联网。
EXPLICIT_NGINX_IMAGE="${CNDB_NGINX_IMAGE:-}"
eval "$(bash "${SCRIPT_DIR}/docker-sources.sh" env)"

VERSION="${1:-${VERSION:-}}"
[[ -n "$VERSION" ]] || die "用法: $0 <version>   例: $0 0.3.0"
VERSION="${VERSION#v}"

IMAGE_REPO="${IMAGE_REPO:-}"
APP_IMAGE="${IMAGE_REPO:-cndb}:${VERSION}"
NGINX_IMAGE="${EXPLICIT_NGINX_IMAGE:-${NGINX_IMAGE}}"
WITH_NGINX="${WITH_NGINX:-1}"
OUTPUT_DIR="${OUTPUT_DIR:-dist/offline}"

BUNDLE_NAME="cndb-${VERSION}-offline"
OUT="${OUTPUT_DIR}/${BUNDLE_NAME}"

if [[ -n "$IMAGE_REPO" ]]; then
  repo_hint="（并设置 IMAGE_REPO=${IMAGE_REPO}）"
else
  repo_hint=""
fi
docker image inspect "$APP_IMAGE" >/dev/null 2>&1 \
  || die "本地无应用镜像 ${APP_IMAGE}；请先执行 ./deploy/build-image.sh ${VERSION}${repo_hint}"

log "重置输出目录 ${OUT} ..."
rm -rf "$OUT"
mkdir -p "$OUT"

# ── 应用镜像 ───────────────────────────────────────────────────
log "导出应用镜像 ${APP_IMAGE} ..."
docker save "$APP_IMAGE" | gzip > "${OUT}/cndb-${VERSION}-image.tar.gz"

# ── nginx 反代镜像（可选）───────────────────────────────────────
if [[ "$WITH_NGINX" == "1" ]]; then
  if ! docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1; then
    log "本地无 ${NGINX_IMAGE}，尝试拉取 ..."
    docker pull "$NGINX_IMAGE" || die "拉取 nginx 镜像失败：${NGINX_IMAGE}（可改 CNDB_NGINX_IMAGE 换源后重试）"
  fi
  log "导出 nginx 反代镜像 ${NGINX_IMAGE} ..."
  docker save "$NGINX_IMAGE" | gzip > "${OUT}/nginx-image.tar.gz"
else
  warn "WITH_NGINX=0：不导出 nginx 镜像，离线机将无法启用 --profile proxy 反代"
fi

# ── 编排与脚本 ─────────────────────────────────────────────────
log "打包 compose / deploy 脚本 / .env 模板 ..."
cp docker-compose.prod.yml "${OUT}/docker-compose.prod.yml"
cp -r deploy "${OUT}/deploy"
# 仓库内 deploy/*.sh 以 644 入库（在线链路由 TAT 运行时 chmod），交付包内补执行位，
# 使离线机可直接 `./deploy/deploy.sh`（含 OFFLINE-README.txt 所述用法）。
chmod +x "${OUT}/deploy"/*.sh

# 离线机快速上手说明（随包生成，非仓库文档）
cat > "${OUT}/OFFLINE-README.txt" <<EOF
cndb ${VERSION} 离线交付包
════════════════════════

组成：应用镜像 tar、nginx 镜像 tar、docker-compose.prod.yml、deploy/ 脚本、.env 模板、SHA256SUMS。

离线服务器上执行：
  1) 校验完整性：  sha256sum -c SHA256SUMS
  2) 初始化配置：  cp deploy/.env.prod.example .env  &&  vim .env
       · CNDB_IMAGE=额度指向本地镜像名（如 cndb:${VERSION}）
       · 需要反向代理时：CNDB_ENABLE_PROXY=1、CNDB_NGINX_IMAGE=${NGINX_IMAGE}、CNDB_BIND=127.0.0.1:8000
       · JWT_SECRET 必填：openssl rand -hex 32
  3) 离线部署：    OFFLINE=1 ./deploy/deploy.sh ${VERSION}
       （脚本会先 sha256sum -c 校验、再 docker load，随后预备份 / 重建 / 健康探测 / 失败回滚）

注意：导出镜像受构建机架构限制，跨架构需在目标架构机上重新构建导出。
EOF

# ── 校验清单 ───────────────────────────────────────────────────
log "生成 SHA256SUMS ..."
(
  cd "$OUT"
  # 覆盖关键载荷：镜像 tar + 编排文件（deploy 脚本自身无需自校验）
  sha256sum cndb-*.tar.gz nginx-image.tar.gz docker-compose.prod.yml 2>/dev/null > SHA256SUMS \
    || sha256sum cndb-*.tar.gz docker-compose.prod.yml > SHA256SUMS
)

# ── 外包装 tar.gz ─────────────────────────────────────────────
OUTER="${OUTPUT_DIR}/${BUNDLE_NAME}-bundle.tar.gz"
log "打包离线交付包 ${OUTER} ..."
tar -czf "$OUTER" -C "$OUTPUT_DIR" "$BUNDLE_NAME"

OUTER_SHA="$(sha256sum "$OUTER" | cut -d' ' -f1)"
OUTER_SIZE="$(du -h "$OUTER" | cut -f1)"

ok "离线交付包就绪"
printf '  产物:   %s\n' "$OUTER"
printf '  大小:   %s\n' "$OUTER_SIZE"
printf '  sha256: %s\n' "$OUTER_SHA"
printf '  解包:   tar -xzf %s\n' "$(basename "$OUTER")"
printf '  离线机: OFFLINE=1 ./%s/deploy/deploy.sh %s\n' "$BUNDLE_NAME" "$VERSION"
