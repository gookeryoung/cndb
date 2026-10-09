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
[[ -n "$TARGET_TAG" ]] || die "用法: $0 <version-tag>   例: $0 v0.3.0"

# ── 读取当前运行中的镜像（用于回滚）─────────────────────────────
CURRENT_IMAGE="$(docker inspect cndb --format '{{.Config.Image}}' 2>/dev/null || echo "")"
CURRENT_TAG=""
[[ -n "$CURRENT_IMAGE" ]] && CURRENT_TAG="${CURRENT_IMAGE##*:}"

log "当前运行版本: ${CURRENT_TAG:-<无, 首次部署>}"

# ── 组装目标镜像地址 ───────────────────────────────────────────
# 从 CNDB_IMAGE 剥掉版本段，拼接目标 tag —— 这样版本升级不需要改 .env
BASE_REPO="$(grep -E '^CNDB_IMAGE=' "$ENV_FILE" | cut -d= -f2- | cut -d: -f1)"
[[ -n "$BASE_REPO" ]] || die ".env 中 CNDB_IMAGE 缺失或格式错误"
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
  set_image_in_env "${BASE_REPO}:${CURRENT_TAG}"

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
if ! dc pull app; then
  rollback "镜像拉取失败"
  exit 1
fi

# 3. 写入新镜像地址并重建
set_image_in_env "$TARGET_IMAGE"
ok "更新 .env → ${TARGET_IMAGE}"

log "重建容器..."
if ! dc up -d --force-recreate app; then
  rollback "容器重建失败"
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
