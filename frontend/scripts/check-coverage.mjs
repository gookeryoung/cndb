/**
 * 覆盖率双门槛校验脚本（spec NFR-3 / AC-2）.
 *
 * 读取 vitest --coverage 产出的 coverage/coverage-summary.json：
 *  1. 核心逻辑集合（FR-2/FR-3 模块）：行覆盖 ≥ 90% 且 分支覆盖 ≥ 85%
 *  2. 全局 src：行覆盖 ≥ 水位常量（低水位起步，随覆盖率提升只升不降）
 *
 * 任一不达标输出明细并以非 0 退出码结束。
 *
 * 用法：node scripts/check-coverage.mjs [--summary <coverage-summary.json 路径>]
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ── 阈值常量 ─────────────────────────────────────────────

/** 核心逻辑集合行覆盖门槛（%） */
const CORE_LINES_MIN = 90
/** 核心逻辑集合分支覆盖门槛（%） */
const CORE_BRANCHES_MIN = 85

/**
 * 全局 src 行覆盖低水位（%）。
 *
 * 取 5 的整数倍；按"实际值向下取 5 的整数倍"校准，覆盖率提升后只升不降。
 * Task 14 校准（2026-09）：三层测试落地后实测全局 17.58%，按规则校准为 15
 * （待用户复核；后续随覆盖提升只升不降）。
 */
const GLOBAL_LINES_MIN = 15

/**
 * 核心逻辑集合（FR-2/FR-3 模块清单，相对 frontend/ 的路径，正斜杠书写）。
 * 含 Task 11 大组件抽取产物 ganttTimeline.ts / kanbanBoard.ts。
 */
const CORE_FILES = [
  // grid 领域
  'src/pages/grid/components/fieldOps.ts',
  'src/pages/grid/components/fieldValueFormat.ts',
  'src/pages/grid/components/dateUtils.ts',
  'src/pages/grid/components/viewOptionSchema.ts',
  'src/pages/grid/components/ganttTimeline.ts',
  'src/pages/grid/components/kanbanBoard.ts',
  // 通用
  'src/utils/tagColors.ts',
  'src/hooks/useResponsive.ts',
  'src/components/report-editor/jinja2Highlight.ts',
  // 数据层
  'src/api/client.ts',
  'src/store/auth.ts',
  'src/store/gridView.ts',
  'src/store/tableSettings.ts',
]

// ── 解析参数 ─────────────────────────────────────────────

function parseArgs(argv) {
  const args = { summary: path.resolve(__dirname, '../coverage/coverage-summary.json') }
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--summary') {
      args.summary = path.resolve(argv[++i])
    }
  }
  return args
}

// ── 主流程 ───────────────────────────────────────────────

const { summary: summaryPath } = parseArgs(process.argv.slice(2))

if (!fs.existsSync(summaryPath)) {
  console.error(`[check-coverage] 找不到覆盖率汇总文件: ${summaryPath}`)
  console.error('[check-coverage] 请先执行 vitest run --coverage 生成报告')
  process.exit(2)
}

const summary = JSON.parse(fs.readFileSync(summaryPath, 'utf-8'))

// coverage-summary.json 的 key 为绝对路径；统一成正斜杠便于匹配
function normalizeKey(key) {
  return key.replaceAll('\\', '/')
}

/** 从 summary 中找出核心集合的条目（按相对路径尾部匹配） */
function collectCoreEntries() {
  const entries = []
  for (const rel of CORE_FILES) {
    const match = Object.entries(summary).find(
      ([key]) => key !== 'total' && normalizeKey(key).endsWith(`/${rel}`),
    )
    if (match) {
      entries.push({ rel, data: match[1] })
    } else {
      entries.push({ rel, data: null })
    }
  }
  return entries
}

/** 按 covered/total 加权聚合求百分比；数据缺 covered/total 时回退 pct 均值 */
function aggregate(entries, metric) {
  let covered = 0
  let total = 0
  let pctSum = 0
  let pctCount = 0
  let hasCounts = true
  for (const e of entries) {
    const m = e.data[metric] ?? {}
    if (typeof m.covered === 'number' && typeof m.total === 'number' && m.total > 0) {
      covered += m.covered
      total += m.total
    } else if (typeof m.pct === 'number') {
      hasCounts = false
      pctSum += m.pct
      pctCount++
    }
  }
  if (hasCounts && total > 0) return { covered, total, pct: (covered / total) * 100 }
  if (pctCount > 0) return { pct: pctSum / pctCount }
  return { pct: NaN }
}

