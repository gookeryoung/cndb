/** 表行 hover 预取（ADR 0116 C7 / D8）—— @perf 观察期.
 *
 * 1. hover 表行 200ms 后出现表详情 / 视图 / 首帧行数据请求；
 * 2. 未 hover 的表不产生逐表请求（扫过列表不应形成请求风暴）；
 * 3. 冷进表只发一次行数据请求（hover 预取与首帧正式请求命中同一 queryKey）。
 */

import { test, expect } from "../fixtures/auth"
import type { Page } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1

function collectTableRequests(page: Page): Array<{ tid: string; kind: "detail" | "views" | "records"; url: string }> {
  const seen: Array<{ tid: string; kind: "detail" | "views" | "records"; url: string }> = []
  page.on("request", (request) => {
    if (request.method() !== "GET") return
    const url = new URL(request.url())
    const pathname = url.pathname
    const match = pathname.match(`/api/v1/workspaces/${WID}/tables/(\\d+)(/views|/records)?$`)
    if (!match) return
    const [, tid, suffix] = match
    seen.push({
      tid: tid!,
      kind: suffix === "/views" ? "views" : suffix === "/records" ? "records" : "detail",
      url: `${pathname}${url.search}`,
    })
  })
  return seen
}

async function openTablesList(page: Page): Promise<{ tid: string; selector: string }> {
  await page.goto(`/w/${WID}/tables`)
  // 桌面是表格行（table-row-*），窄屏才是卡片（table-card-*）；按当前视口命中任一
  const first = page
    .locator('[data-testid^="table-row-"], [data-testid^="table-card-"]')
    .first()
  await expect(first).toBeVisible({ timeout: 15000 })
  const testId = (await first.getAttribute("data-testid")) ?? ""
  const tid = testId.replace(/^table-(row|card)-/, "")
  return { tid, selector: testId }
}

test.describe("性能：表行 hover 预取（ADR 0116 C7）", () => {
  test("hover 200ms 后预取详情 / 视图 / 首帧行数据", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    const requests = collectTableRequests(page)
    const { tid, selector } = await openTablesList(page)
    requests.length = 0

    await page.locator(`[data-testid="${selector}"]`).hover()
    // 无快照时预取链路是「视图列表 → 落地视图参数 → 首帧行」，给足链路时间
    await expect
      .poll(() => requests.filter((item) => item.tid === tid).map((item) => item.kind), { timeout: 5000 })
      .toEqual(expect.arrayContaining(["detail", "views", "records"]))

    const kinds = requests.filter((item) => item.tid === tid).map((item) => item.kind)
    expect(kinds, `实际请求：${JSON.stringify(requests)}`).toContain("detail")
    expect(kinds).toContain("views")
    expect(kinds).toContain("records")
  })

  test("未 hover 的表不产生逐表请求", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    const requests = collectTableRequests(page)
    await openTablesList(page)
    await page.waitForTimeout(500)
    expect(requests, `未 hover 却出现请求：${JSON.stringify(requests)}`).toHaveLength(0)
  })

  test("冷进表行数据请求次数 = 1", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    const requests = collectTableRequests(page)
    const { tid, selector } = await openTablesList(page)
    requests.length = 0

    // 先 hover 命中预取，再点击进入：正式首帧应复用预取结果
    await page.locator(`[data-testid="${selector}"]`).hover()
    await expect
      .poll(() => requests.filter((item) => item.tid === tid && item.kind === "records").length, { timeout: 5000 })
      .toBeGreaterThan(0)
    await page.locator(`[data-testid="${selector}"]`).click()
    await page.waitForURL(new RegExp(`/tables/${tid}`))
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 15000 })
    await page.waitForTimeout(500)

    const recordRequests = requests.filter((item) => item.tid === tid && item.kind === "records")
    expect(
      recordRequests.length,
      `记录请求次数：${recordRequests.length}（${JSON.stringify(requests)}）`,
    ).toBe(1)
  })
})
