# Makefile - shortcut commands for the cndb project (run `make help` for all targets)
# Convention: this file only wires commands together; cross-platform / multi-line logic lives
# in scripts/ so every target stays readable at a glance.

.DEFAULT_GOAL := help

# Block the LD_LIBRARY_PATH injected by the IDE (Trae): its bundled old libsqlite3 lacks the
# sqlite3_deserialize symbol, which crashes the Python sqlite3 module and makes backend tests
# hang. GNU Make passes parent environment variables through to recipes by default; after
# unexport, no `uv run` child process inherits it any more.
unexport LD_LIBRARY_PATH

PACKAGE := cndb

# Gate concurrency (two serial phases, each owning the CPU so pytest and vitest never compete):
# PYTEST_JOBS: pytest-xdist worker count, derived from the local logical core count (cap 32)
#   instead of a hard-coded 16 — measured on 24 cores: n16=89s / n24=70s; worksteal steals
#   tasks dynamically and removes the long tail of whole-file loadfile distribution;
#   low-spec machines / CI override explicitly: make check PYTEST_JOBS=8.
#   Evaluation order: nproc (POSIX / MSYS, sub-millisecond) -> uv run python (cross-platform
#   fallback) -> 8.
CPU_COUNT := $(shell nproc 2>/dev/null | tr -dc 0-9)
ifeq ($(strip $(CPU_COUNT)),)
CPU_COUNT := $(shell uv run python -c "import os; print(os.cpu_count() or 0)" 2>/dev/null | tr -dc 0-9)
endif
ifeq ($(strip $(CPU_COUNT)),)
CPU_COUNT := 8
endif
# Cap 32: beyond that, scheduling and memory overhead of extra workers outweighs the gain
# (measured on 24 cores, 24 workers were already close to optimal).
# Use ifndef + := instead of ?=: the worker count is deterministic, one evaluation is enough,
# and each recipe expansion no longer forks a shell.
ifndef PYTEST_JOBS
ifneq ($(shell test $(CPU_COUNT) -gt 32 && echo y),)
PYTEST_JOBS := 32
else
PYTEST_JOBS := $(CPU_COUNT)
endif
endif
# Exported so scripts/retest.py / scripts/verify_changed.py reuse the same concurrency value
export PYTEST_JOBS
# VITEST_MAX_WORKERS: vitest worker count; left empty, frontend/vite.config.ts derives
#   min(16, CPU quota) from the container quota. Cloud / low-core machines override explicitly:
#   make check VITEST_MAX_WORKERS=4. Only exported when non-empty, so an empty value never
#   overrides the automatic derivation.
VITEST_MAX_WORKERS ?=
ifneq ($(strip $(VITEST_MAX_WORKERS)),)
export VITEST_MAX_WORKERS
endif

# dev target bind address / port, overridable on the command line:
# make dev DEV_HOST=127.0.0.1 DEV_PORT=8000
DEV_HOST ?= 0.0.0.0
DEV_PORT ?= 8772
# Ports released before `make dev` starts: backend DEV_PORT + the fixed Vite port 5173
# (see cli/main.py dev())
DEV_PORTS ?= $(DEV_PORT) 5173

# uvx temporary environments ignore the project [tool.uv.index]; pin the mirror explicitly
UVX_INDEX := --default-index https://mirrors.cloud.tencent.com/pypi/simple

# Frontend dependency stamp: refreshed by make after a successful pnpm install; when lock /
# package.json are unchanged the step is skipped at zero cost
FRONTEND_DEPS := frontend/node_modules/.make-sync

.PHONY: help env-guard sync free-dev-ports dev seed frontend-sync frontend-static frontend-coverage frontend-build \
        build clean test cov lint typecheck e2e e2e-dev bench gitkeep-check adr-check constraint-check \
        check-fast check-docs check-backend check-frontend flow verify-changed verify-changed-plan retest \
        e2e-affected e2e-reuse check bump pub push pack-doctor pack pack-cache-clean \
        docker-dev docker-dev-down docker-stop docker-build docker-export dd ds ddd db de \
        patch minor major

# ── Development ───────────────────────────────────────────────────────

help: ## Show this help
	@uv run python scripts/help.py $(MAKEFILE_LIST)

env-guard: ## Environment check (blocks LD_LIBRARY_PATH pollution: an old libsqlite3 without sqlite3_deserialize hangs tests)
	@uv run python scripts/check_env.py

sync: ## Install backend dev dependencies + git pre-commit hooks (prek)
	uv sync --extra dev
	uv run prek install --force

