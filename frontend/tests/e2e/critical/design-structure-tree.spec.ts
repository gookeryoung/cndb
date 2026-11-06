/** 设计结构 E2E（ADR 0109 D1 / D2 / D3 / D5）—— 根页左右分栏：左产品列表 + 右装配树.
 *
 * 走完整 UI 链路：经 API 建一份带模块 / 布尔分组 / 图元的设计，进入设计模块默认页
 * （/w/:wid/design，ADR 0109 起为左右分栏），断言左栏产品列表与右栏装配树同时可见，
 * 树层级为 组件 → 结构分组 → 零件并带源行元信息；再点击零件节点，
 * 校验跳转到编辑器并带 `?line=` 源行参数。
 * 侧栏装配树已收窄到编辑器页（ADR 0109 D4），由 design-sidebar-assembly 覆盖。
 * 清理统一走 API，避免失败用例残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 源行位置（1 基）：param 1 / module 2 / difference 3 / box 4 / translate 5 / cyl 6 / 闭合 7-9 / 实例 10 */
const CONTENT = [
  "param width = 80",
  "module plate(w, t) {",
  "  difference {",
  "    box(size = [w, 40, t])",
  "    translate([w / 2, 20, -1]) {",
  "      cyl(d = 8, h = t + 2)",
  "    }",
  "  }",
  "}",
  "plate(width, 12)",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E 装配树", content: CONTENT },
  })
  expect(resp.status()).toBe(201)
  const body = (await resp.json()) as { id: number }
  return body.id
}

/** 删除失败不阻断用例结果（超时后 request context 可能已关闭） */
async function safeDeleteDesign(request: APIRequestContext, designId: number) {
  await request
    .delete(`/api/v1/workspaces/${WID}/designs/${designId}`, {
      headers: await authHeaders(request),
    })
    .catch(() => undefined)
}

test.describe("设计结构根页左右分栏（0109）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("左产品列表 / 右装配树 → 组件 / 分组 / 零件带源行 → 点击零件定位编辑器", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const title = `E2E 装配树 ${stamp}`
    let designId = 0

    try {
      designId = await createDesign(request, title)

      // 1) 设计模块默认页为左右分栏（ADR 0109 D1 / D2）：页签激活、左栏产品列表、右栏结构树
      await page.goto(`/w/${WID}/design`)
      await page.waitForURL(/\/w\/1\/design$/)
      await expect(page.getByTestId("design-crumb")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId("design-tab-structure")).toHaveAttribute("aria-selected", "true")
      await expect(page.getByTestId("design-products-box")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId("design-outline-box")).toBeVisible()
      // 根页不再渲染侧栏装配树（ADR 0109 D4）
      await expect(page.getByTestId("sider-designs")).toHaveCount(0)

      // 2) 左栏出现设计行；确保本用例的产品为选中态后，右栏展示其结构树
      //    （默认选中「最近更新」，并行用例会各自建设计，故不是本产品时显式点选；
      //      点已选中行会取消选中，故先判断再点）
      const row = page.getByTestId(`design-row-${designId}`)
      await expect(row).toBeVisible({ timeout: 10_000 })
      if ((await row.getAttribute("aria-selected")) !== "true") await row.click()
      await expect(row).toHaveAttribute("aria-selected", "true")
      await expect(page.getByTestId("design-outline-box")).toContainText(title)

      // 3) 右栏树层级：组件（module 实例）→ 结构分组（布尔块）→ 零件（图元）
      await expect(page.getByText("plate")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("组件 · 第 10 行 · 2 个零件")).toBeVisible()
      await expect(page.getByText("差集")).toBeVisible()
      await expect(page.getByText("结构分组 · 第 3 行 · 2 个零件")).toBeVisible()
      await expect(page.getByText("立方体")).toBeVisible()
      await expect(page.getByText("圆柱")).toBeVisible()
      await expect(page.getByText("零件 · 第 4 行")).toBeVisible()

      // 4) 点击零件节点 → 编辑器带 ?line=4 定位源行
      await page.getByText("零件 · 第 4 行").click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}\\?line=4`))
      await expect(page.locator(".cm-content")).toContainText("box(size = [w, 40, t])", { timeout: 15_000 })
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
