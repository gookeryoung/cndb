/** 表单模块 E2E（critical）.
 *
 * 覆盖：导航 Tab 顺序（数据资产 → 表单 → 报表）/ 表单列表渲染 /
 * 表单运行器全链路（新增数据 → 提交 → 行出现 → 删除确认 → 行消失）.
 * 前置：e2e-server 已 seed「某企业销售管理」工作区（wid=1，员工表含
 * 姓名 text required / 职位 select / 薪资 number 等字段）。
 */

import { test, expect } from "../fixtures/auth"
import { getAdminToken, getWorkspaceId, getTableId } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

let formId = 0

/** 通过 API 建表单定义（员工表：姓名 / 职位 / 薪资 三字段，姓名必填）. */
async function ensureForm(request: any): Promise<number> {
  const token = await getAdminToken(request)
  const headers = { Authorization: `Bearer ${token}` }
  const resp = await request.get(`/api/v1/workspaces/${WID}/forms`, { headers })
  const existing = (await resp.json()) as Array<{ id: number; name: string }>
  const hit = existing.find((f) => f.name === "员工信息登记")
  if (hit) return hit.id

  const tid = await getTableId(request, WID, "员工表")
  const created = await request.post(`/api/v1/workspaces/${WID}/forms`, {
    headers,
    data: {
      table_id: tid,
      name: "员工信息登记",
      description: "E2E 表单链路验证",
      field_config: [
        { field_name: "姓名", editable: true, visible: true, required: true },
        { field_name: "职位", editable: true, visible: true },
        { field_name: "薪资", editable: true, visible: true },
      ],
      use_role: "",
      edit_role: "",
      delete_role: "",
    },
  })
  expect(created.status(), "表单创建成功").toBe(201)
  const body = (await created.json()) as { id: number }
  return body.id
}

test.describe("表单模块", () => {
  test("导航 Tab 顺序为 数据资产 → 表单 → 报表", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    const tabs = page.getByRole("tablist").first().getByRole("tab")
    await expect(tabs.filter({ hasText: "数据资产" })).toBeVisible()
    await expect(tabs.filter({ hasText: /^表单/ })).toBeVisible()
    await expect(tabs.filter({ hasText: /报表/ })).toBeVisible()

    const names = (await tabs.allTextContents()).map((t) => t.trim())
    const idxAssets = names.findIndex((n) => n.includes("数据资产"))
    const idxForms = names.findIndex((n) => n.startsWith("表单"))
    const idxReports = names.findIndex((n) => n.includes("报表"))
    expect(idxAssets).toBeLessThan(idxForms)
    expect(idxForms).toBeLessThan(idxReports)
  })

  test("表单列表页展示 API 创建的表单（权限阈值标签）", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    formId = await ensureForm(request)
    expect(formId).toBeGreaterThan(0)

    await page.goto(`/w/${WID}/forms`)
    await expect(page.locator("h3", { hasText: /^表单/ })).toBeVisible()
    await expect(page.getByText("员工信息登记")).toBeVisible()
    await expect(page.getByText("员工表")).toBeVisible()
  })

  test("表单运行器全链路：新增数据提交 → 行出现 → 删除确认 → 行消失", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const fid = await ensureForm(request)

    await page.goto(`/w/${WID}/forms/${fid}`)
    // meta 渲染：标题 + 所属表 tag
    await expect(page.locator("h3", { hasText: "员工信息登记" })).toBeVisible()
    await expect(page.getByText("员工表", { exact: true })).toBeVisible()

    // 打开新增 Drawer
    await page.getByRole("button", { name: /新\s*增\s*数\s*据/ }).click()
    const drawer = page.getByRole("dialog")
    await expect(drawer).toBeVisible()

    // 姓名（text）
    await drawer.getByLabel("姓名").fill("E2E测试员工")
    // 职位（select）
    await drawer.getByLabel("职位").click()
    await page.locator(".ant-select-item-option-content", { hasText: "工程师" }).click()

    await drawer.getByRole("button", { name: /提\s*交/ }).click()
    await expect(page.getByText("提交成功")).toBeVisible()
    await expect(page.locator(".ant-table-tbody").getByText("E2E测试员工")).toBeVisible()

    // 删除该行（aria-label 动态包含行 id）
    await page.locator('button[aria-label^="删除第"]').first().click()
    const confirm = page.getByRole("dialog")
    await confirm.getByRole("button", { name: /删\s*除/ }).click()
    await expect(page.getByText("已删除")).toBeVisible()
    await expect(page.locator(".ant-table-tbody").getByText("E2E测试员工")).toHaveCount(0)
  })
})
