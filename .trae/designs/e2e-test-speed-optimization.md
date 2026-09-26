# E2E 测试速度优化方案

> Status: DRAFT
> Author: AI
> Last updated: 2026-09-18

## Background

项目 `cndb` 前端 E2E 测试位于 `frontend/tests/e2e/`，基于 Playwright 1.63（`@playwright/test`），共 **30 条用例**（smoke 6 + critical 23 + auth.setup 1）。目标：在不降低覆盖与不引入恶化的前提下，系统性压缩 E2E 套件运行时长，并打通本地一键运行与 CI 持续观测。

## 现状盘点（证据来源）

| 维度 | 现状 | 证据 |
|------|------|------|
| 套件规模 | smoke 6 + critical 23 + setup 1 | `frontend/tests/e2e/{critical,smoke}` |
| 并行度 | `workers: 8`，`retries: 0`，`timeout: 30s` | `frontend/playwright.config.ts` |
| 后端启动 | 无 `webServer`，需手动启后端 | `Makefile` 中 `make e2e` 注释"需后端已启动" |
| CI | 无 E2E job（仅 lint / frontend-check / test） | `.github/workflows/ci.yml` |
| 固定等待 | **110 处** `waitForTimeout`，单点 300~2500ms | 全 `tests/e2e` grep |
| 重复登录/辅助 | **75 处** `getToken`；`getTableId/getWorkspaceId/gotoTable` 约 15 个 spec 重复定义 | 全 `tests/e2e` grep |
| 数据依赖 | 强依赖 `examples/datasets/` seed 数据（如"员工表 5 行"） | `critical/row-crud.spec.ts` 等 |

### 四个主要瓶颈

1. **无 `webServer` 自动拉起后端**：本地要手动启停后端、构建数据，门槛高、无法在干净环境运行，也就无法进入 CI。
2. **大量硬编码 `waitForTimeout` 固定睡眠**：普遍 300~1500ms，个别 2000/2500ms（如 `critical/view-mode-persist.spec.ts`）。叠加后单条测试纯睡眠达数秒，是最大浪费源。
3. **重复登录 + 辅助函数冗余**：每个测试多次 POST 登录取 token（`view-mode-sync` 达 9 次、`table-default-view` 达 8 次）；各 spec 内联重复实现 API 辅助。登录态已被 `auth.setup` 持久化到 `.auth/state.json`，本可复用。
4. **E2E 未接入 CI**：无法被持续观测，速度退化不可见。

---

## 优化方案

### A. 快速见效（低风险，优先落地）

**A1. 消灭硬编码 sleep → 信号化等待**

- 通用规则：`page.waitForTimeout(N)` 一律替换为二选一：
  - 有确定 UI 目标 → `await expect(locator).toBeVisible()`（内置 auto-retry，快则几十 ms）。
  - 有请求 → `page.waitForResponse('**/api/...')` / `page.waitForRequest`。
  - 表格渲染完成 → 等待 loading spinner（`ant-spin`）隐藏等确定性信号。
- 过渡期收敛出口：把残余 `waitForTimeout` 收敛到 fixtures 中单个 helper（如 `settle(page)`），便于审计与全局收紧、后续彻底移除。
- 预期收益：多数测试单条省 1.5~3s。

**A2. token 复用 + 辅助函数收敛**

- 新增 `tests/e2e/helpers/api.ts`：提供单一 API 上下文/`getAdminToken`，优先从 `.auth/state.json` 读 `cndb_access_token` 复用，避免逐测试重复登录（保留 login 失败兜底）。
- 收敛散落的 `getTableId/getWorkspaceId/gotoTable/cleanupExtraRows` 到该模块，各 spec 改为 import，删除重复实现。
- 预期收益：每条涉 API 测试省 2~4 个登录往返。

### B. 结构优化（中等投入，解锁本地一键跑）

**B1. Playwright 配置增加 `webServer` 自动拉起后端**

