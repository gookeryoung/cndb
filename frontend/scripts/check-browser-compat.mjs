#!/usr/bin/env node
/**
 * check-browser-compat.mjs — Chromium 81 兼容静态门禁（ADR 0026 D7）.
 *
 * 每次 `pnpm build` 之后执行，用退出码判定兼容缺口，不依赖人工记忆：
 *  1. 基线常量与 .browserslistrc 必须一致且为 chrome81；
 *  2. 产物 CSS 不得保留 Chrome 81 不支持的写法（:where / :focus-visible /
 *     逻辑属性 / inset），这些会被整条丢弃或忽略；
 *  3. 源码不得新增 :focus-visible；color-mix 必须有 --cn-mix-* 兜底。
 *
 * `--strict`：把 color-mix 兜底缺口从 warn 升级为 error。P1 完成兜底后，
 * build 切到 strict，避免「先合入、忘了补」的长期欠账。
 *
 * 另校验两类跨文件的单一真相源：
 *  - 老内核冒烟的 10 套主题列表必须与 src/theme/meta.ts 的 THEME_MODES 一致；
 *  - 导出路径必须保留 Intl.Segmenter 按需垫片（html2canvas-pro 无条件构造它）。
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { BROWSER_BASELINE, BROWSERLIST_ENTRIES } from './browser-baseline.mjs'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..')
const distDir = path.join(root, 'dist')
const assetsDir = path.join(distDir, 'assets')
const strict = process.argv.includes('--strict')

const errors = []
const warnings = []
const fail = (msg) => errors.push(msg)
const warn = (msg) => warnings.push(msg)

// ── 1. 基线常量与 .browserslistrc ────────────────────────────────────
if (BROWSER_BASELINE !== 'chrome81') {
  fail(`BROWSER_BASELINE 被改为 ${BROWSER_BASELINE}；改基线必须先改 ADR 0026 并重新评估兼容层`)
}

const browserslistPath = path.join(root, '.browserslistrc')
if (!existsSync(browserslistPath)) {
  fail('.browserslistrc 不存在')
} else {
  const entries = readFileSync(browserslistPath, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
  for (const expected of BROWSERLIST_ENTRIES) {
    if (!entries.includes(expected)) fail(`.browserslistrc 缺少基线项「${expected}」`)
  }
}

// ── 2. 产物 CSS ──────────────────────────────────────────────────────
const FORBIDDEN_IN_CSS = [
  { re: /:where\(/g, label: ':where()（Chrome 88+，整条选择器会被丢弃）' },
  { re: /:focus-visible/g, label: ':focus-visible（Chrome 86+）' },
  {
    re: /(?<![\w-])(?:padding|margin|border)-(?:inline|block)(?:-(?:start|end|width|style|color))?\s*:/g,
    label: '逻辑属性（Chrome 87+）',
  },
  {
    re: /(?<![\w-])(?:min-|max-)?(?:inline|block)-size\s*:/g,
    label: '逻辑尺寸属性（Chrome 87+）',
  },
  { re: /(?<![\w-])inset\s*:/g, label: 'inset 简写（Chrome 87+）' },
]

if (!existsSync(path.join(distDir, 'index.html'))) {
  fail('未找到 dist/index.html，请先执行 pnpm build')
} else {
  const cssFiles = existsSync(assetsDir)
    ? readdirSync(assetsDir).filter((name) => name.endsWith('.css'))
    : []
  if (cssFiles.length === 0) fail('dist/assets 下没有 CSS 产物，构建是否完整？')

  for (const file of cssFiles) {
    const css = readFileSync(path.join(assetsDir, file), 'utf8')
    for (const { re, label } of FORBIDDEN_IN_CSS) {
      const hits = css.match(re)
      if (hits) fail(`dist/assets/${file} 仍含 ${label}：${hits.length} 处`)
    }
  }
}

// ── 3. 源码检查 ──────────────────────────────────────────────────────
const SRC_DIR = path.join(root, 'src')
const SOURCE_EXTS = new Set(['.css', '.ts', '.tsx'])
const SKIP_DIRS = new Set(['node_modules', 'test', '__tests__'])

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || SKIP_DIRS.has(entry.name)) continue
    if (/\.test\.(?:ts|tsx|js|jsx)$/.test(entry.name)) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) yield* walk(full)
    else if (SOURCE_EXTS.has(path.extname(entry.name))) yield full
  }
}

let colorMixTotal = 0
let colorMixFallback = 0
let tsxColorMix = 0

for (const file of walk(SRC_DIR)) {
  const rel = path.relative(root, file).replace(/\\/g, '/')
  const text = readFileSync(file, 'utf8')
  // 注释里提到 color-mix() / :focus-visible 不算实际用法
  const source = text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/[^\n]*/gm, '$1')

  if (source.includes(':focus-visible')) {
    fail(`${rel} 含 :focus-visible：Chrome 81 选择器无效，请改 :focus（ADR 0026 D6）`)
  }

  const colorMixCount = (source.match(/color-mix\(/g) ?? []).length
  if (colorMixCount === 0) continue

  if (rel === 'src/theme/themeMix.ts') {
    // 注册表本身允许出现 color-mix 表达式
    continue
  }
  if (rel.endsWith('.css')) {
    colorMixTotal += colorMixCount
    colorMixFallback += (source.match(/var\(--cn-mix-[^)]*\)/g) ?? []).length
  } else {
    tsxColorMix += colorMixCount
  }
}

