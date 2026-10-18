/** 数据分析模块 E2E —— 独立于文档的工作区级模块.
 *
 * 覆盖：
 * - 工作区页签「数据分析」进入 /w/:wid/analytics
 * - 加载 seed 预置分析模板 → 回填公式 / 图表 / 分组汇总配置
 * - 运行分析 → 图表 + 分组汇总表 + 描述统计（含公式列）+ 派生数据预览
 * - 深链 ?template=<id> 刷新保持；模板另存为副本；图表聚合方式切换；CSV 导出
 * - 非法公式实时校验提示 + 运行按钮禁用（后端受限引擎拒绝非白名单表达式）
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

async function gotoAnalytics(page: any, query = "") {
  await page.goto(`/w/${WID}/analytics${query}`)
  await page.waitForURL(/\/analytics(\?.*)?$/)
  await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })
}

/** 选择 antd Select 的某个选项（下拉在 body 上渲染，需单独定位） */
async function pickSelectOption(page: any, selectTestId: string, optionText: string) {
  await page.getByTestId(selectTestId).click()
  await page.locator(".ant-select-dropdown:visible .ant-select-item-option", { hasText: optionText }).first().click()
}

/** 按名称取 seed 预置模板 id（深链用例需要真实 id） */
async function getTemplateId(request: APIRequestContext, name: string): Promise<number> {
  const token = await getAdminToken(request)
  const resp = await request.get(`/api/v1/workspaces/${WID}/analytics/templates`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const list = (await resp.json()) as Array<{ id: number; name: string }>
  const hit = list.find((t) => t.name === name)
  if (!hit) throw new Error(`未找到分析模板: ${name}`)
  return hit.id
}

test.describe("数据分析模块", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("加载预置模板「批次合格率分布」→ 运行 → 图表与描述统计", async ({ page }) => {
    await gotoAnalytics(page)

    // seed 已为该工作区预置 2 个分析模板
    await pickSelectOption(page, "analytics-template-select", "批次合格率分布")

    // 模板回填：公式表达式与图表标题均应来自后端持久化配置
    await expect(page.getByTestId("analytics-formula-expr-0")).toHaveValue(
      "round([合格数] / [实际产量] * 100, 2)",
    )
    await expect(page.getByTestId("analytics-chart-title")).toHaveValue("批次合格率分布")

    // 运行分析
    await page.getByTestId("analytics-run-btn").click()

    // 描述统计表出现，且含「合格率(%)」公式列
    const stats = page.getByTestId("analytics-stats-table")
    await expect(stats).toBeVisible({ timeout: 15_000 })
    await expect(stats).toContainText("合格率(%)")
    await expect(stats).toContainText("公式")

    // 派生数据预览表出现，包含原始字段「批次号」
    await expect(page.getByTestId("analytics-rows-table")).toContainText("批次号")

    // 图表渲染：ECharts 用 SVG renderer
    await expect(page.locator(".cn-chart, svg").first()).toBeVisible()
  })

  test("非法公式实时校验：拒绝非白名单表达式并禁用运行", async ({ page }) => {
    await gotoAnalytics(page)

    await pickSelectOption(page, "analytics-table-select", "产品批次")

    // 注入越权表达式（后端受限引擎应拒绝，绝非 eval 执行）
    await page.getByTestId("analytics-formula-expr-0").fill("__import__('os').system('ls')")

    await expect(page.getByTestId("analytics-formula-error")).toBeVisible({ timeout: 10_000 })
    await expect(page.getByTestId("analytics-run-btn")).toBeDisabled()
  })

  test("合法公式可运行：按公式键生成派生列", async ({ page }) => {
    await gotoAnalytics(page)

    await pickSelectOption(page, "analytics-table-select", "产品批次")
    await page.getByTestId("analytics-formula-expr-0").fill("round([合格数] / [实际产量] * 100, 1)")

    // 校验通过后无错误提示、按钮可用
    await expect(page.getByTestId("analytics-formula-error")).toHaveCount(0, { timeout: 10_000 })
    await expect(page.getByTestId("analytics-run-btn")).toBeEnabled()

    await page.getByTestId("analytics-run-btn").click()
    await expect(page.getByTestId("analytics-stats-table")).toBeVisible({ timeout: 15_000 })
  })

  test("深链 ?template=<id>：刷新后自动回填公式与分组汇总配置", async ({ page, request }) => {
    const templateId = await getTemplateId(request, "批次合格率分布")
    await gotoAnalytics(page, `?template=${templateId}`)

    await expect(page.getByTestId("analytics-formula-expr-0")).toHaveValue(
      "round([合格数] / [实际产量] * 100, 2)",
    )
    // 分组汇总配置随模板回填（seed 已为该模板预置「产品类别」分组）
    await expect(page.getByTestId("analytics-summary-group")).toContainText("产品类别")
    await expect(page.getByTestId("analytics-summary-topn")).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`template=${templateId}`))
    // 已保存模板不应出现未保存标记
    await expect(page.getByTestId("analytics-dirty")).toHaveCount(0)
  })

  test("分组汇总：运行后生成按产品类别分组的汇总表，可导出 CSV", async ({ page, request }) => {
    const templateId = await getTemplateId(request, "批次合格率分布")
    await gotoAnalytics(page, `?template=${templateId}`)

    await page.getByTestId("analytics-run-btn").click()
    const summary = page.getByTestId("analytics-summary-table")
    await expect(summary).toBeVisible({ timeout: 20_000 })
    await expect(summary).toContainText("产品类别")
    await expect(summary).toContainText("平均合格率(%)")
    await expect(summary).toContainText("批次数")

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("analytics-export-summary").click(),
    ])
    expect(download.suggestedFilename()).toContain(".csv")
  })

  test("图表聚合方式：切到柱状图后可选择「平均」并运行", async ({ page, request }) => {
    const templateId = await getTemplateId(request, "批次合格率分布")
    await gotoAnalytics(page, `?template=${templateId}`)

    await pickSelectOption(page, "analytics-chart-type", "柱状图")
    const agg = page.getByTestId("analytics-chart-aggregation")
    await expect(agg).toBeEnabled()
    await pickSelectOption(page, "analytics-chart-aggregation", "平均")

    await page.getByTestId("analytics-run-btn").click()
    await expect(page.getByTestId("analytics-stats-table")).toBeVisible({ timeout: 20_000 })
  })

  test("另存为副本：弹窗保存后生成新模板并进入编辑态", async ({ page, request }) => {
    const templateId = await getTemplateId(request, "批次合格率分布")
    await gotoAnalytics(page, `?template=${templateId}`)

    const copyName = `E2E 分析副本 ${Date.now()}`
    await page.getByTestId("analytics-saveas-btn").click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByTestId("analytics-template-name")).toHaveValue("批次合格率分布 副本")
    await dialog.getByTestId("analytics-template-name").fill(copyName)
    await dialog.getByRole("button", { name: /保\s*存$/ }).click()

    await expect(page.getByTestId("analytics-template-meta")).toContainText(copyName, { timeout: 15_000 })

    // API 校验：新模板已落库，且保留公式 / 图表 / 分组汇总配置
    const token = await getAdminToken(request)
    const resp = await request.get(`/api/v1/workspaces/${WID}/analytics/templates`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const list = (await resp.json()) as Array<{ name: string; config: Record<string, unknown> }>
    const created = list.find((t) => t.name === copyName)
    expect(created, "另存为的副本应出现在模板列表").toBeTruthy()
    expect(created?.config.summary).toBeTruthy()
  })

  test("智能推荐：选表后展示字段推荐，可应用推荐图表与分析列表", async ({ page }) => {
    await gotoAnalytics(page)
    await pickSelectOption(page, "analytics-table-select", "产品批次")

    // 推荐接口基于真实表字段画像返回，面板应展示维度 / 指标与典型示例入口
    const panel = page.getByTestId("analytics-recommend")
    await expect(panel).toBeVisible({ timeout: 15_000 })
    await expect(page.getByTestId("analytics-recommend-group-dimension")).toBeVisible()
    await expect(page.getByTestId("analytics-recommend-group-metric")).toBeVisible()
    await expect(page.getByTestId("analytics-recommend-examples")).toBeEnabled()

    // 一键应用推荐图表：图表配置被回填并提示
    await page.getByTestId("analytics-recommend-chart").click()
    await expect(page.getByText("已应用推荐图表")).toBeVisible()
    await expect(page.getByTestId("analytics-chart-title")).not.toHaveValue("")

    // 分析列表 Drawer 可打开并列出 seed 模板
    await page.getByTestId("analytics-manager-btn").click()
    await expect(page.getByTestId("analytics-manager")).toBeVisible()
    await expect(page.getByText("批次合格率分布")).toBeVisible()
    await expect(page.getByTestId("analytics-manager-new")).toBeVisible()
  })
})
