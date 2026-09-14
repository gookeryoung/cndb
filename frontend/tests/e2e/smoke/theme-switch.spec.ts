/** Smoke — 主题切换功能.
 *
 * 测试范围：
 *   1. 默认进入应用时主题为 modern
 *   2. 通过设置面板可切换到 10 种主题
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
  { id: "ocean", label: "海洋", bodyClass: "theme-ocean", isDark: false },
  { id: "forest", label: "森野", bodyClass: "theme-forest", isDark: false },
  { id: "sepia", label: "纸感", bodyClass: "theme-sepia", isDark: false },
  { id: "sakura", label: "樱粉", bodyClass: "theme-sakura", isDark: false },
  { id: "midnight", label: "午夜紫", bodyClass: "theme-midnight", isDark: true },
  { id: "oled", label: "极夜黑", bodyClass: "theme-oled", isDark: true },
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

  test("按顺序切换所有 10 种主题 — 每个都能正确应用", async ({ page }) => {
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

/* ─────────────── 视觉回归：主题切换后关键区域的颜色不自相矛盾 ───────────────
 * 这组测试是 Issue 修复的回归保护：
 *   - 深色模式下浅色主题卡片的文字不能发白（不能 inherit 外层浅色）
 *   - 深色模式下表设置视图 Tab 的容器背景不能是白色
 *   - 浅色模式下深色主题卡片的文字不能发黑
 */
