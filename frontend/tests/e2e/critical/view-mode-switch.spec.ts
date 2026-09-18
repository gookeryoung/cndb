/** Critical — 右侧视图类型切换按钮根据数据表 views 动态配置.
 *
 * 背景：GridPage 右上角的模式按钮组（表格/看板/画廊/日历/甘特/WBS）之前硬编码全部 6 个按钮，
 *      无论当前数据表是否拥有对应 view_type 的视图。
 *
 * 本次变更：从 views[] 提取存在的 view_type 集合，仅渲染有对应视图的按钮；
 *          若仅 grid 一种视图类型则整个按钮组隐藏（避免单按钮视觉噪音）.
 *
 * 精简说明（2026-09）：原 5 条"换表+换按钮数"测试结构完全一致，合并为表驱动循环；
 *      删掉各条内的 API 侧断言（seed 数据自检，非前端行为）；
 *      切换行为回归合并为 1 条.
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";

// ──────────────────────────── 通用辅助 ────────────────────────────

async function gotoTable(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tableName: string,
) {
  const tid = await getTableId(request, wid, tableName);
  const token = await getAdminToken(request);
  // 清用户激活视图偏好，避免测试间持久化污染
  await request
    .put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    })
    .catch(() => { });

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  // 视图按钮渲染由后续 assertModeButtonCount 的 toHaveCount 自动等待，无需固定 sleep
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({
    timeout: 10000,
  });
}

// ──────────────────────────── 按钮组结构断言 ────────────────────────────

/** 断言 Space.Compact 模式按钮组存在且内部按钮数量 === expectedCount */
async function assertModeButtonCount(page: Page, expectedCount: number) {
  const modeBtns = page.locator(".ant-btn[data-mode]");
  if (expectedCount === 0) {
    await expect(modeBtns).toHaveCount(0, { timeout: 3000 });
  } else {
    await expect(modeBtns).toHaveCount(expectedCount, { timeout: 5000 });
  }
}

/** 断言指定模式按钮在 DOM 中存在/不存在 */
async function assertModeButtonExists(
  page: Page,
  mode: string,
  exists: boolean,
) {
  const btn = page.locator(`.ant-btn[data-mode="${mode}"]`);
  if (exists) {
    await expect(btn).toBeVisible({ timeout: 3000 });
  } else {
    await expect(btn).toHaveCount(0);
  }
}

// ──────────────────────────── 测试用例 ────────────────────────────

const ANON = ["setup", "chromium-anon"];

test.describe("视图类型切换按钮 — 按数据表 views 动态配置", () => {
  // 表驱动矩阵：(工作区, 表名, 期望按钮数)，覆盖单视图隐藏与多视图组合
  const tableMatrix: Array<[string, string, number]> = [
    ["企业销售", "部门表", 0],        // 仅 grid → 按钮组隐藏
    ["科研项目管理", "科研项目", 3],  // grid+kanban+gallery
    ["科研项目管理", "项目进展", 4],  // grid+kanban+gallery+calendar
    ["项目管理", "WBS任务分解", 5],   // grid+kanban+calendar+gantt+wbs
    ["企业销售", "产品开发", 5],      // grid+kanban+gallery+calendar+gantt（缺 wbs）
  ];

  for (const [ws, table, expectedCount] of tableMatrix) {
    test(`${table}（${ws}）→ 模式按钮组显示 ${expectedCount} 个按钮`, async ({
      page,
      request,
    }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 跳过");

      const wid = await getWorkspaceId(request, ws);
      await gotoTable(page, request, wid, table);
      await assertModeButtonCount(page, expectedCount);
    });
  }
});

// ──────────────────────────── 切换行为回归 ────────────────────────────

test.describe("动态按钮组 — 点击切换行为回归", () => {
  test("科研项目表点看板按钮 → 切到 kanban 视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    await gotoTable(page, request, wid, "科研项目");

    await assertModeButtonCount(page, 3);

    // 点击看板按钮 → Segmented 跳转到 kanban 类型的视图
    const kanbanBtn = page.locator('.ant-btn[data-mode="kanban"]');
    await kanbanBtn.click();
    await settle(page);

    const selectedSeg = page.locator(".ant-segmented-item-selected").first();
    const selectedText = (await selectedSeg.innerText()).trim();
    expect(selectedText).toMatch(/看板/);
  });
});

// ──────────────────────────── 跨表导航切换回归 ────────────────────────────

test.describe("跨表导航 — 模式按钮组跟随数据表 views 变化", () => {
  test("部门表 → 产品开发表 → 客户流失表：按钮组数量动态变化", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "企业销售");

    // 1. 部门表：0 个模式按钮（仅 grid）
    await gotoTable(page, request, wid, "部门表");
    await assertModeButtonCount(page, 0);

    // 2. 产品开发表：5 个模式按钮（缺 wbs）
    await gotoTable(page, request, wid, "产品开发");
    await assertModeButtonCount(page, 5);
    await assertModeButtonExists(page, "wbs", false);

    // 3. 客户流失表：3 个模式按钮（grid+kanban+gallery）
    await gotoTable(page, request, wid, "客户流失");
    await assertModeButtonCount(page, 3);
    await assertModeButtonExists(page, "wbs", false);
  });
});
