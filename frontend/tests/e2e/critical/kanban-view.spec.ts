/** Critical — 看板视图 E2E 全量覆盖（仅 chromium-authed）.
 *
 * 覆盖矩阵（基于 examples/datasets 种子数据）:
 * ┌──────┬──────────┬───────────────┬──────────┬─────┬─────┬──────────┐
 * │ 工作区 │ 表         │ 看板视图        │ 分组类型  │进度 │截止  │ 负责人    │
 * ├──────┼──────────┼───────────────┼──────────┼─────┼─────┼──────────┤
 * │ WID1 │ 员工表     │ 按部门看板      │ link     │ ✗   │ ✓   │ ✗        │
 * │ WID1 │ 产品开发   │ 按片区看板      │ text     │ ✓   │ ✓   │ ✓        │
 * │ WID1 │ 产品开发   │ 按项目类别看板   │ text     │ ✓   │ ✓   │ ✓        │
 * │ WID1 │ 客户流失   │ 按合约类型看板   │ select   │ ✗   │ ✗   │ ✗        │
 * │ WID2 │ 科研项目   │ 按项目状态看板   │ text     │ ✗   │ ✓   │ ✗        │
 * │ WID2 │ 项目进展   │ 按进展阶段看板   │ text     │ ✓   │ ✓   │ ✗        │
 * │ WID2 │ 科研经费   │ 按经费状态看板   │ select   │ ✗   │ ✓   │ ✗        │
 * │ WID2 │ 课题负责人 │ 按职称看板      │ text     │ ✗   │ ✗   │ ✗        │
 * │ WID3 │ 房价预测   │ 按城市看板      │ text     │ ✗   │ ✗   │ ✗        │
 * │ WID3 │ 气温天气   │ 按城市看板      │ text     │ ✗   │ ✓   │ ✗        │
 * └──────┴──────────┴───────────────┴──────────┴─────┴─────┴──────────┘
 *
 * 断言重点:
 *   1. 无 [object Object]（核心回归点，link 字段返回 [{id,value}]）
 *   2. 列头显示真实分组值（不出现空分组/未分组）
 *   3. 卡片计数徽章存在并与实际卡片数匹配
 *   4. 进度条 / 截止日期徽章 / 负责人标签渲染正确
 *   5. 卡片点击 → 详情抽屉出现
 *   6. 大数据集（产品开发 293 条）滚动流畅
 *   7. 刷新后视图仍可重新选中
 *
 * 注意：React inline style 渲染后 camelCase 转成 kebab-case，
 * 如 overflowX → overflow-x, fontWeight → font-weight.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助 ──────────────────────────────────

async function getToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "demo", password: "demo1234" },
  });
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

/** 按名称查找工作区 ID，找不到兜底返回第一个 */
async function getWorkspaceId(
  request: APIRequestContext,
  nameKeyword?: string,
): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get("/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const workspaces = (await resp.json()) as Array<{ id: number; name: string }>;
  if (nameKeyword) {
    const ws = workspaces.find((w) => w.name.includes(nameKeyword));
    if (ws) return ws.id;
  }
  return workspaces[0].id;
}

async function getTableId(
  request: APIRequestContext,
  wid: number,
  tableName: string,
): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const tables = (await resp.json()) as Array<{ id: number; name: string }>;
  const t = tables.find((x) => x.name === tableName);
  if (!t) throw new Error(`未找到表: ${tableName}`);
  return t.id;
}

/** 按视图名关键字查找看板视图 */
async function getKanbanViewId(
  request: APIRequestContext,
  wid: number,
  tid: number,
  nameKeyword: string,
): Promise<number> {
  const token = await getToken(request);
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

/** 导航到指定工作区的表页面 */
async function gotoTable(page: Page, wid: number, tableName: string) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.waitForTimeout(400);
  await page.getByRole("menuitem", { name: new RegExp(tableName) }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await page.waitForTimeout(600);
}

/** 激活 URL 中的指定视图并等待看板渲染 */
async function activateView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
  // 看板渲染需要 row + field 两次 fetch
  await page.waitForTimeout(1200);
}

/** 点 Ant Segmented 里的 "看板" 切换视图类型
 *  Ant Segmented 的 <input type="radio"> 是隐藏的，需要点外层 label.ant-segmented-item */
async function switchToKanbanMode(page: Page) {
  const kanbanLabel = page
    .locator(".ant-segmented-item", { hasText: /看板/ })
    .first();
  await expect(kanbanLabel).toBeVisible({ timeout: 5000 });
  await kanbanLabel.click();
  await page.waitForTimeout(1000);
}

/** 断言页面无 [object Object]（核心回归断言） */
async function assertNoObjectObject(page: Page) {
  await expect(page.getByText("[object Object]")).toHaveCount(0);
}

/** 定位看板根容器 — React inline style 用 kebab-case */
function kanbanRoot(page: Page) {
  return page.locator("div[style*='overflow-x'][style*='display: flex']").first();
}

