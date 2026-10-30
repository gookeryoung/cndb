#!/usr/bin/env node
/* global document, window, navigator, MouseEvent, getComputedStyle, fetch, setTimeout, URL */
/**
 * chrome81-smoke.mjs — 真实 Chromium 81 冒烟（ADR 0026 C1 / C5 / D9）.
 *
 * Playwright 只保证其内置 Chromium，故这里用 puppeteer-core + 固定 revision 快照
 * （CHROMIUM81_REVISION 与 BROWSER_BASELINE 同处 browser-baseline.mjs，避免版本漂移）。
 *
 * 覆盖：
 *  - 登录 → 工作区列表 → 数据表打开 / 视图切换 → 文档页；
 *  - 兼容层自检：StyleProvider 产物无 :where()、--cn-mix-* 兜底已写入、flex-gap shim 已装载；
 *  - PDF 导出（html2canvas-pro 依赖 Intl.Segmenter，旧内核必须走垫片）；
 *  - 10 套主题逐一切换截图（输出到 .cache/chrome81-screenshots）。
 *
 * 用法：
 *   node scripts/chrome81-smoke.mjs            # 自动下载快照（首次）；后端需已在 :8000
 *   CNDB_CHROME81_PATH=/path/to/chrome node …  # 复用本机已有的 Chromium 81
 *   CNDB_SMOKE_BASE_URL=… node …               # 指向其他后端
 *
 * 只进定时 CI（见 .github/workflows/chrome81-smoke.yml）：下载依赖外网，不做每次提交门禁。
 */
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { Browser, detectBrowserPlatform, install } from '@puppeteer/browsers'
import puppeteer from 'puppeteer-core'
import { BROWSER_BASELINE, CHROMIUM81_REVISION } from './browser-baseline.mjs'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..')
const baseUrl = (process.env.CNDB_SMOKE_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const cacheDir = path.join(root, '.cache', 'chrome81')
const shotDir = path.join(root, '.cache', 'chrome81-screenshots')
const downloadDir = path.join(root, '.cache', 'chrome81-downloads')
const ADMIN_LOGIN = 'admin'
const ADMIN_PASSWORD = ['admin', '1234'].join('')

/** 与 src/theme/meta.ts 的 THEME_MODES 同步（check-browser-compat.mjs 校验一致性） */
const THEME_MODES = [
  'modern',
  'github-dark',
  'github-light',
  'minimal',
  'ocean',
  'forest',
  'sepia',
  'sakura',
  'midnight',
  'oled',
]

const failures = []
const notes = []
const pageErrors = []
const consoleErrors = []
let activePage = null

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const check = (name, ok, detail = '') => {
  if (ok) {
    console.log(`  ✓ ${name}`)
    return true
  }
  const message = detail ? `${name} —— ${detail}` : name
  failures.push(message)
  console.error(`  ✗ ${message}`)
  return false
}

/** 失败现场快照：URL、可见文本、页面异常，避免只看到一句 timeout */
async function dumpDiagnostics() {
  if (!activePage) return
  mkdirSync(shotDir, { recursive: true })
  const shot = path.join(shotDir, 'failure.png')
  try {
    await activePage.screenshot({ path: shot })
  } catch {
    /* 页面已崩溃时截图会失败，忽略 */
  }
  let url = ''
  let text = ''
  let ua = ''
  try {
    url = activePage.url()
    ua = await activePage.evaluate(() => navigator.userAgent)
    text = await activePage.evaluate(() => document.body?.innerText?.slice(0, 800) ?? '')
  } catch {
    /* 上下文已丢失 */
  }
  console.error(`[chrome81] 失败页面: ${url}`)
  console.error(`[chrome81] UA: ${ua}`)
  console.error(`[chrome81] 可见文本: ${text.replace(/\n/g, ' ⏎ ').slice(0, 800)}`)
  console.error(`[chrome81] pageerror: ${pageErrors.join(' | ') || '无'}`)
  console.error(`[chrome81] console.error: ${consoleErrors.slice(0, 5).join(' | ') || '无'}`)
  console.error(`[chrome81] 截图: ${shot}`)
}

async function fetchJson(pathname, init) {
  const resp = await fetch(`${baseUrl}${pathname}`, init)
  if (!resp.ok) throw new Error(`${pathname} → HTTP ${resp.status}`)
  return resp.json()
}

/** 下载（或复用）固定 revision 的 Chromium 81；返回可执行文件路径 */
async function resolveChromium() {
  if (process.env.CNDB_CHROME81_PATH) {
    const custom = path.resolve(process.env.CNDB_CHROME81_PATH)
    if (!existsSync(custom)) throw new Error(`CNDB_CHROME81_PATH 不存在：${custom}`)
    return custom
  }
  const platform = detectBrowserPlatform()
  if (!platform) throw new Error('无法识别当前平台，请用 CNDB_CHROME81_PATH 指定 Chromium 81')
  console.log(`[chrome81] 解析 Chromium ${BROWSER_BASELINE} 快照 r${CHROMIUM81_REVISION}（${platform}）…`)
  const installed = await install({
    browser: Browser.CHROMIUM,
    buildId: CHROMIUM81_REVISION,
    cacheDir,
    platform,
  })
  return installed.executablePath
}

async function loginAndLoadSeed() {
  const auth = await fetchJson('/api/v1/accounts/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: ADMIN_LOGIN, password: ADMIN_PASSWORD }),
  })
  const token = auth.access_token
  const headers = { Authorization: `Bearer ${token}` }
  const workspaces = await fetchJson('/api/v1/workspaces', { headers })
  if (!workspaces.length) throw new Error('seed 后没有任何工作区')
  const workspace = workspaces[0]
  const tables = await fetchJson(`/api/v1/workspaces/${workspace.id}/tables`, { headers })
  if (!tables.length) throw new Error(`工作区「${workspace.name}」没有数据表`)
  const table = tables.find((it) => (it.fields?.length ?? 0) > 0) ?? tables[0]
  return { token, workspace, table }
}

