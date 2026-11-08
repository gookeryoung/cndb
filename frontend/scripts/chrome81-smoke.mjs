#!/usr/bin/env node
/* global document, window, navigator, MouseEvent, getComputedStyle, fetch, setTimeout, URL, performance, requestAnimationFrame, PerformanceObserver */
/**
 * chrome81-smoke.mjs — 真实 Chromium 81 冒烟（ADR 0026 C1 / C5 / D9）.
 *
 * Playwright 只保证其内置 Chromium，故这里用 puppeteer-core + 固定 revision 快照
 * （CHROMIUM81_REVISION 与 BROWSER_BASELINE 同处 browser-baseline.mjs，避免版本漂移）。
 *
 * 覆盖：
 *  - 登录 → 工作区列表 → 数据表打开 / 视图切换 → 文档页 → 设计编辑器（three.js，ADR 0079 D4）；
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
import { PERF_BUDGET } from './perf-budget.mjs'

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

/** 采集「点击 → 下一帧」时延（Chromium 81 无 Event Timing，只能手工计时） */
async function clickToNextFrame(page, selector) {
  return page.evaluate((sel) => new Promise((resolve) => {
    const target = document.querySelector(sel)
    if (!target) {
      resolve(null)
      return
    }
    const started = performance.now()
    target.click()
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve(performance.now() - started))
    })
  }), selector)
}

/** 清空 longtask 采集，避免上一段负载计入本次测量 */
async function resetLongTasks(page) {
  await page.evaluate(() => {
    if (window.__cndbPerf) window.__cndbPerf.longTasks.length = 0
  })
}

/** 自上次 reset 以来的最长长任务（毫秒） */
async function maxLongTask(page) {
  return page.evaluate(() => {
    const tasks = window.__cndbPerf?.longTasks ?? []
    return tasks.length ? Math.max(...tasks) : 0
  })
}

/** 打开「个人设置 → 主题」页签，供主题切换时延测量使用 */
async function openThemePanel(page) {
  await page.hover('[data-testid="user-menu-trigger"]')
  const opened = await page
    .waitForFunction(
      () => Array.from(document.querySelectorAll('.ant-dropdown-menu-item'))
        .some((el) => (el.textContent || '').includes('个人设置')),
      { timeout: 10_000 },
    )
    .then(() => true)
    .catch(() => false)
  if (!opened) return false
  await page.evaluate(() => {
    const item = Array.from(document.querySelectorAll('.ant-dropdown-menu-item'))
      .find((el) => (el.textContent || '').includes('个人设置'))
    item?.click()
  })
  await page.waitForFunction(
    () => Boolean(document.querySelector('.settings-modal .ant-tabs-tab-btn')),
    { timeout: 15_000 },
  )
  await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('.settings-modal .ant-tabs-tab-btn'))
      .find((el) => (el.textContent || '').trim() === '主题')
    tab?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    tab?.click()
  })
  await page.waitForSelector('.settings-modal [data-theme-card]', { timeout: 10_000 })
  return true
}

