/** Critical — 主页「我的视图」收藏面板（ADR 0021）.
 *
 * 端到端链路：数据表视图栏星标收藏 → 主页右侧面板出现该视图 → 展开详情 →
 * 「打开视图」落回同一视图深链 → 取消收藏后面板回到空态。
 *
 * 用例开始 / 结束都清空收藏，避免 admin 偏好跨用例残留。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";
import { settle } from "../fixtures/settle";

const ANON = ["setup", "chromium-anon"];

/** 清空当前用户的收藏视图（用例隔离） */
async function clearFavoriteViews(request: APIRequestContext) {
  const token = await getAdminToken(request);
  await request.put("/api/v1/accounts/preferences/favorite-views", {
    headers: { Authorization: `Bearer ${token}` },
    data: { view_ids: [] },
  });
}

test.describe("主页「我的视图」收藏面板", () => {
  test("视图栏星标 → 主页面板展开详情 → 打开视图 → 取消收藏", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "企业销售");
    const tid = await getTableId(request, wid, "客户流失");
    await clearFavoriteViews(request);

    try {
      // 1. 数据表视图栏收藏当前激活视图
      await page.goto(`/w/${wid}/tables/${tid}`);
      await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({
        timeout: 10000,
      });

      const favoriteBtn = page.getByTestId("view-favorite-btn");
      await expect(favoriteBtn).toHaveAttribute("aria-pressed", "false", {
        timeout: 10000,
      });
      const activeViewName = (
        await page.locator(".ant-segmented-item-selected").first().innerText()
      ).trim();

      await favoriteBtn.click();
      await expect(favoriteBtn).toHaveAttribute("aria-pressed", "true", {
        timeout: 10000,
      });
      // 成功后端写入才跳转，避免主页读到旧偏好
      await expect(page.getByText(/已收藏/).first()).toBeVisible({ timeout: 10000 });

      // 2. 主页右侧面板出现该收藏
      await page.goto("/w");
      const panel = page.getByTestId("my-views-panel");
      await expect(panel).toBeVisible({ timeout: 10000 });

      const row = panel.locator('[data-testid^="my-view-row-"]').first();
      await expect(row).toBeVisible({ timeout: 10000 });
      await expect(panel.getByText(activeViewName, { exact: true })).toBeVisible();

      // 3. 展开详情 → 打开视图落回同一视图深链
      await row.locator('[data-testid^="my-view-expand-"]').click();
      const detail = panel.locator('[data-testid^="my-view-detail-"]').first();
      await expect(detail).toBeVisible();
      await expect(detail.getByText(/筛选 \d+ 条 · 排序 \d+ 条/)).toBeVisible();

      await panel.locator('[data-testid^="my-view-open-"]').first().click();
      await page.waitForURL(new RegExp(`/w/${wid}/tables/${tid}\\?view=\\d+`));
      await settle(page);

      // 4. 回主页取消收藏 → 面板空态
      await page.goto("/w");
      const panelAgain = page.getByTestId("my-views-panel");
      await panelAgain
        .locator('[data-testid^="my-view-expand-"]')
        .first()
        .click({ timeout: 10000 });
      await panelAgain.locator('[data-testid^="my-view-unfavorite-"]').first().click();
      await expect(panelAgain.getByTestId("my-views-empty")).toBeVisible({
        timeout: 10000,
      });
    } finally {
      await clearFavoriteViews(request);
    }
  });
});
