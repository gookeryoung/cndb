#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 生产服务器初始化（仅首次执行一次）
#
# 在生产服务器上以 root 运行：
#   cd /opt/cndb    # 任意位置均可，脚本会自己建目录
#   bash bootstrap-server.sh
#
# 做的事：
#   1. 建目录（/opt/cndb/deploy、/opt/cndb/backups）
#   2. 落 .env（镜像地址指向 ccr.ccs.tencentyun.com/pydev/pydev）
#      —— 已在 .env 存在时**绝不覆盖**，只补缺失项
#   3. 生成 JWT_SECRET（缺失时自动生成，不打印明文到日志）
#   4. 前置检查：docker / compose / 端口占用
#   5. 装 cron 定时备份（可选，--with-cron）
#
# 幂等：可重复运行，只补缺失项，不动已有配置与数据。
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/cndb}"
REGISTRY="ccr.ccs.tencentyun.com"
GROUP="pydev"
REPO="pydev"
BIND="${BIND:-0.0.0.0:8000}"
VOLUME="${VOLUME:-cndb-data}"
ENV_FILE="$APP_DIR/.env"

WITH_CRON=0
[[ "${1:-}" == "--with-cron" ]] && WITH_CRON=1

log()  { printf '\033[0;36m[%s]\033[0s %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '\033[0;32m[%s]\033[0s %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[0;33m[%s]\033[0s %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '\033[0;31m[%s]\033[0s %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# ── 0. 前置检查 ────────────────────────────────────────────────
# 在写任何文件之前全部检查完：避免检查失败却已改了一半配置
command -v docker >/dev/null || die "未找到 docker，请先安装：https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose v2 插件（docker-compose 旧版不被支持）"
command -v openssl >/dev/null || die "未找到 openssl，用于生成 JWT_SECRET"
log "docker $(docker --version | head -1)"

# ── 1. 目录 ───────────────────────────────────────────────────
mkdir -p "$APP_DIR/deploy" "$APP_DIR/backups"
chmod 700 "$APP_DIR"          # .env 在此目录，收紧权限
log "目录就绪：$APP_DIR"

# ── 2. .env：只补不覆盖 ────────────────────────────────────────
# 覆盖 .env 是最危险的操作 —— 会丢掉已配置的 JWT_SECRET 与域名，
# 所以逻辑是「缺哪个补哪个」，不是「用模板重新生成」。
set_env() {
  local key="$1" val="$2" file="$3"
  # 用 | 而非 / 作分隔符：值里含 /（如镜像地址、URL）会破坏 sed
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    return 0
  fi
  printf '%s=%s\n' "$key" "$val" >> "$file"
  log "补写 ${key}"
}

NEW_ENV=0
[[ -f "$ENV_FILE" ]] || { touch "$ENV_FILE"; chmod 600 "$ENV_FILE"; NEW_ENV=1; warn "未找到 $ENV_FILE，新建"; }

set_env CNDB_IMAGE  "${REGISTRY}/${GROUP}/${REPO}:v0.3.0" "$ENV_FILE"
set_env CNDB_BIND   "$BIND"                    "$ENV_FILE"
set_env CNDB_VOLUME "$VOLUME"                  "$ENV_FILE"
set_env DEBUG       "false"                    "$ENV_FILE"
set_env AUTH_ENABLED "true"                    "$ENV_FILE"

# JWT_SECRET：占位符也当作「未配置」重新生成
if grep -qE '^JWT_SECRET=CHANGE_ME' "$ENV_FILE" 2>/dev/null || ! grep -qE '^JWT_SECRET=' "$ENV_FILE"; then
  set_env JWT_SECRET "$(openssl rand -hex 32)" "$ENV_FILE"
  ok "JWT_SECRET 已生成（不回显明文）"
fi

# CORS_ORIGINS 必须是 JSON 数组字符串 —— Settings 里声明为 list[str]，
# pydantic-settings 对复杂类型一律按 JSON 解析，写成逗号分隔会抛
# SettingsError，表现为容器启动即崩且日志难定位
if ! grep -qE '^CORS_ORIGINS=' "$ENV_FILE" 2>/dev/null; then
  set_env CORS_ORIGINS '["http://localhost:8000"]' "$ENV_FILE"
fi

# 数据库地址：只设 CNDB_DATA_DIR 就够，此处显式写出便于后续切 PostgreSQL。
# 注意变量名是 DATABASE_URL 或 CNDATABASE_URL（代码做了别名兼容），
# 历史上曾统一写成 CNDATABASE_URL 而代码只读 DATABASE_URL，
# 导致容器静默连回 SQLite —— 现在两者都支持。
if ! grep -qE '^(CN)?DATABASE_URL=' "$ENV_FILE" 2>/dev/null; then
  set_env CNDATABASE_URL "sqlite:////data/data/cndb.db" "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"
[[ $NEW_ENV -eq 1 ]] && ok "已创建 $ENV_FILE"

# ── 3. 端口占用检查 ───────────────────────────────────────────
# ss 在精简镜像里可能没装，缺失时降级为静默跳过（只提示，不阻断）。
# 端口占用不阻断部署：首次部署前常是遗留旧容器在跑，
# 强制中断反而让用户不知如何处理。
PORT="${BIND##*:}"
PORT_CHECKED=0
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -qE "[:.]${PORT}[[:space:]]"; then
    PORT_CHECKED=1
    warn "端口 ${PORT} 已被占用。若是遗留的旧容器，部署前先停掉："
    warn "  docker ps -a --filter name=cndb && docker rm -f cndb"
    warn "若被其他程序占用，改 .env 里的 CNDB_BIND 再部署。"
  fi
elif command -v netstat >/dev/null 2>&1; then
  if netstat -ltn 2>/dev/null | grep -qE "[:.]${PORT}[[:space:]]"; then
    PORT_CHECKED=1
    warn "端口 ${PORT} 已被占用（netstat 检测）。"
  fi
fi
[[ $PORT_CHECKED -eq 1 ]] || ok "端口 ${PORT} 空闲"

# ── 4. 磁盘空间检查 ───────────────────────────────────────────
# 镜像 + 数据卷在同一盘，不够会在部署中途失败。
# df -BG --output 是 GNU 扩展，BusyBox/BSD 不支持，故留 fallback。
AVAIL_GB=""
if AVAIL_GB="$(df -BG --output=avail "$APP_DIR" 2>/dev/null | tail -1 | tr -dc '0-9')" && [[ -n "$AVAIL_GB" ]]; then
  :
else
  AVAIL_GB="$(df -g "$APP_DIR" 2>/dev/null | awk 'NR==2{print $4}')"
fi
if [[ -n "${AVAIL_GB:-}" && "$AVAIL_GB" -lt 10 ]]; then
  warn "磁盘剩余 ${AVAIL_GB}GB < 10GB。镜像约 500MB、数据卷随使用增长，建议清理后再部署。"
else
  ok "磁盘剩余 ${AVAIL_GB:-未知}GB"
fi

# ── 5. 可选：定时备份 ─────────────────────────────────────────
if [[ $WITH_CRON -eq 1 ]]; then
  if [[ -f "$APP_DIR/deploy/backup.sh" ]]; then
    #每天 03:17 备份（避开整点，减少与其他任务撞车）
    CRON_CMD="17 3 * * * cd $APP_DIR && ./deploy/backup.sh >> $APP_DIR/backups/cron.log 2>&1"
    if crontab -l 2>/dev/null | grep -qF "deploy/backup.sh"; then
      warn "定时备份已存在，跳过"
    else
      ( crontab -l 2>/dev/null; echo "$CRON_CMD" ) | crontab -
      ok "已安装定时备份（每天 03:17）"
    fi
  else
    warn "未找到 deploy/backup.sh，跳过定时备份配置"
  fi
fi

# ── 汇总 ─────────────────────────────────────────────────────
echo
ok "═══════════════════════════════════════════════"
ok " 初始化完成"
ok "═══════════════════════════════════════════════"
echo "  下一步："
echo "    1) 确认 .env 内容（尤其 CNDB_IMAGE 与 CORS_ORIGINS）："
echo "       cat $ENV_FILE"
echo "    2) 由 CI 触发首次部署（推送 v*.*.* tag），或手工执行："
echo "       cd $APP_DIR && ./deploy/deploy.sh v0.3.0"
echo
echo "  当前 .env 关键项："
grep -E '^(CNDB_IMAGE|CNDB_BIND|CNDB_VOLUME)=' "$ENV_FILE" | sed 's/^/    /'
echo
warn "JWT_SECRET 若要重置：sed -i 's|^JWT_SECRET=.*|JWT_SECRET=\$(openssl rand -hex 32)|' $ENV_FILE"
echo "  （重置会使所有已登录会话失效）"