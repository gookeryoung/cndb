# Makefile - cndb 项目快捷命令
# 运行 `make help` 查看所有可用命令

PACKAGE := cndb
COV_THRESHOLD := 95
# min(cpu*2, 8)：≥4 核跑满 8 worker，低核数机器保守降档（纯 make 计算，避免每次解析都启动 uv/python）
ifeq ($(OS),Windows_NT)
CPUS := $(NUMBER_OF_PROCESSORS)
else
CPUS := $(shell nproc 2>/dev/null || echo 4)
endif
PYTEST_JOBS := $(if $(filter 0 1,$(CPUS)),2,$(if $(filter 2 3,$(CPUS)),4,8))

# push / bump 默认依赖 check，可用 SKIP_CHECK=1 临时跳过（仅限紧急修复，发布场景禁止使用）
CHECK_DEPS := $(if $(SKIP_CHECK),,check)

.PHONY: help sync frontend-build frontend-sync frontend-lint frontend-typecheck frontend-check build b clean c test cov lint typecheck check-fast check-fast-par check doc tox pub bump patch minor major push e2e pack-doctor pack pack-cache-clean

help: ## 显示帮助信息
	@uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); import re;ms=[(m.group(1),m.group(2).strip()) for f in sys.argv[1:] for l in open(f,encoding='utf-8') if (m:=re.match(r'^([a-zA-Z][\w -]*):.*?##\s*(.*)',l))];[print(f'  {n:<14} {d}') for n,d in ms]" $(MAKEFILE_LIST)

sync: ## 安装开发依赖
	uv sync --extra dev

frontend-sync: ## 安装前端依赖（pnpm install，惰性：node_modules 已存在则跳过）
	@uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); import os,subprocess;\
print('[frontend] node_modules 已存在，跳过 install') if os.path.isdir('frontend/node_modules') else (\
print('[frontend] node_modules 不存在，开始 pnpm install...'),\
subprocess.run(['pnpm','install','--frozen-lockfile'],cwd='frontend',check=True))"

frontend-lint: frontend-sync ## 前端 ESLint 检查
	cd frontend && pnpm lint

frontend-typecheck: frontend-sync ## 前端 TypeScript 类型检查
	cd frontend && pnpm typecheck

frontend-check: frontend-typecheck frontend-lint ## 前端门禁（typecheck + lint）

frontend-build: frontend-sync ## 构建前端（Vite，产物输出到 src/cndb/static/）
	cd frontend && pnpm build

build b: frontend-build ## 构建分发包 (前端 → wheel + sdist)
	uv build

clean c: ## 清理构建产物与缓存
	@uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); import shutil,pathlib,glob;\
pts=['build','dist','wheels','*.egg-info','htmlcov','.coverage','.coverage.*','coverage.xml','docs/_build','.tox','.ruff_cache','.pyrefly_cache','.mypy_cache'];\
[shutil.rmtree(m,ignore_errors=True) if pathlib.Path(m).is_dir() else pathlib.Path(m).unlink(missing_ok=True) for p in pts for m in glob.glob(p)];\
[shutil.rmtree(d,ignore_errors=True) for base in ('src','tests') for d in pathlib.Path(base).rglob('__pycache__')];\
[f.unlink(missing_ok=True) for base in ('src','tests') for f in pathlib.Path(base).rglob('*') if f.suffix in ('.pyc','.pyo')]"

test: ## 运行测试（不含覆盖率）
	uv run pytest -m "not slow" -n $(PYTEST_JOBS)

cov: ## 运行测试并生成 HTML 覆盖率报告
	uv run pytest --cov --cov-report=term --cov-fail-under=$(COV_THRESHOLD) --cov-report=html -n $(PYTEST_JOBS)
	@uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); print('Coverage report: htmlcov/index.html')"

e2e: frontend-sync ## 前端 E2E 测试（Playwright；需后端已启动 + 首次先 npx playwright install chromium）
	cd frontend && pnpm e2e

gitkeep-check: ## 校验关键 .gitkeep 文件（缺失会导致 CI/打包失败）
	uv run python scripts/check_gitkeep.py

lint: ## 代码风格检查 (ruff, 与 CI 对齐仅扫 src + tests)
	uv run ruff check src tests --cache-dir .ruff_cache
	uv run ruff format --check src tests

typecheck: ## 类型检查 (pyrefly)
	uv run pyrefly check -j 0

check-fast: gitkeep-check lint typecheck frontend-check ## 轻量门禁（不含覆盖率，适合日常快速验证）

# check-fast 并行版本（用于 check 内部，省时间）——本机 make 3.81 不支持 -O，输出可能交错
check-fast-par: ## 轻量门禁并行入口
	@$(MAKE) -j4 gitkeep-check lint typecheck frontend-check

# cov（pytest）是最长尾，最先启动，与 4 项门禁并行执行
check: ## 运行全套门禁 (gitkeep + lint + typecheck + frontend-check + cov，cov 与门禁并行)
	@$(MAKE) -j5 cov gitkeep-check lint typecheck frontend-check

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
	uvx twine upload dist/*.whl dist/*.tar.gz

# ── fspack 本地打包 ──────────────────────────────────────────

pack-doctor: ## fspack 环境诊断（检查打包工具链可用性）
	uv run fspack doctor

pack: frontend-build ## 本地当前平台打包（fspack build + package + 冒烟测试）
	uv run python -c "import sys,platform; sys.stdout.reconfigure(encoding='utf-8'); p='windows' if platform.system()=='Windows' else ('macos' if platform.system()=='Darwin' else 'linux'); print(f'[pack] 目标平台: {p}')"
	uv run fspack b . --target $$(uv run python -c "import platform; print('windows' if platform.system()=='Windows' else ('macos' if platform.system()=='Darwin' else 'linux'))")
	uv run fspack p . --target $$(uv run python -c "import platform; print('windows' if platform.system()=='Windows' else ('macos' if platform.system()=='Darwin' else 'linux'))") --format all --no-build
	@uv run python -c "import sys,subprocess,platform; sys.stdout.reconfigure(encoding='utf-8'); exe='dist/cndb.exe' if platform.system()=='Windows' else 'dist/cndb'; r=subprocess.run([exe,'info'],capture_output=True,text=True); print(r.stdout); print(f'[pack] 冒烟测试: OK' if r.returncode==0 else f'[pack] 冒烟测试 FAILED (rc={r.returncode})', file=sys.stderr if r.returncode!=0 else sys.stdout); sys.exit(r.returncode)"

pack-cache-clean: ## 清理 fspack 缓存（wheels + nuitka）
	uv run fspack cache clean

push: ## 推送代码到所有远程仓库
	@uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); import subprocess as sp; [print(f'\u63a8\u9001 {r}...',flush=True) or (sp.run(['git','push',r],check=True) and sp.run(['git','push',r,'--tags'],check=True)) for r in sp.check_output(['git','remote'],text=True).split()]"

