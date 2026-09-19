# 项目代码与配置精简清理方案

## 概要

针对 cndb（FastAPI + SQLAlchemy + Vite/React/TS 插件架构数据库平台）做一次证据驱动的精简清理：删除空壳包与死配置、收敛冗余依赖声明、修复失实文档。全部清理分四个独立维度执行，每个维度完成后跑 `make check` 门禁，覆盖率不得下降。

用户已确认三项决策：docs 骨架整体删除；tox.ini 删除；代码/配置清理全部执行（含 pyproject 依赖调整与 docker-compose 修复）。

## 现状分析（证据清单）

### A. 死代码 / 空壳
| 对象 | 证据 | 结论 |
|------|------|------|
| `src/cndb/services/__init__.py` | 仅 6 行模板注释，全仓库（src/tests/frontend）grep 无 `cndb.services` 引用 | 删除整目录 |
| `src/cndb/schemas/__init__.py` | 仅 6 行模板注释，grep 无 `cndb.schemas` 引用；插件实际用 `plugins/*/schemas/` | 删除整目录 |
| `src/cndb/models/` | `models/base.py` 定义 `Base`/`TimestampMixin`，被各插件 models 导入 | 保留 |
| `frontend/src/pages/grid/GridPage.tsx:1211` | 注释"权限设置 Modal 已收敛…仅作为 fallback 保留"，但对应代码已不存在，仅剩孤立注释 | 删除注释行 |

### B. 依赖（pyproject.toml）
| 依赖 | 证据 | 结论 |
|------|------|------|
| `httpx>=0.27.0`（运行时依赖） | src 与 tests 均无 `import httpx`；仅 `httpx2` 被 `plugins/tables/api_fetch.py` 使用。httpx 仅被 starlette TestClient 隐式需要（pytest 运行时） | 移到 `test` extra |
| `psycopg[binary]` | src 无直接 import，但 SQLAlchemy 按 URL scheme 动态加载驱动；docker-compose 双文件均有 `--profile pg` | 保留 |
| `python-docx` / `reportlab` / `jinja2` | `plugins/reports/routers/reports.py:276/345/13` 懒加载使用 | 保留 |
| `openpyxl` | `cli_users.py:128` | 保留 |
| `chardet` / `httpx2` / `python-jose` / `fastapi-offline` | `transfer.py:65` / `api_fetch.py:29` / `core/security.py` / `app.py:25` | 保留 |
| `docs` extra（sphinx 三件套） | docs 骨架待删 | 随 docs 一并删除 |
| 前端 `nunjucks` | `PreviewPanel.tsx:2` 在用 | 保留 |

### C. 配置
| 对象 | 证据 | 结论 |
|------|------|------|
| `docs/`（4 文件） | index.rst 为模板骨架（"Template for python web apps" + "TODO: 添加使用示例"），api.rst 仅 automodule | 整体删除（用户已确认） |
| `.readthedocs.yaml` | 仅服务于 docs 骨架 | 删除 |
| `tox.ini` | CI（ci.yml）不使用；仅 Makefile `tox` 目标经 uvx 调用；项目仅 py312 单版本 | 删除（用户已确认） |
| Makefile `check-fast-par` | `check` 目标（L80）未引用它，直接用 `-j5` 并行 cov 与四项门禁 | 删除死目标 |
| Makefile `doc` / `tox` 目标 | 配合 docs/tox 删除 | 删除 |
| `docker-compose.yml:20` | `context: ..`（父目录），但 compose 文件在仓库根、README 也从根目录运行；wheel 版（L24）正确用 `context: .` | 修复为 `context: .` |
| `ruff.toml:1,22-24` | UP045 ignore 的理由注释提到 typer，实际 runner.py 用 argparse（L9/L14）；`extend-exclude` 含不存在的 `template`、将不存在的 `docs` | 修注释、收敛 exclude |
| `pyrefly.toml:2-3` | includes 含 `**/*.ipynb`（仓库无 notebook）；excludes 含不存在的 `template/**`（docs 删除后 `docs` 相关无需处理，本就未列入） | 收敛 |
| `.copier-answers.yml` | copier 模板元数据，未来模板同步依赖 | 保留 |
| pyproject sdist exclude `.benchmarks/**` 等 | 目录不存在但属防御性排除，代价为零 | 保留 |

### D. 文档
| 对象 | 证据 | 结论 |
|------|------|------|
| `README.md:133-134` | 前端开发用 `npm install/npm run dev`，实际用 pnpm（CI/gitignore 均按 pnpm） | 修为 pnpm |
| `README.md:195` | `make bench` 目标不存在（Makefile 无 bench），实际脚本是 `scripts/bench_10k_rows.py` | 改为脚本调用 |
| `README.md:61,84` | `cp .env.example .env` 两处，但 `.env.example` 不存在 | 删除该指引 |
| `README.md:166` | 结构树列 `schemas/  # 通用 Pydantic schema`（空壳包待删） | 删除该行 |
| `README.md:165` | 结构树列 `health/` 插件，实际无 plugins/health 目录（健康检查在 `core/system_api.py`） | 修正表述 |
| `CHANGELOG.md` | 最新条目 0.1.2，当前版本 0.1.11，落后 9 版 | 追加本次清理条目；不回填历史（标记待用户复核） |
| `.gitignore:34` | `docs/_build/` 行，docs 删除后失效 | 删除该行 |