- 在 `playwright.config.ts` 声明 `webServer`：启动命令一键建库 + seed 演示数据，就绪健康检查通过后再跑；`reuseExistingServer: !process.env.CI`。
- 端口保持 8000（与 `baseURL` 一致）。
- 需要配套：可重复的本地启动脚本 `scripts/e2e_backend.sh`（`uv run python -m cndb` + 重置/seed 演示数据）。
- 收益：本地 `pnpm e2e` 一条命令可跑，并解锁 C 阶段 CI 接入。

**B2. 数据隔离与确定性**

- 现有 E2E 强依赖 seed 数据。落地二选一：
  - 方案①（推荐）：每次 `webServer` 启动重建测试库 + seed，保证确定性；未触达的共享表尽量只读。
  - 方案②：每条套件内建自包含 fixture（独立 workspace/table），彻底解耦全局 seed，便于将来 `--shard` 并行。
- 同步收紧可靠性：CI 设 `retries: 2` 处理偶发 flake，本地 `retries: 0`。

**B3. 并行度决策**

- 当前 `workers: 8` 已共享同一后端；进一步提高 worker 会放大共享数据竞争。**在 B2 数据隔离落地前不宜盲目提高 `workers`**。
- 本地按 CPU 用 `workers: undefined`（自动）；CI 用 `--shard` 切分并在 B2 落地后启用。

### C. 可观测与持续保障

**C1. 新增 `e2e` CI job（`ubuntu-latest`）**

- 步骤：setup Node/pnpm → `playwright install --with-deps chromium`（启用 `cache: 'playwright'`）→ 起后端（B1 脚本）→ `pnpm e2e`。
- 先行用 `--project=chromium-authed tests/e2e/smoke` 冒烟限时，稳定后扩全量 + `--shard`。
- 可先 `continue-on-error: true` 观察，稳定后强制门禁。
- 仅失败时收集 trace/截图/视频，控制存储与带宽。

**C2. 性能回归护栏**

- 新增探针用例：断言慢测阈值（任一条 > N 秒即失败），防硬编码 sleep 回潮。
- reporter 用 `github` + `list`，配合耗时输出做趋势跟踪。

---

## 量化预估与验收

| 项目 | 现状 | 目标 |
|------|------|------|
| 本地 `pnpm e2e` 前置步骤 | 手动起后端 | 一条命令，`webServer` 自动拉起 |
| 每条用例纯 sleep | 300~2500ms 累加 | 全部信号化，无固定 sleep（探针护栏） |
| 每用例重复登录 | 1~9 次 | ≤1 次，token 复用 |
| CI | 无 E2E job | 冒烟 → 全量，含 shard 并行 |
| 套件总时长 | — | 先取基线再定目标（建议 ≥30% 改善） |

**验收标准**
- `make check`（gitkeep + lint + typecheck + frontend-check + cov）不受影响、全绿。
- `pnpm e2e` 在干净环境可一键运行（B1 生效）。
- 全量无 `waitForTimeout` 新增；探针用例通过。
- E2E 30 条用例全通过。

## 落地顺序

1. A1（sleep→信号）+ A2（token/helper 收敛）——先拿单条时间下降的快速回报。
2. B1（webServer）+ B2（数据确定性）——解锁"一条命令跑通"。
3. B3 + C1（CI job + shard + retries）——持续观测。
4. C2（探针护栏）——防回潮。

## 风险

- **强耦合全局 seed 数据**：B2 前提高并行度会放大数据竞争，需先确定性。
- **sleep→信号迁移**：日历/甘特动画、用户偏好查询等信号不明显，可能引入偶发 flake；保留 `settle()` 出口并靠 retries 兜底。
- **CI 新增 job 拉长 PR 队列**：用 smoke 冒烟 + `--shard` 控制单层耗时。

## 决策点

1. **数据确定性选方案①（库级重建）还是方案②（自包含 fixture）？** 影响 B2 与 B3 方式。
2. **CI 是否纳入本次范围？** 涉及新增 job，需确认部署策略（冒烟优先）。
3. **是否接受 `make check` 之外新增 e2e 门禁（探针用例）？**