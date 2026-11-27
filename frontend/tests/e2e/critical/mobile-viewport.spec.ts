/** Critical — 移动视口冒烟（ADR 0123 P3 / D5）.
 *
 * 只跑一条关键链路（登录态 → 工作区列表 → 进入工作区落地页），验证 375px 视口下
 * 布局不横向溢出、核心入口可达：
 *   1. 工作区列表行在窄视口仍能读到完整名称（D6「名称被徽标挤没」的回归防线）；
 *   2. 页面根容器不产生横向滚动（表格容器本体是 §4#1 的例外，故这里只看页面级）；
 *   3. 从列表进入工作区落地页，落地页可见且无横向溢出。
 *
 * 视口在本文件内用 test.use 覆盖（375×812，iPhone X 一档），不依赖 playwright project：
 * 新增 project 会让 critical 全量被跑两遍（时长翻倍），D5 明确否决。
 */
import { test, expect } from "../fixtures/auth";
import { settle } from "../fixtures/settle";

const ANON = ["setup", "chromium-anon"];
const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe("移动视口冒烟（ADR 0123 P3）", () => {
  test.use({ viewport: MOBILE_VIEWPORT });

  test("工作区列表可在 375px 下读完名称，且页面无横向滚动", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto("/w");
    // 列表行渲染完成信号
    const firstRow = page.locator('[data-testid^="workspace-row-"]').first();
    await expect(firstRow).toBeVisible({ timeout: 10000 });
    await settle(page);

    // D6：行内名称占满剩余宽度、不被徽标挤成一条缝。只用「宽度 > 0」抓不到被挤的情况
    // （实测被压到 8px 仍然 > 0），故直接钉可读宽度下限：375px 视口下名称至少 60px
    // （当前实测 98px；被徽标挤压时会跌到个位数，回归立即被抓）
    const nameBox = await firstRow.locator(".cn-ws-row-name").first().boundingBox();
    expect(nameBox).not.toBeNull();
    expect(nameBox!.width).toBeGreaterThan(60);
    const nameText = (await firstRow.locator(".cn-ws-row-name").first().innerText()).trim();
    expect(nameText.length).toBeGreaterThan(0);

    // 页面级不横向溢出（表格容器例外不在本页）
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "移动视口下页面出现横向滚动").toBeLessThanOrEqual(1);
  });

  test("从工作区列表进入落地页：落地页可见且无横向溢出", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto("/w");
    const firstRow = page.locator('[data-testid^="workspace-row-"]').first();
    await expect(firstRow).toBeVisible({ timeout: 10000 });
    await firstRow.locator(".cn-ws-row-main").first().click();

    await page.waitForURL(/\/w\/\d+/);
    // 落地页可见信号：移动端一级导航收在抽屉里，入口是顶栏汉堡按钮
    // （ws-nav-* 只在桌面端常驻渲染，窄视口下不可见）
    await expect(page.getByTestId("mobile-nav-btn")).toBeVisible({ timeout: 10000 });
    await settle(page);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "移动视口下落地页出现横向滚动").toBeLessThanOrEqual(1);
  });
});
