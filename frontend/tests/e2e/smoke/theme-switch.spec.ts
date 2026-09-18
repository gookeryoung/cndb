/** Smoke — 主题切换功能.
 *
 * 精简说明（2026-09）：原 10 条 → 6 条。删"全 10 主题顺序切换"（遍历过重）；
 *      删 Modal/看板/日历深色视觉（与 api-import/kanban/calendar 重复）。
 *      保留主流程 4 条 + 深色/浅色文字对比 2 条核心回归。
 */
import { test, expect } from "../fixtures/auth";
import { settle } from "../fixtures/settle";

const AUTHS = ["chromium-authed"];
function isAuthed(): boolean {
  return AUTHS.includes(test.info().project.name);
}

/** 登录并进入工作区 */
async function gotoApp(page: Parameters<typeof test["fn"]>[0]["page"]) {
  await page.goto("/");
  await page.waitForURL(/\/w(\/\d+)?/);
}

/** 打开个人设置 Modal */
async function openSettings(page: Parameters<typeof test["fn"]>[0]["page"]) {
  const userTrigger = page.locator(".ant-layout-header .ant-dropdown-trigger").last();
  await userTrigger.waitFor({ state: 'visible' });
  await userTrigger.click();
  const menuItem = page.getByRole("menuitem", { name: "个人设置" });
  await menuItem.waitFor({ state: 'visible' });
  await menuItem.click();
  await expect(page.getByRole("dialog", { name: "个人设置" })).toBeVisible();
}

test.describe("主题切换", () => {
  test.skip(() => !isAuthed(), "需要 chromium-authed 项目（已登录）");

  test("默认主题为 modern", async ({ page }) => {
    await gotoApp(page);

    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-modern/);
    await expect(body).not.toHaveClass(/theme-dark/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("modern");
  });

  test("切换到 GitHub 深色 — body class + localStorage 更新", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    const githubDarkCard = page.locator('[data-theme-card="github-dark"]');
    await githubDarkCard.click();

    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-github-dark/);
    await expect(body).toHaveClass(/theme-dark/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("github-dark");
  });

  test("主题切换持久化 — 刷新后仍然保留", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    await page.locator('[data-theme-card="github-light"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-github-light/);

    await page.reload();
    await page.waitForURL(/\/w(\/\d+)?/);

    await expect(page.locator("body")).toHaveClass(/theme-github-light/);
    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("github-light");
  });

  test("设置面板的 Radio.Button 也能切换主题", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    const minimalRadio = page.locator(".ant-radio-button-wrapper", { hasText: "极简" });
    await minimalRadio.click();

    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-minimal/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("minimal");
  });
});

/* ─────────────── 视觉回归：主题切换后关键区域的颜色不自相矛盾 ───────────────
 * 这组测试是 Issue 修复的回归保护：
 *   - 深色模式下浅色主题卡片的文字不能发白（不能 inherit 外层浅色）
 *   - 浅色模式下深色主题卡片的文字不能发黑
 */
test.describe("主题视觉回归（防颜色自相矛盾）", () => {
  test.skip(() => !isAuthed(), "需要 chromium-authed 项目（已登录）");

  test("深色模式下 — 浅色主题卡片文字颜色必须是深色（不能 inherit 外层白字）", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    await page.locator('[data-theme-card="github-dark"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-github-dark/);
    await settle(page);

    const bodyColor = await page.evaluate(() => getComputedStyle(document.body).color);

    const lightCardIds = ["modern", "github-light", "minimal", "ocean", "forest", "sakura"] as const;
    for (const id of lightCardIds) {
      const card = page.locator(`[data-theme-card="${id}"]`).first();
      await expect(card).toBeVisible();

      const cardColor = await card.evaluate(el => getComputedStyle(el).color);
      expect(cardColor).not.toBe(bodyColor);

      const cardBg = await card.evaluate(el => getComputedStyle(el).backgroundColor);
      expect(cardBg).toMatch(/(255,\s*255,\s*255|fafafa|250,\s*250,\s*250)/);
    }
  });

  test("浅色模式下 — 深色主题卡片文字颜色必须是浅色（不能 inherit 外层黑字）", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    await page.locator('[data-theme-card="modern"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-modern/);

    const bodyColor = await page.evaluate(() => getComputedStyle(document.body).color);

    const darkCard = page.locator('[data-theme-card="github-dark"]').first();
    await expect(darkCard).toBeVisible();

    const cardColor = await darkCard.evaluate(el => getComputedStyle(el).color);
    expect(cardColor).not.toBe(bodyColor);

    const cardBg = await darkCard.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(cardBg).not.toMatch(/(255,\s*255,\s*255|fafafa)/);
  });
});
