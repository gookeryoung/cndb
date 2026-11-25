/**
 * Critical — 分析页复合数据源：多链接汇总（ADR 0159 P2）。
 *
 * 链路（全部经真实接口，不用 mock）：同一源工作区的两张不同表各建一条链接
 *（后端限制同一张表只能有一条生效中链接）→ 批准 → 分析页多选链接并按同名
 * 生成列映射 → 运行出结果 → 另存模板 → 撤回其一 → 后端整体 404（L2
 * fail-closed）+ 页面逐项标注失效且不可运行（C8）。
 *
 * 为什么必须 E2E：链接批准、复合源配置弹窗、公式校验（合成字段清单）与
 * union 执行分散在「工作区链接」与「分析」两个模块，jsdom 单测只能 mock 一侧。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { apiCall, getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]

interface TableSummary {
  id: number
  name: string
}

interface LinkPayload {
  id: number
  alias: string
  status: string
}

const NUMERIC_TYPES = new Set(["number", "integer", "decimal", "float", "currency", "percent"])

/**
 * 在源工作区里挑两张能作为 union 输入的表。
 *
 * 优先选共享同一个数值族字段名的两张表：自动列映射会生成该同名列，公式直接可用。
 * 找不到同名数值列时退回任意两张带数值字段的表——union 自动列映射按首输入生成列，
 * 另一输入该列由后端按空值补齐（ADR 0159 C1），公式仍可运行。
 */
async function pickSourceTables(
  request: APIRequestContext,
  token: string,
  sourceWid: number,
): Promise<{ tableA: TableSummary; tableB: TableSummary; numericField: string }> {
  const tables = ((await apiCall(request, token, "get", `/workspaces/${sourceWid}/tables`)).body ?? []) as TableSummary[]
  const candidates: Array<{ table: TableSummary; numeric: string[] }> = []
  for (const table of tables) {
    const res = await apiCall(request, token, "get", `/workspaces/${sourceWid}/tables/${table.id}/fields`)
    const fields = (res.body as Array<{ name: string; field_type: string }>) ?? []
    const numeric = fields.filter((f) => NUMERIC_TYPES.has(f.field_type)).map((f) => f.name)
    if (numeric.length) candidates.push({ table, numeric })
  }

  for (let i = 0; i < candidates.length; i += 1) {
    for (let j = i + 1; j < candidates.length; j += 1) {
      const shared = candidates[i].numeric.find((name) => candidates[j].numeric.includes(name))
      if (shared) {
        return { tableA: candidates[i].table, tableB: candidates[j].table, numericField: shared }
      }
    }
  }
  if (candidates.length >= 2) {
    return { tableA: candidates[0].table, tableB: candidates[1].table, numericField: candidates[0].numeric[0] }
  }
  throw new Error(`工作区 ${sourceWid} 找不到两张带数值字段的表（需要 seed 数据）`)
}

/** 找到一个「有数据表、能作为消费方」的工作区与一个「源工作区」，两者不同 */
async function pickWorkspaces(
  request: APIRequestContext,
  token: string,
): Promise<{ consumerWid: number; sourceWid: number }> {
  const res = await apiCall(request, token, "get", "/workspaces")
  const list = (res.body as Array<{ id: number; name: string }>) ?? []
  for (const ws of list) {
    const tables = (await apiCall(request, token, "get", `/workspaces/${ws.id}/tables`)).body as TableSummary[]
    if (tables?.length) {
      const other = list.find((w) => w.id !== ws.id)
      if (other) {
        const otherTables = (await apiCall(request, token, "get", `/workspaces/${other.id}/tables`))
          .body as TableSummary[]
        if (otherTables?.length) return { consumerWid: ws.id, sourceWid: other.id }
      }
    }
  }
  throw new Error("未找到两个都有数据表的工作区（需要 seed 数据）")
}

async function createAndApproveLink(
  request: APIRequestContext,
  token: string,
  consumerWid: number,
  sourceWid: number,
  tableId: number,
  alias: string,
): Promise<LinkPayload> {
  const created = await apiCall(request, token, "post", `/workspaces/${consumerWid}/links`, {
    source_workspace_id: sourceWid,
    target_table_id: tableId,
    alias,
    ttl_days: 7,
  })
  expect(created.status, JSON.stringify(created.body)).toBe(201)
  const link = created.body as LinkPayload

  const approved = await apiCall(request, token, "post", `/workspaces/${sourceWid}/links/${link.id}/approve`, {})
  expect(approved.status, JSON.stringify(approved.body)).toBe(200)
  return link
}


