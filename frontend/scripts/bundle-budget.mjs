/** bundle-budget.mjs — 关键 chunk gzip 体积门禁.
 *
 * 背景：分包瘦身确立了首屏体积基线。依赖升级失控、把重型库或「按需打开的面板」
 * 静态链入关键 chunk 这类回归很难在 review 中察觉，本脚本在构建后以
 * 「基线 + tolerancePct% 容差」硬校验关键 chunk 的实际传输体积（gzip 字节）。
 *
 * 用法：
 *   pnpm build && pnpm bundle:budget                       # 校验，超限 exit 1
 *   node scripts/bundle-budget.mjs                         # 同上
 *   node scripts/bundle-budget.mjs --update --reason "…"    # 调整基线（必须写理由）
 *   node scripts/bundle-budget.mjs --update --only GridPage --reason "…"
 *
 * 设计约定：
 *  1. 基线外置在 scripts/bundle-budget.json，**只能**通过 --update 修改，
 *     且必须带 --reason（理由落盘：reason/updatedAt/commit），
 *     避免「体积涨了就随手改个数字」把门禁变成橡皮图章。
 *  2. 超限时不只报数字：附带该 chunk 内 Top-N 源文件归属（读构建期产出的
 *     dist/.vite/chunk-modules.json），并给出处置顺序（先 lazy，再谈加基线）。
 *  3. 介于基线与上限之间（已涨但未超）标记 warn 并在输出末尾汇总，
 *     让「慢涨」提前一两次提交可见，而不是攒到超限一次性爆炸。
 */
import { gzipSync } from 'node:zlib'
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..')
const distDir = path.join(root, 'dist')
const assetsDir = path.join(distDir, 'assets')
const configPath = path.join(scriptDir, 'bundle-budget.json')
const attributionPath = path.join(distDir, '.vite', 'chunk-modules.json')

// ── 参数 ────────────────────────────────────────────────────────────
const argv = process.argv.slice(2)
const argValue = (flag) => {
  const i = argv.indexOf(flag)
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : null
}
const hasFlag = (flag) => argv.includes(flag)
const doUpdate = hasFlag('--update')
const only = argValue('--only')
const reason = argValue('--reason')
/** 显式指定新基线（字节）。用于「清理后想留合理余量」的场景：
 *  默认 --update 会把基线压到实测值，没有这个参数就只能手改 JSON 才能留余量。 */
const explicitBytes = argValue('--bytes')
if (explicitBytes != null && (!/^\d+$/.test(explicitBytes) || Number(explicitBytes) <= 0)) {
  console.error(`[bundle-budget] --bytes 必须是正整数（收到 ${explicitBytes}）`)
  process.exit(1)
}

const fail = (msg) => {
  console.error(`[bundle-budget] ${msg}`)
  process.exit(1)
}

if (doUpdate && !reason) {
  fail('调整基线必须说明原因：--reason "feat/fix 描述 + 为什么必须增长"。这是留给 review 的证据。')
}

// ── 环境自检：build 产物缺失要给「怎么修」而不是堆栈 ──────────────────
if (!existsSync(path.join(distDir, 'index.html'))) {
  fail('未找到 dist/index.html，请先执行 pnpm build')
}
if (!existsSync(configPath)) fail(`缺少基线配置 ${path.relative(root, configPath)}`)

const config = JSON.parse(readFileSync(configPath, 'utf8'))
const globalTolerance = (config.tolerancePct ?? 5) / 100
const indexHtml = readFileSync(path.join(distDir, 'index.html'), 'utf8')

const assets = existsSync(assetsDir) ? readdirSync(assetsDir) : []

function resolveFile(spec, name) {
  if (spec === 'entry') {
    const m = indexHtml.match(/src="\/assets\/([^"]+\.js)"/)
    if (!m) fail(`${name}：dist/index.html 未找到主入口 script`)
    return m[1]
  }
  if (spec && typeof spec === 'object' && spec.assetPattern) {
    const re = new RegExp(spec.assetPattern)
    const hit = assets.find((f) => re.test(f))
    if (!hit) fail(`${name}：dist/assets 内未匹配到 ${spec.assetPattern} 的 chunk（是否为重命名/拆分导致该 chunk 消失？）`)
    return hit
  }
  fail(`${name}：resolve 字段无法识别（应为 "entry" 或 { assetPattern }）`)
}

