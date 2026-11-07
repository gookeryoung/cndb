/** perf-baseline.mjs — 把性能旅程读数合并为同环境基线（ADR 0116 C1）.
 *
 * 背景：`tests/e2e/perf/journeys.spec.ts` 每次运行把三条旅程的读数写到
 * `test-results/perf/journeys.json`；基线缺失时只记录不判 FAIL。手工把一次读数
 * 抄进 `baselines.json` 会把环境抖动固化进门槛，故这里要求**同一环境至少 3 份**
 * 读数、逐指标取中位数后写入，避免单次抖动抬高或压低基线。
 *
 * 用法：
 *   cd frontend
 *   pnpm e2e --project=chromium-authed tests/e2e/perf --workers=1
 *   cp test-results/perf/journeys.json /tmp/perf-run-1.json   # 重复 3 次
 *   node scripts/perf-baseline.mjs /tmp/perf-run-{1,2,3}.json --reason "CI 首轮基线"
 *
 * 约定：
 *  1. 三份读数必须来自同一环境（`environment` 字段一致），否则拒绝写入；
 *  2. 只写数值型且 > 0 的指标（0 在断言里表示「本环境无该指标，跳过」）；
 *  3. 基线是「超基线 +15% 即 FAIL」的参照，只允许由本脚本改写，避免手改数字；
 *  4. 不改动其它环境已有基线；`$comment` 原样保留。
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const baselinePath = path.resolve(scriptDir, '../tests/e2e/perf/baselines.json')
const REQUIRED_RUNS = 3
/** 读数文件里与旅程无关的顶层字段，不参与基线 */
const NON_JOURNEY_KEYS = new Set(['environment', 'generatedAt'])

const argv = process.argv.slice(2)
const argValue = (flag) => {
  const i = argv.indexOf(flag)
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : null
}
const files = argv.filter((item) => !item.startsWith('--') && item !== argValue('--reason'))
const reason = argValue('--reason')

const fail = (msg) => {
  console.error(`[perf-baseline] ${msg}`)
  process.exit(1)
}

if (files.length < REQUIRED_RUNS) {
  fail(`至少需要 ${REQUIRED_RUNS} 份同环境读数（当前 ${files.length} 份）——单次读数会把抖动固化进基线`)
}
if (!reason) {
  fail('必须用 --reason "..." 说明基线来源（如 CI 首轮 / 本地三轮中位数）')
}

/** 读取并校验一份读数；返回 { environment, journeys } */
function loadRun(file) {
  if (!existsSync(file)) fail(`读数文件不存在：${file}`)
  let data
  try {
    data = JSON.parse(readFileSync(file, 'utf8'))
  } catch (error) {
    fail(`读数文件不是合法 JSON：${file}（${String(error)}）`)
  }
  const environment = data.environment
  if (environment !== 'local' && environment !== 'ci') {
    fail(`${file} 的 environment 必须是 local / ci（收到 ${String(environment)}）`)
  }
  const journeys = Object.fromEntries(
    Object.entries(data).filter(([key]) => !NON_JOURNEY_KEYS.has(key)),
  )
  if (Object.keys(journeys).length === 0) fail(`${file} 不含任何旅程读数`)
  return { environment, journeys }
}

const runs = files.map(loadRun)
const environments = new Set(runs.map((run) => run.environment))
if (environments.size !== 1) {
  fail(`读数环境不一致：${[...environments].join(' / ')}——基线必须按环境分别采集`)
}
const environment = [...environments][0]

/** 逐指标取中位数；非数值 / 0 值跳过（0 表示该环境无此指标） */
function medianMetrics(values) {
  const result = {}
  const metricKeys = new Set(values.flatMap((metrics) => Object.keys(metrics)))
  for (const key of metricKeys) {
    const numbers = values
      .map((metrics) => metrics[key])
      .filter((value) => typeof value === 'number' && Number.isFinite(value) && value > 0)
    if (numbers.length === 0) continue
    numbers.sort((a, b) => a - b)
    const mid = Math.floor(numbers.length / 2)
    const median = numbers.length % 2 === 0 ? (numbers[mid - 1] + numbers[mid]) / 2 : numbers[mid]
    result[key] = Math.round(median)
  }
  return result
}

const journeyNames = new Set(runs.flatMap((run) => Object.keys(run.journeys)))
const merged = {}
for (const name of journeyNames) {
  const available = runs.filter((run) => run.journeys[name]).map((run) => run.journeys[name])
  // 只采用完整出现在全部读数里的旅程，避免用轮次不同的样本拼基线
  if (available.length !== runs.length) {
    console.warn(`[perf-baseline] 跳过 ${name}：仅 ${available.length}/${runs.length} 份读数包含该旅程`)
    continue
  }
  const metrics = medianMetrics(available)
  if (Object.keys(metrics).length > 0) merged[name] = metrics
}
if (Object.keys(merged).length === 0) fail('没有任何旅程在全部读数中都出现，未写入基线')

const existing = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, 'utf8')) : {}
const next = {
  ...existing,
  _meta: {
    environment,
    runs: runs.length,
    reason,
    updatedAt: new Date().toISOString(),
  },
  [environment]: { ...(existing[environment] ?? {}), ...merged },
}
writeFileSync(baselinePath, `${JSON.stringify(next, null, 2)}\n`)

console.log(
  `[perf-baseline] ${environment} 环境写入 ${Object.keys(merged).length} 条基线（${runs.length} 轮中位数）：` +
    Object.keys(merged).join('、'),
)
