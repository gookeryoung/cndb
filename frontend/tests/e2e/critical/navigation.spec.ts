/** MainLayout Header 导航 E2E.
 *
 * 覆盖：Header 导航按钮可达性 — 工作流、回收站、报表、工作区设置.
 * 关系图目前没有 Header 入口（直接用 URL 访问，已在 graph-page.spec.ts 覆盖）.
 */

import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1

test.describe("MainLayout Header 导航按钮", () => {
  // 起点：工作区表列表页，保证所有 Header 按钮都能看到
  const start = async (page: any) => {
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)
  }

  test("Header 可见 工作流 / 回收站 / 报表 / 工作区设置 按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await expect(page.getByRole("button", { name: /工作流/ })).toBeVisible()
    await expect(page.getByRole("button", { name: /回收站/ })).toBeVisible()
    await expect(page.getByRole("button", { name: /报表/ })).toBeVisible()
    // 工作区设置是 Tooltip 包裹的图标按钮
    await expect(page.locator("[data-testid='workspace-settings-nav']")).toBeVisible()
  })

  test("Header 工作流按钮 → /w/:wid/workflows", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await page.getByRole("button", { name: /工作流/ }).click()
    await page.waitForURL(/\/workflows$/)
    await expect(page.locator("h3", { hasText: /业务工作流/ })).toBeVisible({ timeout: 5000 })
  })

  test("Header 回收站按钮 → /w/:wid/trash", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await page.getByRole("button", { name: /回收站/ }).click()
    await page.waitForURL(/\/trash$/)
    await expect(page.locator(".ant-tabs-tab")).toHaveCount(3, { timeout: 5000 })
  })

  test("Header 报表按钮 → /w/:wid/reports", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await page.getByRole("button", { name: /报表/ }).click()
    await page.waitForURL(/\/reports$/)
    await expect(page.locator("h3", { hasText: /报表模板/ })).toBeVisible({ timeout: 5000 })
  })
})
