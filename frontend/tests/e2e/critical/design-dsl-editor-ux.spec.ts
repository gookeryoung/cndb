/** 结构设计 DSL 编辑器体验增强 E2E（需求卡 0127 C2 / C4 / C6）.
 *
 * 走完整 UI 链路：空白标记可见 → 输入 `{` 后回车展开并对齐右花括号 →
 * 模块体内输入变量出现「模块形参」补全。清理走 API，避免残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

const CONTENT = [
  "param width = 80",
  "module plate(d = 10) {",
  "  box(size = [d, d, d])",
  "}",
  "plate(d = width) as plate_a",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E DSL 体验增强", content: CONTENT },
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

test.describe("结构设计 DSL 编辑器体验增强（0127）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("空白标记 → 花括号回车对齐 → 模块体形参补全", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 体验 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title)
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 编辑态空白可视化
      await page.locator(".cm-content").click()
      await expect(page.locator(".cm-highlightSpace").first()).toBeVisible()

      // 光标落到文末，输入块开括号后回车：自动配对展开且右花括号对齐
      await page.keyboard.press("Control+End")
      await page.keyboard.press("Enter")
      await page.keyboard.type("system s {")
      await page.keyboard.press("Enter")

      const lineTexts = await page.locator(".cm-line").allTextContents()
      expect(lineTexts).toContain("system s {")
      expect(lineTexts.at(-1)).toBe("}")

      // 模块体内输入变量：候选 detail 出现「模块形参」
      await page.keyboard.press("Control+End")
      await page.keyboard.press("Enter")
      await page.keyboard.type("module m(d = 8) {")
      await page.keyboard.press("Enter")
      await page.keyboard.type("box")
      await page.keyboard.press("Escape")
      await page.keyboard.type("(size = [")
      await page.keyboard.type("d")

      const menu = page.locator(".cm-tooltip-autocomplete")
      await expect(menu).toBeVisible()
      await expect(menu.getByText("模块形参").first()).toBeVisible()
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