free-dev-ports: ## Kill stale processes holding dev ports (backend DEV_PORT=8772, frontend 5173; override with DEV_PORTS)
	@uv run python scripts/free_ports.py $(DEV_PORTS)

dev: env-guard free-dev-ports $(FRONTEND_DEPS) ## Dev mode: release stale ports, then start backend + frontend (uvicorn + Vite, Ctrl+C stops both)
	uv run cndb dev --host $(DEV_HOST) --port $(DEV_PORT)

seed: ## Seed demo data for dev / e2e (recreates the DB; refuses when user data exists, use cndb seed --force)
	uv run cndb seed

# ── Frontend ──────────────────────────────────────────────────────────

$(FRONTEND_DEPS): frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml
	cd frontend && pnpm install --frozen-lockfile
	@uv run python -c "import pathlib; pathlib.Path('$(FRONTEND_DEPS)').touch()"

frontend-sync: $(FRONTEND_DEPS) ## Install frontend dependencies (pnpm; skipped when lock / package.json are unchanged)

frontend-static: $(FRONTEND_DEPS) ## Frontend static checks (patch + tsc + eslint)
	cd frontend && pnpm check

frontend-coverage: $(FRONTEND_DEPS) ## Frontend tests + dual coverage thresholds (text + json-summary)
	cd frontend && pnpm test:coverage

frontend-build: $(FRONTEND_DEPS) ## Build the frontend (Vite, output goes to src/cndb/static/)
	cd frontend && pnpm build

# ── Quality gates ─────────────────────────────────────────────────────

lint: ## Backend style checks (ruff check + format, same scope as CI: src + tests)
	uv run ruff check src tests --cache-dir .ruff_cache
	uv run ruff format --check src tests

typecheck: ## Backend type checks (pyrefly)
	uv run pyrefly check -j 0

test: env-guard ## Backend tests (no coverage)
	uv run pytest -m "not slow" -n $(PYTEST_JOBS)

cov: env-guard ## Backend tests + coverage gate (same scope as CI, cndb package only; threshold in pyproject [tool.coverage.report])
	uv run pytest -m "not slow" --cov=$(PACKAGE) --cov-report=term --cov-report=html -n $(PYTEST_JOBS)
	@echo 'Coverage report: htmlcov/index.html'

gitkeep-check: ## Verify key .gitkeep files (missing ones break CI / packaging)
	uv run python scripts/check_gitkeep.py

adr-check: ## Verify ADR landing status, handoff sections and CHANGELOG references
	uv run python scripts/check_adr_landing.py

constraint-check: ## Verify hard-constraint ledger format, unique ids, source ADR and make targets (ADR 0119)
	uv run python scripts/check_constraints.py

e2e: frontend-build ## Frontend E2E (Playwright; webServer boots an isolated backend, run npx playwright install chromium first)
	cd frontend && pnpm e2e

e2e-dev: $(FRONTEND_DEPS) ## E2E in dev mode (Vite dev serves sources; catches regressions only visible in dev)
	cd frontend && pnpm e2e:dev

e2e-affected: frontend-build ## Targeted E2E: select affected specs from git changes (E2E_BASE_REF defaults to HEAD~1, untracked specs count too)
	cd frontend && pnpm e2e:affected

# Reuse an already seeded isolated server for E2E (requirement 0181 C6): saves the fixed cost of
# rmtree + seed + server boot on every round. Local inner loop only — the default path still
# rebuilds every time, so no one reuses a server of unknown origin.
E2E_REUSE_PORT ?= 8001
e2e-reuse: frontend-build ## E2E against an already seeded server (a single spec, e.g. make e2e-reuse SPEC=tests/e2e/critical/navigation.spec.ts)
	cd frontend && CNDB_E2E_REUSE=1 E2E_PORT=$(E2E_REUSE_PORT) pnpm e2e $(SPEC)

# Benchmark import row count: override with make bench ROWS=100000
ROWS ?= 10000

bench: env-guard ## Benchmark (10k-row import + query throughput on a temporary SQLite DB; make bench ROWS=100000 to scale)
	uv run python scripts/bench_10k_rows.py --rows $(ROWS)

# L1 config changes: lightweight static gates (no tests)
check-fast: env-guard gitkeep-check adr-check constraint-check lint typecheck frontend-static ## L0 gate: lightweight static checks (no tests, run every round while implementing; budget <=10s)
# L0 documentation changes: documentation checks only
check-docs: gitkeep-check adr-check constraint-check ## Documentation gate (use when only *.md changed)
# L2 code changes: lightweight static gates + full backend suite (requirement 0181 four-level funnel, L2)
flow: check-fast test ## L2 gate: lightweight static checks + full backend suite (budget <=3min)

