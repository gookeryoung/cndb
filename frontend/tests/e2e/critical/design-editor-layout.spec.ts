/** 设计编辑器布局 E2E（ADR 0103 P0：C2 / C3 / C4 / C6）—— 分栏预设 / 拖拽 / 视口工具条 / 状态条 / 工具栏单行.
 *
 * 走完整 UI 链路：经 API 建一份带参数的设计，进入编辑器断言
 * 工具栏恒单行、三档预设改变分栏比例并落 localStorage、拖拽改变比例、
 * 视口悬浮工具条（定向 / 布满 / 网格开关）、状态条展示单位与统计。
 * 清理统一走 API，避免失败用例残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext, Page } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

const CONTENT = [
  "param width = 80",
  "param height = 12",
  "difference {",
  "  box(size = [width, 40, height])",
  "  translate([0, 0, -1]) cyl(d = 8, h = height + 2)",
  "}",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E 编辑器布局", content: CONTENT },
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

/** 分栏比例（编辑器列宽占 workbench 的百分比） */
async function editorRatio(page: Page): Promise<number> {
  const box = await page.getByTestId("design-workbench").boundingBox()
  const pane = await page.locator(".cn-dsl-pane--editor").boundingBox()
  if (!box || !pane) throw new Error("workbench 未布局")
  return Math.round((pane.width / box.width) * 100)
}

test.describe("设计编辑器布局（0103 P0）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("工具栏单行 / 分栏预设与拖拽 / 视口工具条 / 状态条 / 参数面板常驻", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 布局 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title)
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 1) 工具栏恒单行（C6）：高度不随内容 / 屏宽换行膨胀
      const toolbar = page.locator(".cn-dsl-toolbar")
      const singleLine = await toolbar.boundingBox()
      expect(singleLine!.height).toBeLessThan(64)

      // 2) 默认均分（D10），预设切换改变比例并落 localStorage（C2）
      expect(await editorRatio(page)).toBeGreaterThan(45)
      expect(await editorRatio(page)).toBeLessThan(55)

      await page.getByText("视口", { exact: true }).click()
      await expect.poll(() => editorRatio(page)).toBeLessThan(45)
      expect(await page.evaluate(() => localStorage.getItem("cn-design-editor-split"))).toBe("40")

      await page.getByText("编辑", { exact: true }).click()
      await expect.poll(() => editorRatio(page)).toBeGreaterThan(55)
      expect(await page.evaluate(() => localStorage.getItem("cn-design-editor-split"))).toBe("60")

      // 3) 拖拽 splitter（C2 / D3）：向右拖 → 编辑器变宽
      const before = await editorRatio(page)
      const splitter = page.getByTestId("design-splitter")
      const handle = await splitter.boundingBox()
      await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2)
      await page.mouse.down()
      await page.mouse.move(handle!.x + handle!.width / 2 - 160, handle!.y + handle!.height / 2, { steps: 8 })
      await page.mouse.up()
      await expect.poll(() => editorRatio(page)).toBeLessThan(before - 5)
      const persisted = Number(await page.evaluate(() => localStorage.getItem("cn-design-editor-split")))
      expect(persisted).toBeGreaterThanOrEqual(25)
      expect(persisted).toBeLessThanOrEqual(75)

      // 4) 视口悬浮工具条（C3）：七向定向 / 布满 / 网格开关
      await expect(page.getByTestId("design-viewport-toolbar")).toBeVisible()
      await page.getByRole("button", { name: "视图定向" }).click()
      for (const label of ["主视", "俯视", "仰视", "左视", "右视", "后视", "等轴测"]) {
        await expect(page.getByText(label, { exact: true })).toBeVisible()
      }
      await page.getByText("俯视", { exact: true }).click()
      await page.getByRole("button", { name: "布满视图" }).click()

      const gridToggle = page.getByTestId("design-grid-toggle")
      await expect(gridToggle).toHaveAttribute("aria-pressed", "true")
      await gridToggle.click()
      await expect(gridToggle).toHaveAttribute("aria-pressed", "false")

      // 5) 状态条（C4 / D5）：单位取 IR units.length，节点 / 三角来自 onStats
      await expect(page.getByTestId("design-statusbar")).toHaveText(/mm · 节点 \d+ · 三角 \d+/)

      // 6) 参数面板常驻（C5）：改参即时重编译 + 一键重置
      const params = page.getByTestId("design-params-panel")
      await expect(params).toBeVisible()
      await page.getByLabel("参数 width").fill("120")
      await page.getByLabel("参数 width").blur()
      await expect(page.getByText("已覆盖").first()).toBeVisible({ timeout: 15_000 })
      await page.getByRole("button", { name: /重\s*置/ }).click()
      await expect(page.getByText("已覆盖")).toBeHidden({ timeout: 15_000 })

      // 7) 折叠 / 展开面板（C5）：折叠后细条仍可展开
      await page.getByTestId("design-params-collapse").click()
      await expect(page.getByTestId("design-params-expand")).toBeVisible()
      await page.getByTestId("design-params-expand").click()
      await expect(page.getByTestId("design-params-collapse")).toBeVisible()
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })

  test("窄屏（<1024px）不渲染 splitter，工具条与面板仍可达", async ({ page, request }) => {
    test.setTimeout(90_000)
    const title = `E2E 窄屏布局 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title)
      await page.setViewportSize({ width: 900, height: 900 })
      await page.goto(`/w/${WID}/design/${designId}`)
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })

      await expect(page.getByTestId("design-splitter")).toBeHidden()
      await expect(page.getByTestId("design-viewport-toolbar")).toBeVisible()
      await expect(page.getByTestId("design-statusbar")).toBeVisible()
      await expect(page.getByTestId("design-params-panel")).toBeVisible()
      // 工具栏仍单行
      const toolbar = await page.locator(".cn-dsl-toolbar").boundingBox()
      expect(toolbar!.height).toBeLessThan(64)
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
