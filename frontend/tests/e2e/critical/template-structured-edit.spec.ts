/** Critical — 工作区模板结构化编辑（ADR 0121 P2）.
 *
 * 端到端链路：模板中心新建模板 → 抽屉内结构化新增字段（不碰 JSON）→
 * 大纲搜索 / 分组折叠 → JSON 高级页签确认结构 → 保存 → 详情展示新字段。
 */
import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]

test.describe("工作区模板结构化编辑", () => {
  test("结构化新增字段并保存模板", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过")

    const stamp = Date.now()
    const templateName = `E2E结构化模板-${stamp}`

    await page.goto("/templates")
    await expect(page.getByTestId("templates-page")).toBeVisible()

    await page.getByTestId("create-template-btn").click()
    const drawer = page.getByTestId("template-editor-drawer")
    await expect(drawer).toBeVisible()

    await page.getByTestId("template-name").fill(templateName)

    // 起始骨架含一个表单与一个阶段，直接进入表单分区新增字段
    await page.getByTestId("outline-form-form_1").click()
    await page.getByRole("button", { name: /新增字段/ }).click()
    const modal = page.locator(".ant-modal").filter({ hasText: "编辑字段" })
    await expect(modal).toBeVisible()
    await modal.getByRole("textbox").first().fill("预算金额")
    await modal.getByRole("button", { name: "保存字段" }).click()

    await expect(drawer.getByText("预算金额").first()).toBeVisible()
    await expect(drawer.getByText("结构通过")).toBeVisible()

    // 大纲搜索过滤与分组折叠
    const search = page.getByTestId("template-outline-search")
    await search.fill("表单1")
    await expect(page.getByTestId("outline-form-form_1")).toBeVisible()
    await search.fill("不存在的结构")
    await expect(drawer.getByText(/没有匹配/)).toBeVisible()
    await search.fill("")

    // JSON 高级页签只读确认：结构化改动已进入同一份草稿
    await drawer.getByRole("button", { name: /JSON（高级）/ }).click()
    const specText = await page.getByTestId("template-spec-text").inputValue()
    expect(specText).toContain("预算金额")
    await drawer.getByRole("button", { name: /概览/ }).click()

    await page.getByTestId("template-save-btn").click()
    await expect(page.getByText("模板已创建")).toBeVisible()

    const row = page.getByRole("option", { name: new RegExp(templateName) })
    await expect(row).toBeVisible()
    await row.click()

    const detail = page.getByTestId("template-detail-box")
    await detail.getByRole("tab", { name: /表单（1）/ }).click()
    await detail.getByRole("button", { name: /表单1/ }).click()
    await expect(detail.getByText("预算金额")).toBeVisible()
  })
})
