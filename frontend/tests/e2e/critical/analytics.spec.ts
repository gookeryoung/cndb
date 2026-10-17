/** 数据分析模块 E2E —— 独立于文档的工作区级模块.
 *
 * 覆盖：
 * - 工作区页签「数据分析」进入 /w/:wid/analytics
 * - 加载 seed 预置分析模板 → 回填公式与图表配置
 * - 运行分析 → 图表 + 描述统计（含公式列）+ 派生数据预览
 * - 非法公式实时校验提示 + 运行按钮禁用（后端受限引擎拒绝非白名单表达式）
 */

import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]
const WID = 1

async function gotoAnalytics(page: any) {
  await page.goto(`/w/${WID}/analytics`)
  await page.waitForURL(/\/analytics$/)
  await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 10_000 })
}

/** 选择 antd Select 的某个选项（下拉在 body 上渲染，需单独定位） */
async function pickSelectOption(page: any, selectTestId: string, optionText: string) {
  await page.getByTestId(selectTestId).click()
  await page.locator(".ant-select-dropdown:visible .ant-select-item-option", { hasText: optionText }).first().click()
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
})
