/** Critical — K 线视图（数据源示例/自选股）：一只股一行、行内 JSON 序列.
 *
 * 覆盖链路：进入自选股 → 切 K 线 → 默认落在有序列的标的 → 切换标的（标题/最新价联动）
 *          → 周期切周线（行内派生序列）→ 复权切后复权（seed 未填该列 → 空态提示）
 *          → 切回前复权恢复图表。
 *
 * 依赖：make seed 注入的自选股表 + 「K线图」kline 视图 + 股市日线.csv 离线样本。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";

const ANON = ["setup", "chromium-anon"];

async function gotoTable(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tableName: string,
) {
  const tid = await getTableId(request, wid, tableName);
  const token = await getAdminToken(request);
  // 清用户激活视图偏好，避免测试间持久化污染（默认应落在「K线图」）
  await request
    .put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    })
    .catch(() => { });

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  // 自选股表的 seed 默认视图就是「K线图」（kline），grid 专属的「新增行」按钮不会渲染；
  // 以视图模式切换中的 kline 按钮作为页面就绪信号，避免依赖初始 grid 渲染的竞态。
  await expect(page.locator('[data-mode="kline"]')).toBeVisible({
    timeout: 10000,
  });
}

test.describe("K 线视图 — 自选股行内序列", () => {
  test("默认选中 / 切换标的 / 周期 / 复权空态", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "数据源示例");
    await gotoTable(page, request, wid, "自选股");

    // seed 注入「K线图」kline 视图 → 模式按钮存在
    const klineBtn = page.locator('.ant-btn[data-mode="kline"]');
    await expect(klineBtn).toBeVisible({ timeout: 5000 });
    await klineBtn.click();
    await settle(page);

    // 图表就绪：默认跳过无序列的行，落在首只有序列的标的（视图按股票代码升序）
    const container = page.getByTestId("kline-chart-container");
    await expect(container).toHaveAttribute("data-chart-ready", "true", {
      timeout: 10000,
    });
    await expect(container.locator("svg").first()).toBeVisible();

    const title = page.getByTestId("kline-title");
    await expect(title).toContainText(/^(sh|sz|bj)\d{6}/);

    // 左列表切到另一只有序列的标的 → 标题/最新价联动
    const price = page.getByTestId("kline-latest-price");
    const beforePrice = await price.innerText();
    await page
      .locator('[data-testid="kline-stock-list"] button', { hasText: "sz000001" })
      .click();
    await settle(page);
    await expect(title).toContainText("sz000001");
    await expect(price).not.toHaveText(beforePrice);
    await expect(container).toHaveAttribute("data-chart-ready", "true");

    // 周期切周线：seed 已按日线派生周线前复权列
    await page.getByTestId("kline-period").getByText("周线", { exact: true }).click();
    await settle(page);
    await expect(page.getByTestId("kline-source")).toContainText("周线前复权");
    await expect(container).toHaveAttribute("data-chart-ready", "true");

    // 复权切后复权：seed 不填后复权列 → 空态提示（不崩溃）
    await page.getByTestId("kline-adjust").getByText("后复权", { exact: true }).click();
    await settle(page);
    const emptySeries = page.getByTestId("kline-empty-series");
    await expect(emptySeries).toBeVisible({ timeout: 10000 });
    await expect(emptySeries).toContainText("暂无数据");

    // 切回前复权 → 图表恢复
    await page.getByTestId("kline-adjust").getByText("前复权", { exact: true }).click();
    await settle(page);
    await expect(container).toHaveAttribute("data-chart-ready", "true");
    await expect(page.getByTestId("kline-empty-series")).toHaveCount(0);
  });
});
