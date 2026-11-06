/** 质量检查（流水线）E2E —— 新建 YAML → 校验错误 → 修正保存 → 手动运行 → finding 过滤.
 *
 * ADR 0076 P1 前端主链路。为保证 finding 可复现：先用 API 建一张临时表，
 * 写入含空值的行，再用 `table/null-rate`（max_rate: 0）必然产出 warn 级发现物。
 * 清理统一走 API，避免失败用例残留临时表 / 流水线定义。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

/** 建临时表（含一个文本字段）+ 两行数据（第二行该字段为空，保证空值率 > 0） */
async function createFixtureTable(request: APIRequestContext, name: string): Promise<number> {
  const headers = await authHeaders(request)
  const created = await request.post(`/api/v1/workspaces/${WID}/tables`, {
    headers,
    data: { name },
  })
  expect(created.ok()).toBeTruthy()
  const table = (await created.json()) as { id: number }

  const field = await request.post(`/api/v1/workspaces/${WID}/tables/${table.id}/fields`, {
    headers,
    data: { name: "城市", field_type: "text" },
  })
  expect(field.ok()).toBeTruthy()

  const rows = await request.post(`/api/v1/workspaces/${WID}/tables/${table.id}/records/bulk-create`, {
    headers,
    data: { rows: [{ 城市: "北京" }, {}] },
  })
  expect(rows.ok()).toBeTruthy()
  return table.id
}

/** 清理失败不阻断用例结果（超时后 request context 可能已关闭） */
async function safeDelete(request: APIRequestContext, url: string) {
  await request.delete(url, { headers: await authHeaders(request) }).catch(() => undefined)
}

async function deleteTable(request: APIRequestContext, tableId: number) {
  await safeDelete(request, `/api/v1/workspaces/${WID}/tables/${tableId}`)
}

async function listWorkflows(request: APIRequestContext) {
  const headers = await authHeaders(request)
  const resp = await request.get(`/api/v1/workspaces/${WID}/pipelines`, { headers }).catch(() => null)
  if (!resp?.ok()) return []
  return (await resp.json()) as Array<{ id: number; name: string }>
}

async function deleteWorkflow(request: APIRequestContext, id: number) {
  await safeDelete(request, `/api/v1/workspaces/${WID}/pipelines/${id}`)
}

