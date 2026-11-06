/** 设计结构 E2E（ADR 0109 C1 / C2 / C3 / D4）—— 侧栏共享：产品列表 ↔ 结构树，Content = 编辑器.
 *
 * 走完整 UI 链路：经 API 建一份带模块 / 布尔分组 / 图元的设计，进入设计模块根页
 * （/w/:wid/design，自动打开最近更新产品），侧栏处于结构树态；点「产品列表」就地切回列表，
 * 选本用例产品后侧栏就地进入其结构树，Content 始终是编辑器。
 * 树层级为 组件 → 结构分组 → 零件并带源行元信息；再点击零件节点，
 * 校验跳转到编辑器并带 `?line=` 源行参数。
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

/** 点击某个树节点所在行的展开箭头（testid 在标题内，需回溯到 treenode） */
async function expandNode(page: import("@playwright/test").Page, testId: string) {
  await page
    .locator(".ant-tree-treenode")
    .filter({ has: page.getByTestId(testId) })
    .locator(".ant-tree-switcher")
    .click()
  await page.waitForTimeout(650)
}

test.describe("设计模块单一工作台（0109）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("根页自动打开 → 侧栏列表选产品 → 就地切结构树 → 点击零件定位编辑器", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const title = `E2E 装配树 ${stamp}`
    let designId = 0

    try {
      designId = await createDesign(request, title)

      // 1) 根页自动打开最近更新的产品（D3）：URL 落到 /design/:id，侧栏为结构树态
      await page.goto(`/w/${WID}/design`)
      await page.waitForURL(/\/w\/1\/design\/\d+/, { timeout: 15_000 })
      await expect(page.getByTestId("design-crumb")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId("sider-designs")).toBeVisible()
      await expect(page.getByTestId("design-outline-panel")).toBeVisible()

      // 2) 共享侧栏：点「产品列表」就地切回列表，URL / Content 不变（D4）
      const editorUrl = page.url()
      await page.getByTestId("design-nav-back").click()
      await expect(page.getByTestId("design-products-panel")).toBeVisible()
      await expect(page.getByTestId("design-outline-panel")).toHaveCount(0)
      expect(page.url()).toBe(editorUrl)

      // 3) 选本用例产品：URL 进入其编辑器，侧栏就地切到该产品结构树
      await page.getByTestId(`design-row-${designId}`).click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}$`))
      await expect(page.getByTestId("design-outline-panel")).toContainText(title)

      // 4) Content 只保留编辑器：不再有根页双栏 / 页头
      await expect(page.locator(".cn-qc-split")).toHaveCount(0)
      await expect(page.locator(".cn-page-head")).toHaveCount(0)

      // 5) 结构树层级：组件（module 实例）→ 结构分组（布尔块）→ 零件（图元）
      //    侧栏只自动展开产品根，组件需手动展开；断言收在侧栏内避免与编辑器同名文本冲突
      const nav = page.getByTestId("sider-designs")
      await expect(nav.getByText("plate")).toBeVisible({ timeout: 15_000 })
      await expect(nav.getByText("组件 · 第 10 行 · 2 个零件")).toBeVisible()
      await expandNode(page, `design-outline-node-design-${designId}-0`)
      await expect(nav.getByText("差集")).toBeVisible()
      await expect(nav.getByText("结构分组 · 第 3 行 · 2 个零件")).toBeVisible()
      await expandNode(page, `design-outline-node-design-${designId}-0-0`)
      await expect(nav.getByText("立方体")).toBeVisible()
      await expect(nav.getByText("圆柱")).toBeVisible()
      await expect(nav.getByText("零件 · 第 4 行")).toBeVisible()

      // 6) 点击零件节点 → 编辑器带 ?line=4 定位源行
      await nav.getByText("零件 · 第 4 行").click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}\\?line=4`))
      await expect(page.locator(".cm-content")).toContainText("box(size = [w, 40, t])", { timeout: 15_000 })
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