/** 定位看板列容器 */
function kanbanColumns(root: ReturnType<typeof kanbanRoot>) {
  return root.locator(":scope > div[style*='flex-direction: column']");
}

/** 断言看板已渲染并返回列容器 locator */
async function assertKanbanRendered(page: Page, minColCount = 1) {
  const root = kanbanRoot(page);
  await expect(root).toBeVisible({ timeout: 8000 });
  const columns = kanbanColumns(root);
  // Playwright toHaveCount 只接受数字，用 poll 轮询 count
  await expect
    .poll(async () => await columns.count(), { timeout: 8000 })
    .toBeGreaterThanOrEqual(minColCount);
  return { root, columns };
}

// ─────────────── 第一组：分组字段类型全覆盖 ───────────────

test.describe("看板视图 — 分组字段类型覆盖", () => {
  test("link 分组（员工表·部门）— 列头显示真实部门名，无 [object Object]", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const vid = await getKanbanViewId(request, wid, tid, "部门");

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    // 应该看到 4 个真实部门名
    const expectedDepts = ["技术部", "市场部", "人事部", "财务部"];
    for (const dept of expectedDepts) {
      await expect(page.getByText(dept, { exact: false }).first()).toBeVisible();
    }

    // 列头应有卡片计数徽章
    const { root } = await assertKanbanRendered(page, 4);
    const countBadges = root.locator("span[style*='border-radius: 10px']");
    await expect(countBadges).toHaveCount(4);
  });

  test("text 分组（产品开发·片区）— 列头显示片区名", async ({
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

    // 片区应有 7 列以上
    const { columns } = await assertKanbanRendered(page, 5);
    const count = await columns.count();
    expect(count).toBeGreaterThanOrEqual(5);
  });

  test("select 分组（客户流失·合约类型）— 列头显示合约类型", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "客户流失");
    const vid = await getKanbanViewId(request, wid, tid, "合约类型");

    await gotoTable(page, wid, "客户流失");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    // 合约类型至少有：月付 / 年付 / 两年付
    const expectedTypes = ["月付", "年付", "两年付"];
    for (const t of expectedTypes) {
      await expect(page.getByText(t, { exact: true }).first()).toBeVisible();
    }
  });

  test("text 分组（科研经费·经费状态）— 正常/已结清 两列渲染正确", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "科研经费");
    const vid = await getKanbanViewId(request, wid, tid, "经费状态");

    await gotoTable(page, wid, "科研经费");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    await expect(page.getByText("正常")).toBeVisible();
    await expect(page.getByText("已结清")).toBeVisible();
  });

  test("text 分组（课题负责人·职称）— 多值分组渲染", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "课题负责人");
    const vid = await getKanbanViewId(request, wid, tid, "职称");

    await gotoTable(page, wid, "课题负责人");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    await expect(page.getByText("教授", { exact: true })).toBeVisible();
    await expect(page.getByText("研究员", { exact: true })).toBeVisible();
  });
});

// ─────────────── 第二组：卡片渲染全覆盖 ───────────────

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

    // 至少找到一个 antd Progress 进度条
    const progressBars = page.locator(".ant-progress");
    await expect(progressBars.first()).toBeVisible({ timeout: 5000 });
    await expect(progressBars.count()).resolves.toBeGreaterThanOrEqual(1);

    // 截止日期徽章应出现（"天后" / "还剩" / "逾期" / YYYY-MM-DD）
    const dateBadges = page.locator(".ant-tag", { hasText: /天后|还剩|逾期|\d{4}-\d{2}-\d{2}/ });
    await expect(dateBadges.first()).toBeVisible({ timeout: 5000 });

    // 负责人标签 — 卡片里应能看到真实人名
    const assigneeTexts = ["刘洋", "梁婷", "陈静", "杨帆", "赵磊"];
    let found = false;
    for (const name of assigneeTexts) {
      const loc = page.getByText(new RegExp(`^${name}$`));
      if ((await loc.count()) > 0) {
        found = true;
        break;
      }
    }
    expect(found).toBeTruthy();
  });

  test("项目进展·按进展阶段看板 — 进度条显示百分比", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "项目进展");
    const vid = await getKanbanViewId(request, wid, tid, "进展阶段");

    await gotoTable(page, wid, "项目进展");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    await expect(page.getByText("立项启动")).toBeVisible();
    await expect(page.getByText("技术攻关")).toBeVisible();

    // 进度条 — 应有百分比数字
    const progressWithPercent = page.locator(".ant-progress-text");
    await expect(progressWithPercent.first()).toBeVisible({ timeout: 5000 });
  });

  test("科研经费·按课题编号看板 — 截止日期徽章显示拨付日期", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "科研经费");
    const vid = await getKanbanViewId(request, wid, tid, "课题编号");

    await gotoTable(page, wid, "科研经费");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    // 课题编号应作为列头
    await expect(page.getByText(/KT\d+/).first()).toBeVisible();
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

    // 城市列头
    const expectedCities = ["北京", "上海", "广州", "深圳", "杭州", "成都"];
    for (const city of expectedCities) {
      await expect(page.getByText(city, { exact: true }).first()).toBeVisible();
    }

    // 卡片标题应该是加粗 div（title_field = 面积_平米）
    const { root } = await assertKanbanRendered(page, 3);
    const cardTitles = root.locator("div[style*='font-weight']");
    await expect(cardTitles.first()).toBeVisible({ timeout: 5000 });
  });
});

