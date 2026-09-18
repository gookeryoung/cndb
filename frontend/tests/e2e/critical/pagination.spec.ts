/** Critical — Grid 分页全链路（仅 chromium-authed）.
 *
 * 覆盖场景：
 *   1. 分页控件渲染 + 总数文案 + 页码激活态
 *   2. 点击页码跳转（第 1 → 第 2 页），验证 offset 变化
 *   3. "下一页"/"上一页"箭头按钮状态切换
 *   4. 页大小切换（50 → 100）
 *   5. 排序视图下分页保持排序参数
 *
 * 验证策略：以页码激活态变化为核心断言，网络请求 URL 为辅助证据。
 * React Query 对相同 queryKey 可能使用缓存，所以网络请求验证仅对首次状态变化可靠。
 */
import { test, expect } from "../fixtures/auth";
import type { APIResponse } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

/** 登录获取 token */
async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  const body = await resp.json();
  return body.access_token;
}

/** 找到记录数 >= 50 的表 */
async function findPaginatedTable(request: any, minRecords = 50) {
  const token = await getToken(request);
  const headers = { Authorization: `Bearer ${token}` };

  const wsResp: APIResponse = await request.get("/api/v1/workspaces", { headers });
  const workspaces = await wsResp.json();

  let best: { wid: number; tid: number; name: string; count: number } | null = null;

  for (const ws of workspaces as any[]) {
    const tResp: APIResponse = await request.get(`/api/v1/workspaces/${ws.id}/tables`, { headers });
    const tables = await tResp.json();
    for (const t of tables as any[]) {
      const cnt = t.record_count ?? 0;
      if (cnt >= minRecords && (!best || cnt > best.count)) {
        best = { wid: ws.id, tid: t.id, name: t.name, count: cnt };
      }
    }
  }

  return best;
}

