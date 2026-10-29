/** Critical — gallery 卡片画廊视图基于 seed 注入视图的端到端渲染（ADR 0022）.
 *
 * 背景：数据源示例工作区新增两张 LLM 抓取内容表，默认视图均为 gallery：
 *   - 国际形势发展动态「资讯画廊」：标题 / 摘要 / 彩色标签 / 日期徽章 / 元信息，12 张卡；
 *   - 行业政策与合规台账「政策台账画廊」：标题 / 摘要 / 彩色标签 / 元信息，8 张卡。
 *
 * 断言锚点（GalleryView.tsx）：gallery-view / gallery-count / gallery-card /
 * gallery-card-title / gallery-summary / gallery-tag / gallery-meta。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";

const ANON = ["setup", "chromium-anon"];

async function openGalleryTable(
  page: Page,
  request: APIRequestContext,
  tableName: string,
) {
  const wid = await getWorkspaceId(request, "数据源示例");
  const tid = await getTableId(request, wid, tableName);
  const token = await getAdminToken(request);
  // 清用户激活视图偏好，让默认视图（seed 的 gallery）生效
  await request
    .put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    })
    .catch(() => { });

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByTestId("gallery-view")).toBeVisible({ timeout: 10000 });
  await settle(page);
}

test.describe("gallery 卡片画廊 — seed 注入视图渲染", () => {
  test("国际形势发展动态 → 默认落资讯画廊，12 张卡 + 标签/摘要 + 点击开行详情", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await openGalleryTable(page, request, "国际形势发展动态");

    await expect(page.getByTestId("gallery-count")).toHaveText("共 12 条");
    await expect(page.getByTestId("gallery-card")).toHaveCount(12);
    // 标题 / 摘要 / 彩色标签 / 元信息
    await expect(page.getByTestId("gallery-card-title").first()).toBeVisible();
    await expect(page.getByTestId("gallery-summary").first()).toBeVisible();
    await expect(page.getByTestId("gallery-tag").first()).toBeVisible();
    await expect(page.getByTestId("gallery-meta").first()).toBeVisible();
    // 日期徽章：seed 数据日期为 2026-10-22，12 张卡均显示
    await expect(page.getByText("2026-10-22").first()).toBeVisible();

    // 点击整卡打开行详情抽屉
    await page.getByTestId("gallery-card").first().click();
    await expect(page.getByText(/行详情 #\d+/)).toBeVisible({ timeout: 10000 });
  });

  test("行业政策与合规台账 → 政策台账画廊 8 张卡", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await openGalleryTable(page, request, "行业政策与合规台账");

    await expect(page.getByTestId("gallery-count")).toHaveText("共 8 条");
    await expect(page.getByTestId("gallery-card")).toHaveCount(8);
    await expect(page.getByTestId("gallery-card-title").first()).toBeVisible();
    await expect(page.getByTestId("gallery-tag").first()).toBeVisible();
    await expect(page.getByTestId("gallery-summary").first()).toBeVisible();
  });

  test("切到工作区其它页签再返回，画廊仍按默认视图渲染（不回落表格）", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await openGalleryTable(page, request, "国际形势发展动态");
    await expect(page.getByTestId("gallery-card")).toHaveCount(12);

    // 工作区页签「数据源同步」→ 切回「数据表」页签 → 侧栏点回本表（真实用户路径；
    // 需求 0065 后数据源页无侧栏，表列表只在「数据表」段显示）
    await page.locator(".ant-tabs-tab", { hasText: "数据源同步" }).first().click();
    await expect(page).toHaveURL(/\/datasource/);
    await page.locator(".ant-tabs-tab", { hasText: "数据表" }).first().click();
    await page.getByRole("menuitem", { name: /国际形势发展动态/ }).first().click();

    // 返回后必须仍是画廊，且卡片齐全（回归：视图状态被 reset 后未重新匹配，mode 回落 grid）
    await expect(page.getByTestId("gallery-view")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("gallery-card")).toHaveCount(12);
  });
});
