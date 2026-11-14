#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb 定时备份 → 宿主机留档（数据卷外）+ 完整性校验 + 可选上传 COS + 失败告警
#
# 由 root crontab 每日凌晨 3:17 调用（错开整点，避开同机其他定时任务的 IO 峰值）：
#   17 3 * * * cd /opt/cndb && flock -xn /tmp/cndb-backup.lock \
#     ./deploy/backup.sh >> /opt/cndb/backups/cron.log 2>&1
#
# 手动执行：./deploy/backup.sh
#
# 备份内容：SQLite 数据库 + 用户上传附件（项目自带 cndb backup，
# SQLite 走 native 备份 API，不存在直接 cp 文件导致的快照撕裂问题）。
#
# 为什么归档要落到宿主机而不是留在数据卷里：
#   旧实现写在 /data/backups（= cndb-data 卷内部）。卷损坏、误删卷、容器误操作时
#   备份会随数据一起消失 —— 备份与源同盘等于没有备份。现在统一落到
#   ${ROOT_DIR}/backups（可用 HOST_BACKUP_DIR 覆盖），与数据卷物理隔离。
#   恢复时需先把归档 docker cp 回容器（见 docs/DEPLOY_TENCENT.md）。
#
# 保留策略（GFS）：日备 KEEP_DAYS 天，周备 KEEP_WEEKS 份，月备 KEEP_MONTHS 份。
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="docker-compose.prod.yml"
CONTAINER_NAME="${CONTAINER_NAME:-cndb}"

KEEP_DAYS="${KEEP_DAYS:-14}"          # 日备保留天数
KEEP_WEEKS="${KEEP_WEEKS:-8}"         # 周备保留份数
KEEP_MONTHS="${KEEP_MONTHS:-6}"       # 月备保留份数
HOST_BACKUP_DIR="${HOST_BACKUP_DIR:-${ROOT_DIR}/backups}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date '+%F %T')" "$*" >&2; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# 从 .env 取单个键（不 source：.env 里有 JSON 值，source 会展开其中的 $）
env_get() {
  local key="$1" def="${2:-}" v=""
  v="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  printf '%s' "${v:-$def}"
}

# 企业微信群机器人 / 任意 webhook。未配置则跳过（不影响备份本身）
notify() {
  local text="$1" url payload
  url="$(env_get BACKUP_WEBHOOK_URL)"
  if [[ -z "$url" ]]; then
    log "未配置 BACKUP_WEBHOOK_URL，跳过通知"
    return 0
  fi
  command -v curl >/dev/null 2>&1 || { warn "curl 未安装，无法发送通知"; return 0; }
  payload="$(python3 -c 'import json,sys; print(json.dumps({"msgtype":"text","text":{"content":sys.argv[1]}}, ensure_ascii=False))' "$text" 2>/dev/null || true)"
  [[ -n "$payload" ]] || { warn "构造通知内容失败"; return 0; }
  curl -sS -m 10 -H 'Content-Type: application/json' --data-binary "$payload" "$url" >/dev/null 2>&1 \
    || warn "通知发送失败（不影响备份本身）"
}

die() {
  printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2
  notify "❌ cndb 备份失败 @$(hostname)：$*" || true
  exit 1
}

# 兜住未显式 die 的意外失败（拷贝中断、磁盘满等），同样要告警
on_err() {
  local code=$? line="${BASH_LINENO[0]:-?}"
  warn "备份流程异常终止（exit=${code}, line=${line}）"
  notify "❌ cndb 备份失败 @$(hostname)：意外退出 exit=${code} line=${line}，详见 ${HOST_BACKUP_DIR}/cron.log" || true
}
trap on_err ERR

