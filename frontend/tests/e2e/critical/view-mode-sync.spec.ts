/** Critical — 右侧 ButtonGroup ↔ 左侧 Segmented TAB 双向联动.
 *
 * 问题背景：GridPage 顶部有两套视图控件：
 *   - Segmented TAB（左侧）: 显示后端视图列表（"全部"、"里程碑达成"、"按课题编号看板"...）
 *   - ButtonGroup（右侧）: 四个模式按钮（表格/看板/画廊/日历）
 *
 * 期望双向联动：
 *   方向 A（已有）: Segmented 点选某视图 → loadView 根据 view_type 自动同步 ButtonGroup 高亮
 *   方向 B（本次修复）: ButtonGroup 点击某模式 → 跳到第一个匹配 view_type 的视图 → Segmented 选中项同步变化
 *
 * 测试策略：用"项目进展"表（科研项目管理工作区）——该表四种视图类型齐全：
 *   grid:   全部（默认）、里程碑达成
 *   kanban: 按课题编号看板、按进展阶段看板、按报告季度看板
 *   calendar: 进展日历
 *   gallery: 进展画廊
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助（与 kanban-view.spec.ts 保持一致） ──

async function getToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "demo", password: "demo1234" },
  });
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

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

async function gotoTable(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tableName: string,
) {
  const tid = await getTableId(request, wid, tableName);
  // 清用户激活视图偏好，避免上一个测试的持久化状态污染
  const token = await getToken(request);
  await request.put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { active_view_id: null },
  }).catch(() => {});

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".ant-space-compact")).toHaveCount(1, { timeout: 10000 });
  await page.waitForTimeout(1500);
}

async function activateView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
  await page.waitForTimeout(1200);
}

/** 断言 Segmented 选中项的文本匹配目标视图名 */
async function assertSegmentedSelected(page: Page, viewNameRegex: RegExp) {
  const selected = page.locator(".ant-segmented-item-selected");
  await expect(selected).toHaveCount(1, { timeout: 3000 });
  await expect(selected.first()).toHaveText(viewNameRegex);
}

/** 断言 Segmented 选中项对应的 view_type（通过视图名识别） */
async function assertSegmentedSelectedIsType(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tid: number,
  expectedType: string,
) {
  const selected = page.locator(".ant-segmented-item-selected").first();
  const label = (await selected.innerText()).trim();

  // 从 API 拿到当前表的视图列表，找到名字匹配的那个，确认 view_type
  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
  const matched = views.find((v) => v.name === label || label.includes(v.name));
  expect(matched, `Segmented 选中项 "${label}" 未在视图列表中找到`).toBeTruthy();
  expect(matched!.view_type).toBe(expectedType);
}

/** 断言 ButtonGroup 指定模式按钮为 primary（高亮）.
 *  通过 antd icon class 定位（表格=ColumnHeight, 看板=Appstore, 画廊=Eye, 日历=Calendar）. */
async function assertModeButtonActive(page: Page, mode: "grid" | "kanban" | "gallery" | "calendar") {
  const iconClassMap: Record<string, string> = {
    grid: "anticon-column-height",
    kanban: "anticon-appstore",
    gallery: "anticon-eye",
    calendar: "anticon-calendar",
  };
  const btn = page.locator(`.ant-space-compact button:has(.${iconClassMap[mode]})`);
  await expect(btn).toHaveCount(1, { timeout: 3000 });
  await expect(btn).toHaveClass(/ant-btn-primary/);
}

/** 点击 ButtonGroup 指定模式按钮 */
async function clickModeButton(page: Page, mode: "grid" | "kanban" | "gallery" | "calendar") {
  const iconClassMap: Record<string, string> = {
    grid: "anticon-column-height",
    kanban: "anticon-appstore",
    gallery: "anticon-eye",
    calendar: "anticon-calendar",
  };
  const btn = page.locator(`.ant-space-compact button:has(.${iconClassMap[mode]})`);
  await expect(btn).toHaveCount(1, { timeout: 3000 });
  await btn.click();
  await page.waitForTimeout(1000); // loadView 触发，等待渲染切换
}

