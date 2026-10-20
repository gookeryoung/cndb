# Makefile - cndb 项目快捷命令（`make help` 查看全部目标）
# 约定：本文件只做命令编排，跨平台 / 多行逻辑放 scripts/，保证目标一眼可读。

.DEFAULT_GOAL := help

PACKAGE := cndb
COV_THRESHOLD := 95

# pytest-xdist worker 数：实测 n8 后收益收敛（SQLite 单文件写锁），低配机器用 make test PYTEST_JOBS=4 覆盖
PYTEST_JOBS ?= 8

# dev 目标绑定地址/端口，可在命令行覆盖：make dev DEV_HOST=127.0.0.1 DEV_PORT=8000
DEV_HOST ?= 0.0.0.0
DEV_PORT ?= 8772

# uvx 临时环境不受项目 [tool.uv.index] 约束，显式指定镜像源
UVX_INDEX := --default-index https://mirrors.cloud.tencent.com/pypi/simple

# 前端依赖 stamp：pnpm install 成功后由 make 刷新，lock / package.json 未变时零开销跳过
FRONTEND_DEPS := frontend/node_modules/.make-sync

.PHONY: help sync dev seed frontend-sync frontend-static frontend-coverage frontend-build \
        build clean test cov lint typecheck e2e e2e-dev gitkeep-check adr-check \
        check-fast check-docs flow check bump pub push pack-doctor pack pack-cache-clean \
        docker-build docker-export

# ── 开发 ──────────────────────────────────────────────────────────────

help: ## 显示帮助信息
	@uv run python scripts/help.py $(MAKEFILE_LIST)

sync: ## 安装后端开发依赖 + git pre-commit 钩子 (prek)
	uv sync --extra dev
	uv run prek install --force

dev: $(FRONTEND_DEPS) ## 开发模式：同时启动前后端（uvicorn + Vite，Ctrl+C 一起停）
	uv run cndb dev --host $(DEV_HOST) --port $(DEV_PORT)

seed: ## 注入演示数据（幂等：重建工作区/表/视图/文档并创建演示账号）
	uv run cndb seed

# ── 前端 ──────────────────────────────────────────────────────────────

$(FRONTEND_DEPS): frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml
	cd frontend && pnpm install --frozen-lockfile
	@uv run python -c "import pathlib; pathlib.Path('$(FRONTEND_DEPS)').touch()"

frontend-sync: $(FRONTEND_DEPS) ## 安装前端依赖（pnpm；lock / package.json 未变时跳过）

frontend-static: $(FRONTEND_DEPS) ## 前端静态检查（补丁 + tsc + eslint）
	cd frontend && pnpm check

frontend-coverage: $(FRONTEND_DEPS) ## 前端测试 + 覆盖率双门槛（text + json-summary）
	cd frontend && pnpm test:coverage

frontend-build: $(FRONTEND_DEPS) ## 构建前端（Vite，产物输出到 src/cndb/static/）
	cd frontend && pnpm build

# ── 质量门禁 ──────────────────────────────────────────────────────────

lint: ## 后端风格检查（ruff check + format，与 CI 同口径扫 src + tests）
	uv run ruff check src tests --cache-dir .ruff_cache
	uv run ruff format --check src tests

typecheck: ## 后端类型检查（pyrefly）
	uv run pyrefly check -j 0

test: ## 后端测试（不含覆盖率）
	uv run pytest -m "not slow" -n $(PYTEST_JOBS)

cov: ## 后端测试 + 覆盖率门禁（与 CI 同口径，只统计 cndb 包）
	uv run pytest -m "not slow" --cov=$(PACKAGE) --cov-report=term --cov-report=html --cov-fail-under=$(COV_THRESHOLD) -n $(PYTEST_JOBS)
	@echo 'Coverage report: htmlcov/index.html'

gitkeep-check: ## 校验关键 .gitkeep 文件（缺失会导致 CI/打包失败）
	uv run python scripts/check_gitkeep.py

adr-check: ## 校验 ADR 落地状态、交接节与 CHANGELOG 关联
	uv run python scripts/check_adr_landing.py

e2e: frontend-build ## 前端 E2E（Playwright；webServer 自动起隔离后端，首次先 npx playwright install chromium）
	cd frontend && pnpm e2e

e2e-dev: $(FRONTEND_DEPS) ## dev 模式 E2E（vite dev 源码直出，兜住只在 dev 现形的回归）
	cd frontend && pnpm e2e:dev

# L1 配置改动：轻量静态门禁（无测试）
check-fast: gitkeep-check adr-check lint typecheck frontend-static ## 轻量静态门禁（无测试，实现期快速反馈）
# L0 文档改动：只跑文档级校验
check-docs: gitkeep-check adr-check ## 文档级门禁（只改 *.md 时用）
# L2 代码改动：轻量静态门禁 + 全量后端测试
flow: check-fast test ## AI 开发流：轻量静态门禁 + 全量后端测试

check: $(FRONTEND_DEPS) ## 全套门禁（并行 7 项：gitkeep / adr / lint / 类型 / 前端静态 + 覆盖率 / cov）
	@$(MAKE) -j4 cov frontend-coverage gitkeep-check adr-check lint typecheck frontend-static

# ── 构建 / 打包 / 发布 ────────────────────────────────────────────────

build: frontend-build ## 构建分发包（前端 → wheel + sdist）
	uv build

# ── Docker / 离线部署 ─────────────────────────────────────────────────

# 版本号（默认取 pyproject.toml；可用 make docker-build VERSION=x.y.z 覆盖）
VERSION ?= $(shell grep -m1 -E '^version' pyproject.toml | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

docker-build db: build ## 本地构建镜像（联网机；VERSION=x.y.z 覆盖版本）
	bash deploy/build-image.sh $(VERSION)

docker-export de: ## 导出离线交付包（先 make docker-build；VERSION=x.y.z 覆盖版本）
	bash deploy/export-image.sh $(VERSION)

clean: ## 清理构建产物与缓存
	@uv run python scripts/clean.py

BUMP_PART := $(filter-out bump,$(MAKECMDGOALS))

bump: ## 版本号 bump（默认 patch，用法: make bump [minor|major]）
	@uvx $(UVX_INDEX) bump-my-version bump $(if $(BUMP_PART),$(firstword $(BUMP_PART)),patch) --tag

patch minor major:
	@:

pub: ## 上传 dist/ 到 PyPI（先 make build）
	uvx $(UVX_INDEX) twine upload dist/*.whl dist/*.tar.gz

push: ## 推送当前分支到全部 remote（含 tags）
	@uv run python scripts/push.py

pack-doctor: ## fspack 环境诊断（检查打包工具链可用性）
	uv run fspack doctor

pack: frontend-build ## 本地当前平台打包（fspack build + package + 冒烟测试）
	uv run fspack b .
	uv run fspack p . --format all --no-build
	@uv run python -c "import subprocess, sys; sys.exit(subprocess.run(['dist/cndb.exe' if sys.platform == 'win32' else 'dist/cndb', 'info']).returncode)"

pack-cache-clean: ## 清理 fspack 缓存（wheels + nuitka）
	uv run fspack cache clean