test.describe("主题视觉回归（防颜色自相矛盾）", () => {
  test.skip(!isAuthed(), "需要 chromium-authed 项目（已登录）");

  test("深色模式下 — 浅色主题卡片文字颜色必须是深色（不能 inherit 外层白字）", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    // 切到 GitHub 深色 — 外层 body 背景深、文字浅
    await page.locator('[data-theme-card="github-dark"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-github-dark/);

    const body = page.locator("body");
    const bodyColor = await body.evaluate(el => getComputedStyle(el).color);

    // 白色底浅色主题卡片（modern / github-light / minimal / ocean / forest / sakura）
    // 它们各自的文字颜色必须跟 bodyColor 不同（bodyColor 是浅色，卡片上文字应该是深色）
    // 注意：sepia 是米黄底（#fbf6ea），不适用白色系背景断言，故不在此列
    const lightCardIds = ["modern", "github-light", "minimal", "ocean", "forest", "sakura"] as const;
    for (const id of lightCardIds) {
      const card = page.locator(`[data-theme-card="${id}"]`).first();
      await expect(card).toBeVisible();

      // 拿到卡片根元素的文字颜色
      const cardColor = await card.evaluate(el => getComputedStyle(el).color);
      // 断言：浅色卡片文字色 ≠ 外层深色 body 的浅色文字色
      expect(cardColor).not.toBe(bodyColor);

      // 卡片背景应该是浅色调（白 / 极浅灰），不是深色
      const cardBg = await card.evaluate(el => getComputedStyle(el).backgroundColor);
      // rgba(255,255,255,...) 或 rgb(255,255,255) 或 hsl(...) 白色系
      expect(cardBg).toMatch(/(255,\s*255,\s*255|fafafa|250,\s*250,\s*250)/);
    }
  });

  test("浅色模式下 — 深色主题卡片文字颜色必须是浅色（不能 inherit 外层黑字）", async ({ page }) => {
    await gotoApp(page);
    await openSettings(page);

    // 切到现代（浅色）— 外层 body 背景浅、文字深
    await page.locator('[data-theme-card="modern"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-modern/);

    const body = page.locator("body");
    const bodyColor = await body.evaluate(el => getComputedStyle(el).color);

    // 只有一个深色主题卡片：github-dark
    const darkCard = page.locator('[data-theme-card="github-dark"]').first();
    await expect(darkCard).toBeVisible();

    const cardColor = await darkCard.evaluate(el => getComputedStyle(el).color);
    // 深色卡片文字 ≠ 外层浅色 body 的深色文字色
    expect(cardColor).not.toBe(bodyColor);

    // 卡片背景应该是深色系
    const cardBg = await darkCard.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(cardBg).not.toMatch(/(255,\s*255,\s*255|fafafa)/);
  });

  test("深色模式下 — 表设置 Modal 视图 Tab 的容器背景不是白色", async ({ page }) => {
    await gotoApp(page);

    // 切到深色主题（通过设置 Modal）
    await openSettings(page);
    await page.locator('[data-theme-card="github-dark"]').click();
    await expect(page.locator("body")).toHaveClass(/theme-github-dark/);
    // 关闭设置 Modal
    await page.keyboard.press("Escape");

    // 进入 Grid → 打开表设置 Modal
    // 先可能需要点进工作区 + 表
    if (page.url().match(/\/w\/?$/)) {
      // 在工作区列表页 — 点第一个卡片
      await page.locator(".ant-card").first().click();
      await page.waitForURL(/\/w\/\d+/);
    }
    // 在工作区/网格视图，找到表
    await page.getByRole("menuitem", { name: /产品开发|客户/ }).first().click();
    await page.waitForURL(/\/tables\/\d+/);

    // 打开表设置 Modal
    await page.locator("[data-testid='table-settings-btn']").click();
    const modalBody = page.getByRole("dialog", { name: /表设置/ }).locator(".ant-modal-body");
    await expect(modalBody).toBeVisible();

    // 切到"视图" Tab
    const viewsTab = page.locator(".ant-tabs-tab").filter({ hasText: "视图" }).first();
    await viewsTab.click();
    await expect(viewsTab).toHaveClass(/ant-tabs-tab-active/);
    await expect(page.getByText(/共 \d+ 个视图/)).toBeVisible();

    // 取视图列表容器（有边框的那个 div）的 computed 背景色
    // 找到视图 Tab 下的有 border 1px 的子 div（我们修复的那个）
    const viewListContainer = modalBody.locator("> div > div > div > div").filter({
      hasCSS: { border: /1px solid/ },
    }).first();

    if (await viewListContainer.count() > 0) {
      const bg = await viewListContainer.evaluate(el => getComputedStyle(el).backgroundColor);
      // 深色模式下不应该是白色/极浅灰
      expect(bg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
    }

    // 额外：Modal 本身的背景也不能是白色
    const modal = page.getByRole("dialog", { name: /表设置/ });
    const modalBg = await modal.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(modalBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
  });
});

/* ─────────────── 视觉回归：深色模式下看板 / 画廊 / 日历视图背景 ───────────────
 * 这组测试验证本 Issue 的核心修复：
 *   - 深色模式下看板列容器背景不能是白色（KanbanView.tsx 的硬编码 #f8fafc → var(--cn-bg-subtle)）
 *   - 深色模式下看板卡片的计数徽章背景不能是白色
 *   - 深色模式下日历视图日期格子背景层级合理（非当前月份不接近纯黑）
 */
test.describe("深色模式下看板/日历视图背景回归", () => {
  test.skip(!isAuthed(), "需要 chromium-authed 项目（已登录）");

  /** 辅助：进入指定工作区的表页面 */
  async function gotoWorkspaceTable(page: Parameters<typeof test["fn"]>[0]["page"]) {
    if (page.url().match(/\/w\/?$/)) {
      // 在工作区列表页 — 点第一个卡片
      await page.locator(".ant-card").first().click();
      await page.waitForURL(/\/w\/\d+/);
    }
    // 在工作区/网格视图，找到表
    await page.getByRole("menuitem", { name: /产品开发|客户/ }).first().click();
    await page.waitForURL(/\/tables\/\d+/);
    await page.waitForTimeout(800);
  }

  /** 辅助：切换到深色主题（如未切换） */
  async function ensureDarkTheme(page: Parameters<typeof test["fn"]>[0]["page"]) {
    const body = page.locator("body");
    if (!(await body.evaluate(el => el.classList.contains("theme-github-dark")))) {
      await openSettings(page);
      await page.locator('[data-theme-card="github-dark"]').click();
      await expect(body).toHaveClass(/theme-github-dark/);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    }
  }

  test("深色模式 — 看板列容器背景不是白色", async ({ page }) => {
    await gotoApp(page);
    await ensureDarkTheme(page);
    await gotoWorkspaceTable(page);

    // 切到看板视图（通过 Segmented 或 URL）
    const kanbanLabel = page.locator(".ant-segmented-item", { hasText: /看板/ }).first();
    if (await kanbanLabel.isVisible()) {
      await kanbanLabel.click();
      await page.waitForTimeout(1000);
    }

    // 定位看板列容器 — KanbanView 的列根 div（有 flex-direction: column 且有背景）
    const kanbanRoot = page.locator(
      "div[style*='overflow-x'][style*='display: flex']",
    ).first();
    await expect(kanbanRoot).toBeVisible({ timeout: 8000 });

    // 看板列容器（flex-direction: column 的直接子元素）
    const columns = kanbanRoot.locator(":scope > div[style*='flex-direction: column']");
    const colCount = await columns.count();
    expect(colCount).toBeGreaterThanOrEqual(1);

    // 断言第一列的 computed 背景色不是白色
    const firstCol = columns.first();
    const colBg = await firstCol.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(colBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);

    // 看板卡片的计数徽章（border-radius: 10px）背景也不是白色
    const countBadge = firstCol.locator("span[style*='border-radius: 10px']").first();
    if (await countBadge.isVisible()) {
      const badgeBg = await countBadge.evaluate(el => getComputedStyle(el).backgroundColor);
      expect(badgeBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
    }

    // 看板卡片本身的背景也不是白色
    const card = firstCol.locator(
      "div[style*='cursor: pointer'][style*='border']",
    ).first();
    if (await card.isVisible()) {
      const cardBg = await card.evaluate(el => getComputedStyle(el).backgroundColor);
      expect(cardBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
    }
  });

  test("深色模式 — 日历视图非当前月份格子背景不是近纯黑", async ({ page }) => {
    await gotoApp(page);
    await ensureDarkTheme(page);
    await gotoWorkspaceTable(page);

    // 切到日历视图（找到带日历 icon 的按钮）
    const calBtn = page
      .locator("button")
      .filter({ has: page.locator(".anticon-calendar") })
      .first();
    await expect(calBtn).toBeVisible({ timeout: 5000 });
    await calBtn.click();
    await page.waitForTimeout(1500);

    // 日历月视图根容器 — 7列 grid + border
    const monthRoot = page.locator(
      "div[style*='grid-template-columns: repeat(7, 1fr)'][style*='border: 1px solid']",
    ).first();
    const hasMonthView = await monthRoot.isVisible();

    if (hasMonthView) {
      // 找到一个非当前月份的日期格子 — 通过判断 color: var(--cn-text-disabled) 来识别
      const allCells = monthRoot.locator(":scope > div[style*='min-height']");
      const cellCount = await allCells.count();
      expect(cellCount).toBeGreaterThan(0);

      // 检查前 10 个格子的背景色，确保没有接近纯黑 (#010409)
      for (let i = 0; i < Math.min(10, cellCount); i++) {
        const cell = allCells.nth(i);
        const bg = await cell.evaluate(el => getComputedStyle(el).backgroundColor);
        // 断言：不能是 rgb(1, 4, 9) 或 rgb(0, 0, 0) 这种近纯黑
        expect(bg).not.toMatch(/rgba?\(\s*[0-9]\s*,\s*[0-9]\s*,\s*[0-9]/);
        expect(bg).not.toMatch(/rgba?\(\s*0\s*,\s*0\s*,\s*0/);
      }
    } else {
      // 如果没有月视图（可能是空状态），检查日历导航栏背景也不是白色
      const navBar = page.locator(
        "div[style*='border-bottom'][style*='background']",
      ).first();
      if (await navBar.isVisible()) {
        const navBg = await navBar.evaluate(el => getComputedStyle(el).backgroundColor);
        expect(navBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
      }
    }
  });
});
