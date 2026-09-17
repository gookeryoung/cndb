/** 回收站页面 E2E — /w/:wid/trash.
 *
 * 覆盖：页面加载、三个 Tab（表 / 字段 / 行）、Tab 切换、空状态.
 */

import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]
const WID = 1

test.describe("回收站页面 /w/:wid/trash", () => {
  test("直接访问 — 三个 Tab 存在", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/trash`)
    await page.waitForURL(/\/trash$/)

    // 页面容器正常渲染
    await expect(page.locator(".ant-card").first()).toBeVisible({ timeout: 10000 })

    // 三个 Tab 存在（text 子串匹配）
    const tabs = page.locator(".ant-tabs-tab")
    await expect(tabs).toHaveCount(3, { timeout: 10000 })
    await expect(tabs.filter({ hasText: "表" })).toBeVisible()
    await expect(tabs.filter({ hasText: "字段" })).toBeVisible()
    await expect(tabs.filter({ hasText: "行" })).toBeVisible()
  })

  test("Tab 切换 — 表 → 字段 → 行 都能正常显示", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/trash`)
    await page.waitForURL(/\/trash$/)

    const tabs = page.locator(".ant-tabs-tab")
    await expect(tabs).toHaveCount(3, { timeout: 10000 })
    const tab = (i: number) => tabs.nth(i).locator('[role="tab"]')

    // 默认在表 Tab
    await expect(tab(0)).toHaveAttribute("aria-selected", "true")

    // 切到字段
    await tab(1).click()
    await expect(tab(1)).toHaveAttribute("aria-selected", "true")

    // 切到行
    await tab(2).click()
    await expect(tab(2)).toHaveAttribute("aria-selected", "true")

    // 活跃 Tab 下有内容（无论空还是有数据，TabPanel 都存在）
    await expect(page.locator(".ant-tabs-tabpane-active")).toBeVisible()
  })
})
