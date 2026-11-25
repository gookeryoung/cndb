/**
 * Critical — 数据表列表在宽度变化时的行高 / 列宽稳定性（需求 0157 列表布局收口）。
 *
 * 回归背景：`scroll.x='max-content'` + 未固定名称列宽时，窄宽度会把列压到
 * 84~100px，长表名换行导致行高翻倍、相邻单元格文字错位。
 *
 * 现在口径：固定列宽 + `tableLayout="fixed"` + 名称/描述单行省略；
 * 宽屏表格铺满内容区，窄屏横向滚动，行高恒定 33px 左右。
 */
import { expect, test } from "../fixtures/auth"
import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api"
import type { APIRequestContext } from "@playwright/test"

const stamp = Date.now()
const LONG_NAME = `这是一个非常长的数据表名称用于验证窄宽度下的行高稳定性-${stamp}`

test.describe.configure({ timeout: 120_000 })

let token = ""
let wid = 0
let tid = 0

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request)
  wid = await getWorkspaceId(request)
  const created = await apiCall(request, token, "post", `/workspaces/${wid}/tables`, { name: LONG_NAME })
  expect(created.status, JSON.stringify(created.body)).toBe(201)
  tid = (created.body as { id: number }).id
})

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (tid) await apiCall(request, token, "delete", `/workspaces/${wid}/tables/${tid}`).catch(() => undefined)
})

test("长表名在宽 → 窄过程中行高恒定，名称省略而不换行", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过")

  for (const width of [1600, 1200, 1000, 900, 800, 769, 768]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`/w/${wid}/tables`)
    const row = page.getByTestId(`table-row-${tid}`)
    await expect(row).toBeVisible({ timeout: 20_000 })

    // 1) 行高稳定：不再被长名称撑成两行
    const rowHeight = (await row.boundingBox())!.height
    expect(rowHeight, `width=${width} 行高应保持单行`).toBeLessThan(48)

    // 2) 名称单行省略（可 hover 看全称），不是折行
    const nameEllipsized = await row.locator(".cn-table-list-name-text").evaluate(
      el => el.scrollWidth > el.clientWidth + 1,
    )
    expect(nameEllipsized, `width=${width} 长名称应省略`).toBe(true)
    await expect(row.locator(".cn-table-list-name")).toHaveAttribute("title", LONG_NAME)

    // 3) 表头与表体列宽同源（固定布局），不出现文字错位
    const layout = await page.evaluate((tid) => {
      const tr = document.querySelector(`[data-testid="table-row-${tid}"]`) as HTMLElement
      const table = tr.closest("table") as HTMLElement
      const container = table.parentElement as HTMLElement
      const headWidths = Array.from(document.querySelectorAll(".cn-table-list thead th"))
        .map(th => Math.round(th.getBoundingClientRect().width))
      const cellWidths = Array.from(tr.querySelectorAll("td"))
        .map(td => Math.round(td.getBoundingClientRect().width))
      return {
        tableWidth: Math.round(table.getBoundingClientRect().width),
        containerWidth: Math.round(container.getBoundingClientRect().width),
        headWidths,
        cellWidths,
      }
    }, tid)

    expect(layout.headWidths, `width=${width} 表头/表体列宽应一致`).toEqual(layout.cellWidths)

    if (width >= 1600) {
      // 宽屏铺满内容区，不留下大块空白
      expect(Math.abs(layout.tableWidth - layout.containerWidth)).toBeLessThanOrEqual(4)
    } else {
      // 窄屏保持最小列宽并横向滚动，而不是压缩换行
      expect(layout.tableWidth).toBeGreaterThan(layout.containerWidth)
    }
  }
})
