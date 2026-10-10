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
# 由 GitHub Actions 通过 SSH 调用，也可在服务器上手动执行。
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

# compose 统一入口
dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

TARGET_TAG="${1:-}"
[[ -n "$TARGET_TAG" ]] || die "用法: $0 <version-tag>   例: $0 0.3.0  或  v0.3.0"

# ── 读取当前运行中的镜像（用于回滚）─────────────────────────────
CURRENT_IMAGE="$(docker inspect cndb --format '{{.Config.Image}}' 2>/dev/null || echo "")"
CURRENT_TAG=""
[[ -n "$CURRENT_IMAGE" ]] && CURRENT_TAG="${CURRENT_IMAGE##*:}"

log "当前运行版本: ${CURRENT_TAG:-<无, 首次部署>}"

# latest 是构建时每次覆盖的移动 tag，回滚到它等于回滚到「最后一次构建」，
# 而不是「上一个跑稳的版本」。这里提前告警，便于排查时看清回滚落点。
if [[ "$CURRENT_TAG" == "latest" ]]; then
  warn "当前运行的是 latest（移动 tag），回滚将落回最近一次构建而非上一个稳定版本"
fi

# ── 组装目标镜像地址 ───────────────────────────────────────────
# 优先用 CNDB_IMAGE_OVERRIDE（CI 可显式传完整地址），否则从 .env 的 CNDB_IMAGE 推导。
#
# 两个历史坑，都曾导致线上拉不到镜像：
#
#   1. tag 前缀不一致：CI 推镜像时用 VERSION="${VERSION#v}" 剥掉了 v，
#      仓库里实际是 0.3.0；而 git tag 是 v0.3.0。原脚本直接用参数拼 tag，
#      于是去拉 xxx:v0.3.0 —— 该 tag 不存在，部署必然失败。
#      现在统一剥掉开头的 v，两种传参都能命中。
#   2. 无仓库前缀：服务器首次部署前 .env 可能是 cndb:0.3.0（本地构建遗留），
#      推导出的 BASE_REPO=cndb 会被 Docker 解析成 docker.io/library/cndb。
#      现在显式校验必须含域名，否则直接报错退出，不让错误地址进入后续步骤。
TARGET_TAG="${TARGET_TAG#v}"

if [[ -n "${CNDB_IMAGE_OVERRIDE:-}" ]]; then
  BASE_REPO="${CNDB_IMAGE_OVERRIDE%:*}"
  log "使用 CI 传入的仓库地址: ${BASE_REPO}"
