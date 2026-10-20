#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 本地镜像构建（联网机器执行）—— 供「离线部署导出」与本地验证
#
# 与服务器端构建**同源**：复用 deploy/Dockerfile.base + Dockerfile.prod 与依赖指纹
# 机制，不定义第二套构建。产出镜像默认用本地名（无 registry 前缀），便于离线机
# `docker load` 后直接引用（配合 deploy.sh 的 OFFLINE=1）。
#
# 用法：
#   ./deploy/build-image.sh 0.3.0
#   IMAGE_REPO=ccr.ccs.tencentyun.com/pydev/cndb ./deploy/build-image.sh 0.3.0
#   BUILD_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim ./deploy/build-image.sh 0.3.0
#   BUILD_PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple ./deploy/build-image.sh 0.3.0
#
# 前置产物：dist/cndb-<version>-*.whl 与 dist/requirements.lock.txt
#   （缺 wheel 时先执行 `make build`；缺锁定清单时脚本会尝试用 uv 生成）
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

VERSION="${1:-${VERSION:-}}"
[[ -n "$VERSION" ]] || die "用法: $0 <version>   例: $0 0.3.0"
VERSION="${VERSION#v}"

# 镜像仓库前缀：默认空 → 本地名 cndb:<version>（离线 load 后可直接引用）
IMAGE_REPO="${IMAGE_REPO:-}"
if [[ -n "$IMAGE_REPO" ]]; then
  APP_IMAGE="${IMAGE_REPO}:${VERSION}"
  BASE_IMAGE_REPO="${IMAGE_REPO}-base"
else
  APP_IMAGE="cndb:${VERSION}"
  BASE_IMAGE_REPO="cndb-base"
fi

# ── 前置产物 ───────────────────────────────────────────────────
if [[ ! -f dist/requirements.lock.txt ]]; then
  command -v uv >/dev/null 2>&1 \
    || die "缺少 dist/requirements.lock.txt 且未找到 uv；请先执行 uv export 或 make build"
  log "生成 dist/requirements.lock.txt ..."
  uv export --frozen --no-hashes --no-dev --no-emit-project -o dist/requirements.lock.txt
fi
[[ -f deploy/Dockerfile.base && -f deploy/Dockerfile.prod ]] \
  || die "缺少 deploy/Dockerfile.base / deploy/Dockerfile.prod"

# 只保留目标版本 wheel：多版本共存会让 Dockerfile.prod 的 pip install ./*.whl 冲突
find dist -maxdepth 1 -name 'cndb-*.whl' ! -name "cndb-${VERSION}-*.whl" -delete 2>/dev/null || true
ls dist/cndb-"${VERSION}"-*.whl >/dev/null 2>&1 \
  || die "缺少 dist/cndb-${VERSION}-*.whl；请先执行 make build（构建前端 + wheel）"

# ── 依赖基础镜像（与 deploy.sh 同一指纹口径，跨机可复用同一 tag）──────
fingerprint="$(sha256sum dist/requirements.lock.txt deploy/Dockerfile.base | sha256sum | cut -c1-12)"
BASE_TAG="${BASE_IMAGE_REPO}:deps-${fingerprint}"

if docker image inspect "$BASE_TAG" >/dev/null 2>&1; then
  ok "复用依赖基础镜像: ${BASE_TAG}"
else
  log "构建依赖基础镜像（系统字体 + 锁定依赖，约 1-3 分钟）..."
  # Dockerfile.base 的 BASE_IMAGE 默认 python:3.12-slim，这里显式传，便于换源
  base_image="${BUILD_BASE_IMAGE:-python:3.12-slim}"
  pip_index="${BUILD_PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
  if ! docker build -f deploy/Dockerfile.base \
      --build-arg "BASE_IMAGE=${base_image}" \
      --build-arg "PIP_INDEX_URL=${pip_index}" \
      -t "$BASE_TAG" . ; then
    warn "依赖基础镜像构建失败（pip 源: ${pip_index}），改用官方 PyPI 重试..."
    docker build -f deploy/Dockerfile.base \
      --build-arg "BASE_IMAGE=${base_image}" \
      --build-arg "PIP_INDEX_URL=https://pypi.org/simple" \
      -t "$BASE_TAG" . || die "依赖基础镜像构建失败"
  fi
  ok "依赖基础镜像就绪: ${BASE_TAG}"
fi

# ── 应用镜像（构建上下文 = 仓库根，沿用仓库 .dockerignore）───────────
log "构建应用镜像 ${APP_IMAGE} ..."
docker build -f deploy/Dockerfile.prod \
  --build-arg "BASE_IMAGE=${BASE_TAG}" \
  -t "$APP_IMAGE" . || die "应用镜像构建失败"

# ── 冒烟验证（与 deploy.sh 同口径：cndb 可导入 + 前端静态非空）────────
log "冒烟验证镜像..."
docker run --rm --entrypoint python "$APP_IMAGE" -c "
import cndb
from cndb.core.config import STATIC_DIR
assert STATIC_DIR.is_dir(), f'前端静态资源缺失: {STATIC_DIR}'
assets = list((STATIC_DIR / 'assets').glob('*')) if (STATIC_DIR / 'assets').is_dir() else []
assert assets, '前端 assets 目录为空 —— wheel 可能未内嵌前端产物'
print('OK cndb', cndb.__version__, '| assets:', len(assets))
" || die "镜像冒烟验证失败"

ok "应用镜像就绪: ${APP_IMAGE}"
ok "依赖基础镜像: ${BASE_TAG}"
log "下一步：./deploy/export-image.sh ${VERSION}    # 导出离线交付包"