### E. 明确不动
- tests/ 下 16 个 `test_cov_*`/`test_coverage_*` 文件（约 1200 行）：合法测试，合并属高风险 churn，收益低。
- `.pre-commit-config.yaml`、`.github/workflows/{ci,release}.yml`、`.bumpversion.toml`、`alembic.ini`、`pytest.ini`：无冗余。
- `frontend/` 组件：抽查的 TableSettingsPage/TableSettingsDialog/SettingsModal/ImportExportDialog/ApiImportDialog 均有引用，无死文件。

## 变更清单

### 维度 1：空壳包与死代码删除
1. 删除目录 `src/cndb/services/`、`src/cndb/schemas/`（各仅含一个 6 行 `__init__.py`）。
2. 删除 `frontend/src/pages/grid/GridPage.tsx:1211` 的孤立注释行（连同其上相邻的空注释块，保留"移动表 Modal"注释）。
3. 执行前再次 grep 确认 `cndb\.services|cndb\.schemas` 零引用（迁移门禁）。

### 维度 2：依赖调整（pyproject.toml）
1. 从 `[project.dependencies]` 移除 `"httpx>=0.27.0"`；在 `[project.optional-dependencies]` 的 `test` 列表加入 `"httpx>=0.27.0"`（starlette TestClient 需要；CI test job 用 `--extra test`、e2e job 用 `--extra dev`→含 test，均覆盖）。
2. 删除 `docs = [...]` extra 行；`dev = ["cndb[lint,test,docs]"]` 改为 `["cndb[lint,test]"]`。
3. 运行 `uv lock` 重建锁文件，`uv sync --extra dev` 重建环境。

### 维度 3：配置文件删除与收敛
1. 删除文件：`docs/index.rst`、`docs/api.rst`、`docs/changelog.rst`、`docs/conf.py`、`docs/_static/.gitkeep`（整个 `docs/` 目录）、`.readthedocs.yaml`、`tox.ini`。
2. Makefile：
   - `.PHONY` 与目标体中删除 `doc`、`tox`、`check-fast-par` 三项（含 L75-77 的 check-fast-par 定义与其注释）。
3. ruff.toml：
   - `extend-exclude = ["docs", "examples", "template", "alembic"]` → `extend-exclude = ["examples", "alembic"]`。
   - L22-24 UP045 注释改写为 argparse 语境（"runner.py CLI 用 argparse + 函数分发，命令函数保留 Optional[X] 注解"），规则本身保留。
4. pyrefly.toml：
   - `project-includes` 移除 `"**/*.ipynb"`。
   - `project-excludes` 移除 `"template/**"`（执行时先确认 `template/`、`assets/` 目录确实不存在；`assets/**` 若目录存在则保留）。
5. `.gitignore`：删除 `docs/_build/` 行。

### 维度 4：文档与部署修复
1. `docker-compose.yml`：L20 `context: ..` → `context: .`（与 docker-compose.wheel.yml 对齐；compose 文件在仓库根，README 部署指引也从根目录执行）。
2. `README.md`：
   - L133-134：`npm install`/`npm run dev`/`npm run build` → `pnpm install`/`pnpm dev`/`pnpm build`。
   - L195：`make bench` → `uv run python scripts/bench_10k_rows.py  # 10k 行导入+查询基准`。
   - L61、L84：删除 `cp .env.example .env` 行及其引导句。
   - 项目结构树（L156-169）：删除 `schemas/` 行；`health/` 插件行改为说明健康检查由 `core/system_api.py` 提供；`plugins/` 树补 `wechat_auth/`（微信登录）。
   - L188 `完整文档` 段落保留（FastAPI /docs 自生成，不受 Sphinx 删除影响）。
3. `CHANGELOG.md`：顶部新增 `## [0.1.12] — 未发布` 条目（Removed/Changed/Fixed 分类）记录本次清理；历史 0.1.3–0.1.11 不回填（迭代记录中标注"待用户复核"）。

## 假设与决策

1. **授权**：删除整包/整目录/docs/tox 属高风险操作，已经由本方案征求用户确认（三项决策均选"删除/全部执行"），方案获批即为执行授权。
2. **httpx2 保留**：与 httpx 并存的原因未在注释中说明，但 `api_fetch.py` 实际使用且工作正常，不猜测、不动。
3. **覆盖率不降**：删除的空壳包无测试覆盖，分母减小可能使百分比微升；任何下降都视为误删，立即回滚该维度。
4. **每维度独立提交**：4 个维度按序执行，各自通过 `make check` 后单独 commit（便于回滚），最后统一 `make push`。
5. **不动测试与 CI**：本轮为纯减法清理，不触碰 16 个 cov 测试文件与 workflows。

## 验证

每个维度完成后：
1. `uv run ruff check src tests` + `uv run pyrefly check`（导入残留即失败）。
2. 维度 2 后：`uv lock`、`uv sync --extra dev`、`uv run pytest -m "not slow" -x -q` 快速确认测试可跑。
3. 全部维度完成后：`make check` 全绿（gitkeep + lint + typecheck + frontend-check + cov ≥ 95%）。
4. `uv build` 冒烟：确认 hatchling 打包不含已删目录（src/cndb wheel packages 验证）。
5. 本机若有 docker：`docker compose -f docker-compose.yml config -q` 验证 compose 语法与 context 解析。
6. 最终按仓库规范：`make check` 复核 → 中文 conventional commit（4 条，每维度一条）→ `make push`。