# 校验归档真的可恢复：tar 可读 + manifest 可解析 + DB integrity_check 通过。
# 只查字节数不够 —— 磁盘满/中断产生的半截归档同样有几十 MB。
verify_archive() {
  local file="$1"
  python3 - "$file" <<'PY'
import json, os, sqlite3, sys, tarfile, tempfile

path = sys.argv[1]
size = os.path.getsize(path)
if size < 1024:
    sys.exit(f"归档过小（{size} 字节），疑似空备份")

try:
    tf = tarfile.open(path, "r:gz")
except Exception as exc:  # 任何打开失败都算归档损坏
    sys.exit(f"归档无法打开：{exc}")

with tf:
    names = tf.getnames()
    manifest = [n for n in names if n.endswith("manifest.json")]
    if not manifest:
        sys.exit("归档内缺少 manifest.json")
    try:
        meta = json.loads(tf.extractfile(manifest[0]).read().decode("utf-8", "replace"))
    except Exception as exc:
        sys.exit(f"manifest.json 解析失败：{exc}")

    dbs = [n for n in names if n.endswith(".db")]
    if not dbs:
        sys.exit("归档内缺少数据库文件")

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, os.path.basename(dbs[0]))
        with open(out, "wb") as fh:
            fh.write(tf.extractfile(dbs[0]).read())
        con = sqlite3.connect(out)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
        finally:
            con.close()
        result = (row or ["unknown"])[0]
        if result != "ok":
            sys.exit(f"SQLite integrity_check 未通过：{result}")

    db_meta = meta.get("database") or {}
    up_meta = meta.get("uploads") or {}
    tables = db_meta.get("tables") or []
    rows = sum((db_meta.get("row_counts") or {}).values())
    declared = int(up_meta.get("file_count") or 0)
    packed = sum(1 for n in names if n.startswith("uploads/") or "/uploads/" in n)
    # 归档内附件少于 manifest 声明数 → 打包被截断，必须拦下
    if declared and packed < declared:
        sys.exit(f"附件数量不符：manifest={declared}，归档内={packed}，疑似打包截断")
    print(
        f"v{meta.get('version', '?')} app={meta.get('app_version', '?')} "
        f"表数={len(tables)} 行数={rows} 附件={packed} "
        f"schema={db_meta.get('schema_version') or '-'}"
    )
PY
}

command -v docker >/dev/null 2>&1 || die "docker 不可用"
command -v python3 >/dev/null 2>&1 || die "python3 不可用（归档校验依赖）"
[[ -f "$ENV_FILE" ]] || die "缺少 ${ENV_FILE}"

# 容器未运行 → 无从备份，直接退出（非零退出码 + 告警）
docker inspect "$CONTAINER_NAME" --format '{{.State.Running}}' 2>/dev/null | grep -q true \
  || die "容器 ${CONTAINER_NAME} 未运行，跳过备份"

mkdir -p "$HOST_BACKUP_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
IN_CONTAINER="/data/backups/cndb-${STAMP}.tar.gz"
HOST_FILE="${HOST_BACKUP_DIR}/cndb-${STAMP}.tar.gz"
TMP_FILE="${HOST_BACKUP_DIR}/.cndb-${STAMP}.tar.gz.partial"

log "开始备份 → 容器内 ${IN_CONTAINER}"
dc exec -T app cndb backup -o "$IN_CONTAINER" || die "cndb backup 执行失败"

# 先落 .partial 再 mv：避免上传/其他进程读到写了一半的归档
log "拷贝到宿主机 ${HOST_FILE}"
docker cp "${CONTAINER_NAME}:${IN_CONTAINER}" "$TMP_FILE" >/dev/null || die "从容器拷贝备份失败"
mv -f "$TMP_FILE" "$HOST_FILE"

log "校验归档（tar 可读性 + manifest + SQLite integrity_check）"
VERIFY_OUT="$(verify_archive "$HOST_FILE")" || { rm -f "$HOST_FILE"; die "备份校验失败，已删除损坏副本"; }
log "校验通过：${VERIFY_OUT}"

SIZE="$(stat -c %s "$HOST_FILE")"
SIZE_MB="$((SIZE / 1024 / 1024))"
log "备份完成，大小: ${SIZE_MB} MB"

