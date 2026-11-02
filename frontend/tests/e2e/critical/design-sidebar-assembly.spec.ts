/** 设计侧栏三级装配 E2E（ADR 0084 C1/C2/C3）—— 系统 → 组件 → 零件.
 *
 * 走完整 UI 链路：经 API 建一份带 `system` 声明的设计，进入设计模块后
 * 在侧栏展开设计 → 系统 → 组件，断言三级装配层级与源行元信息；
 * 再点击零件节点，校验跳转到编辑器并带 `?line=` 源行参数。
 * 清理统一走 API，避免失败用例残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 源行位置（1 基）：param 1 / module 2-9 / 空行 10 / system 11 / 组件实例 12 / 零件 13 */
const CONTENT = [
  "param width = 80",
  "module chassis(w) {",
  "  difference {",
  "    box(size = [w, 40, 12])",
  "    translate([w / 2, 20, -1]) {",
  "      cyl(d = 8, h = 14)",
  "    }",
  "  }",
  "}",
  "",
  "system rover {",
  "  chassis(width)",
  "  sphere(r = 6)",
  "}",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E 三级装配", content: CONTENT },
  })
  expect(resp.status()).toBe(201)
  const body = (await resp.json()) as { id: number }
  return body.id
}

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

test.describe("设计侧栏三级装配（0084）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("侧栏出现系统 / 组件 / 零件三级 → 点击零件定位编辑器", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const title = `E2E 三级装配 ${stamp}`
    let designId = 0

    try {
      designId = await createDesign(request, title)

      // 1) 进入设计模块，侧栏出现设计清单
      await page.goto(`/w/${WID}/design`)
      await page.waitForURL(/\/w\/1\/design$/)
      await expect(page.getByTestId("sider-designs")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId(`design-node-${designId}`)).toBeVisible({ timeout: 10_000 })

      // 2) 展开设计 → 系统级节点（system 声明）
      await expandNode(page, `design-node-${designId}`)
      await expect(page.getByText("rover")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("系统 · 第 11 行 · 3 个零件")).toBeVisible()

      // 3) 展开系统 → 组件（module 实例）与系统直属零件
      await expandNode(page, `design-outline-node-design-${designId}-0`)
      await expect(page.getByText("chassis")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("组件 · 第 12 行 · 2 个零件")).toBeVisible()
      await expect(page.getByText("球体")).toBeVisible()
      await expect(page.getByText("零件 · 第 13 行")).toBeVisible()

      // 4) 点击零件节点 → 编辑器带 ?line=13 定位源行
      await page.getByText("零件 · 第 13 行").click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}\\?line=13`))
      await expect(page.locator(".cm-content")).toContainText("sphere(r = 6)", { timeout: 15_000 })
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
