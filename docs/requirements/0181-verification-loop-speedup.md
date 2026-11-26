# 需求卡片：验证环节耗时优化（AI 开发内环提速）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0181
- 来源 / 提出人：用户（2026-11-26 会话）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片）

## 需求原句（逐字）

> 当前项目开发过程中测试时间太长，导致大模型调用等待过久，请针对AI开发流程验证环节的策略，给出建议。

后续确认（m00248）：

> 直接按此建议修复，确认修改项。

## 背景实测（2026-11-26，24 核 Windows，缓存全热）

| 环节 | 命令 | 墙钟 |
|---|---|---|
| 静态门禁 | `make check-fast` | 3s |
| 后端全量 | `pytest -m "not slow" -n 16` | 89s |
| 后端全量 | `pytest -m "not slow" -n 24` | 70s |
| 后端 + 覆盖率 | `make cov`（n16） | 96s |
| 前端单测 | `pnpm test` | 101s |
| 前端覆盖率 | `pnpm test:coverage` | 116s |
| e2e 全量 | `playwright test --project=chromium-authed` | 142s（含约 20s 起服务器 + seed） |
| e2e 单 spec | `playwright test tests/e2e/critical/navigation.spec.ts` | 30s（纯执行约 8–10s） |
| `make flow`（check-fast + test） | | 92s |
| `make check`（后端 → 前端串行） | | 约 208s |

三条关键剖面：

1. **纯逻辑测试被 jsdom 拖累**：79 个不碰 DOM 的测试文件在 node 环境跑 **2.6s**，在 jsdom + 全局 setup 下同样是这 79 个文件要 **18.6s**（Duration 剖面 setup 65% / environment 29% / tests 5%）。即环境与 setup 占 94%。
2. **后端并发度未打满**：`PYTEST_JOBS ?= 16`，24 核实测 n24 比 n16 快 19s。
3. **e2e 固定开销大**：每轮都 rmtree + seed + 起服务，单 spec 30s 里只有 8–10s 是真实执行。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「测试时间太长」 | 建立四级验证漏斗，每级有明确耗时预算：L0 静态 `make check-fast` ≤10s；L1 定向 `make verify-changed` ≤60s；L2 全量 `make flow` + `make check-frontend` ≤240s；L3 e2e 定向 ≤180s。预算写入 `AGENTS.md`，超预算视为需要排查的信号而非放行理由 | `AGENTS.md`、`docs/AI_DRIVEN_DEV_FLOW.md` | 文档存在且与实测一致 |
| C2 | 「验证环节」 | 新增 `make verify-changed`：按 `git diff` 变更文件定向跑后端与前端**相关**测试，命中不到或无把握时回退全量（fail-safe），不得因筛选而漏跑 | `Makefile`、`scripts/verify_changed.py` | 变更单个后端模块时只跑相关用例且全绿；改动核心文件时回退全量 |
| C3 | 「测试时间太长」 | `PYTEST_JOBS` 默认值改为按本机核数求值（上限 32，可用环境变量覆盖），不再硬编码 16 | `Makefile` | 24 核机器上默认并发为 24 |
| C4 | 「大模型调用等待过久」 | 失败回传精简：pytest 默认输出改为 `-q --tb=short --no-header`，不在失败时倾倒整段全量日志；`--lf` 类重跑前先判空，lastfailed 为空时不静默跑全量 | `pytest.ini`、`Makefile`、`scripts/` | 失败输出行数显著下降，重跑语义明确 |
| C5 | 「验证环节」 | 前端单测按环境拆 vitest project：纯逻辑测试走 node 环境 + 极简 setup，其余走 jsdom；清单由脚本按静态扫描生成并提交，提供 sync 命令与漂移校验，漏标只回退 jsdom（慢但不错） | `frontend/vite.config.ts`、`frontend/src/test/setup.pure.ts`、`frontend/scripts/pure-tests.mjs` | 两个 project 都全绿，覆盖率数值与拆分前一致 |
| C6 | 「验证环节」 | e2e 支持复用已 seed 的隔离服务器：新增显式开关与配套 make 目标，默认行为不变（仍每次重建，防止复用来源不明的端口服务） | `frontend/playwright.config.ts`、`frontend/scripts/e2e-server.py`、`Makefile` | 显式开启时单 spec 耗时下降且默认路径不变 |
| C7 | 「测试时间太长」 | 修 `frontend/scripts/e2e-affected.mjs` 筛选用例的缺陷：源码改动也能筛出受影响 spec，未跟踪的新 spec 不被漏掉；筛不出时回退 smoke | 同上 | 改 `frontend/src` 时能命中 e2e，新增未 add 的 spec 也能跑到 |

