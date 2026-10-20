#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 数据源同步 —— 到期扫描（生产 cron 每分钟调用一次）
#
# 安装（宿主机 crontab -e）：
#   * * * * * /opt/cndb/deploy/sync.sh >> /opt/cndb/data/sync.log 2>&1
#
# 判定与单飞：任务自身的「到没到点」判定与租约都在 DB 层完成，
# 多副本 / 多个 cron 同时跑也只会有一个执行者（ADR 0006 D3）。
# 手动执行：./deploy/sync.sh            # 只跑到期任务
#           ./deploy/sync.sh --limit 5  # 限制单轮处理条数
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="docker-compose.prod.yml"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# 容器未运行 → 本轮无事可做（不打告警：部署窗口里容器短暂缺席属正常）
if ! docker inspect cndb --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  log "cndb 容器未运行，跳过同步 tick"
  exit 0
fi

if ! dc exec -T app cndb sync tick "$@"; then
  log "同步 tick 存在失败任务（详见容器内 cndb sync list）"
  exit 1
fi

log "同步 tick 完成"
