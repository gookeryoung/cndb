/** 报表模板页面 E2E — /w/:wid/reports.
 *
 * 覆盖：标题、模板表格、新建按钮、模板名称、表头.
 */

import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1

test.describe("报表模板页面 /w/:wid/reports", () => {
  test("直接访问 — 标题 + 表格 + 新建按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/reports`)
    await page.waitForURL(/\/reports$/)

    // 标题
    await expect(page.locator("h3", { hasText: /报表模板/ })).toBeVisible({ timeout: 10000 })

    // 新建按钮
    await expect(page.getByRole("button", { name: /新建模板/ })).toBeVisible()

    // 表格存在
    await expect(page.locator(".ant-table")).toBeVisible()

    // 表头：至少 6 列（模板名称/输出格式/关联表/描述/参数/操作）
    const headers = page.getByRole("columnheader")
    await expect(headers).toHaveCount(6, { timeout: 5000 })
  })

  test("模板列表 — 有至少一条模板记录（员工名册）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/reports`)
    await page.waitForURL(/\/reports$/)

    await expect(page.locator(".ant-table-row")).toHaveCount(1, { timeout: 10000 })

    // 用 columnheader 限定在表格内，避免匹配侧栏 Menu
    const firstRow = page.locator(".ant-table-row").first()
    await expect(firstRow.getByText(/员工名册/)).toBeVisible()
  })
})