if (colorMixFallback < colorMixTotal) {
  const message =
    `src/index.css: ${colorMixTotal} 处 color-mix 中仅 ${colorMixFallback} 处有 --cn-mix-* 兜底` +
    '（Chrome 81 会丢弃这些声明）'
  if (strict) fail(message)
  else warn(message)
}
if (tsxColorMix > 0) {
  const message =
    `src/**/*.tsx: ${tsxColorMix} 处直接使用 color-mix（应改为 var(--cn-mix-*) 或 mixColor()）`
  if (strict) fail(message)
  else warn(message)
}

// ── 4. 主题列表与导出垫片（单一真相源）───────────────────────────────
const metaPath = path.join(SRC_DIR, 'theme', 'meta.ts')
const smokePath = path.join(scriptDir, 'chrome81-smoke.mjs')
const exportPdfPath = path.join(SRC_DIR, 'pages', 'import-export', 'ImportExportDialog', 'exportPdf.ts')

function readThemes(text) {
  const block = /THEME_MODES\s*=\s*\[([\s\S]*?)\]/.exec(text)
  if (!block) return []
  return [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
}

if (!existsSync(metaPath)) {
  fail('src/theme/meta.ts 不存在，无法校验主题列表')
} else if (!existsSync(smokePath)) {
  fail('scripts/chrome81-smoke.mjs 不存在，老内核冒烟缺失（ADR 0026 C5）')
} else {
  const expected = readThemes(readFileSync(metaPath, 'utf8'))
  const actual = readThemes(readFileSync(smokePath, 'utf8'))
  if (expected.length !== actual.length || expected.some((id, i) => id !== actual[i])) {
    fail(`chrome81-smoke.mjs 的主题列表与 src/theme/meta.ts 不一致：[${actual.join(', ')}] ≠ [${expected.join(', ')}]`)
  }
}

if (!existsSync(exportPdfPath)) {
  fail('exportPdf.ts 不存在')
} else {
  const exportPdf = readFileSync(exportPdfPath, 'utf8')
  if (!exportPdf.includes('ensureIntlSegmenter')
    || !exportPdf.includes('@formatjs/intl-segmenter/polyfill.js')
    || !exportPdf.includes('await ensureIntlSegmenter()')) {
    fail('exportPdf.ts 缺失 Intl.Segmenter 按需垫片：Chromium 81 上 html2canvas-pro 会直接抛错（ADR 0026 D3）')
  }
}

// ── 输出 ─────────────────────────────────────────────────────────────
for (const item of errors) console.error(`[compat] error: ${item}`)
for (const item of warnings) console.warn(`[compat] warn:  ${item}`)

if (errors.length) {
  console.error(`[compat] ${errors.length} error，${warnings.length} warning（基线 ${BROWSER_BASELINE}）`)
  process.exit(1)
}
console.log(`[compat] Chromium 81 静态兼容检查通过（${warnings.length} warning）`)
