# ADR 0002: Frontend Check 拆分并行（分片 + 覆盖率合并）

Status: Proposed（待确认后实施）
Date: 2026-10-16

## Context

`ci.yml` 的 `frontend-check` 是整条 CI 的唯一长尾：

| job | 近 4 次 run 耗时 |
| --- | --- |
| Lint & Typecheck | 14 / 12 / 13 / 13 s |
| Test (Python 3.12) | 112~152 s |
| E2E ×4 shard | 105~220 s |
| **Frontend Check** | **350 / 441 / 454 s** |

单 job 内部步骤耗时（run 38847084681，总计 349 s）：

| 步骤 | 耗时 | 占比 |
| --- | --- | --- |
| pnpm install | 5 s | 1% |
| Typecheck | 11 s | 3% |
| ESLint | 6 s | 2% |
| **Frontend tests + coverage** | **288 s** | **82%** |
| Build frontend | 22 s | 6% |
| Bundle size budget | <1 s | ~0% |

vitest 自报的分段（CI，`Duration 287.88s`）：

`tests 54% · setup 25% · environment 10% · import 9% · transform 1% · worker 1%`

即 **约一半成本是每个测试文件的固定启动开销**（setupFiles + jsdom 环境 + 模块图求值），
只有 54% 是测试本身。123 个文件串行摊在 **4 个 worker** 上（`maxWorkers = min(16, availableParallelism())`，
公开仓库标准 runner = 4 vCPU → 实际 4 worker）→ 288 s。

结论：瓶颈是**单机 4 核跑 123 个文件**，不是某一步慢。当前 job 把所有步骤串成一条流水线，
最长的那一步决定整体时长。

## Decision

把 `frontend-check` 拆成 **2 条并行链 + 1 个串行收口**：

1. `frontend-static`：Typecheck → ESLint → Build → Bundle budget（约 70 s 独立跑）
2. `frontend-test`：matrix `shard: [1,2,3,4]`，每片 1 台 4 vCPU runner，`vitest --shard=i/4`
   输出 blob 报告（含覆盖率原始数据）并上传 artifact
3. `frontend-coverage`：`needs: [frontend-test]`，下载全部 blob → `vitest --merge-reports --coverage`
   → `node scripts/check-coverage.mjs`（**唯一**执行覆盖率门禁的地方）

关键点：**覆盖率门禁只在合并后的报告上执行**。单个分片只看到 1/4 源码，其
`coverage-summary.json` 不完整，不能用于门槛判定。

## 实测依据（本机 24 核，`VITEST_MAX_WORKERS=4` 模拟 4 vCPU 单机）

| 配置 | 墙钟 | 结果 |
| --- | --- | --- |
| 单进程 4 worker（= 当前 CI 形态） | **176 s** | 123 files / 1541 tests 全绿，全局行覆盖 79.15% |
| **4 分片并行（每片 4 worker）+ 合并** | **77 s + 5 s** | 同上，合并后覆盖率与单进程**完全一致**（79.15% / 核心集合 97.63%） |
| `--pool=threads` | 195 s | 更慢（沙箱实测，`vitest doctor` 同样报 195.53s） |
| `--pool=vmThreads` / `vmForks` | 失败 | 不可用 |
| `--no-isolate` | 72 s | **12 文件 / 48 用例失败**，不可用 |

- 链路已跑通：4 个 blob（`blob-1-4.json`…`blob-4-4.json`）并行写入同一 `.vitest/blob/` 无冲突
  （文件名含 `<index>-<count>`，见 `BlobReporter.onTestRunEnd`），`--merge-reports` 合并出
  123 files / 1541 tests 与完整覆盖率，`check-coverage.mjs` 全部达标。
- 分片均衡度可接受：各片文件耗时合计 75 / 71 / 72 / 86 s（默认按 `sha1(path)` 排序切分，
  均衡率约 93%），无需自定义 sequencer。

**预期 CI 收益**：`frontend-static` ≈ 70 s ∥ `frontend-test` 每片 ≈ 288/4×1.3+20 ≈ 115 s
→ 收口 30 s ⇒ **Frontend Check ≈ 150 s（-57%）**，并退出关键路径
（新的瓶颈变为 E2E / Python Test 的 105~220 s），整条 CI 从 ~7.5 min 降到 ~3.5 min。

## Consequences

- 分片不是免费：多 3 台 runner 的固定开销（checkout + pnpm install ≈ 20 s/台）+ 1 台合并 runner。
  公开仓库 Actions 分钟数免费，时间上净赚。
- `--reporter=blob` 会**替换**默认 reporter，必须同时传 `--reporter=default`，否则分片日志静默
  （已实测确认）。
- `--merge-reports` 与 `--reporter=blob` 冲突（`Cannot merge reports when --reporter=blob is used`），
  故 blob reporter **只能由 CLI 传入**，不能写进 `vite.config.ts`。
- **风险：job 名称变化会打断分支保护的 required status check。** 若 GitHub 分支保护里
  配了名为 `Frontend Check` 的必过检查，需同步改为新 job 名（3 个）。
- `.vitest/` 需加入 `frontend/.gitignore`。
- 后续可继续压缩的点（本次不做）：E2E 的 4 个 shard **各自重复执行 `pnpm build`**（≈30 s/片），
  可由 `frontend-static` 上传 `src/cndb/static` 产物、E2E 下载复用；分片后 E2E 会成为新瓶颈。

## 已否决 / 不采用的方案

| 方案 | 结论 |
| --- | --- |
| 只把 typecheck/eslint/build 与 test 拆成两个并行 job | 收益仅 ~40 s（tests 步仍占 82%），单独做不值得，已并入 `frontend-static` |
| vitest 配置调优（threads / vmThreads / isolate:false） | 实测全部劣于或等于基线：threads 更慢，vm* 直接失败，`isolate:false` 破坏 12 个文件的隔离假设（zustand 单例、MSW 状态） |
| happy-dom 替代 jsdom | antd 5 兼容性欠佳（`vite.config.ts` 已有结论），不评估 |
| 覆盖率与测试解耦（PR 不跑 coverage） | 收益小（coverage 本身不是主要开销），且丢失 PR 期覆盖率门禁 |
| 更大 runner / 自建 runner | 公开仓库已是 4 vCPU；larger runner 付费，Lighthouse(2C) 自建更慢 |
