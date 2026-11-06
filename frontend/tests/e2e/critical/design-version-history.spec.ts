/** 设计版本历史 E2E（ADR 0113 P2：C1 / C2 / C4 / C5 / C6）.
 *
 * 覆盖：自动保存落 `auto` 小版本并在历史中折叠 / 展开；版本类型徽标；
 * 任选两版对比（结构摘要先于文本 diff）。版本数据经 API 预置，避免依赖编辑器输入速度。
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

async function saveContent(
  request: APIRequestContext,
  designId: number,
  content: string,
  changeType: "manual" | "auto",
) {
  const resp = await request.put(`/api/v1/workspaces/${WID}/designs/${designId}/content`, {
    headers: await authHeaders(request),
    data: { content, change_type: changeType },
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
  await page.getByRole("button", { name: "更多" }).click()
  await page.getByText(/版本历史（\d+）/).click()
}

test.describe("设计版本历史与 DIFF（0113 P2）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("自动保存落 auto 小版本，历史折叠为「N 个自动小版本」并可展开", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 自动小版本 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title, contentOf(80))
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 编辑 → 停止输入 3s → 自动保存为 auto 版本（C2 / Q1）
      await page.locator(".cm-content").click()
      await page.keyboard.press("Control+End")
      await page.keyboard.type("\n// 自动保存备注", { delay: 20 })
      await expect(page.getByTestId("design-autosave-status")).toHaveText("已自动保存", { timeout: 15_000 })
      await expect(page.getByTestId("design-version-tag")).toHaveText("v2", { timeout: 15_000 })

      // 历史里自动版本折叠，展开可逐条回看（C4）
      await openHistory(page)
      const group = page.getByTestId("design-auto-group-v-2")
      await expect(group).toContainText("1 个自动小版本")
      await group.click()
      await expect(page.getByRole("button", { name: "回看版本 2" })).toBeVisible()
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })

  test("版本 DIFF：类型徽标 + 任选两版 + 结构摘要先于文本差异", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 版本 DIFF ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title, contentOf(80))
      await saveContent(request, designId, contentOf(100), "auto")
      await saveContent(request, designId, contentOf(120), "auto")
      await saveContent(request, designId, contentOf(140), "manual")

      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await openHistory(page)

      // 类型徽标：主动保存 / 自动（C1 / C4）；连续 auto 折叠
      await expect(page.getByText("主动保存").first()).toBeVisible()
      const group = page.getByTestId("design-auto-group-v-3")
      await expect(group).toContainText("2 个自动小版本")
      await group.click()

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
