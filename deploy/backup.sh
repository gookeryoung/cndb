#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 定时备份 → 本地留存 + 可选上传 COS
#
# 由 crontab 每日凌晨 3:17 调用（错开整点，避开同机其他定时任务的 IO 峰值）：
#   17 3 * * * /opt/cndb/deploy/backup.sh >> /opt/cndb/backups/backup.log 2>&1
#
# 手动执行：./deploy/backup.sh
#
# 备份内容：SQLite 数据库 + 用户上传附件（项目自带 cndb backup，
# SQLite 走 native 备份 API，不存在直接 cp 文件导致的快照撕裂问题）。
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
KEEP_DAYS="${KEEP_DAYS:-14}"          # 本地保留天数
COMPOSE_FILE="docker-compose.prod.yml"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# 备份产物全部写在容器内 /data/backups（即数据卷），随卷持久化，
# 部署与重建容器都不会丢。不在宿主机另存一份 —— 卷才是唯一数据源。

# 容器未运行 → 无从备份，直接退出（非零退出码让 cron 邮件告警）
if ! docker inspect cndb --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  die "cndb 容器未运行，跳过备份"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
# 容器内路径（卷内）：/data/backups 已在卷上，备份产物天然持久化
IN_CONTAINER="/data/backups/cndb-${STAMP}.tar.gz"

log "开始备份 → ${IN_CONTAINER}"
if ! dc exec -T app cndb backup -o "$IN_CONTAINER"; then
  die "cndb backup 执行失败"
fi

# 校验产物非空（0 字节的归档 = 静默失败，必须显式拦截）
SIZE="$(dc exec -T app sh -c "stat -c %s '${IN_CONTAINER}' 2>/dev/null || echo 0" | tr -d '\r')"
if [[ "${SIZE:-0}" -lt 1024 ]]; then
  die "备份产物异常（${SIZE} 字节），疑似空归档"
fi
log "备份完成，大小: $((SIZE / 1024)) KB"

# ── 上传 COS（可选）────────────────────────────────────────────
COS_ENABLE="$(grep -E '^COS_ENABLE=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || echo false)"
COS_BUCKET="$(grep -E '^COS_BUCKET=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)"
COS_REGION="$(grep -E '^COS_REGION=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)"
COS_PREFIX="$(grep -E '^COS_PREFIX=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)"

if [[ "$COS_ENABLE" == "true" && -n "$COS_BUCKET" ]]; then
  command -v coscmd >/dev/null || die "COS_ENABLE=true 但未安装 coscmd（pip install coscmd）"

  # 先拉到本地临时目录再上传：容器内无 coscmd 凭证，也不该把云凭证打进镜像
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  docker cp "cndb:${IN_CONTAINER}" "${TMP}/" >/dev/null

  LOCAL_FILE="$(find "$TMP" -name '*.tar.gz' | head -1)"
  [[ -n "$LOCAL_FILE" ]] || die "从容器拷贝备份文件失败"

  PREFIX="${COS_PREFIX:-cndb/}"
  log "上传 COS: cos://${COS_BUCKET}/${PREFIX}"
  if coscmd upload "${COS_BUCKET}/${PREFIX}" "$LOCAL_FILE" --region "$COS_REGION"; then
    log "COS 上传成功"
  else
    # 上传失败不删本地文件 —— 本地副本仍是有效备份，只是没上云
    die "COS 上传失败（本地副本保留于容器 ${IN_CONTAINER}）"
  fi
else
  log "COS_ENABLE 未开启，跳过上传（本地备份仍有效）"
fi

# ── 本地保留策略 ───────────────────────────────────────────────
# 只清理过期归档，绝不删最新一份（删光 = 没有回滚余地）。
# 同时匹配 cndb-*（定时备份）与 pre-deploy-*（部署前备份），
# 否则部署产生的预备份会绕过此策略无限堆积。
log "清理 ${KEEP_DAYS} 天前的归档"
dc exec -T app sh -c "
  find /data/backups \( -name 'cndb-*.tar.gz' -o -name 'pre-deploy-*.tar.gz' \) \
    -type f -mtime +${KEEP_DAYS} -print -delete
" 2>/dev/null || warn "清理归档时出错（不影响备份本身）"

REMAINING="$(dc exec -T app sh -c "ls -1 /data/backups/*.tar.gz 2>/dev/null | wc -l" | tr -d '\r')"
log "当前保留归档数: ${REMAINING:-0}"
log "完成"
