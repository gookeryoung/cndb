#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 腾讯云生产部署脚本（服务器端执行）
#
# 设计为幂等 + 可回滚：任何一步失败都会自动恢复到上一个可用版本，
# 避免「CI 推了新镜像 → 服务器拉完起不来 → 线上长时间不可用」。
#
# 用法：
#   ./deploy/deploy.sh v0.3.0              # 部署指定版本
#   ./deploy/deploy.sh                     # 不传版本则沿用 .env 中的 CNDB_IMAGE
#   FORCE_ROLLBACK_ON_FAIL=0 ./deploy/deploy.sh v0.3.0   # 失败不回滚（仅调试用）
#
# 镜像获取方式（按环境变量自动二选一）：
#   1. SERVER_BUILD=1（CI 常规路径）：在服务器本地构建镜像。
#      CI 仅同步 dist/*.whl + requirements.lock.txt + Dockerfile 到 /opt/cndb，
#      本脚本按「依赖基础镜像（字体 + 锁定依赖）→ 应用层（wheel）」两段构建：
#      依赖未变时复用 cndb-base:deps-<hash>，只重建 20-40s 的 wheel 薄层；
#      uv.lock 变化时才多花一次 1-3 分钟重建基础镜像。
#      可选环境变量（国内服务器拉 Docker Hub 超时的换源逃生通道）：
#        BUILD_BASE_IMAGE       覆盖基础镜像，如 docker.m.daocloud.io/library/python:3.12-slim
#        BUILD_PIP_INDEX_URL    覆盖 pip 源，不设时基础镜像构建默认腾讯云 PyPI 内网镜像
#   2. 无 SERVER_BUILD（手动部署/回滚历史版本）：走 TCR docker pull，
#      需 TCR_USERNAME/TCR_PASSWORD（CI 注入或手工 export）。
#      镜像仍以 TCR 地址命名（与历史版本同名），保证回滚可命中。
#
# 由 CI 经 TAT 下发触发，也可在服务器上手动执行。
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

# ── 定位项目根目录（本脚本在 deploy/ 下，根目录为其父的父）────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="${ENV_FILE:-.env}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-3}"

