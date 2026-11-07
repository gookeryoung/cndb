/** perf-baseline-ci.mjs — 在 CI runner 上连续采集性能旅程并写入 `ci` 基线（ADR 0116 C1）.
 *
 * `perf-baseline.mjs` 只负责「合并已有读数」；CI 一次 job 只产出一份
 * `test-results/perf/journeys.json`，凑不出中位数。本脚本负责补齐采集环节：
 *
 *   1. 连续运行 N 轮 `tests/e2e/perf`（默认 10 轮，ADR 0116 下一步口径）；
 *   2. 每轮结束后把 `journeys.json` 快照到 `test-results/perf-baseline-runs/`；
 *   3. 全部成功后调用 `perf-baseline.mjs`，按同环境 N 轮中位数写入 `baselines.json`。
 *
 * 任一轮失败立即中止且不写基线，避免用残缺样本抬高/压低门槛。
 *
 * 用法（CI job 内）：
 *   pnpm perf:baseline:ci
 *   pnpm perf:baseline:ci --runs 10 --reason "CI 首轮基线"
 *   pnpm perf:baseline:ci --runs 1 --dry-run      # 只验证采集链路，不写文件
 *
 * 约束：
 *  - 默认只允许在 CI 环境执行（`CI=true`）：本机/沙箱读数与 runner 差异大，
 *    混写会让基线失真；本地调试可显式加 `--allow-non-ci`。
 *  - 写基线至少 3 轮（`perf-baseline.mjs` 也会再校验一次）。
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { copyFile, mkdir, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(scriptDir, '..')
// 每轮快照不能放 test-results 下：Playwright 启动时会清空该目录，跨轮快照会丢
const runsDir = path.join(tmpdir(), 'cndb-perf-baseline-runs')
const journeysPath = path.resolve(frontendDir, 'test-results/perf/journeys.json')
const baselineWriter = path.resolve(scriptDir, 'perf-baseline.mjs')

const argv = process.argv.slice(2)
const argValue = (flag) => {
  const index = argv.indexOf(flag)
  return index >= 0 && argv[index + 1] && !argv[index + 1].startsWith('--') ? argv[index + 1] : null
}
const runs = Number(argValue('--runs') ?? '10')
const dryRun = argv.includes('--dry-run')
const allowNonCi = argv.includes('--allow-non-ci')
const reason = argValue('--reason') ?? `CI 连续 ${runs} 轮中位数`

const fail = (message) => {
  console.error(`[perf-baseline-ci] ${message}`)
  process.exit(1)
}

if (!Number.isInteger(runs) || runs < 1) fail(`--runs 必须是正整数（收到 ${String(runs)}）`)
if (!dryRun && runs < 3) fail(`写基线至少需要 3 轮（收到 ${runs} 轮）——单次读数会把抖动固化进门槛`)

const isCi = Boolean(process.env.CI) && process.env.CI !== 'false' && process.env.CI !== '0'
if (!isCi && !allowNonCi) {
  fail('当前不在 CI 环境（CI 未置位）。本机读数请用 perf-baseline.mjs 手动合并，或加 --allow-non-ci 明确承担风险')
}

/** 运行子进程并继承输出；非 0 退出码直接拒绝 */
function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: frontendDir, env: process.env, stdio: 'inherit' })
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${command} ${args.join(' ')} 退出码 ${String(code)}`))
    })
  })
}

/** 等待读数文件落盘：pnpm 退出与 Playwright 最后一次同步写之间有极短窗口 */
async function waitForFile(file, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs
  while (!existsSync(file)) {
    if (Date.now() > deadline) return false
    await delay(100)
  }
  return true
}

/** 读取一轮读数，打印关键指标便于在 CI 日志里观察抖动 */
async function summarize(file, round) {
  const data = JSON.parse(await readFile(file, 'utf8'))
  const cold = data.coldGrid ?? {}
  console.log(
    `[perf-baseline-ci] 第 ${round}/${runs} 轮完成 · environment=${String(data.environment)}` +
      ` · coldGrid.lcp=${String(cold.lcp ?? '-')}ms` +
      ` · coldGrid.longTaskMax=${String(cold.longTaskMax ?? '-')}ms`,
  )
  return data
}

async function main() {
  const pnpm = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
  await rm(runsDir, { recursive: true, force: true })
  await mkdir(runsDir, { recursive: true })

  const runFiles = []
  for (let round = 1; round <= runs; round += 1) {
    await run(pnpm, ['e2e', '--project=chromium-authed', 'tests/e2e/perf', '--workers=1'])
    if (!(await waitForFile(journeysPath))) {
      fail(`第 ${round} 轮未产出 ${journeysPath}（检查 perf 用例是否被跳过）`)
    }
    const snapshot = path.join(runsDir, `run-${round}.json`)
    await copyFile(journeysPath, snapshot)
    await summarize(snapshot, round)
    runFiles.push(snapshot)
  }

  if (dryRun) {
    console.log(`[perf-baseline-ci] --dry-run：${runFiles.length} 轮采集完成，未写入 baselines.json`)
    console.log(`[perf-baseline-ci] 快照目录：${runsDir}`)
    return
  }

  await run(process.execPath, [baselineWriter, ...runFiles, '--reason', reason])
  console.log(`[perf-baseline-ci] 已写入 ci 基线（${runFiles.length} 轮中位数）；快照保留在 ${runsDir}`)
}

main().catch((error) => fail(error instanceof Error ? error.message : String(error)))
