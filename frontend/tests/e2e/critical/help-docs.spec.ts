/** Critical — 帮助文档整页（ADR 0029 P2）.
 *
 * 端到端链路：顶栏入口 → `/help` 默认落点 → 两级导航切换 → 刷新与后退保持主题
 * → 典型示例清单渲染并下载 CSV → 窄屏目录抽屉可用。
 */
import { test, expect } from "../fixtures/auth";

const ANON = ["setup", "chromium-anon"];

test.describe("帮助文档整页", () => {
  test("顶栏入口 → 两级导航切换 → 刷新与后退保持主题", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/w");
    await page.getByTestId("help-btn").click();

    await expect(page).toHaveURL(/\/help\/quick-start\/overview$/);
    await expect(
      page.getByRole("heading", { name: "认识 cndb", exact: true }),
    ).toBeVisible({ timeout: 10000 });
    // 桌面：两级侧栏常驻，窄屏抽屉按钮不出现
    await expect(page.getByTestId("help-docs-aside")).toBeVisible();
    await expect(page.getByTestId("help-docs-menu-btn")).toHaveCount(0);

    // 二级主题切换：URL 与正文同时更新
    await page.getByRole("menuitem", { name: "权限与角色", exact: true }).click();
    await expect(page).toHaveURL(/\/help\/tutorials\/roles$/);
    await expect(
      page.getByRole("heading", { name: "权限与角色", exact: true }),
    ).toBeVisible();

    // 刷新仍是当前主题
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "权限与角色", exact: true }),
    ).toBeVisible({ timeout: 10000 });

    // 页内目录（L3）：点击小节写入锚点，地址可直接分享
    await expect(page.getByTestId("help-docs-toc")).toBeVisible();
    await page.getByTestId("help-toc-row-level").click();
    await expect(page).toHaveURL(/#help-row-level$/);
    await expect(page.locator("#help-row-level")).toBeVisible();

    // 浏览器后退回到上一主题
    await page.goBack();
    await expect(page).toHaveURL(/\/help\/quick-start\/overview$/);
    await expect(
      page.getByRole("heading", { name: "认识 cndb", exact: true }),
    ).toBeVisible();
  });

  test("典型示例清单渲染 → 下载 CSV → 切换教程主题", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/help/examples/sales");
    const section = page.getByTestId("help-examples-section");
    await expect(section).toBeVisible({ timeout: 10000 });
    await expect(section.getByText("电商销售", { exact: true })).toBeVisible();

    // 图示例（ADR 0030）：后端按真实 CSV 生成的预览图能内联渲染出来
    const preview = page.getByTestId("help-figure-canvas-example-sales-table-1");
    await expect(preview).toBeVisible({ timeout: 15000 });
    await expect(preview.locator("svg")).toHaveCount(1);

    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId("help-example-download-电商销售.csv").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("电商销售.csv");

    await page.getByRole("menuitem", { name: "视图类型", exact: true }).click();
    await expect(page).toHaveURL(/\/help\/tutorials\/view-types$/);
  });
});

test.describe("帮助文档窄屏", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("目录抽屉可开关，选中主题后自动关闭", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/help");
    await expect(page.getByTestId("help-docs-page")).toBeVisible({ timeout: 10000 });
    // 窄屏不渲染常驻侧栏
    await expect(page.getByTestId("help-docs-aside")).toHaveCount(0);

    await page.getByTestId("help-docs-menu-btn").click();
    const drawer = page.getByTestId("help-docs-nav-drawer");
    await expect(drawer).toBeVisible();

    await drawer.getByRole("menuitem", { name: "科研项目管理", exact: true }).click();
    await expect(page).toHaveURL(/\/help\/examples\/research$/);
    await expect(
      page.getByRole("heading", { name: "科研项目管理", exact: true }),
    ).toBeVisible();
    await expect(drawer).toBeHidden();
  });
});
