/** 设计结构 E2E（需求 0083 C1–C4 / ADR 0084 C1）—— 侧栏装配树展示层级 + 节点定位源行.
 *
 * 走完整 UI 链路：经 API 建一份带模块 / 布尔分组 / 图元的设计，进入设计模块默认页
 * （/w/:wid/design），在侧栏展开装配树，断言 组件 → 结构分组 → 零件 三层与源行元信息；
 * 再点击零件节点，校验跳转到编辑器并带 `?line=` 源行参数。
 * 主区已恢复设计管理页（ADR 0084 C5），装配树迁到侧栏。
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
}

test.describe("设计结构（0083 / 0084）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("侧栏展开装配树 → 组件 / 分组 / 零件带源行 → 点击零件定位编辑器", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const title = `E2E 装配树 ${stamp}`
    let designId = 0

    try {
      designId = await createDesign(request, title)

      // 1) 设计模块默认页为设计管理页，页签激活；装配树落在侧栏（ADR 0084 D4 / C5）
      await page.goto(`/w/${WID}/design`)
      await page.waitForURL(/\/w\/1\/design$/)
      await expect(page.getByTestId("design-crumb")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId("design-tab-structure")).toHaveAttribute("aria-selected", "true")
      await expect(page.getByTestId("sider-designs")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId(`design-node-${designId}`)).toBeVisible({ timeout: 10_000 })

      // 2) 展开设计 → 懒加载大纲，出现组件（module 实例）
      await expandNode(page, `design-node-${designId}`)
      await expect(page.getByText("plate")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("组件 · 第 10 行 · 2 个零件")).toBeVisible()

      // 3) 展开组件 → 结构分组（布尔块）
      await expandNode(page, `design-outline-node-design-${designId}-0`)
      await expect(page.getByText("差集")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("结构分组 · 第 3 行 · 2 个零件")).toBeVisible()

      // 4) 展开分组 → 零件（图元）与源行
      await expandNode(page, `design-outline-node-design-${designId}-0-0`)
      await expect(page.getByText("立方体")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("圆柱")).toBeVisible()
      await expect(page.getByText("零件 · 第 4 行")).toBeVisible()

      // 5) 点击零件节点 → 编辑器带 ?line=4 定位源行
      await page.getByText("零件 · 第 4 行").click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}\\?line=4`))
      await expect(page.locator(".cm-content")).toContainText("box(size = [w, 40, t])", { timeout: 15_000 })
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