/** 断言当前渲染确实是目标模式（通过 DOM 特征）.
 *  gallery/calendar 是自定义组件，难用通用选择器命中，通过前置断言（Segmented + ButtonGroup）已足够。 */
async function assertRenderedMode(page: Page, mode: "grid" | "kanban" | "gallery" | "calendar") {
  if (mode === "grid") {
    await expect(page.locator(".ant-table").first()).toBeVisible({ timeout: 5000 });
  } else if (mode === "kanban") {
    await expect
      .poll(
        async () =>
          await page
            .locator("div[style*='overflow-x'][style*='display: flex']")
            .count(),
        { timeout: 8000 },
      )
      .toBeGreaterThan(0);
  }
  // gallery / calendar: 跳过渲染断言，前置 Segmented 选中 + ButtonGroup 高亮已确认模式切换完成
}

// ─────────────── 方向 B（本次修复）：ButtonGroup → Segmented 联动 ───────────────

test.describe("双向联动 — 方向 B：ButtonGroup 点击 → Segmented 选中项跳到匹配视图", () => {
  test("grid 默认视图 → 点看板按钮 → Segmented 跳到第一个 kanban 视图", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");

    await gotoTable(page, request, wid, "项目进展");

    // 断言初始状态：当前激活视图是 grid 类型
    await assertSegmentedSelectedIsType(page, request, wid, tid, "grid");
    await assertModeButtonActive(page, "grid");
    await assertRenderedMode(page, "grid");

    // 点 ButtonGroup 的看板按钮
    await clickModeButton(page, "kanban");

    // Segmented 应跳到第一个 kanban 视图
    await assertSegmentedSelectedIsType(page, request, wid, tid, "kanban");
    // ButtonGroup 看板按钮应高亮
    await assertModeButtonActive(page, "kanban");
    // 渲染确实是看板
    await assertRenderedMode(page, "kanban");
    // URL 的 view= 参数应已更新（loadView 会更新）
    expect(page.url()).toMatch(/view=\d+/);
  });

  test("grid 默认视图 → 点画廊按钮 → Segmented 跳到进展画廊", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");

    await gotoTable(page, request, wid, "项目进展");
    await assertSegmentedSelectedIsType(page, request, wid, tid, "grid");

    await clickModeButton(page, "gallery");

    await assertSegmentedSelectedIsType(page, request, wid, tid, "gallery");
    await assertModeButtonActive(page, "gallery");
    await assertRenderedMode(page, "gallery");
  });

  test("grid 默认视图 → 点日历按钮 → Segmented 跳到进展日历", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");

    await gotoTable(page, request, wid, "项目进展");
    await assertSegmentedSelectedIsType(page, request, wid, tid, "grid");

    await clickModeButton(page, "calendar");

    await assertSegmentedSelectedIsType(page, request, wid, tid, "calendar");
    await assertModeButtonActive(page, "calendar");
    await assertRenderedMode(page, "calendar");
  });

  test("看板视图 → 点 ButtonGroup 表格按钮 → Segmented 跳到第一个 grid 视图（方向 B 反向）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");
    const token = await getToken(request);
    const views = (
      await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json() as Promise<Array<{ id: number; view_type: string }>>;
    const kanbanViews = (await views).filter((v) => v.view_type === "kanban");
    if (kanbanViews.length === 0) test.skip("无看板视图");

    await gotoTable(page, request, wid, "项目进展");
    await activateView(page, kanbanViews[0].id);
    await assertSegmentedSelectedIsType(page, request, wid, tid, "kanban");
    await assertModeButtonActive(page, "kanban");

    // 点 ButtonGroup 的表格按钮
    await clickModeButton(page, "grid");

    // Segmented 应跳到第一个 grid 视图
    await assertSegmentedSelectedIsType(page, request, wid, tid, "grid");
    await assertModeButtonActive(page, "grid");
    await assertRenderedMode(page, "grid");
  });
});

