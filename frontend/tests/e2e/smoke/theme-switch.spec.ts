/** Smoke — 主题切换功能.
 *
 * 测试范围：
 *   1. 默认进入应用时主题为 modern
 *   2. 通过设置面板可切换到 4 种主题
 *   3. 每次切换后 body 上对应 class 被更新
 *   4. 切换后 localStorage 中值正确
 *   5. 深色主题同时带 body.theme-dark class（向后兼容）
 *   6. 刷新页面后主题持久化
 */
import { test, expect } from "@playwright/test";

const AUTHS = ["chromium-authed"];
function isAuthed(): boolean {
  return AUTHS.includes(test.info().project.name);
}

/** 登录并进入工作区 */
async function gotoApp(page: Parameters<typeof test["fn"]>[0]["page"]) {
  await page.goto("/");
  // 可能是 /w（多工作区列表）或 /w/{wid}/tables（已自动进入）
  await page.waitForURL(/\/w(\/\d+)?/);
}

/** 打开个人设置 Modal */
async function openSettings(page: Parameters<typeof test["fn"]>[0]["page"]) {
  // 用户头像 Dropdown — 点击用户图标/头像打开菜单
  const userAvatar = page.locator(".ant-layout-header .ant-avatar, .ant-layout-header .ant-dropdown-trigger").first();
  await userAvatar.click();
  // 点击"个人设置"
  await page.getByRole("menuitem", { name: "个人设置" }).click();
  // 等待 Modal 出现
  await expect(page.getByRole("dialog", { name: "个人设置" })).toBeVisible();
}

const THEMES = [
  { id: "modern", label: "现代", bodyClass: "theme-modern", isDark: false },
  { id: "github-dark", label: "GitHub 深色", bodyClass: "theme-github-dark", isDark: true },
  { id: "github-light", label: "GitHub 浅色", bodyClass: "theme-github-light", isDark: false },
  { id: "minimal", label: "极简", bodyClass: "theme-minimal", isDark: false },
] as const;

test.describe("主题切换", () => {
  test.skip(!isAuthed, "需要 chromium-authed 项目（已登录）");

  test("默认主题为 modern", async ({ page }) => {
    await gotoApp(page);

    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-modern/);
    // 默认不是深色
    await expect(body).not.toHaveClass(/theme-dark/);

    // localStorage 应该有值
    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("modern");
  });

  test("切换到 GitHub 深色 — body class + localStorage 更新", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    // 点击卡片式选择器里的 GitHub 深色
    const githubDarkCard = page.locator('[data-theme-card="github-dark"]');
    await githubDarkCard.click();

    // body class 更新
    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-github-dark/);
    // 向后兼容：同时有 theme-dark
    await expect(body).toHaveClass(/theme-dark/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("github-dark");
  });

  test("按顺序切换所有 4 种主题 — 每个都能正确应用", async ({ page }) => {
    await gotoApp(page);

    for (const t of THEMES) {
      // 设置 Modal 可能需要重新打开（如果上次关闭了也没事）
      const modal = page.getByRole("dialog", { name: "个人设置" });
      if (!(await modal.isVisible())) {
        await openSettings(page);
      }

      await page.locator(`[data-theme-card="${t.id}"]`).click();

      const body = page.locator("body");
      await expect(body).toHaveClass(new RegExp(t.bodyClass));

      // 深色主题必须带 theme-dark；浅色主题不能带
      if (t.isDark) {
        await expect(body).toHaveClass(/theme-dark/);
      } else {
        await expect(body).not.toHaveClass(/theme-dark/);
      }

      const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
      expect(stored).toBe(t.id);
    }
  });

  test("主题切换持久化 — 刷新后仍然保留", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    // 先切到 GitHub 浅色
    await page.locator('[data-theme-card="github-light"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-github-light/);

    // 刷新页面
    await page.reload();
    await page.waitForURL(/\/w(\/\d+)?/);

    // 主题应该被恢复
    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-github-light/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("github-light");
  });

  test("设置面板的 Radio.Button 也能切换主题", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    // 找到 Radio.Button 里的 "极简" 并点击
    const minimalRadio = page.getByRole("radio", { name: "极简" });
    await minimalRadio.click();

    const body = page.locator("body");
    await expect(body).toHaveClass(/theme-minimal/);

    const stored = await page.evaluate(() => localStorage.getItem("cndb_theme"));
    expect(stored).toBe("minimal");
  });
});
