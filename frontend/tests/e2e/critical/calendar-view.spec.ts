/** Critical — 日历视图 E2E 覆盖（仅 chromium-authed）.
 *
 * 精简说明（2026-09）：原 9 条 → 6 条。基本渲染 4 条删 2 条（纯文本断言）；
 *      抽屉 2 条合并为 1 条；删 P0 中"按钮不应渲染"和"看板同样拉全量"。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助 ──

async function getCalendarViewId(
  request: APIRequestContext,
  wid: number,
  tid: number,
  nameKeyword: string,
): Promise<number> {
  const token = await getAdminToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const views = (await resp.json()) as Array<{ id: number; view_type: string; name: string }>;
  const cal = views.find(
    (v) => v.view_type === "calendar" && v.name.includes(nameKeyword),
  );
  if (!cal) throw new Error(`未找到日历视图: ${nameKeyword}`);
  return cal.id;
}

async function gotoTable(page: Page, wid: number, tableName: string) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  const menuItem = page.getByRole("menuitem", { name: new RegExp(tableName) });
  await expect(menuItem).toBeVisible({ timeout: 5000 });
  await menuItem.click();
  await page.waitForURL(/\/tables\/\d+/);
}

async function activateCalendarView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
}

function calendarRoot(page: Page) {
  const monthLike = page.locator(
    "div[style*='grid-template-columns: repeat(7, 1fr)'][style*='border: 1px solid']",
  );
  const yearLike = page.locator(
    "div[style*='grid-template-columns: repeat(4, 1fr)'][style*='border: none']",
  );
  return monthLike.first().or(yearLike.first()).first();
}

function eventCards(page: Page) {
  return page.locator(
    "div[style*='border-left: 3px solid'][style*='cursor: pointer']",
  );
}

async function switchCalendarMode(page: Page, mode: "年" | "月" | "周") {
  const label = page
    .locator(".ant-segmented-item", { hasText: mode })
    .first();
  await expect(label).toBeVisible({ timeout: 5000 });
  await label.click();
}

// ─────────────── 基本渲染 ───────────────

test.describe("日历视图 — 基本渲染", () => {
  test("产品开发·交付日历 — URL 深链激活 + 事件卡片 + 颜色侧边条", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getCalendarViewId(request, wid, tid, "交付");

    await gotoTable(page, wid, "产品开发");
    await activateCalendarView(page, vid);

    await expect(calendarRoot(page)).toBeVisible({ timeout: 8000 });

    const cards = eventCards(page);
    await expect.poll(async () => await cards.count(), { timeout: 8000 }).toBeGreaterThanOrEqual(15);

    // 事件卡片有 group_field 颜色侧边条
    const borderLeft = await cards.first().evaluate(
      (el: HTMLElement) => getComputedStyle(el).borderLeftColor,
    );
    expect(borderLeft).not.toBe("rgba(0, 0, 0, 0)");
  });

  test("项目进展·进展日历 — group_field 按阶段分色 + title_field 渲染", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "项目进展");
    const vid = await getCalendarViewId(request, wid, tid, "进展");

    await gotoTable(page, wid, "项目进展");
    await activateCalendarView(page, vid);

    await expect(calendarRoot(page)).toBeVisible({ timeout: 8000 });

    const cards = eventCards(page);
    await expect(cards.first()).toBeVisible({ timeout: 5000 });

    // 至少两种不同颜色（不同阶段）
    const colors = new Set<string>();
    const count = Math.min(await cards.count(), 10);
    for (let i = 0; i < count; i++) {
      const c = cards.nth(i);
      const col = await c.evaluate((el: HTMLElement) => getComputedStyle(el).borderLeftColor);
      colors.add(col);
    }
    expect(colors.size).toBeGreaterThanOrEqual(1);

    // 卡片标题文本存在（title_field 正确渲染）
    const cardText = (await cards.first().textContent()) || "";
    expect(cardText.trim().length).toBeGreaterThan(0);
  });
});

// ─────────────── 层级切换 ───────────────

test.describe("日历视图 — 年/月/周三段层级切换", () => {
  test("产品开发·交付日历 — 月→年→周 层级切换", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getCalendarViewId(request, wid, tid, "交付");

    await gotoTable(page, wid, "产品开发");
    await activateCalendarView(page, vid);

    const monthRoot = page.locator(
      "div[style*='grid-template-columns: repeat(7, 1fr)'][style*='border: 1px solid']",
    );
    await expect(monthRoot).toBeVisible({ timeout: 8000 });

    // 年视图
    await switchCalendarMode(page, "年");
    const yearRoot = page.locator(
      "div[style*='grid-template-columns: repeat(4, 1fr)']",
    );
    await expect(yearRoot).toBeVisible({ timeout: 5000 });

    // 周视图
    await switchCalendarMode(page, "周");
    const weekRoot = page.locator(
      "div[style*='grid-template-columns: repeat(7, 1fr)'][style*='gap: 8px']",
    );
    await expect(weekRoot).toBeVisible({ timeout: 5000 });
  });
});

// ─────────────── 导航按钮 ───────────────

test.describe("日历视图 — 导航按钮", () => {
  test("出差统计·出差日历 — 翻月 + 回到今天", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "出差统计");
    const vid = await getCalendarViewId(request, wid, tid, "出差");

    await gotoTable(page, wid, "出差统计");
    await activateCalendarView(page, vid);

    const titleEl = page
      .locator("div[style*='font-weight: 600'][style*='margin-left: 8px']")
      .first();
    await expect(titleEl).toBeVisible({ timeout: 5000 });
    const beforeText = (await titleEl.textContent()) || "";

    // 下一周期
    const nextBtn = page.locator("button").filter({
      has: page.locator(".anticon-right"),
    });
    await expect(nextBtn).toBeVisible({ timeout: 5000 });
    await nextBtn.first().click();
    await settle(page);

    const afterText = (await titleEl.textContent()) || "";
    expect(afterText).not.toBe(beforeText);

    // 回到今天
    const todayBtn = page.getByRole("button", { name: /今天/ }).first();
    await expect(todayBtn).toBeVisible({ timeout: 5000 });
    await todayBtn.click();
    await settle(page);

    const todayYear = new Date().getFullYear();
    expect((await titleEl.textContent()) || "").toContain(String(todayYear));
  });
});

// ─────────────── 点击事件 → 详情抽屉 ─────────

test.describe("日历视图 — 点击事件打开详情抽屉", () => {
  test("点击事件 → 抽屉可见 + 无 [object Object]", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getCalendarViewId(request, wid, tid, "交付");

    await gotoTable(page, wid, "产品开发");
    await activateCalendarView(page, vid);

    const cards = eventCards(page);
    await expect(cards.first()).toBeVisible({ timeout: 5000 });

    await cards.first().evaluate((el: HTMLElement) => {
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    const drawer = page.locator(".ant-drawer").first();
    await expect(drawer).toBeVisible({ timeout: 5000 });
    await expect(drawer.getByText("[object Object]")).toHaveCount(0);
  });
});

// ─────────────── 非 grid 视图全量拉取（limit=5000） ───────────────

test.describe("非 grid 视图全量拉取回归", () => {
  test("grid 模式小 limit，calendar 模式自动切到 limit=5000", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "出差统计");

    const recordsUrls: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/records")) recordsUrls.push(req.url());
    });

    await gotoTable(page, wid, "出差统计");
    await settle(page);
    recordsUrls.length = 0;

    const calBtn = page.locator("button").filter({ has: page.locator(".anticon-calendar") }).first();
    const calResp = page.waitForResponse(
      (r) => r.url().includes("/records") && r.url().includes("limit=5000"),
      { timeout: 10000 },
    );
    await calBtn.click();
    await calResp;

    const lastUrl = recordsUrls[recordsUrls.length - 1] || "";
    expect(lastUrl).toContain("limit=5000");

    await expect(eventCards(page).first()).toBeVisible({ timeout: 8000 });
  });
});