// ─────────────── 方向 A（回归）：Segmented → ButtonGroup 同步（已有 loadView 保证） ───────────────

test.describe("双向联动 — 方向 A：Segmented 点击 → ButtonGroup 模式同步（回归）", () => {
  test("Segmented 点 kanban 视图 → ButtonGroup 看板按钮高亮", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");
    const token = await getToken(request);
    const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
    const kanbanView = views.find((v) => v.view_type === "kanban");
    if (!kanbanView) test.skip("无看板视图");

    await gotoTable(page, request, wid, "项目进展");
    await activateView(page, kanbanView.id);

    await assertSegmentedSelected(page, new RegExp(kanbanView.name));
    await assertModeButtonActive(page, "kanban");
    await assertRenderedMode(page, "kanban");
  });

  test("Segmented 点 gallery 视图 → ButtonGroup 画廊按钮高亮", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");
    const token = await getToken(request);
    const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
    const galleryView = views.find((v) => v.view_type === "gallery");
    if (!galleryView) test.skip("无画廊视图");

    await gotoTable(page, request, wid, "项目进展");
    await activateView(page, galleryView.id);

    await assertSegmentedSelected(page, new RegExp(galleryView.name));
    await assertModeButtonActive(page, "gallery");
  });
});

// ─────────────── 循环切换与幂等 ───────────────

test.describe("双向联动 — 循环切换、幂等与边界", () => {
  test("按 ButtonGroup 四种模式依次切换 → Segmented 选中项循环匹配", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");

    await gotoTable(page, request, wid, "项目进展");
    await assertSegmentedSelectedIsType(page, request, wid, tid, "grid");

    const cycle: Array<"kanban" | "gallery" | "calendar" | "grid"> = [
      "kanban",
      "gallery",
      "calendar",
      "grid",
    ];
    for (const m of cycle) {
      await clickModeButton(page, m);
      await assertSegmentedSelectedIsType(page, request, wid, tid, m);
      await assertModeButtonActive(page, m);
      await assertRenderedMode(page, m);
    }
  });

  test("当前视图已是目标类型 → 连续点同一按钮不触发视图跳转（幂等）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");
    const token = await getToken(request);
    const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; view_type: string }>;
    const kanbanView = views.find((v) => v.view_type === "kanban");
    if (!kanbanView) test.skip("无看板视图");

    await gotoTable(page, request, wid, "项目进展");
    await activateView(page, kanbanView.id);
    await assertModeButtonActive(page, "kanban");

    // 记录当前 URL（含 view=）
    const before = page.url();

    // 连续点看板按钮 3 次
    for (let i = 0; i < 3; i++) {
      await clickModeButton(page, "kanban");
    }

    // URL 不变（没有触发 loadView）
    expect(page.url()).toBe(before);
    // Segmented 选中项仍是同一个
    await assertSegmentedSelectedIsType(page, request, wid, tid, "kanban");
    await assertModeButtonActive(page, "kanban");
  });
});

// ─────────────── 回归：Button.Group 废弃警告已消除 ───────────────

test.describe("废弃 API 清理 — Button.Group 警告", () => {
  test("GridPage + CalendarView 页面打开时无 Button.Group 控制台警告", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (
        msg.type() === "warning" &&
        msg.text().includes("Button.Group")
      ) {
        warnings.push(msg.text());
      }
    });

    // 先打开 GridPage 等待 2 秒
    await page.goto(`/w/1/tables/1`);
    await page.waitForTimeout(2000);

    // 再切到 calendar 模式（GridPage 渲染 CalendarView 子组件）
    const calendarBtn = page.locator('.ant-space-compact button:has(.anticon-calendar)');
    if ((await calendarBtn.count()) > 0) {
      await calendarBtn.click();
      await page.waitForTimeout(1000);
    }

    expect(warnings, `发现 Button.Group 废弃警告: ${warnings.join(" | ")}`).toHaveLength(0);
  });
});

