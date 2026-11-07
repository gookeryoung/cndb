/** Critical — 工作区模板导入导出（需求 0120）.
 *
 * 端到端链路：模板中心上传 .workspace-template.json → 服务端校验预览 →
 * 确认导入 → 列表出现新模板 → 导出该模板并校验下载文件名。
 */
import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]

test.describe("工作区模板导入导出", () => {
  test("上传 JSON 导入模板后可导出为 JSON 文件", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过")

    const stamp = Date.now()
    const templateName = `E2E导入模板-${stamp}`
    const payload = {
      format: "cndb.workspace-template",
      schema_version: 1,
      name: templateName,
      description: "E2E 导入导出",
      category: "测试",
      modules: ["tables", "documents"],
      version: 2,
      spec: {
        forms: [
          { key: "apply", name: "申请单", fields: [{ name: "事项", type: "text", required: true }] },
        ],
        documents: [],
        stages: [{ key: "s1", name: "阶段一", order: 1, forms: ["apply"], documents: [] }],
      },
    }

    await page.goto("/templates")
    await expect(page.getByTestId("templates-page")).toBeVisible()

    await page.getByTestId("import-template-btn").click()
    await expect(page.getByTestId("template-import-modal").locator(".ant-modal")).toBeVisible()
    await page.locator('input[type="file"]').setInputFiles({
      name: "e2e.workspace-template.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(payload)),
    })

    await expect(page.getByTestId("template-import-preview")).toBeVisible()
    await expect(page.getByText(templateName, { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "确认导入" }).click()
    await expect(page.getByText(`模板已导入：${templateName}`)).toBeVisible()

    // 列表刷新后新模板出现在左栏清单，选中后从右栏详情导出
    const row = page.getByRole("option", { name: new RegExp(templateName) })
    await expect(row).toBeVisible()
    await row.click()
    const detail = page.getByTestId("template-detail-box")
    await expect(detail.getByText(templateName, { exact: true })).toBeVisible()
    const responsePromise = page.waitForResponse(
      r => r.url().includes("/export") && r.request().method() === "GET",
    )
    const downloadPromise = page.waitForEvent("download")
    await detail.getByRole("button", { name: "导出" }).click()
    await downloadPromise
    const response = await responsePromise
    expect(response.status()).toBe(200)
    // 建议文件名由后端 Content-Disposition（RFC 5987）下发，中文名可解码
    expect(decodeURIComponent(response.headers()["content-disposition"]))
      .toContain(`${templateName}.workspace-template.json`)
  })
})
