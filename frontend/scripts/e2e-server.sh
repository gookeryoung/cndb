#!/usr/bin/env bash
# E2E 后端一键启动（供 Playwright `webServer` 使用）。
# 流程：seed 注入演示数据（幂等 drop_all 重建）→ 启动后端:8000。
# 前置：前端已构建到 src/cndb/static（make frontend-build / npm run build）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PORT="${E2E_PORT:-8000}"

echo "[e2e-server] seed 演示数据..."
uv run cndb seed

echo "[e2e-server] 启动后端 http://127.0.0.1:${PORT} ..."
exec uv run cndb serve --host 127.0.0.1 --port "${PORT}"