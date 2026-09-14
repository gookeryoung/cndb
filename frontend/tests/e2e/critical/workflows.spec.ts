/** 工作流列表 + 编辑器 E2E — /w/:wid/workflows + /w/:wid/workflows/:fwid.
 *
 * 覆盖：列表标题、列表项渲染、新建按钮、编辑器节点/边/画布.
 */

import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1
const FID = 1 // seed 数据有 "员工入职流程"

test.describe("工作流列表页面 /w/:wid/workflows", () => {
  test("直接访问 — 标题 + 工作流卡片 + 新建按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/workflows`)
    await page.waitForURL(/\/workflows$/)

    // 标题
    await expect(page.locator("h3", { hasText: /业务工作流/ })).toBeVisible({ timeout: 10000 })

    // 新建按钮
    const newBtn = page.getByRole("button", { name: /新建工作流/ })
    await expect(newBtn).toBeVisible()

    // 至少一个工作流卡片（seed 有员工入职流程）
    await expect(page.getByText(/员工入职流程/)).toBeVisible()
  })

  test("点击「进入编辑」导航到编辑器", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/workflows`)
    await page.waitForURL(/\/workflows$/)

    // 卡片上有"进入编辑"按钮
    const enterBtn = page.locator("button", { hasText: /进入编辑/ }).first()
    await expect(enterBtn).toBeVisible()
    await enterBtn.click()

    await page.waitForURL(/\/workflows\/\d+$/)
  })
})

test.describe("工作流编辑器 /w/:wid/workflows/:fwid", () => {
  test("直接访问 — React Flow 画布 + 节点 + 边", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/workflows/${FID}`)
    await page.waitForURL(/\/workflows\/\d+$/)

    // React Flow 画布
    const rf = page.locator(".react-flow")
    await expect(rf).toBeVisible({ timeout: 10000 })

    // 至少 3 个节点 + 2 条边（seed: 员工入职流程）
    const nodes = page.locator(".react-flow__node")
    await expect(nodes).toHaveCount(3, { timeout: 10000 })
    const edges = page.locator(".react-flow__edge")
    await expect(edges).toHaveCount(2)

    // 添加节点按钮
    await expect(page.getByRole("button", { name: /添加节点/ })).toBeVisible()
  })

  test("节点渲染 — 有名字、绑定表信息可见", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/workflows/${FID}`)
    await page.waitForURL(/\/workflows\/\d+$/)

    await expect(page.locator(".react-flow__node")).toHaveCount(3, { timeout: 10000 })

    // 至少有一个节点显示"绑定表"标签
    await expect(page.getByText(/绑定表/).first()).toBeVisible()
  })
})
