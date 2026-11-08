/** 设计保存策略 E2E（ADR 0125 P2：C1 / C4 / C5）.
 *
 * 覆盖：3s 自动保存只写草稿、版本号不动；手动保存才落 `manual`；重开页面出现
 * 草稿恢复提示并可恢复。版本数据经 API 预置，避免依赖编辑器输入速度。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext, Page } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

function contentOf(width: number): string {
  return `param width = ${width}\nbox(size = [width, 40, 12])`
}

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string, content: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E 版本历史", content },
  })
  expect(resp.status()).toBe(201)
  return ((await resp.json()) as { id: number }).id
}

async function saveContent(request: APIRequestContext, designId: number, content: string) {
  const resp = await request.put(`/api/v1/workspaces/${WID}/designs/${designId}/content`, {
    headers: await authHeaders(request),
    data: { content },
  })
  expect(resp.status()).toBe(200)
}

async function safeDeleteDesign(request: APIRequestContext, designId: number) {
  await request
    .delete(`/api/v1/workspaces/${WID}/designs/${designId}`, {
      headers: await authHeaders(request),
    })
    .catch(() => undefined)
}

async function openHistory(page: Page) {
  await page.getByRole("button", { name: "版本历史" }).click()
}

test.describe("设计保存策略：草稿 / 版本分离（0125 P2）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("自动保存只写草稿不涨版本；手动保存才落版；重开可恢复草稿", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 草稿分离 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title, contentOf(80))
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 编辑 → 3s → 只写草稿（C1）：状态变化但版本号仍为 v1
      await page.locator(".cm-content").click()
      await page.keyboard.press("Control+End")
      await page.keyboard.type("\n// 草稿自动保存", { delay: 20 })
      await expect(page.getByTestId("design-autosave-status")).toHaveText("草稿已保存", { timeout: 15_000 })
      await expect(page.getByTestId("design-version-tag")).toHaveText("v1", { timeout: 15_000 })

      // 历史里只有手动版本，没有自动版本分组
      await openHistory(page)
      await expect(page.getByRole("button", { name: "回看版本 1" })).toBeVisible()
      await expect(page.locator('[data-testid^="design-auto-group"]')).toHaveCount(0)

      // 关闭抽屉，避免遮罩挡住编辑器
      await page.keyboard.press("Escape")
      await expect(page.getByRole("button", { name: "回看版本 1" })).toHaveCount(0)

      // 手动保存 → v2，草稿被清空
      await page.keyboard.press("Control+s")
      await expect(page.getByTestId("design-version-tag")).toHaveText("v2", { timeout: 15_000 })

      // 再编辑产生草稿，重开页面出现恢复提示（C5）：等草稿 PUT 真正完成再刷新
      await page.locator(".cm-content").click()
      await page.keyboard.press("Control+End")
      const draftSaved = page.waitForResponse(
        resp => resp.request().method() === "PUT" && resp.url().includes("/draft"),
        { timeout: 15_000 },
      )
      await page.keyboard.type("\n// 重开恢复标记", { delay: 20 })
      await draftSaved

      await page.reload()
      const recovery = page.getByTestId("design-draft-recovery")
      await expect(recovery).toBeVisible({ timeout: 30_000 })
      await expect(recovery).toContainText("检测到未保存的编辑")
      await page.getByRole("button", { name: "恢复上次编辑" }).click()
      await expect(page.locator(".cm-content")).toContainText("// 重开恢复标记")
      await expect(recovery).toHaveCount(0)
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })

  test("版本 DIFF：手动版本类型徽标 + 任选两版 + 结构摘要先于文本差异", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 版本 DIFF ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title, contentOf(80))
      await saveContent(request, designId, contentOf(100))
      await saveContent(request, designId, contentOf(120))
      await saveContent(request, designId, contentOf(140))

      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await openHistory(page)

      // 类型徽标：全部为主动保存（C3 / D4）
      await expect(page.getByText("主动保存").first()).toBeVisible()

      // 选 v4 回看：默认对比上一版 v3（C6）
      await page.getByRole("button", { name: "回看版本 4" }).click()
      await expect(page.getByText("版本回看：v4")).toBeVisible()

      const summary = page.getByTestId("design-version-diff-summary")
      await expect(summary).toBeVisible({ timeout: 15_000 })
      await expect(summary).toContainText("参数 +0 / -0 / ~1（width）")
      await expect(summary).toContainText("节点 1 → 1")

      const diffView = page.getByTestId("document-diff")
      await expect(diffView).toBeVisible()
      await expect(diffView).toContainText("+param width = 140")

      // 摘要 DOM 顺序先于文本 diff
      const ordered = await page.evaluate(() => {
        const summaryEl = document.querySelector('[data-testid="design-version-diff-summary"]')
        const diffEl = document.querySelector('[data-testid="document-diff"]')
        if (!summaryEl || !diffEl) return false
        return Boolean(summaryEl.compareDocumentPosition(diffEl) & Node.DOCUMENT_POSITION_FOLLOWING)
      })
      expect(ordered).toBe(true)
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
