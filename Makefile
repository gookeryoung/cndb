# Makefile - cndb 项目快捷命令
# 运行 `make help` 查看所有可用命令

PACKAGE := cndb
COV_THRESHOLD := 95
FRONTEND_DIR := frontend
PYTEST_JOBS := 8  # pytest-xdist 并行进程数；Windows 默认 8 避免句柄耗尽

.PHONY: help sync build b clean c test cov lint typecheck typecheck-ci check doc tox bump patch minor major push \
        fe-install fe-lint fe-typecheck fe-build fe-check fe-clean

help: ## 显示帮助信息
	@uv run python -c "import re,sys;ms=[(m.group(1),m.group(2).strip()) for f in sys.argv[1:] for l in open(f,encoding='utf-8') if (m:=re.match(r'^([a-zA-Z][\w -]*):.*?##\s*(.*)',l))];[print(f'  {n:<14} {d}') for n,d in ms]" $(MAKEFILE_LIST)

sync: ## 安装开发依赖
	uv sync --extra dev

build b: ## 构建分发包 (wheel + sdist)
	uv build

clean c: ## 清理构建产物与缓存
	rm -rf build/ dist/ wheels/ *.egg-info htmlcov/ .coverage .coverage.* coverage.xml docs/_build/ .tox/
	rm -rf .ruff_cache/ .pyrefly_cache/ .mypy_cache/
	find src tests -type d -name __pycache__ -exec rm -rf {} +
	find src tests -type f -name "*.py[oc]" -delete

# ── Python 后端检查 ──────────────────────────────────

test: ## 运行测试（不含覆盖率，xdist 并行）
	uv run pytest -m "not slow" -n $(PYTEST_JOBS)

cov: ## 运行测试并检查覆盖率（xdist 并行）
	uv run pytest -m "not slow" -n $(PYTEST_JOBS) --cov=$(PACKAGE) --cov-fail-under=$(COV_THRESHOLD)

lint: ## 代码风格检查 (ruff)
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## 类型检查 (pyrefly)
	uv run pyrefly check

typecheck-ci: ## 类型检查 (pyrefly, CI 平台 linux — 捕获跨平台问题)
	uv run pyrefly check --python-platform linux

# ── 前端检查 ──────────────────────────────────────────

fe-install: ## 安装前端依赖 (pnpm)
	@if command -v pnpm > /dev/null 2>&1; then \
		cd $(FRONTEND_DIR) && pnpm install; \
	else \
		cd $(FRONTEND_DIR) && npm install; \
	fi

fe-lint: ## 前端 ESLint 检查
	@if [ ! -f $(FRONTEND_DIR)/node_modules/.bin/eslint ]; then \
		echo "前端依赖未安装，正在执行 fe-install..."; \
		$(MAKE) fe-install; \
	fi
	cd $(FRONTEND_DIR) && npx eslint .

fe-typecheck: ## 前端 TypeScript 类型检查
	cd $(FRONTEND_DIR) && npx tsc -b

fe-build: ## 前端生产构建 (tsc + vite)
	cd $(FRONTEND_DIR) && npx tsc -b && npx vite build

fe-check: fe-typecheck fe-lint ## 前端全套检查 (typecheck + lint)

fe-clean: ## 清理前端构建产物
	rm -rf $(FRONTEND_DIR)/dist
	rm -rf $(FRONTEND_DIR)/node_modules/.tmp

# ── 全套门禁 ──────────────────────────────────────────

check: lint typecheck typecheck-ci cov fe-check ## 运行全套门禁 (后端 + 前端)

doc: ## 构建 Sphinx 文档
	uv run sphinx-build -b html docs docs/_build/html

tox: ## 多版本测试 (tox)
	uvx tox -p auto

BUMP_PART := $(filter-out bump,$(MAKECMDGOALS))

bump: ## 版本号 bump (默认 patch，用法: make bump [minor|major])
	@uvx bump-my-version bump $(if $(BUMP_PART),$(firstword $(BUMP_PART)),patch) --tag

patch minor major:
	@:

pub:  ## 推送到pypi
	uvx twine upload ./dist/**

push: ## 推送代码到所有远程仓库
	@uv run python -c "import subprocess as sp; [print(f'\u63a8\u9001 {r}...',flush=True) or (sp.run(['git','push',r],check=True) and sp.run(['git','push',r,'--tags'],check=True)) for r in sp.check_output(['git','remote'],text=True).split()]"
