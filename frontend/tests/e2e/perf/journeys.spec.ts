/** 性能旅程基线（ADR 0116 C1 / D2）—— @perf 观察期.
 *
 * 三条旅程：冷启动进表、打开文档查看态、表格交互。每条旅程输出结构化 JSON
 * （LCP / FCP / TTFB、longtask、event timing、资源传输量）到
 * `test-results/perf/journeys.json`，并与 `tests/e2e/perf/baselines.json` 中
 * 同环境（local / ci）基线按 ±15% 容差比较：超基线即 FAIL。
 *
 * 基线缺失时只记录不判 FAIL —— 首次读数尚未采集，避免把环境差异误判为回归。
 * 运行方式与 grid-lcp 一致：@perf 标签，CI 从并行分片剔除后在 shard 内串行独占。
 * 手动：pnpm e2e --project=chromium-authed tests/e2e/perf/journeys.spec.ts --workers=1
 */

import { test, expect } from "../fixtures/auth"
import type { Page } from "@playwright/test"
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { publishedDocUrl } from "./docFixtures"

const ANON = ["setup", "chromium-anon"]
const TOLERANCE = 0.15
const OUTPUT_DIR = path.resolve(process.cwd(), "test-results", "perf")
const BASELINE_PATH = path.resolve(process.cwd(), "tests/e2e/perf", "baselines.json")

interface JourneyMetrics {
  lcp: number
  fcp: number
  ttfb: number
  longTaskMax: number
  longTaskCount: number
  eventMax: number
  eventCount: number
  jsBytes: number
  cssBytes: number
  fontBytes: number
  totalBytes: number
}

type Environment = "local" | "ci"

function environment(): Environment {
  return process.env.CI ? "ci" : "local"
}

/** 页面初始化时注册观测器：LCP / longtask / event timing（buffered 覆盖早期条目） */
async function installObservers(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __perfLcp: number
      __perfLongTasks: Array<{ d: number; t: number }>
      __perfEvents: Array<{ d: number; t: number }>
    }
    w.__perfLcp = 0
    w.__perfLongTasks = []
    w.__perfEvents = []
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.startTime > w.__perfLcp) w.__perfLcp = entry.startTime
      }
    }).observe({ type: "largest-contentful-paint", buffered: true })
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        w.__perfLongTasks.push({ d: entry.duration, t: entry.startTime })
      }
    }).observe({ type: "longtask", buffered: true })
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        w.__perfEvents.push({ d: entry.duration, t: entry.startTime })
      }
    }).observe({ type: "event", buffered: true, durationThreshold: 16 } as PerformanceObserverInit)
  })
}

/** 等异步数据驱动的绘制落定后收集指标（双 rAF + 200ms，与 grid-lcp 一致） */
async function collectMetrics(page: Page): Promise<JourneyMetrics> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 200))),
      ),
  )
  return page.evaluate(() => {
    const w = window as unknown as {
      __perfLcp: number
      __perfLongTasks: Array<{ d: number }>
      __perfEvents: Array<{ d: number }>
    }
    const [nav] = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[]
    const fcpEntry = performance.getEntriesByName("first-contentful-paint").at(-1)
    const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[]
    const sum = (pattern: RegExp) =>
      resources
        .filter((entry) => pattern.test(entry.name))
        .reduce((total, entry) => total + (entry.transferSize || 0), 0)
    return {
      lcp: Math.round(w.__perfLcp || 0),
      fcp: fcpEntry ? Math.round(fcpEntry.startTime) : 0,
      ttfb: nav ? Math.round(nav.responseStart) : 0,
      longTaskMax: Math.round(Math.max(0, ...w.__perfLongTasks.map((item) => item.d))),
      longTaskCount: w.__perfLongTasks.length,
      eventMax: Math.round(Math.max(0, ...w.__perfEvents.map((item) => item.d))),
      eventCount: w.__perfEvents.length,
      jsBytes: sum(/\.js(\?|$)/),
      cssBytes: sum(/\.css(\?|$)/),
      fontBytes: sum(/\.woff2(\?|$)/),
      totalBytes: resources.reduce((total, entry) => total + (entry.transferSize || 0), 0),
    }
  })
}

function readBaselines(): Record<string, Record<string, Partial<JourneyMetrics>>> {
  if (!existsSync(BASELINE_PATH)) return {}
  try {
    return JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
  } catch {
    return {}
  }
}

