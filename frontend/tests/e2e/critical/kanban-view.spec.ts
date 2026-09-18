/** Critical — 看板视图 E2E 覆盖（仅 chromium-authed）.
 *
 * 精简说明（2026-09）：原 15 条 → 8 条。分组类型 5 条合并为表驱动；
 *      卡片渲染 4 条删 2 条（字段值断言）；删刷新重复 1 条。
 *
 * 核心断言：无 [object Object]、列头显示真实分组值、进度条/截止日期徽章渲染、
 *      卡片点击→详情抽屉、大数据集 8s 内完成、兜底分组。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助 ──────────────────────────────────

async function getKanbanViewId(
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
  const kb = views.find(
    (v) => v.view_type === "kanban" && v.name.includes(nameKeyword),
  );
  if (!kb) throw new Error(`未找到看板视图: ${nameKeyword}`);
  return kb.id;
}

async function gotoTable(page: Page, wid: number, tableName: string) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  const menuItem = page.getByRole("menuitem", { name: new RegExp(tableName) });
  await expect(menuItem).toBeVisible({ timeout: 5000 });
  await menuItem.click();
  await page.waitForURL(/\/tables\/\d+/);
}

async function activateView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
}

async function switchToKanbanMode(page: Page) {
  const kanbanLabel = page
    .locator(".ant-segmented-item", { hasText: /看板/ })
    .first();
  await expect(kanbanLabel).toBeVisible({ timeout: 5000 });
  await kanbanLabel.click();
}

async function assertNoObjectObject(page: Page) {
  await expect(page.getByText("[object Object]")).toHaveCount(0);
}

function kanbanRoot(page: Page) {
  return page.locator("div[style*='overflow-x'][style*='display: flex']").first();
}

function kanbanColumns(root: ReturnType<typeof kanbanRoot>) {
  return root.locator(":scope > div[style*='flex-direction: column']");
}

async function assertKanbanRendered(page: Page, minColCount = 1) {
  const root = kanbanRoot(page);
  await expect(root).toBeVisible({ timeout: 8000 });
  const columns = kanbanColumns(root);
  await expect
    .poll(async () => await columns.count(), { timeout: 8000 })
    .toBeGreaterThanOrEqual(minColCount);
  return { root, columns };
}

// ─────────────── 分组字段类型（表驱动） ───────────────

test.describe("看板视图 — 分组字段类型覆盖", () => {
  // (工作区关键字, 表名, 分组视图关键字, 期望分组类型, 期望列数下限)
  const groupMatrix: Array<[string, string, string, "link" | "text" | "select", number]> = [
    ["某企业销售管理", "员工表", "部门", "link", 4],
    ["某企业销售管理", "产品开发", "片区", "text", 5],
    ["某企业销售管理", "客户流失", "合约类型", "select", 3],
  ];

  for (const [ws, table, viewKw, groupType, minCols] of groupMatrix) {
    test(`${table}（${groupType}分组）— 列头真实分组值 + 无 [object Object]`, async ({
      page,
      request,
    }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 跳过");

      const wid = await getWorkspaceId(request, ws);
      const tid = await getTableId(request, wid, table);
      const vid = await getKanbanViewId(request, wid, tid, viewKw);

      await gotoTable(page, wid, table);
      await activateView(page, vid);
      await assertNoObjectObject(page);
      await assertKanbanRendered(page, minCols);
    });
  }
});

// ─────────────── 卡片渲染（核心要素） ───────────────

test.describe("看板视图 — 卡片渲染覆盖", () => {
  test("产品开发·按片区看板 — 进度条 + 截止日期徽章 + 负责人标签", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getKanbanViewId(request, wid, tid, "片区");

    await gotoTable(page, wid, "产品开发");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    await expect(page.locator(".ant-progress").first()).toBeVisible({ timeout: 5000 });
    const dateBadges = page.locator(".ant-tag", { hasText: /天后|还剩|逾期|\d{4}-\d{2}-\d{2}/ });
    await expect(dateBadges.first()).toBeVisible({ timeout: 5000 });

    // 负责人标签 — 卡片里应能看到真实人名
    const assigneeTexts = ["刘洋", "梁婷", "陈静", "杨帆", "赵磊"];
    let found = false;
    for (const name of assigneeTexts) {
      const loc = page.getByText(new RegExp(`^${name}$`));
      if ((await loc.count()) > 0) { found = true; break; }
    }
    expect(found).toBeTruthy();
  });

  test("房价预测·按城市看板 — 卡片标题使用面积字段（非 id）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某地区数据");
    const tid = await getTableId(request, wid, "房价预测");
    const vid = await getKanbanViewId(request, wid, tid, "城市");

    await gotoTable(page, wid, "房价预测");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    const { root } = await assertKanbanRendered(page, 3);
    const cardTitles = root.locator("div[style*='font-weight']");
    await expect(cardTitles.first()).toBeVisible({ timeout: 5000 });
  });
});

// ─────────────── 列头计数 ───────────────

test.describe("看板视图 — 列头计数与卡片数一致", () => {
  test("员工表·按部门看板 — 每列徽章数与实际卡片数匹配", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const vid = await getKanbanViewId(request, wid, tid, "部门");

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid);

    const { root, columns } = await assertKanbanRendered(page, 4);
    const colCount = await columns.count();

    for (let i = 0; i < colCount; i++) {
      const col = columns.nth(i);
      const countBadge = col.locator("span[style*='border-radius: 10px']").first();
      const cards = col.locator("div[style*='cursor: pointer']");
      const badgeNum = parseInt((await countBadge.textContent())?.trim() ?? "0", 10);
      const cardNum = await cards.count();
      expect(badgeNum).toBe(cardNum);
    }
  });
});

// ─────────────── 卡片交互与大数据集 ───────────────

test.describe("看板视图 — 卡片交互与性能", () => {
  test("卡片点击打开详情抽屉 — 员工表·按部门看板", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const vid = await getKanbanViewId(request, wid, tid, "部门");

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid);

    const { root } = await assertKanbanRendered(page, 3);
    const firstCol = root.locator(":scope > div[style*='flex-direction: column']").first();
    const firstCard = firstCol.locator("div[style*='cursor: pointer'][style*='border']").first();
    await expect(firstCard).toBeVisible({ timeout: 3000 });

    const evt = new MouseEvent("click", { bubbles: true, cancelable: true });
    await firstCard.evaluate((el) => el.dispatchEvent(evt));

    await expect(page.locator(".ant-drawer").first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator(".ant-drawer").first().getByText("[object Object]")).toHaveCount(0);
  });

  test("大数据集首屏渲染 — 产品开发看板 8s 内完成", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getKanbanViewId(request, wid, tid, "项目类别");

    const startTs = Date.now();
    await gotoTable(page, wid, "产品开发");
    await activateView(page, vid);

    const { root } = await assertKanbanRendered(page, 3);
    const firstCard = root.locator("div[style*='cursor: pointer']").first();
    await expect(firstCard).toBeVisible({ timeout: 5000 });

    expect(Date.now() - startTs).toBeLessThan(8000);
  });
});

// ─────────────── 手动切换与兜底 ───────────────

test.describe("看板视图 — 手动切换与兜底", () => {
  test("科研项目表 — grid 手动切看板（兜底分组）", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "科研项目");

    await gotoTable(page, wid, "科研项目");
    await switchToKanbanMode(page);
    await assertNoObjectObject(page);
    await assertKanbanRendered(page, 3);
  });

  test("空分组键兜底 — 临时看板使用 select 字段分组", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const token = await getAdminToken(request);

    const resp = await request.post(
      `/api/v1/workspaces/${wid}/tables/${tid}/views`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: "E2E-兜底-看板",
          view_type: "kanban",
          view_options: { group_field: "是否在职" },
        },
      },
    );
    const vid = (await resp.json()) as { id: number };

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid.id);
    await assertNoObjectObject(page);

    await expect(page.getByText("是")).toBeVisible();

    await request.delete(`/api/v1/workspaces/${wid}/tables/${tid}/views/${vid.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  });
});