test.describe("Grid 分页", () => {
  test("分页控件渲染 + 翻页 + 页大小切换", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const table = await findPaginatedTable(request, 50);
    if (!table) {
      test.skip("没有 >= 50 条记录的表，跳过分页测试");
      return;
    }

    console.log(`[分页测试] 使用表: ${table.name} (wid=${table.wid}, tid=${table.tid}, ${table.count} 条)`);

    // 监听 records API 请求 URL
    const apiRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/records") && req.method() === "GET") {
        apiRequests.push(req.url());
      }
    });

    // 直接导航到目标表
    await page.goto(`/w/${table.wid}/tables/${table.tid}`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });

    // 等数据加载
    await expect(page.locator(".ant-table-tbody tr.ant-table-row").first()).toBeVisible({ timeout: 10000 });

    // ---- 1. 分页控件渲染 ----
    const pagination = page.locator(".ant-pagination");
    await expect(pagination).toBeVisible({ timeout: 5000 });

    // 显示总数文案
    await expect(pagination.getByText(/共\s*\d+\s*条/)).toBeVisible();

    // 页码 >= 2（501 条 / 50 每页 = 约 11 页，AntD 默认显示 5 个页码 + 省略号）
    const pageItems = pagination.locator(".ant-pagination-item");
    await expect(pageItems.first()).toBeVisible({ timeout: 3000 });
    const itemCount = await pageItems.count();
    expect(itemCount).toBeGreaterThanOrEqual(2);
    console.log(`  页码项数: ${itemCount}`);

    // 初始在第 1 页
    await expect(pagination.locator(".ant-pagination-item-active")).toHaveText("1");

    // prev 按钮初始禁用
    const prevBtn = pagination.locator(".ant-pagination-prev");
    await expect(prevBtn).toHaveClass(/ant-pagination-disabled/);

    // ---- 2. 翻页到第 2 页（验证 offset 变化 + onChange 正确触发） ----
    const reqBeforeClick = apiRequests.length;

    await pageItems.nth(1).click();
    await expect(pagination.locator(".ant-pagination-item-active")).toHaveText("2", { timeout: 5000 });

    // 验证 React Query 发送了新请求（带 offset=50）
    const newRequests = apiRequests.slice(reqBeforeClick);
    const hasOffset50 = newRequests.some((r) => {
      try {
        const url = new URL(r);
        return url.searchParams.get("offset") === "50";
      } catch {
        return r.includes("offset=50");
      }
    });
    expect(hasOffset50).toBe(true);
    console.log(`  翻到第 2 页 ✓ 新请求带 offset=50`);

    // 现在 prev 按钮应该启用
    await expect(prevBtn).not.toHaveClass(/ant-pagination-disabled/);

    // ---- 3. "上一页" 箭头 ----
    const reqBeforePrev = apiRequests.length;
    await prevBtn.click();
    await expect(pagination.locator(".ant-pagination-item-active")).toHaveText("1", { timeout: 5000 });
    // 回到第 1 页（offset=0 是初始值），React Query 可能用缓存，不强制检查请求
    console.log(`  回到第 1 页 ✓`);

    // ---- 4. "下一页" 箭头 ----
    const reqBeforeNext = apiRequests.length;
    const nextBtn = pagination.locator(".ant-pagination-next");
    await nextBtn.click();
    await expect(pagination.locator(".ant-pagination-item-active")).toHaveText("2", { timeout: 5000 });
    console.log(`  下一页到第 2 页 ✓`);

    // ---- 5. 页大小切换（50 → 100） ----
    const sizeChanger = pagination.locator(".ant-pagination-options-size-changer");
    await expect(sizeChanger).toBeVisible();

    await sizeChanger.click();
    // AntD Select 选项在 body 根节点
    const opt100 = page.locator(".ant-select-item-option").filter({ hasText: /100/ }).first();
    await expect(opt100).toBeVisible({ timeout: 3000 });

    const reqBeforeResize = apiRequests.length;
    await opt100.click();

    // 等待新数据加载（确定性：等到 limit=100 请求出现）
    await expect
      .poll(
        () => {
          const resizeRequests = apiRequests.slice(reqBeforeResize);
          return resizeRequests.some((r) => {
            try {
              return new URL(r).searchParams.get("limit") === "100";
            } catch {
              return r.includes("limit=100");
            }
          });
        },
        { timeout: 10000 },
      )
      .toBe(true);

    // 验证请求带 limit=100
    const resizeRequests = apiRequests.slice(reqBeforeResize);
    const hasLimit100 = resizeRequests.some((r) => {
      try {
        const url = new URL(r);
        return url.searchParams.get("limit") === "100";
      } catch {
        return r.includes("limit=100");
      }
    });
    expect(hasLimit100).toBe(true);
    console.log(`  切换到 100/页 ✓ 请求带 limit=100`);

    // 总数文案仍正确
    await expect(pagination.getByText(/共\s*\d+\s*条/)).toBeVisible();

    console.log(`\n✅ 分页全链路测试通过`);
  });

  test("视图带排序时分页保持排序参数", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const table = await findPaginatedTable(request, 50);
    if (!table) {
      test.skip("没有 >= 50 条记录的表");
      return;
    }

    const apiRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes("/records") && req.method() === "GET") {
        apiRequests.push(req.url());
      }
    });

    await page.goto(`/w/${table.wid}/tables/${table.tid}`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".ant-table-tbody tr.ant-table-row").first()).toBeVisible({ timeout: 10000 });

    // 初始加载：应该带视图排序
    const initWithSorts = apiRequests.some((r) => {
      try { return new URL(r).searchParams.has("sorts"); } catch { return r.includes("sorts="); }
    });
    console.log(`初始请求带排序: ${initWithSorts}`);

    if (!initWithSorts) {
      console.log("当前视图无排序，无法验证排序+分页组合，跳过");
      return;
    }

    // 翻到第 2 页
    const pagination = page.locator(".ant-pagination");
    await pagination.locator(".ant-pagination-item").nth(1).click();
    await expect(pagination.locator(".ant-pagination-item-active")).toHaveText("2", { timeout: 5000 });

    // 最新的 records 请求应该同时带 sorts 和 offset=50
    const latest = apiRequests[apiRequests.length - 1];
    const url = new URL(latest);
    const offset = url.searchParams.get("offset");
    const hasSorts = url.searchParams.has("sorts");
    expect(offset).toBe("50");
    expect(hasSorts).toBe(true);
    console.log(`翻页请求: offset=${offset}, hasSorts=${hasSorts} ✓`);

    console.log(`\n✅ 排序后分页测试通过`);
  });
});
