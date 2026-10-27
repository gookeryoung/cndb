#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# cndb Docker 构建源解析（GitHub 官方源 / 国内镜像源）
#
# 所有联网构建点（基础镜像、apt、pip、uv、npm/corepack、nginx 镜像）的源
# 只在这里定义一次，Dockerfile / compose / shell 脚本不再各自写默认值。
#
# 用法：
#   bash deploy/docker-sources.sh detect        # 打印最终 profile（cn / global）
#   bash deploy/docker-sources.sh env           # 输出可 eval 的 export 行
#   bash deploy/docker-sources.sh exec <cmd..>  # 解析后带环境执行命令
#   bash deploy/docker-sources.sh print         # 输出 KEY=VALUE（不 exec）
#
# profile 选择（优先级从高到低）：
#   1. CNDB_SOURCES=cn|global
#   2. CNDB_SOURCES=auto（默认）：GITHUB_ACTIONS=true → global，其余 → cn
#      本地 / CodeUp / 腾讯服务器都按 cn；GitHub Actions 按 global。
#   3. 非法值直接失败，不静默回退。
#
# 单项覆盖（仍兼容旧变量名，优先级高于 profile）：
#   BUILD_BASE_IMAGE / CNDB_PYTHON_IMAGE       基础镜像
#   CNDB_APT_MIRROR                            Debian 源主机（显式空串 = 官方源）
#   BUILD_PIP_INDEX_URL / CNDB_PIP_INDEX        pip 索引
#   CNDB_UV_INDEX                              uv 默认索引
#   CNDB_NODE_IMAGE                            前端基础镜像
#   CNDB_NPM_REGISTRY                          npm / corepack registry
#   CNDB_NGINX_IMAGE                           nginx 镜像
# ═══════════════════════════════════════════════════════════════════
set -Eeuo pipefail

die() { printf '[docker-sources] %s\n' "$*" >&2; exit 1; }

CNDB_SOURCES="${CNDB_SOURCES:-auto}"

resolve_profile() {
  local requested="${CNDB_SOURCES:-auto}"
  case "$requested" in
    cn|global) printf '%s' "$requested" ;;
    auto)
      if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
        printf 'global'
      else
        printf 'cn'
      fi
      ;;
    *) die "CNDB_SOURCES=${requested} 非法；允许 auto / cn / global" ;;
  esac
}

PROFILE="$(resolve_profile)"

if [[ "$PROFILE" == "cn" ]]; then
  BASE_IMAGE="docker.m.daocloud.io/library/python:3.12-slim"
  NODE_IMAGE="docker.m.daocloud.io/library/node:22-alpine"
  NGINX_IMAGE="docker.m.daocloud.io/library/nginx:1.27-alpine"
  APT_MIRROR_HOST="mirrors.cloud.tencent.com"
  PIP_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple"
  UV_DEFAULT_INDEX="https://mirrors.cloud.tencent.com/pypi/simple"
  NPM_REGISTRY="https://registry.npmmirror.com"
else
  BASE_IMAGE="python:3.12-slim"
  NODE_IMAGE="node:22-alpine"
  NGINX_IMAGE="nginx:1.27-alpine"
  APT_MIRROR_HOST=""
  PIP_INDEX_URL="https://pypi.org/simple"
  UV_DEFAULT_INDEX="https://pypi.org/simple"
  NPM_REGISTRY="https://registry.npmjs.org/"
fi

# ── 单项覆盖（显式值优先；空串对 apt 有「明确使用官方源」语义）──────
if [[ -n "${BUILD_BASE_IMAGE:-}" ]]; then
  BASE_IMAGE="$BUILD_BASE_IMAGE"
elif [[ -n "${CNDB_PYTHON_IMAGE:-}" ]]; then
  BASE_IMAGE="$CNDB_PYTHON_IMAGE"
fi
if [[ -n "${CNDB_APT_MIRROR+x}" ]]; then
  APT_MIRROR_HOST="$CNDB_APT_MIRROR"
fi
if [[ -n "${BUILD_PIP_INDEX_URL:-}" ]]; then
  PIP_INDEX_URL="$BUILD_PIP_INDEX_URL"
elif [[ -n "${CNDB_PIP_INDEX:-}" ]]; then
  PIP_INDEX_URL="$CNDB_PIP_INDEX"
fi
if [[ -n "${CNDB_UV_INDEX:-}" ]]; then
  UV_DEFAULT_INDEX="$CNDB_UV_INDEX"
fi
if [[ -n "${CNDB_NODE_IMAGE:-}" ]]; then
  NODE_IMAGE="$CNDB_NODE_IMAGE"
fi
if [[ -n "${CNDB_NPM_REGISTRY:-}" ]]; then
  NPM_REGISTRY="$CNDB_NPM_REGISTRY"
fi
if [[ -n "${CNDB_NGINX_IMAGE:-}" ]]; then
  NGINX_IMAGE="$CNDB_NGINX_IMAGE"
fi

# 兼容 compose 旧变量名（docker-compose.dev.yml 仍读 CNDB_*）
CNDB_SOURCES_RESOLVED="$PROFILE"
CNDB_PYTHON_IMAGE="$BASE_IMAGE"
CNDB_APT_MIRROR="$APT_MIRROR_HOST"
CNDB_PIP_INDEX="$PIP_INDEX_URL"
CNDB_UV_INDEX="$UV_DEFAULT_INDEX"
CNDB_NODE_IMAGE="$NODE_IMAGE"
CNDB_NPM_REGISTRY="$NPM_REGISTRY"
CNDB_NGINX_IMAGE="$NGINX_IMAGE"

readonly EXPORTED_VARS=(
  CNDB_SOURCES CNDB_SOURCES_RESOLVED
  BASE_IMAGE CNDB_PYTHON_IMAGE
  APT_MIRROR_HOST CNDB_APT_MIRROR
  PIP_INDEX_URL CNDB_PIP_INDEX
  UV_DEFAULT_INDEX CNDB_UV_INDEX
  NODE_IMAGE CNDB_NODE_IMAGE
  NPM_REGISTRY CNDB_NPM_REGISTRY
  NGINX_IMAGE CNDB_NGINX_IMAGE
)

# shell 安全引用：值里可能出现 / : 等，统一单引号并转义内部单引号
quote() {
  local value="$1"
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

print_env() {
  local name
  for name in "${EXPORTED_VARS[@]}"; do
    printf 'export %s=%s\n' "$name" "$(quote "${!name-}")"
  done
}

print_plain() {
  local name
  for name in "${EXPORTED_VARS[@]}"; do
    printf '%s=%s\n' "$name" "${!name-}"
  done
}

command="${1:-detect}"
case "$command" in
  detect) printf '%s\n' "$PROFILE" ;;
  env) print_env ;;
  print) print_plain ;;
  exec)
    shift
    [[ $# -gt 0 ]] || die "用法: $0 exec <命令...>"
    eval "$(print_env)"
    exec "$@"
    ;;
  *) die "未知子命令 ${command}；允许 detect / env / print / exec" ;;
esac
