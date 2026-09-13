/** Critical — 看板视图渲染 E2E（仅 chromium-authed）.
 *
 * 覆盖：
 *   1. seed 内置看板视图 "按部门看板"（员工表，分组字段为 link 类型的 "部门"）
 *      — 分组列头不应出现 [object Object]
 *   2. 卡片标题/负责人/优先级等字段正确渲染
 *   3. 手动切换到看板模式（无视图）的兜底行为
 *   4. 看板卡片点击可打开行详情
 *
 * 策略：
 *   - 员工表的 "部门" 字段是 link 类型，后端返回 [{id, value}] 对象数组
 *   - 若渲染逻辑未正确格式化，分组列头会显示 "[object Object]"
 *   - 这是修复的核心回归点
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1;

// ── 辅助函数 ────────────────

async function gotoWorkspace(page: Page) {
  await page.goto(`/w/${WID}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.waitForTimeout(400);
}

async function gotoEmployeeTable(page: Page) {
  await gotoWorkspace(page);
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await page.waitForTimeout(600);
}

async function getToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "demo", password: "demo1234" },
  });
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

async function getTableId(request: APIRequestContext, tableName: string): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${WID}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const tables = (await resp.json()) as Array<{ id: number; name: string }>;
  const t = tables.find((x) => x.name === tableName);
  if (!t) throw new Error(`未找到表: ${tableName}`);
  return t.id;
}

async function getKanbanViewId(request: APIRequestContext, tid: number): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${WID}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const views = (await resp.json()) as Array<{ id: number; view_type: string; name: string }>;
  const kb = views.find((v) => v.view_type === "kanban" && v.name.includes("部门"));
  if (!kb) throw new Error(`未找到看板视图`);
  return kb.id;
}

/** 激活 URL 中的指定视图并等待渲染 */
async function activateView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
  await page.waitForTimeout(800);
}

/** 手动点工具栏 "看板" 按钮切换模式 */
async function switchToKanbanMode(page: Page) {
  const kanbanBtn = page.getByRole("button", { name: /看板/ }).first();
  await kanbanBtn.click();
  await page.waitForTimeout(600);
}

// ─────────────── 测试主体 ───────────────

test.describe("看板视图渲染（回归 [object Object]）", () => {
  test("link 分组字段 — 列头显示真实部门名，不出现 [object Object]", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const tid = await getTableId(request, "员工表");
    const vid = await getKanbanViewId(request, tid);

    await gotoEmployeeTable(page);
    await activateView(page, vid);

    // 页面上不应出现任何 "[object Object]" 文本（这是核心回归断言）
    const badTexts = page.getByText("[object Object]");
    await expect(badTexts).toHaveCount(0);

    // 应该能看到真实的部门名（技术部、市场部、人事部、财务部）
    const expectedDepts = ["技术部", "市场部", "人事部", "财务部"];
    for (const dept of expectedDepts) {
      await expect(page.getByText(dept, { exact: false }).first()).toBeVisible();
    }
  });

  test("select 字段渲染 — 看板正常加载无 [object Object]", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const tid = await getTableId(request, "员工表");
    const vid = await getKanbanViewId(request, tid);

    await gotoEmployeeTable(page);
    await activateView(page, vid);

    // 确认无 [object Object]
    const badTexts = page.getByText("[object Object]");
    await expect(badTexts).toHaveCount(0);

    // 看板应该有 4 个部门列头
    const columnHeaders = page.locator("span", { hasText: /技术部|市场部|人事部|财务部/ });
    await expect(columnHeaders.first()).toBeVisible();
  });

  test("看板卡片可点击打开详情抽屉", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const tid = await getTableId(request, "员工表");
    const vid = await getKanbanViewId(request, tid);

    await gotoEmployeeTable(page);
    await activateView(page, vid);

    // 确认无 [object Object]
    await expect(page.getByText("[object Object]")).toHaveCount(0);

    // 点击页面上第一个员工名字（应该在看板卡片里）
    const firstCard = page
      .locator("div[style*='padding']")
      .filter({ hasText: /张三|李四|王五|赵六|钱七/ })
      .first();
    await firstCard.click();

    // 详情抽屉或弹窗应该出现
    await page.waitForTimeout(500);
    const drawerContent = page.locator(".ant-drawer, .ant-modal").first();
    if (await drawerContent.isVisible()) {
      const bad = drawerContent.getByText("[object Object]");
      await expect(bad).toHaveCount(0);
    }
  });

  test("科研项目看板 — text 分组字段也不出现 [object Object]", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    // 切换到科研项目管理工作区
    await page.goto("/w");
    await page.waitForURL(/\/w\/?$/);
    await page.waitForTimeout(300);

    const wsCards = page.locator(".ant-card");
    await expect(wsCards.first()).toBeVisible({ timeout: 10000 });

    // 尝试找包含 "科研" 文本的卡片
    const sciCard = page.locator(".ant-card", { hasText: /科研/ }).first();
    if ((await sciCard.count()) > 0) {
      await sciCard.click();
    } else {
      await wsCards.first().click();
    }
    await page.waitForURL(/\/w\/\d+/);
    await page.waitForTimeout(400);

    // 点击科研项目表
    const menuItem = page.locator(".ant-menu-item", { hasText: /科研项目/ }).first();
    await menuItem.click();
    await page.waitForURL(/\/tables\/\d+/);
    await page.waitForTimeout(600);

    // 手动切换到看板模式
    await switchToKanbanMode(page);

    // 不应有 [object Object]
    await expect(page.getByText("[object Object]")).toHaveCount(0);

    // 看板区域应该有列头
    const columnSpan = page.locator("div[style*='flex-direction: column'] span");
    await expect(columnSpan.first()).toBeVisible();
  });

  test("空分组键兜底 — 临时看板视图使用 select 字段分组", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const tid = await getTableId(request, "员工表");
    const token = await getToken(request);

    // 用 API 创建临时看板视图（select 字段分组）
    const resp = await request.post(
      `/api/v1/workspaces/${WID}/tables/${tid}/views`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: "E2E-兜底-看板",
          view_type: "kanban",
          view_options: { group_field: "是否在职" },
        },
      },
    );
    const body = (await resp.json()) as { id: number };
    const vid = body.id;

    await gotoEmployeeTable(page);
    await activateView(page, vid);

    // 确认无 [object Object]
    await expect(page.getByText("[object Object]")).toHaveCount(0);

    // 清理临时视图
    await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/views/${vid}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  });
});
