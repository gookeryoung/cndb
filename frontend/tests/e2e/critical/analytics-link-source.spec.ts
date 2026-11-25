/**
 * Critical — 分析页使用「工作区链接」作为数据源（ADR 0158 P2）。
 *
 * 链路（全部经真实接口，不用 mock）：建链接 → 源工作区批准 → 分析页把链接选为数据源
 * → 运行出结果 → 撤回链接 → 数据源失效。
 *
 * 为什么必须 E2E：链接授权（批准 / 批量加成员 / 撤回）与分析页数据源下拉、运行载荷
 * 分散在「工作区链接」与「分析」两个模块，jsdom 单测只能各自 mock 一侧。
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

async function firstTableId(request: APIRequestContext, token: string, wid: number): Promise<TableSummary> {
  const res = await apiCall(request, token, "get", `/workspaces/${wid}/tables`)
  const tables = (res.body as TableSummary[]) ?? []
  if (!tables.length) throw new Error(`工作区 ${wid} 没有数据表（需要 seed 数据）`)
  return tables[0]
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
): Promise<{ link: LinkPayload; tableId: number; numericField: string }> {
  const table = await firstTableId(request, token, sourceWid)
  const created = await apiCall(request, token, "post", `/workspaces/${consumerWid}/links`, {
    source_workspace_id: sourceWid,
    target_table_id: table.id,
    alias: "E2E 链接源",
    ttl_days: 7,
  })
  expect(created.status, JSON.stringify(created.body)).toBe(201)
  const link = created.body as LinkPayload

  const approved = await apiCall(request, token, "post", `/workspaces/${sourceWid}/links/${link.id}/approve`, {})
  expect(approved.status, JSON.stringify(approved.body)).toBe(200)

  const fieldsRes = await apiCall(request, token, "get", `/workspaces/${consumerWid}/links/${link.id}/fields`)
  const fields = (fieldsRes.body as { fields: Array<{ name: string; field_type: string }> }).fields ?? []
  const numeric = fields.find((f) => ["number", "integer", "decimal", "currency", "percent"].includes(f.field_type))
  return { link, tableId: table.id, numericField: numeric?.name ?? fields[0]?.name ?? "" }
}

test.describe("分析页 · 链接数据源", () => {
  test.beforeEach(async () => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
  })

  test("批准链接 → 选为数据源 → 运行 → 撤回后失效", async ({ page, request }) => {
    const token = await getAdminToken(request)
    const { consumerWid, sourceWid } = await pickWorkspaces(request, token)
    const { link, numericField } = await createAndApproveLink(request, token, consumerWid, sourceWid)
    expect(numericField, "源表至少需要一个可分析的字段").not.toBe("")

    try {
      await page.goto(`/w/${consumerWid}/analytics`)
      await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })

      // 打开公式区块（默认只开「可视化」）
      const formulaToggle = page.getByTestId("analytics-block-toggle-formula")
      if ((await formulaToggle.getAttribute("aria-pressed")) !== "true") await formulaToggle.click()

      // 数据源下拉里出现「外部链接（只读）」分组，选中链接
      const select = page.getByTestId("analytics-table-select")
      await select.click()
      // 下拉是虚拟列表：直接搜索链接名，避免依赖滚动位置
      await select.locator("input").fill("E2E 链接源")
      const dropdown = page.locator(".ant-select-dropdown:visible")
      await expect(dropdown.getByText("外部链接（只读）")).toBeVisible()
      await dropdown.locator(".ant-select-item-option", { hasText: "E2E 链接源" }).first().click()

      // 只读来源提示（来源工作区 / 到期 / 行级与字段隐藏照旧）
      const hint = page.getByTestId("analytics-link-source-hint")
      await expect(hint).toBeVisible()
      await expect(hint).toContainText("只读引用")

      // 配一条公式并运行
      await page.getByTestId("analytics-formula-expr-0").fill(`sum([${numericField}])`)
      const runBtn = page.getByTestId("analytics-run-btn")
      await expect(runBtn).toBeEnabled()
      await runBtn.click()

      // 结果区出现（导出入口只在有结果时渲染，用它做稳妥判定）
      await expect(page.getByTestId("analytics-export-rows")).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("metric_1（公式）").first()).toBeVisible()

      // 撤回链接 → 重新进入分析页，链接不再出现在数据源里（不静默伪装成空数据源）
      const revoked = await apiCall(request, token, "delete", `/workspaces/${consumerWid}/links/${link.id}`)
      expect([204, 404]).toContain(revoked.status)
      await page.reload()
      await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })
      await page.getByTestId("analytics-table-select").click()
      const dropdownAfter = page.locator(".ant-select-dropdown:visible")
      await expect(dropdownAfter.locator(".ant-select-item-option", { hasText: "E2E 链接源" })).toHaveCount(0)
    } finally {
      await apiCall(request, token, "delete", `/workspaces/${consumerWid}/links/${link.id}`)
    }
  })
})
