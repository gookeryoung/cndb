#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 流水线检查 —— 定时扫描（生产 cron 每分钟调用一次）
#
# 安装（宿主机 crontab -e）：
#   * * * * * /opt/cndb/deploy/pipeline.sh >> /opt/cndb/data/pipeline.log 2>&1
#
# 判定与单飞：cron 到期判定在 DB 层完成，同一定义已有活跃运行时静默跳过
# （ADR 0076 I6 / D8）；tick 内同步执行，进程退出前运行已落终态。
# 手动执行：./deploy/pipeline.sh            # 只跑到期定义
#           ./deploy/pipeline.sh --limit 5  # 限制单轮处理条数
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="docker-compose.prod.yml"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# 容器未运行 → 本轮无事可做（部署窗口里容器短暂缺席属正常）
if ! docker inspect cndb --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  log "cndb 容器未运行，跳过流水线 tick"
  exit 0
fi

if ! dc exec -T app cndb pipeline tick "$@"; then
  log "流水线 tick 存在失败运行（详见容器内 cndb pipeline tick --json）"
  exit 1
fi

log "流水线 tick 完成"
