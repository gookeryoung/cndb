/** Critical — 帮助文档整页（ADR 0029 P2 / ADR 0105）.
 *
 * 端到端链路：顶栏入口 → `/help` 默认落点 → 两级导航切换 → 刷新与后退保持主题
 * → 典型示例清单渲染并下载 CSV → 窄屏目录抽屉可用；
 * ADR 0105：侧栏就地 L3、新主题直达、L4 深链、全局搜索空态帮助链接。
 */
import { test, expect } from "../fixtures/auth";
import fs from "node:fs";

const ANON = ["setup", "chromium-anon"];

test.describe("帮助文档整页", () => {
  test("顶栏入口 → 两级导航切换 → 刷新与后退保持主题", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/w");
    await page.getByTestId("help-btn").click();

    await expect(page).toHaveURL(/\/help\/quick-start\/overview$/);
    await expect(
      page.getByRole("heading", { name: "认识晶格协同", exact: true }),
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
      page.getByRole("heading", { name: "认识晶格协同", exact: true }),
    ).toBeVisible();
  });

  test("侧栏就地 L3：点击小节定位，新主题与 L4 深链可直达", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/help/tutorials/roles");
    const aside = page.getByTestId("help-docs-aside");
    // 当前主题在侧栏就地展开 L3（数据来自已加载正文）
    await expect(
      aside.getByRole("menuitem", { name: "行级权限规则", exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await aside.getByRole("menuitem", { name: "行级权限规则", exact: true }).click();
    await expect(page).toHaveURL(/#help-row-level$/);
    await expect(page.locator("#help-row-level")).toBeVisible();

    // 新增主题直达，并展开自己的 L3
    await page.goto("/help/tutorials/templates");
    await expect(
      page.getByRole("heading", { name: "工作区模板", exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      aside.getByRole("menuitem", { name: "模板是什么", exact: true }),
    ).toBeVisible();

    await page.goto("/help/tutorials/data-flow");
    await expect(
      page.getByRole("heading", { name: "数据流程", exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      aside.getByRole("menuitem", { name: "流程图与步骤", exact: true }),
    ).toBeVisible();

    // L4 深链：派生字段（公式）直达条目
    await page.goto("/help/tutorials/field-types#help-advanced--formula");
    await expect(
      page.locator("#help-advanced--formula"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("全局搜索空态帮助链接直达搜索主题的 L3", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/w");
    const input = page.getByTestId("global-search-input");
    await input.click();
    await input.fill("zzz-adr0105-no-hit");
    const link = page.getByTestId("global-search-help-link");
    await expect(link).toBeVisible({ timeout: 10000 });
    await link.click();
    await expect(page).toHaveURL(/\/help\/tutorials\/search#help-global$/);
    await expect(
      page.getByRole("heading", { name: "搜索与收藏", exact: true }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("典型示例清单渲染 → 下载 CSV → 切换教程主题", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    await page.goto("/help/examples/sales");
    // 示例正文拆成 5 个 L3 小节（ADR 0036 / 需求 0106），表清单在「数据表与下载」小节内
    const tables = page.getByTestId("help-subsection-tables");
    await expect(tables).toBeVisible({ timeout: 10000 });
    await expect(tables.getByText("电商销售", { exact: true })).toBeVisible();

    // 图示例（ADR 0030）：后端按真实 CSV 生成的预览图能内联渲染出来
    const preview = page.getByTestId("help-figure-canvas-example-sales-table-1");
    await expect(preview).toBeVisible({ timeout: 15000 });
    await expect(preview.locator("svg")).toHaveCount(1);

    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId("help-example-download-电商销售.csv").click();
    const download = await downloadPromise;
    // Chromium 145 会把非 ASCII 的 download 文件名回落为 "download"，
    // 文件名断言交给 ExamplesSection 单测，这里以导出内容为准。
    const csv = fs.readFileSync(await download.path(), "utf-8");
    expect(csv.replace(/^\uFEFF/, "").split("\n")[0]).toBe(
      "订单号,用户ID,商品类别,单价,数量,支付方式,评分,销售额,日期",
    );

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