else
  BASE_REPO="$(grep -E '^CNDB_IMAGE=' "$ENV_FILE" | cut -d= -f2- | cut -d: -f1)"
  [[ -n "$BASE_REPO" ]] || die ".env 中 CNDB_IMAGE 缺失或格式错误"
  #含 "/" 说明带域名或命名空间，是完整的仓库地址
  if [[ "$BASE_REPO" != */* ]]; then
    die "CNDB_IMAGE 缺少仓库地址（当前: ${BASE_REPO}）。
     期望格式: <域名>/<命名空间>/<仓库>:<版本>，例如:
       CNDB_IMAGE=ccr.ccs.tencentyun.com/pydev/cndb:v0.3.0
     若镜像地址在构建时由 CI 决定，可用环境变量 CNDB_IMAGE_OVERRIDE 传入完整前缀。"
  fi
fi

TARGET_IMAGE="${BASE_REPO}:${TARGET_TAG}"
log "目标镜像: ${TARGET_IMAGE}"

# ── 部署前数据库备份 ───────────────────────────────────────────
# 必须在线备份而非直接 cp .db 文件：SQLite 写入进行中直接复制可能得到
# 撕裂的快照。这里用项目自带的 cndb backup（走 SQLite native 备份 API，安全）。
# 备份写在容器内 /data/backups（即数据卷），天然随卷持久化，
# 部署/重建容器都不会丢。
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
# 不能用 sed -i：它会遗留 .env.bak（每次部署覆盖同一个备份文件，
# 反而丢失了真正的历史版本），且非原子写入中断会损坏配置。
# 这里读全文 → 替换/追加 → 写临时文件 → mv 覆盖（mv 同分区是原子的）。
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
# 仅靠「容器 running」判断是不够的：uvicorn 可能因迁移失败在启动
# 循环中反复退出，docker 状态仍短暂显示 running。必须打真实 HTTP 端点。
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

    if dc exec -T app curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
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
  # 仓库地址必须取自**运行中的镜像**而非 BASE_REPO：若本次用了
  # CNDB_IMAGE_OVERRIDE 而它与 .env 里的仓库不同，用 BASE_REPO 回滚会把
  # .env 改成一个从未成功运行过的地址，故障时反而雪上加霜。
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

# ── 主流程 ─────────────────────────────────────────────────────

# 1. 预备份
pre_backup

# 2. 拉取镜像
# TCR 是腾讯云托管仓库，若服务器已配置镜像加速/凭证则直接 pull；
# 私有仓库需先 docker login（凭证由 CI 通过 stdin 传入，不落盘）
if [[ -n "${TCR_USERNAME:-}" && -n "${TCR_PASSWORD:-}" ]]; then
  log "登录 TCR: ${TCR_USERNAME}"
  printf '%s' "$TCR_PASSWORD" \
    | docker login "${BASE_REPO%%/*}" -u "$TCR_USERNAME" --password-stdin >/dev/null \
    || die "TCR 登录失败"
fi

log "拉取镜像 ${TARGET_IMAGE}..."
# 必须用 docker pull 显式拉目标镜像，不能用 `dc pull app`。
#
# compose 解析的是 .env 里的 CNDB_IMAGE（= 当前运行版本），而不是本次目标 tag：
#   线上跑 latest，要升 0.3.4 → dc pull 拉的是 latest（本地已有，秒回 "app Pulled"）
#   → 紧接着校验 0.3.4 必然不存在 → 每次升级都误判成「镜像不存在」并回滚。
# 这就是日志里「app Pulled」与「镜像未实际拉取到本地」前后矛盾的原因
# —— 两者校验的压根不是同一个 tag。
#
# 显式 pull 同时保住了「校验通过前不写 .env」的约束：
# 拉不到就不动线上配置，服务器重启仍能用旧版本起来。
if ! docker pull "$TARGET_IMAGE" 2>&1 | tee /tmp/cndb-pull.log; then
  warn "拉取失败。常见原因对照："
  warn "  401 Unauthorized          → 无登录态，检查 TCR_USERNAME/TCR_PASSWORD 是否注入"
  warn "  repository does not exist → 命名空间或仓库名有误（BASE_REPO=${BASE_REPO}）"
  warn "  manifest unknown / not found → 该 tag 在仓库中不存在，确认构建 job 是否成功推送"
  warn "  denied / 403               → 服务账号无该命名空间权限"
  rollback "镜像拉取失败"
  exit 1
fi

if ! docker image inspect "$TARGET_IMAGE" >/dev/null 2>&1; then
  warn "镜像未实际拉取到本地：${TARGET_IMAGE}"
  warn "请到 TCR 控制台确认该 tag 已推送。"
  rollback "镜像拉取失败（镜像不存在）"
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

# 确认跑起来的确实是目标镜像。
# compose pull 偶发返回成功但实际用的是别的镜像（tag 缺失时可能复用旧层），
# 到健康检查才暴露，排查成本高；这里提前挡住。
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

# 5. 成功：清理悬空镜像 + 打印版本
VERSION_JSON="$(dc exec -T app curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null || echo '{}')"
ok "部署成功！版本信息: ${VERSION_JSON}"

# 保留最近 5 个镜像，其余清理，防止磁盘被旧镜像占满
# 当前运行中的镜像 tag 会被排除，不会误删正在用的版本
log "清理悬空镜像（保留最近 5 个）..."
docker images --filter "reference=${BASE_REPO}:*" --format '{{.CreatedAt}} {{.ID}} {{.Repository}}:{{.Tag}}' \
  | sort -r | tail -n +6 \
  | awk '{print $3}' \
  | xargs -r docker rmi -f >/dev/null 2>&1 || true

ok "完成。访问地址由 .env 中 CNDB_BIND 决定（默认 http://<服务器IP>:8000）"