log()  { printf '\033[0;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '\033[0;32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[0;33m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '\033[0;31m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# ── 前置检查 ───────────────────────────────────────────────────
command -v docker >/dev/null || die "未找到 docker，请先在服务器安装 Docker"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件"
[[ -f "$ENV_FILE" ]] || die "缺少 $ENV_FILE，请先 cp deploy/.env.prod.example .env 并填写"

# ── 反向代理开关（可选）────────────────────────────────────────
# .env 里 CNDB_ENABLE_PROXY=1 时启用 nginx 容器（统一入口）。
# 不启用时行为与从前完全一致（单容器，直接暴露 CNDB_BIND）。
ENABLE_PROXY="$(grep -E '^CNDB_ENABLE_PROXY=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | xargs || true)"
ENABLE_PROXY="${ENABLE_PROXY:-0}"
BIND_VALUE="$(grep -E '^CNDB_BIND=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | xargs || true)"

# compose 统一入口（启用代理时带上 profile，否则 nginx 容器不会被创建/启动）
dc() {
  if [[ "$ENABLE_PROXY" == "1" ]]; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile proxy "$@"
  else
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

TARGET_TAG="${1:-}"
[[ -n "$TARGET_TAG" ]] || die "用法: $0 <version-tag>   例: $0 0.3.0  或  v0.3.0"

# ── 读取当前运行中的镜像（用于回滚）─────────────────────────────
CURRENT_IMAGE="$(docker inspect cndb --format '{{.Config.Image}}' 2>/dev/null || echo "")"
CURRENT_TAG=""
[[ -n "$CURRENT_IMAGE" ]] && CURRENT_TAG="${CURRENT_IMAGE##*:}"

if [[ "$ENABLE_PROXY" == "1" ]]; then
  log "反向代理：已启用（CNDB_ENABLE_PROXY=1）"
  # 直连应用端口会绕过代理，也会让客户端 IP 可伪造（登录限流被绕过）→ 强制提醒
  case "${BIND_VALUE:-}" in
    "0.0.0.0:8000"|"")
      warn "CNDB_BIND=${BIND_VALUE:-<未设置>} 会让应用端口对公网直连（绕过代理、可伪造 IP）"
      warn "建议在 .env 中改为 CNDB_BIND=127.0.0.1:8000 后重新部署"
      ;;
    *) log "应用端口绑定: ${BIND_VALUE}（仅本机 / 指定地址，符合反代形态）" ;;
  esac
  [[ -f deploy/nginx/templates/default.conf.template ]] \
    || die "缺少 deploy/nginx 配置（CI 会同步；手动部署请一并上传 deploy/nginx 目录）"
else
  log "反向代理：未启用（如需要，把 .env 的 CNDB_ENABLE_PROXY 改为 1）"
fi

log "当前运行版本: ${CURRENT_TAG:-<无, 首次部署>}"

# latest 是构建时每次覆盖的移动 tag，回滚到它等于回滚到「最后一次构建」，
# 而不是「上一个跑稳的版本」。这里提前告警，便于排查时看清回滚落点。
if [[ "$CURRENT_TAG" == "latest" ]]; then
  warn "当前运行的是 latest（移动 tag），回滚将落回最近一次构建而非上一个稳定版本"
fi

# ── 组装目标镜像地址 ───────────────────────────────────────────
# 优先用 IMAGE_REPO_OVERRIDE（CI 显式传完整仓库前缀），否则从 .env 的 CNDB_IMAGE 推导。
#
# 两处必须的规范化（否则会导致线上拉不到镜像）：
#   1. 统一剥掉 tag 开头的 v：CI 打镜像时用 VERSION="${VERSION#v}" 剥了 v，
#      仓库里是 0.3.0 而 git tag 是 v0.3.0，不剥则拼出的 tag 不存在。
#   2. 校验仓库地址必须含域名（含 "/"）：否则 cndb:0.3.0 会被 Docker 解析成
#      docker.io/library/cndb，这里直接报错退出，不让错误地址进入后续步骤。
TARGET_TAG="${TARGET_TAG#v}"

if [[ -n "${IMAGE_REPO_OVERRIDE:-}" ]]; then
  BASE_REPO="${IMAGE_REPO_OVERRIDE%:*}"
  log "使用 CI 传入的仓库地址: ${BASE_REPO}"
else
  BASE_REPO="$(grep -E '^CNDB_IMAGE=' "$ENV_FILE" | cut -d= -f2- | cut -d: -f1)"
  [[ -n "$BASE_REPO" ]] || die ".env 中 CNDB_IMAGE 缺失或格式错误"
  # 含 "/" 说明带域名或命名空间，是完整的仓库地址
  if [[ "$BASE_REPO" != */* ]]; then
    die "CNDB_IMAGE 缺少仓库地址（当前: ${BASE_REPO}）。
     期望格式: <域名>/<命名空间>/<仓库>:<版本>，例如:
       CNDB_IMAGE=ccr.ccs.tencentyun.com/pydev/cndb:v0.3.0
     若镜像地址由 CI 决定，可用环境变量 IMAGE_REPO_OVERRIDE 传入完整前缀。"
  fi
fi

TARGET_IMAGE="${BASE_REPO}:${TARGET_TAG}"
log "目标镜像: ${TARGET_IMAGE}"

# 依赖基础镜像仓库：与应用镜像同前缀，tag 用依赖指纹（见 build_image 的 ensure_base_image）
BASE_IMAGE_REPO="${BASE_IMAGE_REPO:-${BASE_REPO}-base}"

# ── 部署前数据库备份 ───────────────────────────────────────────
# 用项目自带的 cndb backup（走 SQLite native 备份 API），而非直接 cp .db 文件
# —— 后者在写入进行中可能得到撕裂的快照。备份写在容器内 /data/backups（即数据卷），
# 随卷持久化，部署/重建容器都不会丢。
pre_backup() {
  local stamp ts_file="/data/data/cndb.db"
  stamp="$(date +%Y%m%d-%H%M%S)"
  local out="/data/backups/pre-deploy-${TARGET_TAG}-${stamp}.tar.gz"

  # 容器未运行或数据库尚不存在 → 首次部署无需备份
  if ! dc exec -T app test -f "$ts_file" >/dev/null 2>&1; then
    warn "未检测到数据库文件（首次部署？）跳过备份"
    return 0
  fi

  log "执行部署前数据库备份..."
  if dc exec -T app cndb backup -o "$out" >/dev/null 2>&1; then
    ok "备份完成: ${out}"

    # 裁剪预备份：只留最近 3 份。部署比定时备份频繁得多，
    # 不清理的话 pre-deploy 归档会无限堆积吃满数据卷
    dc exec -T app sh -c "
      ls -1t /data/backups/pre-deploy-*.tar.gz 2>/dev/null \
        | tail -n +4 | xargs -r rm -f
    " >/dev/null 2>&1 || warn "裁剪历史预备份失败（不影响本次部署）"
  else
    warn "备份失败（继续部署）—— 建议先手工执行 cndb backup 确认"
  fi
}

# 原子更新 .env 中的镜像地址。
# 不用 sed -i：它会遗留 .env.bak（每次覆盖同一备份文件反而丢掉历史版本），
# 且非原子写入中断会损坏配置。这里读全文 → 替换/追加 → 写临时文件 → mv 覆盖。
set_image_in_env() {
  local image="$1"
  local tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  if grep -qE '^CNDB_IMAGE=' "$ENV_FILE"; then
    # 分隔符用 | 而非 /：镜像地址含 / ，用 / 会破坏 sed 表达式
    sed -E "s|^CNDB_IMAGE=.*|CNDB_IMAGE=${image}|" "$ENV_FILE" > "$tmp"
  else
    cp "$ENV_FILE" "$tmp"
    printf 'CNDB_IMAGE=%s\n' "$image" >> "$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# ── 健康探测 ───────────────────────────────────────────────────
# 仅靠「容器 running」不够：uvicorn 可能因迁移失败在启动循环中反复退出，
# docker 状态仍短暂显示 running，必须打真实 HTTP 端点。
# 探测命令用 python 标准库：生产镜像不装 curl，dc exec 内只能用 python。
health_body() {
  dc exec -T app python -c "import sys, urllib.request as u; sys.stdout.write(u.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read().decode())"
}

wait_healthy() {
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
  local cid

  while [[ $(date +%s) -lt $deadline ]]; do
    cid="$(docker inspect cndb --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"

    # none：说明旧版镜像没有 healthcheck 定义（首次从 wheel 迁过来会遇到），
    # 退化为直接打 HTTP 端点判断，避免永久等待一个不存在的状态
    if [[ "$cid" == "unhealthy" ]]; then
      return 1
    fi

    if health_body >/dev/null 2>&1; then
      return 0
    fi

    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

# ── 回滚 ───────────────────────────────────────────────────────
rollback() {
  local reason="$1"
  warn "部署失败: ${reason}"

  if [[ "${FORCE_ROLLBACK_ON_FAIL:-1}" == "0" ]]; then
    warn "FORCE_ROLLBACK_ON_FAIL=0，跳过回滚（当前服务处于不可用状态）"
    return 0
  fi

  if [[ -z "$CURRENT_TAG" ]]; then
    die "无历史版本可回滚（首次部署失败）。请查看日志: docker logs cndb"
  fi

  warn "回滚到 ${CURRENT_TAG}..."

  # 关键：回滚的是**镜像版本**，不是容器配置。compose 文件若未变，
  # 仅需把 .env 的镜像地址改回去再 up -d，卷不受影响。
  #
  # 仓库地址取自**运行中的镜像**而非 BASE_REPO：若本次用了覆盖的仓库地址，
  # 用 BASE_REPO 回滚会把 .env 改成从未成功运行过的地址，故障时雪上加霜。
  ROLLBACK_REPO="${CURRENT_IMAGE%:*}"
  if [[ -z "$ROLLBACK_REPO" || "$ROLLBACK_REPO" == "$CURRENT_IMAGE" ]]; then
    # CURRENT_IMAGE 没有 tag 段（理论上不该发生），退回 BASE_REPO
    ROLLBACK_REPO="$BASE_REPO"
  fi
  log "回滚目标仓库: ${ROLLBACK_REPO}"

  set_image_in_env "${ROLLBACK_REPO}:${CURRENT_TAG}"

  dc up -d --force-recreate app >/dev/null 2>&1 || true

  if wait_healthy; then
    ok "回滚成功，服务已恢复到 ${CURRENT_TAG}"
  else
    warn "回滚后仍未健康，请人工介入：docker logs cndb"
  fi
  return 1
}

# ── 依赖基础镜像（系统字体 + 锁定依赖）─────────────────────────
# 把「apt 装字体 + pip 装锁定依赖」这段慢且基本不变的工作固化成一个镜像，
# 按 requirements.lock.txt 与 Dockerfile.base 的内容指纹打 tag：
#   · 发布时依赖未变 → 直接复用，只重建 wheel 薄层（20-40s）
#   · uv.lock 或 Dockerfile.base 变化 → 多一次 1-3 分钟的基础镜像构建
# 这样即使 Docker 层缓存被清理，也不会再出现 5-15 分钟的冷启动。
BASE_TAG=""

deps_fingerprint() {
  [[ -f dist/requirements.lock.txt && -f deploy/Dockerfile.base ]] || return 1
  sha256sum dist/requirements.lock.txt deploy/Dockerfile.base | sha256sum | cut -c1-12
}

ensure_base_image() {
  local fingerprint pip_index
  fingerprint="$(deps_fingerprint)" \
    || die "无法计算依赖指纹：缺少 dist/requirements.lock.txt 或 deploy/Dockerfile.base"
  BASE_TAG="${BASE_IMAGE_REPO}:deps-${fingerprint}"

  if docker image inspect "$BASE_TAG" >/dev/null 2>&1; then
    ok "复用依赖基础镜像: ${BASE_TAG}"
    return 0
  fi

  # 换了机器 / 清过本地镜像时先尝试从镜像仓库拉；不存在会快速失败，不阻塞
  log "本地无依赖基础镜像，尝试拉取: ${BASE_TAG}"
  if docker pull "$BASE_TAG" >/dev/null 2>&1; then
    ok "拉取到依赖基础镜像: ${BASE_TAG}"
    return 0
  fi

  log "构建依赖基础镜像（仅依赖变化时发生一次，约 1-3 分钟）..."
  # 服务器在腾讯云内网，默认走腾讯云 PyPI 镜像；失败再用官方源兜底（可能较慢）
  pip_index="${BUILD_PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
  if ! docker build -f deploy/Dockerfile.base \
      ${BUILD_BASE_IMAGE:+--build-arg "BASE_IMAGE=${BUILD_BASE_IMAGE}"} \
      --build-arg "PIP_INDEX_URL=${pip_index}" \
      -t "$BASE_TAG" . ; then
    warn "依赖基础镜像构建失败（pip 源: ${pip_index}），改用官方 PyPI 重试..."
    docker build -f deploy/Dockerfile.base \
      ${BUILD_BASE_IMAGE:+--build-arg "BASE_IMAGE=${BUILD_BASE_IMAGE}"} \
      --build-arg "PIP_INDEX_URL=https://pypi.org/simple" \
      -t "$BASE_TAG" . || die "依赖基础镜像构建失败"
  fi
  ok "依赖基础镜像就绪: ${BASE_TAG}"
}

# ── 服务器本地构建应用镜像（SERVER_BUILD=1）─────────────────────
# CI 经 TAT 下发触发：在依赖基础镜像上只装 wheel，再冒烟验证。
# 依赖 CI 已同步：dist/cndb-*.whl、dist/requirements.lock.txt、deploy/Dockerfile*。
build_image() {
  [[ -f "deploy/Dockerfile.prod" && -f "deploy/Dockerfile.base" ]] \
    || die "缺少 deploy/Dockerfile.prod 或 Dockerfile.base（CI 的同步步骤应已放到 /opt/cndb/deploy）"

  # 只保留目标版本的 wheel：同步的 wheel 文件名带版本号，历史版本残留会让
  # pip install ./*.whl 同时装两个版本互相冲突
  find dist -maxdepth 1 -name 'cndb-*.whl' ! -name "cndb-${TARGET_TAG}-*.whl" -delete 2>/dev/null || true
  ls "dist/cndb-${TARGET_TAG}"-*.whl >/dev/null 2>&1 \
    || die "缺少 dist/cndb-${TARGET_TAG}-*.whl。CI 会同步构建产物到 /opt/cndb/dist；手动执行请先按 Dockerfile.prod 头部说明准备 dist/"

  # 构建上下文最小化：/opt/cndb 下有 backups（可能数 GB）、.env 等，
  # 不排除会把备份数据整个发给 docker daemon。只放行 dist 与 Dockerfile。
  # 注意 dockerignore 语义：父目录被 * 排除后，须先放行父目录再收窄到具体文件。
  printf '*\n!dist\n!deploy\ndeploy/*\n!deploy/Dockerfile.prod\n!deploy/Dockerfile.base\n' > .dockerignore

  ensure_base_image

  log "构建应用镜像（仅 wheel 层）${TARGET_IMAGE} ..."
  if ! docker build -f deploy/Dockerfile.prod \
      --build-arg "BASE_IMAGE=${BASE_TAG}" \
      -t "$TARGET_IMAGE" \
      -t "${BASE_REPO}:latest" \
      . ; then
    rollback "服务器构建镜像失败"
    exit 1
  fi

  # 冒烟检查：确认 cndb 可导入、前端静态已打进 wheel。前端产物缺失这类问题
  # 必须在替换线上容器前拦住，否则要到线上打开页面才发现白屏。
  log "冒烟验证镜像..."
  if ! docker run --rm --entrypoint python "$TARGET_IMAGE" -c "
import cndb
from cndb.core.config import STATIC_DIR
assert STATIC_DIR.is_dir(), f'前端静态资源缺失: {STATIC_DIR}'
assets = list((STATIC_DIR / 'assets').glob('*')) if (STATIC_DIR / 'assets').is_dir() else []
assert assets, '前端 assets 目录为空 —— wheel 可能未内嵌前端产物'
print('OK cndb', cndb.__version__, '| assets:', len(assets))
"; then
    rollback "镜像冒烟验证失败"
    exit 1
  fi
  ok "镜像构建完成: ${TARGET_IMAGE}"
}

# ── 主流程 ─────────────────────────────────────────────────────

# 1. 预备份
pre_backup

# 2. 获取镜像：
#    SERVER_BUILD=1 → 服务器本地构建（CI 常规路径，镜像不过网）；
#    否则           → TCR pull（手动部署/回滚历史版本，需先 docker login）。
if [[ "${SERVER_BUILD:-0}" == "1" ]]; then
  # 显式拦截：收到 SERVER_BUILD=1 却找不到 build_image，说明服务器上的脚本是
  # 旧版本（CI 同步未生效），避免被误导成镜像仓库权限/命名问题。
  if ! declare -f build_image >/dev/null 2>&1; then
    die "收到 SERVER_BUILD=1 但当前 deploy.sh 不支持服务器端构建（缺少 build_image）。
     说明服务器上的脚本是旧版本，CI 的文件同步未生效。
     常见原因：同步路径保留了目录层级，脚本被放到 deploy/deploy/deploy.sh，
     而实际执行路径 /opt/cndb/deploy/deploy.sh 仍是旧文件。
     处置：修正同步目标目录（应为 /opt/cndb）后重新部署。"
  fi
  build_image
else
  # TCR 回退路径：手动部署/回滚历史版本。TCR 是腾讯云托管仓库，
  # 私有仓库需先 docker login（凭证由 CI 通过环境变量注入，不落盘）
  if [[ -n "${TCR_USERNAME:-}" && -n "${TCR_PASSWORD:-}" ]]; then
    log "登录 TCR: ${TCR_USERNAME}"
    printf '%s' "$TCR_PASSWORD" \
      | docker login "${BASE_REPO%%/*}" -u "$TCR_USERNAME" --password-stdin >/dev/null \
      || die "TCR 登录失败"
  fi

  log "拉取镜像 ${TARGET_IMAGE}..."
  # 必须用 docker pull 显式拉目标 tag，不能用 `dc pull app`：compose 解析的是
  # .env 里的 CNDB_IMAGE（当前运行版本），而非本次目标 tag，会导致校验的
  # 根本不是同一个 tag（拉到了 latest 却校验 0.3.4 → 误判镜像不存在并回滚）。
  # 显式 pull 同时保住「校验通过前不写 .env」的约束：拉不到就不动线上配置。
  if ! docker pull "$TARGET_IMAGE" 2>&1 | tee /tmp/cndb-pull.log; then
    warn "拉取失败。常见原因对照："
    warn "  401 Unauthorized          → 无登录态，检查 TCR_USERNAME/TCR_PASSWORD 是否注入"
    warn "  repository does not exist → 命名空间或仓库名有误（BASE_REPO=${BASE_REPO}）"
    warn "  manifest unknown / not found → 该 tag 在仓库中不存在，确认构建 job 是否成功推送"
    warn "  denied / 403               → 服务账号无该命名空间权限"
    rollback "镜像拉取失败"
    exit 1
  fi
fi

if ! docker image inspect "$TARGET_IMAGE" >/dev/null 2>&1; then
  warn "镜像未实际就位于本地：${TARGET_IMAGE}"
  warn "SERVER_BUILD 路径请确认构建步骤成功（docker build 日志）；TCR 路径请到 TCR 控制台确认该 tag 已推送。"
  rollback "镜像获取失败（镜像不存在）"
  exit 1
fi
ok "镜像已就位: ${TARGET_IMAGE}"

# 3. 写入新镜像地址并重建
set_image_in_env "$TARGET_IMAGE"
ok "更新 .env → ${TARGET_IMAGE}"

log "重建容器..."
if ! dc up -d --force-recreate app; then
  rollback "容器重建失败"
  exit 1
fi

# 启用代理时把 nginx 一并拉起/更新（配置改动也在此生效）
if [[ "$ENABLE_PROXY" == "1" ]]; then
  log "启动/更新 nginx 反代..."
  if ! dc up -d nginx; then
    rollback "nginx 反代启动失败"
    exit 1
  fi
  # 必须 reload：上一步 app 容器已被 --force-recreate 重建，容器 IP 可能变化。
  # nginx 的 upstream 里写的是容器名，静态解析只发生在启动/reload 时，
  # 不 reload 就会继续拿旧 IP → 部署完接口 502。reload 是热加载，可安全重复执行。
  if ! docker exec cndb-nginx nginx -s reload >/dev/null 2>&1; then
    warn "nginx reload 失败，尝试完整重建容器..."
    dc up -d --force-recreate nginx || true
    sleep 2
  fi
fi

# 确认跑起来的确实是目标镜像：compose pull 偶发返回成功但实际用的是别的镜像，
# 到健康检查才暴露、排查成本高，这里提前挡住。
RUNNING_IMAGE="$(docker inspect cndb --format '{{.Config.Image}}' 2>/dev/null || echo "")"
if [[ "$RUNNING_IMAGE" != "$TARGET_IMAGE" ]]; then
  warn "运行镜像与目标不一致：期望 ${TARGET_IMAGE}，实际 ${RUNNING_IMAGE:-<读取失败>}"
  rollback "镜像地址不匹配"
  exit 1
fi

# 4. 健康探测（窗口内滚动替换，流量层面无明显中断）
log "等待服务健康（最长 ${HEALTH_TIMEOUT}s）..."
if ! wait_healthy; then
  log "---- 失败容器日志（末尾 50 行）----"
  docker logs --tail 50 cndb 2>&1 || true
  rollback "健康检查超时"
  exit 1
fi

# 4.5 反向代理冒烟验证（启用代理时）
# 经代理探测健康端点，确认 nginx 到应用的上游链路可用。
if [[ "$ENABLE_PROXY" == "1" ]]; then
  log "验证反向代理（经容器 nginx）..."
  HTTP_BIND="${CNDB_HTTP_BIND:-80}"
  # 经代理探测健康端点。**非 2xx 视为失败**（502 曾被当成成功，隐蔽且致命）。
  # 重试是为了给 nginx reload 后的 worker 切换留窗口。
  PROXY_STATUS=""
  for attempt in 1 2 3 4 5 6; do
    PROXY_STATUS="$(docker exec cndb-nginx wget -q -O /dev/null -S "http://127.0.0.1/api/health" 2>&1 | grep -o 'HTTP/[0-9.]* [0-9]*' | head -1 || true)"
    case "$PROXY_STATUS" in
      *" 200"|*" 204"|*" 301"|*" 302") break ;;
    esac
    [[ "$attempt" -lt 6 ]] && sleep 2
  done
  if [[ -z "$PROXY_STATUS" ]]; then
    warn "代理内 /api/health 探测无响应，请检查 nginx 日志：dc logs nginx"
    die "反向代理不可用（应用本身已部署成功，仅代理层故障）"
  fi
  case "$PROXY_STATUS" in
    *" 200"|*" 204"|*" 301"|*" 302")
      log "代理内 /api/health → ${PROXY_STATUS}" ;;
    *)
      warn "代理内 /api/health → ${PROXY_STATUS}（非 2xx：应用健康但反代不通）"
      warn "重点排查两项："
      warn "  ① .env 的 CNDB_APP_UPSTREAM 是否用了服务名 app —— 同机其他 compose 项目"
      warn "     服务名也叫 app 时会与它 round-robin 撞车，必须改容器名 cndb:8000"
      warn "  ② nginx 是否 reload（本脚本已自动 reload；手工起容器需自行 reload）"
      warn "应用容器健康、数据无碍，**不要急着重跑部署**，先按上面两项修 nginx"
      die "反向代理不可用" ;;
  esac
fi

# 5. 成功：清理悬空镜像 + 打印版本
VERSION_JSON="$(health_body 2>/dev/null || echo '{}')"
ok "部署成功！版本信息: ${VERSION_JSON}"

# 保留最近 5 个镜像，其余清理，防止磁盘被旧镜像占满
# 当前运行中的镜像 tag 会被排除，不会误删正在用的版本
log "清理悬空镜像（保留最近 5 个）..."
docker images --filter "reference=${BASE_REPO}:*" --format '{{.CreatedAt}} {{.ID}} {{.Repository}}:{{.Tag}}' \
  | sort -r | tail -n +6 \
  | awk '{print $3}' \
  | xargs -r docker rmi -f >/dev/null 2>&1 || true

# 依赖基础镜像单独清理（仓库名是 <应用仓库>-base，不会被上面的规则命中）。
# 保留最近 3 个指纹；被应用镜像引用的层不会真正删除，磁盘占用仍可控。
log "清理旧依赖基础镜像（保留最近 3 个）..."
docker images --filter "reference=${BASE_IMAGE_REPO}:*" --format '{{.CreatedAt}} {{.ID}} {{.Repository}}:{{.Tag}}' \
  | sort -r | tail -n +4 \
  | awk '{print $3}' \
  | xargs -r docker rmi -f >/dev/null 2>&1 || true

if [[ "$ENABLE_PROXY" == "1" ]]; then
  ok "完成。访问地址：http://<服务器IP>:${CNDB_HTTP_BIND:-80}（经容器 nginx 反代；配好证书后可用 HTTPS）"
else
  ok "完成。访问地址由 .env 中 CNDB_BIND 决定（默认 http://<服务器IP>:8000）"
fi