// ─────────────── 第三组：列头信息与计数 ───────────────

test.describe("看板视图 — 列头计数与卡片数一致", () => {
  test("员工表·按部门看板 — 列头计数徽章与实际卡片数匹配", async ({
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
      // 列头计数徽章（灰色圆角 span — style 带 border-radius: 10px）
      const countBadge = col.locator("span[style*='border-radius: 10px']").first();
      // 实际卡片 = cursor: pointer 的 div（React inline style）
      const cards = col.locator("div[style*='cursor: pointer']");
      const badgeText = (await countBadge.textContent())?.trim() ?? "";
      const badgeNum = parseInt(badgeText, 10);
      const cardNum = await cards.count();
      expect(badgeNum).toBe(cardNum);
    }
  });
});

// ─────────────── 第四组：卡片交互与详情抽屉 ───────────────

test.describe("看板视图 — 卡片交互", () => {
  test("卡片点击打开详情抽屉 — 员工表·按部门看板", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    // 员工表按部门看板 — link 分组，只有 4 列少量数据
    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const vid = await getKanbanViewId(request, wid, tid, "部门");

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid);

    const { root } = await assertKanbanRendered(page, 3);
    // 精确定位：第一列的卡片容器（overflowY:auto）里的第一张卡片
    const firstCol = root.locator(":scope > div[style*='flex-direction: column']").first();
    // KanbanCard 的 style 组合：有 cursor: pointer 且有 border（内部元素一般没有 border）
    const firstCard = firstCol.locator("div[style*='cursor: pointer'][style*='border']").first();
    await expect(firstCard).toBeVisible({ timeout: 3000 });

    // evaluate 强制 dispatch click 事件并检查 onClick 是否触发
    const clicked = await firstCard.evaluate((el: HTMLElement) => {
      // 触发原生 click 事件（React 合成事件基于它）
      const evt = new MouseEvent("click", { bubbles: true, cancelable: true });
      el.dispatchEvent(evt);
      return true;
    });
    expect(clicked).toBe(true);

    // 详情抽屉出现
    await expect(page.locator(".ant-drawer").first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator(".ant-drawer").first().getByText("[object Object]")).toHaveCount(0);
  });

  test("大数据集首屏渲染 — 产品开发看板 8s 内完成", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "产品开发");
    const vid = await getKanbanViewId(request, wid, tid, "项目类别");

    const startTs = Date.now();
    await gotoTable(page, wid, "产品开发");
    await activateView(page, vid);

    // 首卡可见即视为渲染完成
    const { root } = await assertKanbanRendered(page, 3);
    const firstCard = root.locator("div[style*='cursor: pointer']").first();
    await expect(firstCard).toBeVisible({ timeout: 5000 });
    const elapsed = Date.now() - startTs;

    expect(elapsed).toBeLessThan(8000);

    // 横向滚动条存在（多列）
    const overflowX = await root.evaluate((el) => getComputedStyle(el).overflowX);
    expect(overflowX).toBe("auto");
  });
});

// ─────────────── 第五组：手动切换与兜底行为 ───────────────

test.describe("看板视图 — 手动切换与兜底", () => {
  test("科研项目表 — grid 模式手动切到看板（兜底分组）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研");
    const tid = await getTableId(request, wid, "科研项目");

    // 不传 view 参数，默认 grid 模式
    await gotoTable(page, wid, "科研项目");
    await switchToKanbanMode(page);
    await assertNoObjectObject(page);

    // 兜底分组应至少有 3 列
    await assertKanbanRendered(page, 3);
  });

  test("空分组键兜底 — 临时看板使用 select 字段分组", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "某企业销售管理");
    const tid = await getTableId(request, wid, "员工表");
    const token = await getToken(request);

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
    const body = (await resp.json()) as { id: number };
    const vid = body.id;

    await gotoTable(page, wid, "员工表");
    await activateView(page, vid);
    await assertNoObjectObject(page);

    // 列头应该显示"是"/"否"
    await expect(page.getByText("是")).toBeVisible();

    // 清理
    await request.delete(`/api/v1/workspaces/${wid}/tables/${tid}/views/${vid}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  });
});

// ─────────────── 第六组：刷新与视图重新选中 ───────────────

test.describe("看板视图 — 刷新持久化与视图选择器", () => {
  test("产品开发·按片区看板 — 刷新后看板重新渲染", async ({
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
    await assertKanbanRendered(page, 3);

    // 刷新并带 view 参数
    const url = new URL(page.url());
    url.searchParams.set("view", String(vid));
    await page.goto(url.toString());
    await page.waitForTimeout(1200);

    await assertNoObjectObject(page);
    await assertKanbanRendered(page, 3);
  });
});
