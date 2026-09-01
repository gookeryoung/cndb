# Makefile - cndb 项目快捷命令
# 运行 `make help` 查看所有可用命令

PACKAGE := cndb
COV_THRESHOLD := 95
COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help sync build b clean c test cov lint typecheck typecheck-ci check doc tox bump patch minor major push \
        dev migrate makemigrations su shell dbshell routes static seed bench up down logs ps

help: ## 显示帮助信息
	@uv run python -c "import re,sys;ms=[(m.group(1),m.group(2).strip()) for f in sys.argv[1:] for l in open(f,encoding='utf-8') if (m:=re.match(r'^([a-zA-Z][\w -]*):.*?##\s*(.*)',l))];[print(f'  {n:<18} {d}') for n,d in ms]" $(MAKEFILE_LIST)

sync: ## 安装开发依赖
	uv sync --extra dev

# ---------- 本地运行 ----------

dev: ## 启动开发服务器 (http://127.0.0.1:8000，SQLite)
	uv run python manage.py migrate
	uv run python manage.py runserver

migrate: ## 执行数据库迁移
	uv run python manage.py migrate

makemigrations: ## 生成数据库迁移文件
	uv run python manage.py makemigrations

su: ## 创建超级用户 (需 DJANGO_SUPERUSER_PASSWORD 环境变量，用户名默认 admin)
	@uv run python scripts/dev_setup.py --superuser

shell: ## 进入 Django shell
	uv run python manage.py shell

dbshell: ## 进入数据库 shell
	uv run python manage.py dbshell

routes: ## 列出全部 URL 路由
	uv run python scripts/dev_setup.py --routes

static: ## 收集静态文件到 STATIC_ROOT
	uv run python manage.py collectstatic --noinput

seed: ## 写入演示数据（用户/工作区/表/字段/视图/示例行，幂等可重复执行）
	uv run python scripts/seed_demo.py

bench: ## 运行行数据压测基准（slow 标记）
	uv run pytest tests/test_bench_rows.py -m slow -s --no-cov

# ---------- 容器部署 ----------

up: ## 启动生产容器 (gunicorn + PostgreSQL，需 deploy/.env)
	$(COMPOSE) up -d --build

down: ## 停止生产容器
	$(COMPOSE) down

logs: ## 跟随查看容器日志
	$(COMPOSE) logs -f web

ps: ## 查看容器状态
	$(COMPOSE) ps

# ---------- 工具链 ----------

build b: ## 构建分发包 (wheel + sdist)
	uv build

clean c: ## 清理构建产物与缓存
	rm -rf build/ dist/ wheels/ *.egg-info htmlcov/ .coverage .coverage.* coverage.xml docs/_build/ .tox/
	rm -rf .ruff_cache/ .pyrefly_cache/ .mypy_cache/
	find src tests -type d -name __pycache__ -exec rm -rf {} +
	find src tests -type f -name "*.py[oc]" -delete

test: ## 运行测试（不含覆盖率）
	uv run pytest -m "not slow"

cov: ## 运行测试并检查覆盖率
	uv run pytest -m "not slow" --cov=$(PACKAGE) --cov-fail-under=$(COV_THRESHOLD) -n auto

lint: ## 代码风格检查 (ruff)
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## 类型检查 (pyrefly)
	uv run pyrefly check

typecheck-ci: ## 类型检查 (pyrefly, CI 平台 linux — 捕获跨平台问题)
	uv run pyrefly check --python-platform linux

check: lint typecheck typecheck-ci cov ## 运行全套门禁 (lint + typecheck + typecheck-ci + cov)

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