# L1 targeted verification (requirement 0181 C2): run only the tests related to the git change,
# typically 20-40s for a single module. Shared infrastructure / too-wide hits fall back to the
# full suite — slower is better than missing. BASE can point at a remote branch.
BASE ?= HEAD
verify-changed: env-guard ## L1 gate: targeted verification, only tests related to the git change (BASE=origin/main compares against a remote branch; budget <=60s)
	@uv run python scripts/verify_changed.py --base $(BASE)

verify-changed-plan: ## Only print the verify-changed plan, run no tests
	@uv run python scripts/verify_changed.py --base $(BASE) --dry-run

retest: env-guard ## Re-run only last round's failures (falls back to the full suite explicitly when lastfailed is empty)
	@uv run python scripts/retest.py $(PYTEST_EXTRA)

check-backend: env-guard ## Backend gate (cov + lint + types + gitkeep + ADR; PYTEST_JOBS tunable)
	@$(MAKE) --no-print-directory -j1 cov gitkeep-check adr-check lint typecheck

check-frontend: $(FRONTEND_DEPS) ## Frontend gate (vitest coverage + patch + tsc + eslint; VITEST_MAX_WORKERS tunable)
	@$(MAKE) --no-print-directory -j1 frontend-coverage frontend-static

# Backend and frontend run serially: vitest jsdom cases next to pytest -n 16 oversubscribe the
# CPU and the RTL findBy* default 1s wait times out under the congestion; the semantics are
# still "one command runs every gate".
check: env-guard $(FRONTEND_DEPS) ## Full gate (backend -> frontend serially, each phase owning the CPU)
	@$(MAKE) --no-print-directory check-backend
	@$(MAKE) --no-print-directory check-frontend

# ── Build / package / release ─────────────────────────────────────────

build: frontend-build ## Build release artifacts (frontend -> wheel + sdist)
	uv build

# ── Docker / offline deployment ───────────────────────────────────────

# Version (defaults to pyproject.toml; override with make docker-build VERSION=x.y.z)
VERSION ?= $(shell grep -m1 -E '^version' pyproject.toml | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

docker-dev dd: ## Docker dev mode: backend + frontend in containers (CNDB_SOURCES=auto defaults to cn locally; frontend 5173 / backend 8772)
	bash deploy/docker-sources.sh exec docker compose -f docker-compose.dev.yml up --build

docker-dev-down ddd: ## Stop Docker dev mode (removes containers and network, keeps data volumes)
	docker compose -f docker-compose.dev.yml down

docker-stop ds: ## Quickly stop Docker dev mode (stops containers only, keeps them and the data volumes)
	docker compose -f docker-compose.dev.yml stop

docker-build db: build ## Build the image locally (CNDB_SOURCES=auto defaults to cn, GitHub uses global)
	bash deploy/build-image.sh $(VERSION)

docker-export de: ## Export the offline delivery bundle (run make docker-build first; CNDB_SOURCES only affects the nginx image source)
	bash deploy/export-image.sh $(VERSION)

clean: ## Remove build artifacts and caches
	@uv run python scripts/clean.py

BUMP_PART := $(filter-out bump,$(MAKECMDGOALS))

bump: ## Bump the version (patch by default, usage: make bump [minor|major])
	@uvx $(UVX_INDEX) bump-my-version bump $(if $(BUMP_PART),$(firstword $(BUMP_PART)),patch) --tag

patch minor major:
	@:

pub: ## Upload dist/ to PyPI (run make build first)
	uvx $(UVX_INDEX) twine upload dist/*.whl dist/*.tar.gz

push: ## Push the current branch to every remote (tags included)
	@uv run python scripts/push.py

pack-doctor: ## fspack environment diagnostics (checks packaging toolchain availability)
	uv run fspack doctor

pack: frontend-build ## Package for the current platform (fspack build + package + smoke test)
	uv run fspack b .
	uv run fspack p . --format all --no-build
	@uv run python -c "import subprocess, sys; sys.exit(subprocess.run(['dist/cndb.exe' if sys.platform == 'win32' else 'dist/cndb', 'info']).returncode)"

pack-cache-clean: ## Clean the fspack cache (wheels + nuitka)
	uv run fspack cache clean
