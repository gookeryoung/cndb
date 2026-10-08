/** Critical — matrix 矩阵视图基于 seed 注入视图的端到端渲染.
 *
 * 背景：matrix 视图此前无 e2e 覆盖；seed 2026-10 视图补充后提供两类典型矩阵：
 *   - 气温天气「城市月份气候矩阵」：纵轴 城市 × 横轴 日期(月粒度)，验证日期桶列头；
 *   - 员工表「人力分布矩阵」：纵轴 部门(link) × 横轴 职位(select)，验证 link 字段归桶。
 *
 * 断言锚点（MatrixView.tsx）：matrix-view / matrix-corner / matrix-col-header /
 * matrix-row-header / matrix-cell。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";

const ANON = ["setup", "chromium-anon"];

async function openMatrixView(
  page: Page,
  request: APIRequestContext,
  workspace: string,
  tableName: string,
) {
  const wid = await getWorkspaceId(request, workspace);
  const tid = await getTableId(request, wid, tableName);
  const token = await getAdminToken(request);
  // 清用户激活视图偏好，避免测试间持久化污染
  await request
    .put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    })
    .catch(() => { });

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  const matrixBtn = page.locator('.ant-btn[data-mode="matrix"]');
  await expect(matrixBtn).toBeVisible({ timeout: 10000 });
  await matrixBtn.click();
  await settle(page);
}

test.describe("matrix 矩阵视图 — seed 注入视图渲染", () => {
  test("气温天气 城市月份气候矩阵 → 角格轴标注与月份列头", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await openMatrixView(page, request, "某地区数据", "气温天气");

    await expect(page.getByTestId("matrix-view")).toBeVisible({ timeout: 10000 });
    // 左上角纵轴/横轴标注格
    await expect(page.getByTestId("matrix-corner")).toBeVisible();
    // 日期 month 粒度列头为 YYYY-MM 日期桶；行头为城市
    const firstCol = page.getByTestId("matrix-col-header").first();
    await expect(firstCol).toBeVisible();
    expect((await firstCol.innerText()).trim()).toMatch(/^\d{4}-\d{2}/);
    await expect(page.getByTestId("matrix-row-header").first()).toBeVisible();
    // 至少渲染一个数据单元格
    await expect(page.getByTestId("matrix-cell").first()).toBeVisible();
  });

  test("员工表 人力分布矩阵 → 部门行 × 职位列分类桶", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await openMatrixView(page, request, "企业销售", "员工表");

    await expect(page.getByTestId("matrix-view")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("matrix-corner")).toBeVisible();
    // link 字段（部门）按显示名归桶为行头
    await expect(page.getByTestId("matrix-row-header").first()).toBeVisible();
    await expect(page.getByTestId("matrix-cell").first()).toBeVisible();
  });
});
