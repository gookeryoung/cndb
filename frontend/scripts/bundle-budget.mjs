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
 *  1b. FAIL 判据是 chunk 的显式 `budget`（gzip 字节硬上限）——基线只是 warn 参照，
 *     --update 不会重置上限；上调上限必须走 `--set-budget --only <名> --reason`。
 *     小步增量只 warn 不 FAIL，「一劳永逸」与防膨胀并存（需求卡片 0090）。
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
/** 显式设置 chunk 的 budget（gzip 字节硬上限）。0090 起基线与上限分离：
 *  baseline 只是 warn 参照，FAIL 判据是 actual > budget；调整上限必须显式走这里。 */
const setBudget = argValue('--set-budget')
if (setBudget != null && (!/^\d+$/.test(setBudget) || Number(setBudget) <= 0)) {
  console.error(`[bundle-budget] --set-budget 必须是正整数（收到 ${setBudget}）`)
  process.exit(1)
}

const fail = (msg) => {
  console.error(`[bundle-budget] ${msg}`)
  process.exit(1)
}

if (setBudget != null && !only) {
  fail('--set-budget 必须配合 --only <chunk 名> 使用，防止误改多个 chunk 的上限')
}

if ((doUpdate || setBudget != null) && !reason) {
  fail('调整基线 / 上限必须说明原因：--reason "feat/fix 描述 + 为什么必须增长"。这是留给 review 的证据。')
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

/** 模块归属表（build 期 chunk-attribution 插件产出，见 vite.config.ts） */
function readChunkModules() {
  if (!existsSync(attributionPath)) {
    fail('未找到 dist/.vite/chunk-modules.json，请先执行 pnpm build（本文件由 chunk-attribution 插件生成）')
  }
  return JSON.parse(readFileSync(attributionPath, 'utf8'))
}

/** 把 resolve 声明解析为一组待测文件（多文件时体积求和，如 CSS / 字体总量）。
 *
 * 支持：
 *  - "entry"                 主入口 script（dist/index.html）
 *  - "entryCss"              主入口 <link rel=stylesheet> 的 CSS
 *  - "fonts"                 首屏入口 CSS 引用的 woff2（懒加载 chunk 的字体不计入首屏）
 *  - { assetPattern }        文件名正则
 *  - { moduleMarker }        模块路径子串（按 chunk-modules.json 归属定位，避免 hash 改名失效）
 */
function resolveFiles(spec, name) {
  if (spec === 'entry') {
    const m = indexHtml.match(/src="\/assets\/([^"]+\.js)"/)
    if (!m) fail(`${name}：dist/index.html 未找到主入口 script`)
    return [m[1]]
  }
  if (spec === 'entryCss') {
    const links = [...indexHtml.matchAll(/href="\/assets\/([^"]+\.css)"/g)].map((m) => m[1])
    const hits = links.filter((f) => assets.includes(f))
    if (!hits.length) fail(`${name}：dist/index.html 未找到主入口样式表`)
    return hits
  }
  if (spec === 'fonts') {
    // 只统计「首屏入口 CSS」真正引用的字体；设置面板 / 编辑器 chunk 里按需加载的字体
    // 不应算进首屏预算（否则每加一套编辑器字体都会误判为首屏体积膨胀）。
    const cssLinks = [...indexHtml.matchAll(/href="\/assets\/([^"]+\.css)"/g)].map((m) => m[1])
    const referenced = new Set()
    for (const css of cssLinks) {
      if (!assets.includes(css)) continue
      const text = readFileSync(path.join(assetsDir, css), 'utf8')
      for (const m of text.matchAll(/url\((?:\.\/)?([^)"']+\.woff2)\)/g)) {
        referenced.add(path.basename(m[1]))
      }
    }
    const hits = [...referenced].filter((f) => assets.includes(f))
    if (!hits.length) fail(`${name}：首屏入口 CSS 内未找到 woff2 字体（构建是否启用了 @fontsource？）`)
    return hits
  }
  if (spec && typeof spec === 'object' && spec.assetPattern) {
    const re = new RegExp(spec.assetPattern)
    const hit = assets.find((f) => re.test(f))
    if (!hit) fail(`${name}：dist/assets 内未匹配到 ${spec.assetPattern} 的 chunk（是否为重命名/拆分导致该 chunk 消失？）`)
    return [hit]
  }
  if (spec && typeof spec === 'object' && spec.moduleMarker) {
    const table = readChunkModules()
    const marker = String(spec.moduleMarker).replace(/\\/g, '/')
    const hits = Object.entries(table)
      .filter(([file]) => file.endsWith('.js') && assets.includes(file.replace(/^assets\//, '')))
      .filter(([, modules]) => modules.some((m) => String(m.id).replace(/\\/g, '/').includes(marker)))
      .map(([file]) => file.replace(/^assets\//, ''))
    if (!hits.length) fail(`${name}：没有 chunk 包含模块 ${spec.moduleMarker}（模块是否被改名/移出包？）`)
    return hits
  }
  fail(`${name}：resolve 字段无法识别（应为 "entry" / "entryCss" / "fonts" / { assetPattern } / { moduleMarker }）`)
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
  const files = resolveFiles(item.resolve, item.name)
  const actual = files.reduce((sum, file) => sum + gzipSize(file), 0)
  const tolerance = item.tolerance != null ? item.tolerance / 100 : globalTolerance
  // 0090 C3：上限优先取显式 budget；未声明时回退旧的「基线 + 容差」口径
  const limit = item.budget ?? Math.ceil(item.baseline * (1 + tolerance))
  const delta = actual - item.baseline
  results.push({ item, files, actual, limit, delta })
}

const overs = results.filter((r) => r.actual > r.limit)
const warns = results.filter((r) => r.actual <= r.limit && r.delta > 0)

if (setBudget != null) {
  const head = shortHead()
  const stamp = today()
  const target = Number(setBudget)
  for (const r of results) {
    const before = r.item.budget ?? Math.ceil(r.item.baseline * (1 + (r.item.tolerance ?? config.tolerancePct ?? 5) / 100))
    r.item.budget = target
    r.item.reason = reason.trim()
    r.item.updatedAt = stamp
    r.item.commit = head
    console.log(`[bundle-budget] 设置上限 ${r.item.name}: ${before} → ${target}（${target >= before ? '+' : ''}${(((target - before) / before) * 100).toFixed(1)}%）`)
  }
  config.history = [...(config.history || []), `${stamp} [set-budget] ${reason.trim()}`].slice(-20)
  writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`)
  console.log(`[bundle-budget] 已写入 ${path.relative(root, configPath)}（reason: ${reason.trim()}）`)
  process.exit(0)
}

if (doUpdate) {
  const head = shortHead()
  const stamp = today()
  const target = explicitBytes != null ? Number(explicitBytes) : null
  for (const r of results) {
    const before = r.item.baseline
    r.item.baseline = target ?? r.actual
    r.item.reason = reason.trim()
    r.item.updatedAt = stamp
    r.item.commit = head
    const pct = before ? ((r.actual - before) / before) * 100 : 0
    const tag = Math.abs(pct) < 0.05 ? '持平' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
    // 0090 C4：--update 只动基线，budget 上限保持不变（上限调整走 --set-budget）
    const budgetNote = r.item.budget != null ? `，budget 上限 ${r.item.budget} 不变` : ''
    console.log(`[bundle-budget] 更新基线 ${r.item.name}: ${before} → ${r.item.baseline}（${tag}）${budgetNote}`)
    if (pct > 10) {
      console.warn(
        `[bundle-budget] ⚠ ${r.item.name} 单次上调 ${pct.toFixed(1)}%（>10%）：请先确认没有可用 React.lazy 拆出的按需代码，` +
        ' 并在 PR 说明中解释该增量的必要性。',
      )
    }
    if (r.item.budget != null && r.item.baseline > r.item.budget) {
      console.warn(
        `[bundle-budget] ⚠ ${r.item.name} 实测已超过 budget 上限 ${r.item.budget}：本次 --update 只更新了基线，` +
        '校验仍会 FAIL。确属合理增长请用 --set-budget 显式调整上限并说明理由。',
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
  const { item, files, actual, limit, delta } = r
  const status = actual > limit ? 'FAIL' : delta > 0 ? 'warn' : 'ok'
  const deltaPct = ((delta / item.baseline) * 100).toFixed(1)
  const deltaTxt = `${delta >= 0 ? '+' : '-'}${formatKB(Math.abs(delta))} / ${deltaPct >= 0 ? '+' : '-'}${Math.abs(Number(deltaPct)).toFixed(1)}%`
  const limitSrc = item.budget != null ? 'budget' : '基线+容差'
  const fileTxt = files.length > 1 ? `${files.length} 个文件` : files[0]
  console.log(
    `[bundle-budget] ${status.padEnd(4)} ${item.name}: ${formatKB(actual)}` +
    `（基线 ${formatKB(item.baseline)}，上限 ${formatKB(limit)}〔${limitSrc}〕，偏差 ${deltaTxt}）  ${fileTxt}`,
  )
}

if (warns.length) {
  console.log(
    `\n[bundle-budget] 注意：${warns.map((w) => w.item.name).join('、')} 已超过基线但在上限内。` +
    ' 这是「慢涨」信号，别等到超限才处理。',
  )
}

if (overs.length) {
  for (const o of overs) {
    console.log(
      `\n[bundle-budget] ── ${o.item.name} 超限 ${formatKB(o.actual - o.limit)}（当前 ${formatKB(o.actual)}，上限 ${formatKB(o.limit)}）`,
    )
    // 多文件条目（CSS / 字体 / 跨 chunk 模块）无法用单 chunk 归因，逐文件列体积
    if (o.files.length === 1) {
      printAttribution(o.files[0])
    } else {
      for (const file of o.files) {
        console.log(`  ${formatKB(gzipSize(file)).padStart(10)}  ${file}`)
      }
    }
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