/** 测量主题切换时延：预热一轮后切到深色再切回默认，取较慢一次（ADR 0117 C2 / C3 / D7） */
async function measureThemeSwitch(page) {
  let themeSwitchMs = null
  let longTaskMs = 0
  try {
    if (!(await openThemePanel(page))) return { themeSwitchMs, longTaskMs }
    // 预热：首次切换包含一次性主题快照 / 样式计算，不计入「切换」口径（D7）
    for (const mode of ['github-dark', 'modern']) {
      await clickToNextFrame(page, `.settings-modal [data-theme-card="${mode}"]`)
      await sleep(250)
    }
    await resetLongTasks(page)
    const durations = []
    for (const mode of ['github-dark', 'modern']) {
      const latency = await clickToNextFrame(page, `.settings-modal [data-theme-card="${mode}"]`)
      if (latency != null) durations.push(latency)
      await sleep(250)
    }
    longTaskMs = await maxLongTask(page)
    if (durations.length) themeSwitchMs = Math.max(...durations)
  } catch {
    return { themeSwitchMs: null, longTaskMs }
  } finally {
    await page.evaluate(() => {
      document.querySelector('.settings-modal .ant-modal-close')?.click()
    })
    await page
      .waitForFunction(() => !document.querySelector('.settings-modal'), { timeout: 10_000 })
      .catch(() => {})
  }
  return { themeSwitchMs, longTaskMs }
}

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

    // 旧内核性能采集（ADR 0117 C2 / C6）：longtask 是唯一可用的长任务口径
    await page.evaluateOnNewDocument(() => {
      window.__cndbPerf = { longTasks: [] }
      try {
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) window.__cndbPerf.longTasks.push(entry.duration)
        }).observe({ entryTypes: ['longtask'] })
      } catch {
        // 极老内核不支持 longtask 时按 0 处理，不阻断功能冒烟
      }
    })

    // ── 1. 登录态进入工作区（C1：不白屏、无未捕获异常）────────────────
    await page.goto(`${baseUrl}/w`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForFunction(
      () => Boolean(document.querySelector('.cn-app-header')) && document.body.innerText.length > 0,
      { timeout: 30_000 },
    )
    check('工作区列表渲染', page.url().includes('/w'), page.url())
    const firstInteractiveMs = await page.evaluate(() => performance.now())
    check(
      `首屏可交互 ≤ ${PERF_BUDGET.firstInteractiveMs}ms`,
      firstInteractiveMs <= PERF_BUDGET.firstInteractiveMs,
      `${firstInteractiveMs.toFixed(1)}ms`,
    )

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
    // 预热：首次进入视图会拉取懒加载 chunk（KanbanView / ChartView 等），属于一次性加载成本，
    // 不计入「视图切换（不含网络）」口径（ADR 0117 D7）
    for (const mode of modes) {
      await clickToNextFrame(page, `[data-mode="${mode}"]`)
      await sleep(1200)
    }
    const viewDurations = []
    const viewLongTasks = {}
    await resetLongTasks(page)
    for (const mode of modes) {
      const latency = await clickToNextFrame(page, `[data-mode="${mode}"]`)
      if (latency != null) viewDurations.push(latency)
      await sleep(1200)
      const rendered = await page.evaluate(() => document.body.innerText.length > 0)
      check(`视图切换 ${mode}`, rendered)
      viewLongTasks[mode] = await maxLongTask(page)
      await resetLongTasks(page)
    }
    if (!modes.length) notes.push('当前表没有多视图按钮（跳过视图切换）')

    // ── 3.5 旧内核性能基线（C2 / C6；阈值唯一来源 perf-budget.mjs）───────
    const viewSwitchMs = viewDurations.length ? Math.max(...viewDurations) : null
    if (viewSwitchMs != null) {
      check(
        `视图切换 ≤ ${PERF_BUDGET.viewSwitchMs}ms`,
        viewSwitchMs <= PERF_BUDGET.viewSwitchMs,
        `${viewSwitchMs.toFixed(1)}ms`,
      )
    }
    for (const [mode, longTaskMs] of Object.entries(viewLongTasks)) {
      const budget = PERF_BUDGET.viewLongTaskByModeMs[mode] ?? PERF_BUDGET.viewLongTaskMs
      check(
        `视图切换 ${mode} 最长任务 ≤ ${budget}ms`,
        longTaskMs <= budget,
        `${longTaskMs.toFixed(1)}ms`,
      )
    }

    const themePerf = await measureThemeSwitch(page)
    if (themePerf.themeSwitchMs != null) {
      check(
        `主题切换 ≤ ${PERF_BUDGET.themeSwitchMs}ms`,
        themePerf.themeSwitchMs <= PERF_BUDGET.themeSwitchMs,
        `${themePerf.themeSwitchMs.toFixed(1)}ms`,
      )
      check(
        `主题切换最长任务 ≤ ${PERF_BUDGET.themeLongTaskMs}ms`,
        themePerf.longTaskMs <= PERF_BUDGET.themeLongTaskMs,
        `${themePerf.longTaskMs.toFixed(1)}ms`,
      )
    } else {
      notes.push('主题切换未能测量（未找到主题卡片），性能基线缺项')
    }
    const perf = {
      firstInteractiveMs: Math.round(firstInteractiveMs),
      themeSwitchMs: themePerf.themeSwitchMs == null ? null : Math.round(themePerf.themeSwitchMs),
      themeLongTaskMs: Math.round(themePerf.longTaskMs),
      viewSwitchMs: viewSwitchMs == null ? null : Math.round(viewSwitchMs),
      viewLongTasksMs: Object.fromEntries(
        Object.entries(viewLongTasks).map(([mode, ms]) => [mode, Math.round(ms)]),
      ),
    }
    console.log(`[chrome81] perf: ${JSON.stringify(perf)}`)
    notes.push(`性能基线 ${JSON.stringify(perf)}`)

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

    // ── 4.5 设计模块（ADR 0079 D4：three.js 0.165 在 Chromium 81 实测）────
    // 经 API 创建示例设计（参数化法兰板，与 DesignsPage 的起步模板同源）
    const DESIGN_CONTENT = [
      'param width = 80',
      'param height = 40',
      'param hole_d = 8',
      'module plate(w, h, t) {',
      '  difference {',
      '    box(size = [w, h, t])',
      '    translate([w / 2, h / 2, -1]) {',
      '      cyl(d = hole_d, h = t + 2)',
      '    }',
      '  }',
      '}',
      'plate(width, height, 12)',
      '',
    ].join('\n')
    const design = await fetchJson(`/api/v1/workspaces/${seed.workspace.id}/designs`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${seed.token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '冒烟-法兰板', description: 'Chromium 81 冒烟样例', content: DESIGN_CONTENT }),
    })
    await page.goto(`${baseUrl}/w/${seed.workspace.id}/design`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })
    await page.waitForFunction(
      () => document.body.innerText.includes('冒烟-法兰板'),
      { timeout: 30_000 },
    )
    check('设计列表打开', true)

    await page.goto(`${baseUrl}/w/${seed.workspace.id}/design/${design.id}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    })
    // three.js lazy chunk 在 Chromium 81 上加载并执行：画布挂载或 WebGL 不可用时的降级提示
    await page.waitForFunction(
      () => Boolean(
        document.querySelector('[data-testid="design-preview-canvas"]') ||
        document.querySelector('[data-testid="design-preview-webgl-unsupported"]'),
      ),
      { timeout: 30_000 },
    )
    const webglRendered = await page.evaluate(() =>
      Boolean(document.querySelector('[data-testid="design-preview-canvas"]')),
    )
    // 出现画布或降级提示即证明 lazy chunk 加载并执行成功（否则仅剩 Skeleton + pageerror）
    check('设计编辑器与 three.js chunk 在 Chromium 81 可用', true)
    if (webglRendered) notes.push('three.js WebGL 渲染在 Chromium 81 实际产出画布')
    else notes.push('Chromium 81 headless 无 WebGL 上下文，预览走降级提示（DSL 模块本身未崩）')

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
    // antd 6：Tab 面板类名由 .ant-tabs-tabpane 改为 .ant-tabs-content（激活态 .ant-tabs-content-active）；
    // 同时移除了 .ant-select-selector，mousedown 事件需派发到 .ant-select 根节点
    await page.waitForSelector('.ant-modal .ant-tabs-content-active .ant-select', { timeout: 15_000 })
    await page.evaluate(() => {
      const selector = document.querySelector('.ant-modal .ant-tabs-content-active .ant-select')
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
      () => (document.querySelector('.ant-modal .ant-tabs-content-active .ant-select-content')?.textContent ?? '')
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
      const active = document.querySelector('.ant-modal .ant-tabs-content-active')
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
