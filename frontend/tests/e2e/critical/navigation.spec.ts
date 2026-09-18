/** MainLayout Header 导航 E2E.
 *
 * 覆盖：Header 导航按钮可达性 — 回收站、报表、工作区设置.
 * 以及表列表 owner 列展示 + 筛选器.
 */

import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]
const WID = 1

test.describe("MainLayout Header 导航按钮", () => {
  // 起点：工作区表列表页，保证所有 Header 按钮都能看到
  const start = async (page: any) => {
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)
  }

  test("Header 可见 回收站 / 报表 / 工作区设置 按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await expect(page.getByRole("button", { name: /回收站/ })).toBeVisible()
    await expect(page.getByRole("button", { name: /报表/ })).toBeVisible()
    // 工作区设置是 Tooltip 包裹的图标按钮
    await expect(page.locator("[data-testid='workspace-settings-nav']")).toBeVisible()
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

test.describe("表列表 owner 列 + 访问级筛选器", () => {
  const start = async (page: any) => {
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)
    // 等待表列表渲染
    await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(6, { timeout: 10000 })
  }

  test("访问级筛选器：「我拥有的」可筛选出全部表（admin 是所有 seed 表的 owner）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 点击「我拥有的」筛选器
    const seg = page.locator(".ant-segmented-item", { hasText: "我拥有的" })
    await seg.click()
    await expect(seg).toHaveClass(/ant-segmented-item-selected/)

    // seed 所有 6 张表的 owner 都是 admin（当前用户），筛选后仍应显示 6 张
    await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(6, { timeout: 5000 })
  })
})