/** 写入本次读数并对比同环境基线；基线缺失只记录（返回值为是否已对比） */
function recordJourney(
  testInfo: { annotations: Array<{ type: string; description?: string }> },
  name: string,
  metrics: JourneyMetrics,
): Partial<JourneyMetrics> | null {
  mkdirSync(OUTPUT_DIR, { recursive: true })
  const outputPath = path.join(OUTPUT_DIR, "journeys.json")
  const previous = existsSync(outputPath)
    ? (JSON.parse(readFileSync(outputPath, "utf8")) as Record<string, unknown>)
    : {}
  writeFileSync(
    outputPath,
    `${JSON.stringify(
      { ...previous, environment: environment(), [name]: metrics, generatedAt: new Date().toISOString() },
      null,
      2,
    )}\n`,
  )

  const baseline = readBaselines()[environment()]?.[name]
  if (!baseline) {
    testInfo.annotations.push({
      type: "perf-baseline",
      description: `${name}：${environment()} 环境暂无基线，仅记录读数（${JSON.stringify(metrics)}）`,
    })
    return null
  }
  return baseline
}

function assertWithinBaseline(
  name: string,
  metrics: JourneyMetrics,
  baseline: Partial<JourneyMetrics> | null,
): void {
  if (!baseline) return
  for (const [key, expected] of Object.entries(baseline)) {
    if (typeof expected !== "number" || expected <= 0) continue
    const actual = metrics[key as keyof JourneyMetrics]
    expect(
      actual,
      `${name} ${key} 超出基线：实际 ${actual}，基线 ${expected}（容差 +${TOLERANCE * 100}%）`,
    ).toBeLessThanOrEqual(Math.ceil(expected * (1 + TOLERANCE)))
  }
}

async function gotoGrid(page: Page): Promise<void> {
  await page.goto("/")
  await page.waitForURL(/\/w/)
  if (page.url().match(/\/w\/?$/)) {
    const firstRow = page.locator('[data-testid^="workspace-row-"]').first()
    await expect(firstRow).toBeVisible({ timeout: 10000 })
    await firstRow.locator(".cn-ws-row-main").first().click()
  }
  await page.waitForURL(/\/w\/\d+/)
  await page.getByRole("menuitem", { name: /员工表/ }).click()
  await page.waitForURL(/\/tables\/\d+/)
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible()
}

test.describe("性能旅程基线（ADR 0116 C1）", () => {
  test("冷启动进表", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    await installObservers(page)
    await gotoGrid(page)

    const metrics = await collectMetrics(page)
    const baseline = recordJourney(testInfo, "coldGrid", metrics)
    assertWithinBaseline("coldGrid", metrics, baseline)
  })

  test("打开文档查看态", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    await installObservers(page)
    await page.goto("/w/1/documents")
    await page.goto(await publishedDocUrl(page, 1))

    // 已发布文档（草稿默认进编辑态，不是查看态）
    await page.locator('.cn-list-item:has([data-testid^="doc-list-format-"])').first().click()
    await page.waitForURL(/\/documents\/\d+/)
    // 查看态渲染完成信号
    await expect(page.getByTestId("doc-mode-switch")).toBeVisible({ timeout: 15000 })

    const metrics = await collectMetrics(page)
    const baseline = recordJourney(testInfo, "documentView", metrics)
    assertWithinBaseline("documentView", metrics, baseline)
  })

  test("表格交互（排序 / INP / longtask）", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    await installObservers(page)
    await gotoGrid(page)

    // 点击列头排序：触发一笔行数据请求与表格重渲染，覆盖交互指标
    const sortableHeader = page.locator(".ant-table-thead th").nth(2)
    await sortableHeader.click()

    const metrics = await collectMetrics(page)
    const baseline = recordJourney(testInfo, "gridInteraction", metrics)
    assertWithinBaseline("gridInteraction", metrics, baseline)

    // C10：交互响应与主线程长任务硬上限（观察期取保守值，避免 runner 抖动误伤）
    expect(metrics.eventMax, `eventMax=${metrics.eventMax}ms`).toBeLessThan(600)
    expect(metrics.longTaskMax, `longTaskMax=${metrics.longTaskMax}ms`).toBeLessThan(400)

    // ADR 0117 C5：主表沿用虚拟滚动，挂载行数与总 DOM 不得随数据量线性增长。
    // 上限与数据集规模无关，参考规模（5000 行 × 20 列）下同样必须成立。
    const dom = await page.evaluate(() => ({
      mountedRows: document.querySelectorAll("[data-row-key]").length,
      elements: document.querySelectorAll("*").length,
    }))
    expect(dom.mountedRows, `挂载行数 ${dom.mountedRows}`).toBeLessThanOrEqual(100)
    expect(dom.elements, `DOM 元素 ${dom.elements}`).toBeLessThanOrEqual(8000)
  })
})