## 不做的事（与需求方确认的边界）

- 不放宽覆盖率、不加 `--ignore`、不注释断言、不跳过用例（H9–H12）。
- 不删 pyrefly / eslint / tsc 等静态检查。
- 不为省时间专门优化个别慢测试文件（实测剔除 4 个重文件仅省 3s）。
- 不开全局 `--no-isolate`（实测 20–81 个文件失败，属真实隔离需求）。
- 不做前后端并行（实测与串行持平且引入假失败）。

## 现状影响面（已核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 后端测试并发 | `Makefile:16` | `PYTEST_JOBS ?= 16`，注释「n16 最优」已被 n24 实测推翻 |
| 2 | 后端测试命令 | `Makefile:90`、`Makefile:93` | `test` / `cov` 均 `-m "not slow" -n $(PYTEST_JOBS)` |
| 3 | pytest 默认输出 | `pytest.ini:6` | `addopts = --dist worksteal`，无输出精简参数 |
| 4 | 门禁编排 | `Makefile:118`、`:120`、`:122`、`:124`、`:132` | check-fast / check-docs / flow / check-backend / check |
| 5 | 前端测试配置 | `frontend/vite.config.ts:216-245` | 单一 jsdom environment + 全局 `setup.ts` |
| 6 | 前端全局 setup | `frontend/src/test/setup.ts` | 326 行，jsdom polyfill + MSW 生命周期，per-file 执行 |
| 7 | e2e 服务器 | `frontend/playwright.config.ts:28-33` | `reuseExistingServer: false`，固定重建 |
| 8 | e2e 起服脚本 | `frontend/scripts/e2e-server.py` | rmtree + seed + serve |
| 9 | e2e 筛选 | `frontend/scripts/e2e-affected.mjs` | 只看 spec 自身变更，源码改动与未跟踪文件筛不出 |
| 10 | 流程文档 | `AGENTS.md` 3.2、`docs/AI_DRIVEN_DEV_FLOW.md` 3.E | 只有 L0/L1/L2 三级，无耗时预算 |

## 落地结果（2026-11-26）

| C | 落地位置 | 实测 / 验收 |
|---|---|---|
| C1 | `AGENTS.md` 新增 3.3「验证漏斗与耗时预算」；`docs/AI_DRIVEN_DEV_FLOW.md` 3 节引用 | F0 `make check-fast` 2.68s（≤10s） |
| C2 | `Makefile` 的 `verify-changed` / `verify-changed-plan`；`scripts/verify_changed.py`；`tests/test_verify_changed.py` | 危险路径（含 `pyproject.toml` / `pytest.ini` 这类非 `.py`）与「零命中」「命中 >60%」均回退全量；本轮变更（含 `frontend/package.json` 共享设施与 `pytest.ini`）正确判定为前后端全量；判定层 22 例单测覆盖四类回退与 `retest` 判空 |
| C3 | `Makefile` 顶部 `CPU_COUNT` 推导 + `export PYTEST_JOBS` | 24 核机器 `CPU=[24] JOBS=[24]`，`PYTEST_JOBS=8` 可覆盖 |
| C4 | `pytest.ini` 默认 `-q --tb=short --no-header`；`scripts/retest.py` + `make retest` | `--lf` 空缓存场景显式回退全量并打印原因 |
| C5 | `frontend/vite.config.ts` 的 `pure` / `dom` project；`frontend/scripts/pure-tests.mjs`、`src/test/pure-tests.json`、`src/test/setup.pure.ts`；`pnpm test:pure:check` 进 `pnpm check` | 纯逻辑 61 文件 1055 例 793ms；全量 293 文件 3610 例 85.6s（原 101s）；覆盖率核心集合 lines 97.66% / branches 100%、全局 83.85%（与拆分前一致） |
| C6 | `frontend/playwright.config.ts` 的 `reuseExistingServer: CNDB_E2E_REUSE === "1"`；`make e2e-reuse` | 默认仍每次重建；复用需显式开关 + 显式端口 |
| C7 | `frontend/scripts/e2e-affected.mjs` 重写 | `--dry-run` 实测：base=HEAD~1 → 1 spec、HEAD~3 → 9 spec、HEAD~6/10 → 22 spec；未跟踪新 spec 纳入变更集 |

## 未决问题

- [x] 拆分 project 后覆盖率是否仍完整 → 由 `check-coverage.mjs` 双门槛实测把关（C5 验收）。
- [x] 复用 e2e 服务器是否降低可信度 → 默认关闭，仅显式开关开启（C6）。

## 卡点

- [x] 每条需求句都有 C 编号约束。
- [x] 未决问题全部有结论，需求方（用户 m00248）已确认按建议实施。