/** 用 API 建流水线定义（E2E 准备数据，避免表单输入受补全菜单干扰） */
async function createWorkflow(request: APIRequestContext, content: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/pipelines`, {
    headers: await authHeaders(request),
    data: { content },
  })
  expect(resp.status()).toBe(201)
  return ((await resp.json()) as { id: number }).id
}

/** 最小可产生发现的 DSL（空值率阈值 0 → 任一空值都命中） */
function pipelineYaml(name: string, tableName: string) {
  return [
    `name: ${name}`,
    "on:",
    "  manual: true",
    "jobs:",
    "  体检:",
    "    steps:",
    "      - uses: table/null-rate",
    "        with:",
    `          table: ${tableName}`,
    "          fields: [城市]",
    "          max_rate: 0",
  ].join("\n")
}

test.describe("质量检查", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("数据表段质量检查页可直接进入，仅呈现数据表域规则", async ({ page }) => {
    await page.goto(`/w/${WID}/pipelines`)
    await expect(page.getByText("质量检查").first()).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole("button", { name: /新建流水线/ })).toBeVisible()
    // 数据表域入口只呈现 table/* 动作与规则，不混入文档规则（ADR 0080 D4 修订）
    await expect(page.getByText(/仅数据表检查动作与规则/)).toBeVisible()
  })

  test("新建（校验错误可见）→ 修正保存 → 运行 → finding 过滤", async ({ page, request }) => {
    test.setTimeout(60_000)
    const stamp = Date.now()
    const tableName = `E2E 质量表 ${stamp}`
    const workflowName = `E2E 质量流水线 ${stamp}`
    const tableId = await createFixtureTable(request, tableName)

    try {
      await page.goto(`/w/${WID}/pipelines`)
      await page.getByRole("button", { name: /新建流水线/ }).click()

      const drawer = page.locator(".ant-drawer-section")
      const editor = drawer.getByLabel("流水线 YAML")

      // 1) 非法 DSL：保存按钮禁用 + 错误提示可见
      await editor.fill("name: 坏流水线\njobs: {}\n")
      await expect(drawer.getByText("DSL 校验未通过")).toBeVisible({ timeout: 15_000 })
      await expect(drawer.getByText(/jobs 必须是非空映射/)).toBeVisible()

      // 2) 修正为合法 DSL → 校验通过
      await editor.fill(pipelineYaml(workflowName, tableName))
      await expect(drawer.getByText(/校验通过/)).toBeVisible({ timeout: 15_000 })

      // 保存按钮位于 Drawer extra（header），不在 .ant-drawer-section 内
      // antd 会在两个汉字的按钮文案间插入空格（"保 存"），用正则匹配
      await page.locator(".ant-drawer").getByRole("button", { name: /保\s*存/ }).click()
      await expect(page.getByText(workflowName).first()).toBeVisible({ timeout: 15_000 })

      // 3) 手动运行 → 停留在运行列表并刷新历史，新运行到达终态后点行才进详情
      const item = page.locator('[data-testid^="pipeline-item-"]').filter({ hasText: workflowName })
      await expect(item).toBeVisible()
      await item.getByRole("button", { name: /运行/ }).click()
      // 不自动跳详情（URL 仍是列表页）
      await expect(page).toHaveURL(new RegExp(`/w/${WID}/pipelines$`))
      // 新建成功会自动选中该规则（右栏只显示它的运行，不再带规则名），因此按 testid 取第一条
      const runRow = page.locator('[data-testid^="run-item-"]').first()
      await expect(runRow).toBeVisible({ timeout: 30_000 })
      // 运行中显示转圈图标 + 已用时；终态后为「有告警」
      await expect(runRow.getByText("有告警")).toBeVisible({ timeout: 30_000 })
      await runRow.click()
      await page.waitForURL(/\/w\/\d+\/pipelines\/\d+/)
      // 详情页内断言，避免与列表页残留的规则行 / 历史行标签撞车
      const detail = page.getByTestId("pipeline-run-detail")
      await expect(detail).toBeVisible({ timeout: 30_000 })
      await expect(detail.getByText("有告警")).toBeVisible({ timeout: 30_000 })

      // 4) finding 可见，按严重度过滤（warn 命中、error 为空）
      await expect(page.getByText(/字段「城市」空值率/)).toBeVisible({ timeout: 15_000 })
      const segmented = page.locator(".ant-segmented")
      await segmented.getByText("错误", { exact: true }).click()
      await expect(page.getByText("没有匹配的发现物")).toBeVisible({ timeout: 15_000 })
      await segmented.getByText("告警", { exact: true }).click()
      await expect(page.getByText(/字段「城市」空值率/)).toBeVisible({ timeout: 15_000 })
    } finally {
      await deleteTable(request, tableId)
      const workflows = await listWorkflows(request)
      const created = workflows.find(workflow => workflow.name === workflowName)
      if (created) await deleteWorkflow(request, created.id)
    }
  })

  test("编辑器补全：输入触发候选 → 选择插入 → 校验与保存不回归", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const tableName = `E2E 补全表 ${stamp}`
    const workflowName = `E2E 补全流水线 ${stamp}`
    const tableId = await createFixtureTable(request, tableName)
    let workflowId = 0

    try {
      workflowId = await createWorkflow(request, pipelineYaml(workflowName, tableName))
      await page.goto(`/w/${WID}/pipelines`)
      const item = page.locator('[data-testid^="pipeline-item-"]').filter({ hasText: workflowName })
      await expect(item).toBeVisible({ timeout: 15_000 })
      await item.getByRole("button", { name: /编\s*辑/ }).click()

      const drawer = page.locator(".ant-drawer-section")
      const editor = drawer.locator(".cm-content")
      // 光标移到文末（with 块内）另起一行输入 `tab` → 触发 with 键位补全
      await editor.click()
      await page.keyboard.press("Control+End")
      await page.keyboard.press("Enter")
      await page.keyboard.type("tab")

      const menu = page.locator(".cm-tooltip-autocomplete")
      await expect(menu).toBeVisible()
      await menu.getByText("table", { exact: true }).click()
      // 补全只插入键名，继续补值确保 DSL 仍可编译
      await page.keyboard.type(`: ${tableName}`)

      // 400ms 防抖校验链路不回归
      await expect(drawer.getByText(/校验通过/)).toBeVisible({ timeout: 15_000 })

      await page.locator(".ant-drawer").getByRole("button", { name: /保\s*存/ }).click()
      await expect(page.getByText(workflowName).first()).toBeVisible({ timeout: 15_000 })
    } finally {
      if (workflowId) await deleteWorkflow(request, workflowId)
      await deleteTable(request, tableId)
    }
  })
})
