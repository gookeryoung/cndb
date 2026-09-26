/** bundle-budget.mjs — 关键 chunk gzip 体积门禁.
 *
 * 背景：第 1 轮分包瘦身确立了首屏体积基线（主入口 184KB gzip、GridPage 34KB gzip）。
 * 依赖升级失控、把重型库误静态链入主包等回归很难在 review 中察觉，本脚本在构建后
 * 以「基线 +5% 容差」硬校验关键 chunk 的实际传输体积（gzip 字节）。
 *
 * 用法：pnpm build && node scripts/bundle-budget.mjs
 * 超限以退出码 1 失败；需要正式调整基线时，同步更新下方 BASELINES 并在提交说明注明原因。
 */
import { gzipSync } from 'node:zlib'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(root, 'dist')
const assetsDir = path.join(distDir, 'assets')

const fail = (msg) => {
  console.error(`[bundle-budget] ${msg}`)
  process.exit(1)
}

const indexHtml = readFileSync(path.join(distDir, 'index.html'), 'utf8')
const mainMatch = indexHtml.match(/src="\/assets\/(index-[^"]+\.js)"/)
if (!mainMatch) fail('dist/index.html 未找到主入口 script，请先执行 pnpm build')

const assets = readdirSync(assetsDir)
const gridFile = assets.find((f) => /^GridPage-.*\.js$/.test(f))
if (!gridFile) fail('dist/assets 未找到 GridPage chunk，请先执行 pnpm build')

/** gzip 字节数，与生产服务器 Content-Encoding: gzip 的实际传输体积一致 */
const gzipSize = (file) => gzipSync(readFileSync(path.join(assetsDir, file))).length
const formatKB = (bytes) => `${(bytes / 1024).toFixed(2)} KiB`

const TOLERANCE = 1.05

/** 关键 chunk 基线（gzip bytes，2025-07-01 分包瘦身 + 运行时优化后实测） */
const BASELINES = [
  { name: '主入口 index', file: mainMatch[1], baseline: 185_324 },
  // 2026-09-26：排序三态、列宽估算/拖宽、列序 DnD 及重置入口三项功能提交（b05350d/95a638e/b3c7f5c）使 GridPage 增长约 2.5KB gzip
  { name: 'GridPage（表页闭包）', file: gridFile, baseline: 36_946 },
]

let over = false
for (const item of BASELINES) {
  const actual = gzipSize(item.file)
  const limit = Math.ceil(item.baseline * TOLERANCE)
  const deltaPct = (((actual - item.baseline) / item.baseline) * 100).toFixed(1)
  const status = actual > limit ? 'FAIL' : 'ok'
  if (actual > limit) over = true
  console.log(
    `[bundle-budget] ${status.padEnd(4)} ${item.name}: ${formatKB(actual)}（基线 ${formatKB(item.baseline)}，上限 ${formatKB(limit)}，偏差 ${deltaPct}%）`,
  )
}

if (over) {
  fail('有关键 chunk 超过体积上限。若为合理增长，请更新 scripts/bundle-budget.mjs 的 BASELINES 并说明原因')
}
console.log('[bundle-budget] 全部关键 chunk 在体积预算内')
