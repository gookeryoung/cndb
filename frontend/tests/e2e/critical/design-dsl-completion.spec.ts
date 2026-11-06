/** 设计结构 DSL 编辑器自动完成 E2E（需求卡 0110 C4 / C5 / C8）.
 *
 * 走完整 UI 链路：在编辑器行首输入标识符 → 出现补全菜单 → 选择图元片段插入 →
 * 编辑器文本更新 → 预览仍编译通过。清理走 API，避免残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

const CONTENT = [
  "param width = 80",
  "box(size = [width, 40, 12])",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E DSL 自动完成", content: CONTENT },
  })
  expect(resp.status()).toBe(201)
  return ((await resp.json()) as { id: number }).id
}

async function safeDeleteDesign(request: APIRequestContext, designId: number) {
  await request
    .delete(`/api/v1/workspaces/${WID}/designs/${designId}`, {
      headers: await authHeaders(request),
    })
    .catch(() => undefined)
}

test.describe("设计结构 DSL 编辑器自动完成（0110）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("行首输入触发补全 → 选择图元片段插入 → 预览不回归", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 补全 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title)
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 光标落到文末，另起一行输入标识符（触发自动补全）
      await page.locator(".cm-content").click()
      await page.keyboard.press("Control+End")
      await page.keyboard.press("Enter")
      await page.keyboard.type("bo")

      const menu = page.locator(".cm-tooltip-autocomplete")
      await expect(menu).toBeVisible()
      await menu.getByText("box 片段", { exact: false }).click()

      // 片段按槽位展开为带签名的骨架（默认值 10）
      await expect(page.locator(".cm-content")).toContainText("box(size = [10, 10, 10])")
      // 预览随编辑重编译，仍通过且画布在
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible()
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
