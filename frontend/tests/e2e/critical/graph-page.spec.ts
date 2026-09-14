/** 关系图页面 E2E — /w/:wid/graph.
 *
 * 覆盖：页面加载、标题、SVG 画布、表节点渲染.
 *
 * 注意：关系图目前在 Header 上没有导航按钮，只能直接通过 URL 访问.
 */

import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1

test.describe("关系图页面 /w/:wid/graph", () => {
  test("直接访问 — 标题 + SVG 画布 + 表节点渲染", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/graph`)
    await page.waitForURL(/\/graph$/)

    // 标题：h2
    const h2 = page.locator("h2", { hasText: /关系图/ })
    await expect(h2).toBeVisible({ timeout: 10000 })

    // 提示说明文本
    await expect(page.getByText(/双击节点跳转/)).toBeVisible()

    // SVG 画布存在
    await expect(page.locator("svg").first()).toBeVisible()

    // 至少 4 个 <rect> 代表有表节点渲染（seed 数据 6 张表）
    const rectCount = await page.locator("svg rect").count()
    expect(rectCount).toBeGreaterThanOrEqual(4)
  })

  test("头部有「刷新」按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/graph`)
    await page.waitForURL(/\/graph$/)

    // 顶部操作按钮（刷新 / 缩放系列）
    await expect(page.getByRole("button", { name: /刷新/ })).toBeVisible()
  })
})