# ── 周备 / 月备（GFS 分层，纯复制，不重跑备份）──────────────────
if [[ "$(date +%u)" == "7" ]]; then
  if cp -f "$HOST_FILE" "${HOST_BACKUP_DIR}/weekly-${STAMP}.tar.gz"; then
    ls -1t "${HOST_BACKUP_DIR}"/weekly-*.tar.gz 2>/dev/null \
      | tail -n "+$((KEEP_WEEKS + 1))" | xargs -r rm -f || true
    log "生成周备（保留最近 ${KEEP_WEEKS} 份）"
  else
    warn "生成周备失败（日备不受影响）"
  fi
fi

if [[ "$(date +%d)" == "01" ]]; then
  if cp -f "$HOST_FILE" "${HOST_BACKUP_DIR}/monthly-${STAMP}.tar.gz"; then
    ls -1t "${HOST_BACKUP_DIR}"/monthly-*.tar.gz 2>/dev/null \
      | tail -n "+$((KEEP_MONTHS + 1))" | xargs -r rm -f || true
    log "生成月备（保留最近 ${KEEP_MONTHS} 份）"
  else
    warn "生成月备失败（日备不受影响）"
  fi
fi

# ── 上传 COS（可选，异地副本）──────────────────────────────────
COS_ENABLE="$(env_get COS_ENABLE false)"
if [[ "$COS_ENABLE" == "true" ]]; then
  COS_BUCKET="$(env_get COS_BUCKET)"
  COS_PREFIX="$(env_get COS_PREFIX 'cndb/')"
  [[ -n "$COS_BUCKET" ]] || die "COS_ENABLE=true 但缺少 COS_BUCKET"
  command -v coscmd >/dev/null 2>&1 || die "COS_ENABLE=true 但未安装 coscmd（pip install coscmd）"

  # coscmd 的桶来自 ~/.cos.conf，路径参数只写对象前缀（不能带 Bucket 名）
  COS_PATH="/${COS_PREFIX#/}"
  [[ "$COS_PATH" == */ ]] || COS_PATH="${COS_PATH}/"

  log "上传 COS: cos://${COS_BUCKET}${COS_PATH}$(basename "$HOST_FILE")"
  if coscmd upload "$HOST_FILE" "$COS_PATH" >/dev/null; then
    log "COS 上传成功"
  else
    # 上传失败不删本地副本 —— 本地那份仍是有效备份，但异地副本缺失必须告警
    die "COS 上传失败（本地副本保留于 ${HOST_FILE}）"
  fi
else
  log "COS_ENABLE 未开启，跳过上传（本地备份仍有效，但缺异地副本）"
fi

# ── 清理 ───────────────────────────────────────────────────────
# 本次归档已拷到宿主机，留在卷里只白占空间
log "清理容器内本次归档"
dc exec -T app rm -f "$IN_CONTAINER" >/dev/null 2>&1 || warn "删除容器内归档失败（不影响备份）"

log "清理宿主机 ${KEEP_DAYS} 天前的日备"
find "$HOST_BACKUP_DIR" -maxdepth 1 -name 'cndb-*.tar.gz' -type f -mtime "+${KEEP_DAYS}" -delete 2>/dev/null \
  || warn "清理过期日备出错（不影响备份本身）"
# 中断遗留的半截文件
find "$HOST_BACKUP_DIR" -maxdepth 1 -name '.cndb-*.partial' -type f -mtime +1 -delete 2>/dev/null || true

# 只统计本脚本产出的归档（不把 pre-seed / 手工归档混进来，避免"保留份数"虚高）
COUNT="$(find "$HOST_BACKUP_DIR" -maxdepth 1 -type f \
  \( -name 'cndb-*.tar.gz' -o -name 'weekly-*.tar.gz' -o -name 'monthly-*.tar.gz' \) 2>/dev/null \
  | wc -l | tr -d ' ')"
TOTAL="$(du -sh "$HOST_BACKUP_DIR" 2>/dev/null | cut -f1 || echo '?')"
log "当前保留归档: ${COUNT} 份，占用 ${TOTAL}"

notify "✅ cndb 备份成功 @$(hostname)
归档: $(basename "$HOST_FILE")
大小: ${SIZE_MB} MB
校验: 通过
保留: ${COUNT} 份 / ${TOTAL}"
log "完成"