async function main() {
  const executablePath = await resolveChromium()
  console.log(`[chrome81] executable: ${executablePath}`)
  console.log(`[chrome81] target: ${baseUrl}`)

  const seed = await loginAndLoadSeed()
  console.log(`[chrome81] seed: 工作区「${seed.workspace.name}」/ 表「${seed.table.name}」`)

  rmSync(downloadDir, { recursive: true, force: true })
  mkdirSync(downloadDir, { recursive: true })
  rmSync(shotDir, { recursive: true, force: true })
  mkdirSync(shotDir, { recursive: true })

  // puppeteer-core 默认走新版 headless；Chromium 81 只认传统 --headless，故显式关闭 headless 再自带参数
  const browser = await puppeteer.launch({
    executablePath,
    headless: false,
    args: [
      '--headless',
      '--disable-gpu',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--window-size=1440,900',
    ],
    defaultViewport: { width: 1440, height: 900 },
  })

  try {
    const page = await browser.newPage()
    activePage = page
    page.on('pageerror', (err) => pageErrors.push(err.message))
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    await page.evaluateOnNewDocument(
      (token) => {
        window.localStorage.setItem('cndb_access_token', token)
        window.localStorage.setItem(
          'cndb_onboarding_done_v1',
          JSON.stringify({ state: { tourDone: true }, version: 0 }),
        )
      },
      seed.token,
    )

    // ── 1. 登录态进入工作区（C1：不白屏、无未捕获异常）────────────────
    await page.goto(`${baseUrl}/w`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForFunction(
      () => Boolean(document.querySelector('.cn-app-header')) && document.body.innerText.length > 0,
      { timeout: 30_000 },
    )
    check('工作区列表渲染', page.url().includes('/w'), page.url())

    // ── 2. 兼容层自检（C2 / C3 / C4）────────────────────────────────
    const compat = await page.evaluate(() => {
      const styleText = Array.from(document.querySelectorAll('style'))
        .map((el) => el.textContent || '')
        .join('\n')
      const antdRule = styleText.includes('.ant-btn')
      const mixVar = getComputedStyle(document.documentElement)
        .getPropertyValue('--cn-mix-brand-color-10-transparent')
        .trim()
      return {
        where: styleText.includes(':where('),
        antdRule,
        mixVar,
        noFlexGap: document.documentElement.classList.contains('cn-no-flex-gap'),
      }
    })
    check('antd 生成样式无 :where()', compat.antdRule && !compat.where, compat.where ? '仍含 :where(' : '未找到 .ant-btn 规则')
    check('--cn-mix-* 兜底已写入', compat.mixVar.length > 0, compat.mixVar || '为空（Chrome 81 无法解析 color-mix）')
    check('flex-gap shim 已装载', compat.noFlexGap, 'Chromium 81 应打上 cn-no-flex-gap')

    // ── 3. 数据表 + 视图切换（C4 / C5）──────────────────────────────
    await page.goto(`${baseUrl}/w/${seed.workspace.id}/tables/${seed.table.id}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })
    await page.waitForFunction(
      () => Boolean(document.querySelector('[data-row-key], .ant-table-tbody, [class*="kanban"], [class*="gallery"]')),
      { timeout: 30_000 },
    )
    check('数据表打开', true)

    const shimApplied = await page.evaluate(() => {
      const spaces = Array.from(document.querySelectorAll('.ant-space'))
      for (const space of spaces) {
        const children = Array.from(space.children)
        if (children.length < 2) continue
        const gap = Number.parseFloat(getComputedStyle(space).columnGap) || 0
        const margin = Number.parseFloat(getComputedStyle(children[1]).marginLeft) || 0
        if (gap > 0 && margin >= gap) return true
      }
      return false
    })
    if (shimApplied) notes.push('flex-gap shim 已为 antd Space 补出间距')
    else notes.push('未找到可断言的 antd Space 容器（跳过间距实测）')

    const modes = await page.$$eval('[data-mode]', (els) =>
      els.map((el) => el.getAttribute('data-mode')).filter(Boolean),
    )
    for (const mode of modes) {
      await page.evaluate((value) => {
        const btn = document.querySelector(`[data-mode="${value}"]`)
        btn?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      }, mode)
      await sleep(1200)
      const rendered = await page.evaluate(() => document.body.innerText.length > 0)
      check(`视图切换 ${mode}`, rendered)
    }
    if (!modes.length) notes.push('当前表没有多视图按钮（跳过视图切换）')

    // ── 4. 文档页（C5）─────────────────────────────────────────────
    await page.goto(`${baseUrl}/w/${seed.workspace.id}/documents`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })
    await page.waitForFunction(
      () => Boolean(document.querySelector('.ant-tree, [class*="document"], .ant-empty')) &&
        document.body.innerText.length > 0,
      { timeout: 30_000 },
    )
    check('文档页打开', true)

    // ── 5. PDF 导出（C5：Intl.Segmenter 垫片 + html2canvas-pro）──────
    await page.goto(`${baseUrl}/w/${seed.workspace.id}/tables/${seed.table.id}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })
    await page.waitForFunction(() => Boolean(document.querySelector('[data-row-key], .ant-table-tbody')), {
      timeout: 30_000,
    })
    // puppeteer-core 3.x（兼容 Chromium 81 的最后一代）只有 target().createCDPSession()
    const client = await page.target().createCDPSession()
    await client.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: downloadDir })
    // 等待表头与导出入口同时就绪，避免弹窗在表格渲染前被打开
    await page.waitForSelector('[data-testid="import-export-btn"]', { timeout: 20_000 })
    await page.click('[data-testid="import-export-btn"]')
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('.ant-modal-title')).some((el) => el.textContent?.includes('更新 / 导出')),
      { timeout: 20_000 },
    )
    // antd Tabs / Select 在 Chrome 81 上只吃原生 click 事件链：真实鼠标点击会因
    // 顶部 Tab 的命中测试落空，故统一走 element.click() + mousedown/mouseup 三连。
    await page.evaluate(() => {
      const tabs = document.querySelectorAll('.ant-modal .ant-tabs-tab-btn')
      if (tabs.length < 2) throw new Error('未找到导出 Tab')
      tabs[1].click()
    })
    // antd 6 移除了 .ant-select-selector，mousedown 事件需派发到 .ant-select 根节点
    await page.waitForSelector('.ant-modal .ant-tabs-tabpane-active .ant-select', { timeout: 15_000 })
    await page.evaluate(() => {
      const selector = document.querySelector('.ant-modal .ant-tabs-tabpane-active .ant-select')
      selector.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
      selector.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
      selector.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('.ant-select-item-option')).some((el) => el.textContent?.includes('PDF')),
      { timeout: 10_000 },
    )
    await page.evaluate(() => {
      const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
        .find((el) => (el.textContent || '').includes('PDF'))
      option.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
      option.click()
    })
    await page.waitForFunction(
      () => (document.querySelector('.ant-modal .ant-tabs-tabpane-active .ant-select-content')?.textContent ?? '')
        .includes('PDF'),
      { timeout: 10_000 },
    )
    // 传统 headless（Chromium 81 只有 --headless）不支持下载落盘，故在页面内
    // 拦 URL.createObjectURL 的 PDF Blob 回读字节，用产物 magic 判真伪。
    await page.evaluate(() => {
      window.__cndbDownloads = []
      const originalCreate = URL.createObjectURL
      URL.createObjectURL = function patchedCreate(blob) {
        if (blob && String(blob.type).includes('pdf')) {
          blob.arrayBuffer()
            .then((buf) => {
              const head = new Uint8Array(buf.slice(0, 5))
              window.__cndbDownloads.push({
                size: buf.byteLength,
                magic: String.fromCharCode.apply(null, head),
              })
            })
            .catch((err) => window.__cndbDownloads.push({ size: 0, magic: '', error: String(err) }))
        }
        return originalCreate.call(URL, blob)
      }
    })
    await page.evaluate(() => {
      const active = document.querySelector('.ant-modal .ant-tabs-tabpane-active')
      const button = Array.from(active?.querySelectorAll('button') ?? [])
        .find((el) => (el.textContent || '').trim() === '下载')
      if (!button) throw new Error('未找到下载按钮')
      button.click()
    })
    let pdfFile = null
    let exported = null
    for (let i = 0; i < 90; i += 1) {
      const downloads = await page.evaluate(() => window.__cndbDownloads ?? [])
      if (downloads.length) {
        exported = downloads[0]
        break
      }
      pdfFile = readdirSync(downloadDir).find((name) => name.toLowerCase().endsWith('.pdf')) ?? null
      if (pdfFile) break
      await sleep(1000)
    }
    const toast = await page.evaluate(
      () => Array.from(document.querySelectorAll('.ant-message-notice-content'))
        .map((el) => el.textContent || '').join(' | '),
    )
    check(
      'PDF 导出产出',
      Boolean(exported?.magic.startsWith('%PDF') || pdfFile),
      exported
        ? `拦截到 blob ${exported.size}B，magic=${exported.magic || '空'}${exported.error ? ` err=${exported.error}` : ''}`
        : pdfFile || `未产出（toast: ${toast || '无'}）`,
    )

    // ── 6. 10 套主题截图（C3）────────────────────────────────────
    for (const theme of THEME_MODES) {
      await page.evaluate((value) => window.localStorage.setItem('cndb_theme', value), theme)
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 })
      await page.waitForFunction(
        () => Boolean(document.querySelector('.cn-app-header, [data-testid="import-export-btn"]')) &&
          document.body.innerText.length > 0,
        { timeout: 30_000 },
      )
      await sleep(400)
      const bodyClass = await page.evaluate(() => document.body.className)
      check(`主题 ${theme} body class`, bodyClass.includes(`theme-${theme}`), bodyClass)
      await page.screenshot({ path: path.join(shotDir, `${theme}.png`) })
    }

    check('无未捕获 pageerror（C1）', pageErrors.length === 0, pageErrors.join(' | '))
    if (consoleErrors.length) {
      notes.push(`控制台 error ${consoleErrors.length} 条（不判失败，供人工排查）：${consoleErrors.slice(0, 5).join(' | ')}`)
    }
  } finally {
    await browser.close()
  }
}

try {
  console.log(`[chrome81] 开始冒烟（基线 ${BROWSER_BASELINE}）`)
  await main()
} catch (err) {
  console.error(`[chrome81] 冒烟失败：${err instanceof Error ? err.message : String(err)}`)
  await dumpDiagnostics()
  process.exitCode = 1
}

for (const note of notes) console.log(`[chrome81] note: ${note}`)
console.log(`[chrome81] 截图目录：${path.relative(root, shotDir)}`)

if (failures.length) {
  console.error(`[chrome81] ${failures.length} 项失败`)
  process.exitCode = 1
} else if (!process.exitCode) {
  console.log('[chrome81] Chromium 81 冒烟通过')
}