function fmtPct(n) {
  return `${n.toFixed(2)}%`
}

const failures = []

// ── 1. 核心集合校验 ─────────────────────────────────────

const coreEntries = collectCoreEntries()
const missing = coreEntries.filter((e) => e.data === null)
if (missing.length > 0) {
  failures.push({
    scope: '核心集合',
    metric: '文件存在性',
    threshold: '全部在覆盖率报告中出现',
    actual: missing.map((m) => m.rel).join(', '),
    detail: '以下核心模块未出现在覆盖率报告中（文件不存在或未被 include 匹配）',
  })
}

const present = coreEntries.filter((e) => e.data !== null)
const coreLines = aggregate(present, 'lines')
const coreBranches = aggregate(present, 'branches')

// 数据无效（无法解析出有限百分比）视为失败，防止 NaN 静默通过
if (!Number.isFinite(coreLines.pct) || !Number.isFinite(coreBranches.pct)) {
  failures.push({
    scope: '核心集合',
    metric: '数据有效性',
    threshold: '聚合结果为有限数值',
    actual: `lines=${coreLines.pct}, branches=${coreBranches.pct}`,
    detail: 'coverage-summary.json 缺少可解析的 covered/total/pct 字段',
  })
}

if (coreLines.pct < CORE_LINES_MIN) {
  failures.push({
    scope: '核心集合',
    metric: 'lines',
    threshold: `≥ ${CORE_LINES_MIN}%`,
    actual: `${fmtPct(coreLines.pct)}（${coreLines.covered}/${coreLines.total}）`,
  })
}
if (coreBranches.pct < CORE_BRANCHES_MIN) {
  failures.push({
    scope: '核心集合',
    metric: 'branches',
    threshold: `≥ ${CORE_BRANCHES_MIN}%`,
    actual: `${fmtPct(coreBranches.pct)}（${coreBranches.covered}/${coreBranches.total}）`,
  })
}

// ── 2. 全局低水位校验 ───────────────────────────────────

const globalLines = summary.total.lines
if (globalLines.pct < GLOBAL_LINES_MIN) {
  failures.push({
    scope: '全局 src',
    metric: 'lines',
    threshold: `≥ ${GLOBAL_LINES_MIN}%`,
    actual: `${fmtPct(globalLines.pct)}（${globalLines.covered}/${globalLines.total}）`,
  })
}

// ── 输出 ─────────────────────────────────────────────────

console.log('[check-coverage] 覆盖率双门槛校验')
console.log(
  `  核心集合（${present.length}/${CORE_FILES.length} 文件聚合）: ` +
    `lines ${fmtPct(coreLines.pct)}（门槛 ${CORE_LINES_MIN}%）, ` +
    `branches ${fmtPct(coreBranches.pct)}（门槛 ${CORE_BRANCHES_MIN}%）`,
)
console.log(
  `  全局 src: lines ${fmtPct(globalLines.pct)}（水位 ${GLOBAL_LINES_MIN}%）`,
)

if (failures.length > 0) {
  console.error('\n[check-coverage] 未达标项明细:')
  for (const f of failures) {
    console.error(`  ✗ [${f.scope}] ${f.metric}: 阈值 ${f.threshold}, 实际 ${f.actual}`)
    if (f.detail) console.error(`    ${f.detail}`)
  }
  // 按模块列出差距，便于定位
  console.error('\n[check-coverage] 核心集合单文件明细（低于阈值的项）:')
  for (const e of present) {
    const l = e.data.lines.pct
    const b = e.data.branches.pct
    if (l < CORE_LINES_MIN || b < CORE_BRANCHES_MIN) {
      console.error(
        `  ✗ ${e.rel}: lines ${fmtPct(l)} / branches ${fmtPct(b)}`,
      )
    }
  }
  process.exit(1)
}

console.log('[check-coverage] 全部达标')