test.describe("分析页 · 多链接汇总（union）", () => {
  test.beforeEach(async () => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
  })

  test("两条链接建 union → 运行 → 撤回其一 → 整体失效", async ({ page, request }) => {
    test.setTimeout(60_000)
    const token = await getAdminToken(request)
    const { consumerWid, sourceWid } = await pickWorkspaces(request, token)
    const { tableA, tableB, numericField } = await pickSourceTables(request, token, sourceWid)
    const stamp = Date.now()
    const aliasA = `E2E 汇总A ${stamp}`
    const aliasB = `E2E 汇总B ${stamp}`
    const templateName = `E2E 汇总模板 ${stamp}`

    const linkA = await createAndApproveLink(request, token, consumerWid, sourceWid, tableA.id, aliasA)
    const linkB = await createAndApproveLink(request, token, consumerWid, sourceWid, tableB.id, aliasB)
    let templateId: number | null = null

    try {
      await page.goto(`/w/${consumerWid}/analytics`)
      await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })

      // 打开公式区块（默认只开「可视化」）
      const formulaToggle = page.getByTestId("analytics-block-toggle-formula")
      if ((await formulaToggle.getAttribute("aria-pressed")) !== "true") await formulaToggle.click()

      // 数据源下拉 → 搜「多链接汇总」（虚拟列表不依赖滚动位置）
      const dsSelect = page.getByTestId("analytics-table-select")
      await dsSelect.click()
      await dsSelect.locator("input").fill("多链接汇总")
      const dsDropdown = page.locator(".ant-select-dropdown:visible")
      const unionOption = dsDropdown.locator(".ant-select-item-option", { hasText: "多链接汇总" }).first()
      await expect(unionOption).toBeVisible()
      await unionOption.click()

      // 弹窗：多选两条链接 → 按同名生成列映射 → 应用
      const modal = page.getByRole("dialog")
      await expect(modal).toBeVisible()
      await modal.getByTestId("analytics-union-inputs").click()
      const inputsDropdown = page.locator(".ant-select-dropdown:visible")
      await inputsDropdown.locator(".ant-select-item-option", { hasText: aliasA }).click()
      await inputsDropdown.locator(".ant-select-item-option", { hasText: aliasB }).click()
      await page.keyboard.press("Escape")

      // 链接字段异步加载完成后自动生成同名列
      await expect(page.getByTestId("analytics-union-column-name-0")).toBeVisible({ timeout: 15_000 })
      await page.getByTestId("analytics-union-autofill").click()
      await modal.getByRole("button", { name: /应用数据源/ }).click()

      // 复合源生效：提示 + 逐项状态（C8）
      await expect(page.getByTestId("analytics-composite-source-hint")).toContainText("多链接汇总")
      await expect(page.getByTestId(`analytics-composite-input-link-${linkA.id}`)).toContainText("可读")
      await expect(page.getByTestId(`analytics-composite-input-link-${linkB.id}`)).toContainText("可读")

      // 公式走合成字段清单校验，通过后运行出结果
      await page.getByTestId("analytics-formula-expr-0").fill(`sum([${numericField}])`)
      const runBtn = page.getByTestId("analytics-run-btn")
      await expect(runBtn).toBeEnabled({ timeout: 10_000 })
      // 捕获 compute 响应：失败时把后端 detail 带进断言，避免只看到“结果区未出现”
      const [computeResp] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/analytics/compute") && r.request().method() === "POST"),
        runBtn.click(),
      ])
      expect(computeResp.status(), await computeResp.text()).toBe(200)
      await expect(page.getByTestId("analytics-export-rows")).toBeVisible({ timeout: 15_000 })

      // 另存模板：撤回链接后深链重开需要持久化配置
      await page.getByTestId("analytics-saveas-btn").click()
      const saveDialog = page.getByRole("dialog")
      await saveDialog.getByTestId("analytics-template-name").fill(templateName)
      await saveDialog.getByRole("button", { name: /保\s*存$/ }).click()
      await expect(page.getByTestId("analytics-template-meta")).toContainText(templateName, { timeout: 15_000 })

      const listRes = await apiCall(request, token, "get", `/workspaces/${consumerWid}/analytics/templates`)
      const templates = (listRes.body ?? []) as Array<{
        id: number
        name: string
        config?: { source?: Record<string, unknown> }
      }>
      const saved = templates.find((t) => t.name === templateName)
      if (!saved) throw new Error("保存的模板未出现在列表")
      templateId = saved.id
      const unionSource = saved.config?.source
      expect(unionSource?.type, "模板应固化 union 数据源").toBe("union")

      // 撤回其一：后端整体 fail-closed（不返回部分结果）
      const revoked = await apiCall(request, token, "delete", `/workspaces/${consumerWid}/links/${linkB.id}`)
      expect([204, 404]).toContain(revoked.status)
      const computeRes = await apiCall(request, token, "post", `/workspaces/${consumerWid}/analytics/compute`, {
        source: unionSource,
        formulas: [{ key: "total", expr: `sum([${numericField}])` }],
      })
      expect(computeRes.status, JSON.stringify(computeRes.body)).toBe(404)

      // 深链重开：失效项逐项标注、运行按钮禁用
      await page.goto(`/w/${consumerWid}/analytics?template=${templateId}`)
      await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })
      await expect(page.getByTestId("analytics-composite-invalid")).toContainText("整体无法运行", {
        timeout: 15_000,
      })
      await expect(page.getByTestId(`analytics-composite-input-link-${linkB.id}`)).toContainText("已失效")
      await expect(page.getByTestId("analytics-run-btn")).toBeDisabled()
    } finally {
      await apiCall(request, token, "delete", `/workspaces/${consumerWid}/links/${linkA.id}`)
      await apiCall(request, token, "delete", `/workspaces/${consumerWid}/links/${linkB.id}`)
      const cleanupTemplates = await apiCall(
        request, token, "get", `/workspaces/${consumerWid}/analytics/templates`,
      )
      const hit = ((cleanupTemplates.body ?? []) as Array<{ id: number; name: string }>)
        .find((t) => t.name === templateName)
      if (hit) {
        await apiCall(request, token, "delete", `/workspaces/${consumerWid}/analytics/templates/${hit.id}`)
      }
    }
  })
})