/** gzip 字节数，与生产服务器 Content-Encoding: gzip 的实际传输体积一致 */
const gzipSize = (file) => gzipSync(readFileSync(path.join(assetsDir, file))).length
const formatKB = (bytes) => `${(bytes / 1024).toFixed(2)} KiB`
const today = () => new Date().toISOString().slice(0, 10)
const shortHead = () => {
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

// ── 超限归因：把「哪个源文件让包变大了」打印出来 ──────────────────────
function printAttribution(file, limitTopN = 10) {
  if (!existsSync(attributionPath)) {
    console.log('  （无 dist/.vite/chunk-modules.json，无法归因；请重新执行 pnpm build 生成）')
    return
  }
  const table = JSON.parse(readFileSync(attributionPath, 'utf8'))
  const modules = table[`assets/${file}`]
  if (!modules?.length) {
    console.log(`  （chunk-modules.json 中没有 ${file} 的记录，请重新执行 pnpm build）`)
    return
  }
  const mappedTotal = modules.reduce((sum, m) => sum + m.bytes, 0)
  const shorten = (id) => {
    const rel = path.relative(root, id).replace(/\\/g, '/')
    const nm = rel.lastIndexOf('node_modules/')
    return nm >= 0 ? `node_modules/${rel.slice(nm + 'node_modules/'.length)}` : rel || id
  }
  const top = [...modules].sort((a, b) => b.bytes - a.bytes).slice(0, limitTopN)
  console.log(`\n  ${file} 内体积最大的源文件（压缩前源码字节，分母为该 chunk 源码合计 ${(mappedTotal / 1024).toFixed(1)} KB）：`)
  for (const [i, m] of top.entries()) {
    const pct = mappedTotal ? ((m.bytes / mappedTotal) * 100).toFixed(1) : '0.0'
    console.log(`   ${String(i + 1).padStart(2)}. ${(m.bytes / 1024).toFixed(1).padStart(7)} KB  ${pct.padStart(5)}%  ${shorten(m.id)}`)
  }
}

// ── 主流程 ───────────────────────────────────────────────────────────
const results = []
for (const item of config.chunks) {
  if (only && !item.name.includes(only)) continue
  const file = resolveFile(item.resolve, item.name)
  const actual = gzipSize(file)
  const tolerance = item.tolerance != null ? item.tolerance / 100 : globalTolerance
  const limit = Math.ceil(item.baseline * (1 + tolerance))
  const delta = actual - item.baseline
  results.push({ item, file, actual, limit, delta })
}

const overs = results.filter((r) => r.actual > r.limit)
const warns = results.filter((r) => r.actual <= r.limit && r.delta > 0)

if (doUpdate) {
  const head = shortHead()
  const stamp = today()
  const target = explicitBytes != null ? Number(explicitBytes) : null
  for (const r of results) {
    const before = r.item.baseline
    r.item.baseline = target ?? r.actual
    r.item.reason = reason.trim()
    r.item.updatedAt = today()
    r.item.commit = head
    const pct = before ? ((r.actual - before) / before) * 100 : 0
    const tag = Math.abs(pct) < 0.05 ? '持平' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
    console.log(`[bundle-budget] 更新基线 ${r.item.name}: ${before} → ${r.item.baseline}（${tag}）`)
    if (pct > 10) {
      console.warn(
        `[bundle-budget] ⚠ ${r.item.name} 单次上调 ${pct.toFixed(1)}%（>10%）：请先确认没有可用 React.lazy 拆出的按需代码，` +
        ' 并在 PR 说明中解释该增量的必要性。',
      )
    }
  }
  // history 自动追加并截断，保留最近 20 条演化记录
  config.history = [...(config.history || []), `${stamp} ${reason.trim()}`].slice(-20)
  writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`)
  console.log(`[bundle-budget] 已写入 ${path.relative(root, configPath)}（reason: ${reason.trim()}）`)
  process.exit(0)
}

for (const r of results) {
  const { item, file, actual, limit, delta } = r
  const status = actual > limit ? 'FAIL' : delta > 0 ? 'warn' : 'ok'
  const deltaPct = ((delta / item.baseline) * 100).toFixed(1)
  const deltaTxt = `${delta >= 0 ? '+' : '-'}${formatKB(Math.abs(delta))} / ${deltaPct >= 0 ? '+' : '-'}${Math.abs(Number(deltaPct)).toFixed(1)}%`
  console.log(
    `[bundle-budget] ${status.padEnd(4)} ${item.name}: ${formatKB(actual)}` +
    `（基线 ${formatKB(item.baseline)}，上限 ${formatKB(limit)}，偏差 ${deltaTxt}）  ${file}`,
  )
}

if (warns.length) {
  console.log(
    `\n[bundle-budget] 注意：${warns.map((w) => w.item.name).join('、')} 已超过基线但在容差内。` +
    ' 这是「慢涨」信号，别等到超限才处理。',
  )
}

if (overs.length) {
  for (const o of overs) {
    console.log(
      `\n[bundle-budget] ── ${o.item.name} 超限 ${formatKB(o.actual - o.limit)}（当前 ${formatKB(o.actual)}，上限 ${formatKB(o.limit)}）`,
    )
    printAttribution(o.file)
  }
  console.log(
    '\n[bundle-budget] 处置顺序（跳过第 1 步直接加基线是本工具要防的行为）：\n' +
    '  1) 先看上面的归属列表：体积是否来自「点了才出现」的 UI（Dialog/Modal/Drawer/Manager）？\n' +
    '     是 → 改成 React.lazy + Suspense（GridPage 里 FieldManager / GovernanceDialog /\n' +
    '          ViewConfigDialog 都是这个套路），通常能直接消除增量甚至净减。\n' +
    '     否 → 检查是否误把重型依赖静态 import 进了该 chunk\n' +
    '          （echarts / jspdf / html2canvas-pro / 日期库等必须走 lazy）。\n' +
    '  2) 确认增长不可避免后，再记录基线：\n' +
    `     node scripts/bundle-budget.mjs --update --reason "feat: xxx，为何必须随该 chunk 加载"\n` +
    '     理由会写进 bundle-budget.json 一并提交，供 review 追溯。',
  )
  fail('有关键 chunk 超过体积上限')
}

console.log('[bundle-budget] 全部关键 chunk 在体积预算内')
