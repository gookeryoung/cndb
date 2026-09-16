/** Critical — 创建表时后端自动生成默认视图「全部」（grid, is_default=true, order=0）.
 *
 * 覆盖：
 *   1. POST /workspaces/{wid}/tables → 新建表后 GET /views 返回 1 条「全部」grid 视图
 *   2. 不能重复创建同名「全部」视图（后端唯一约束）
 *   3. 调用 copy_table 生成的副本同样自带默认视图
 */
import { test, expect, type APIResponse } from "@playwright/test";

const WID = 1;

async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  return (await resp.json()).access_token;
}

async function createTable(request: any, wid: number, name: string): Promise<number> {
  const resp: APIResponse = await request.post(`/api/v1/workspaces/${wid}/tables`, {
    data: { name, description: "E2E 默认视图测试表" },
    headers: { Authorization: `Bearer ${await getToken(request)}` },
  });
  expect(resp.status()).toBe(201);
  return (await resp.json()).id;
}

async function deleteTable(request: any, wid: number, tid: number): Promise<void> {
  await request.delete(`/api/v1/workspaces/${wid}/tables/${tid}`, {
    headers: { Authorization: `Bearer ${await getToken(request)}` },
  });
}

async function listViews(request: any, wid: number, tid: number): Promise<any[]> {
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${wid}/tables/${tid}/views`,
    { headers: { Authorization: `Bearer ${await getToken(request)}` } },
  );
  expect(resp.status()).toBe(200);
  return (await resp.json()) as any[];
}

test.describe("创建表 → 自动生成默认视图「全部」", () => {
  let tid: number;

  test.afterAll(async ({ request }) => {
    if (tid) await deleteTable(request, WID, tid);
  });

  test("新表只有 1 条视图：名为「全部」、类型 grid、is_default=true、order=0", async ({
    request,
  }) => {
    tid = await createTable(request, WID, "E2E-默认视图测试表");

    const views = await listViews(request, WID, tid);
    expect(views.length).toBe(1);

    const v = views[0];
    expect(v.name).toBe("全部");
    expect(v.view_type).toBe("grid");
    expect(v.is_default).toBe(true);
    expect(v.order).toBe(0);
  });

  test("同表不能重复创建同名「全部」视图（后端唯一约束返回 400）", async ({ request }) => {
    if (!tid) tid = await createTable(request, WID, "E2E-默认视图重复名测试表");

    const resp: APIResponse = await request.post(
      `/api/v1/workspaces/${WID}/tables/${tid}/views`,
      {
        data: { name: "全部", view_type: "grid" },
        headers: { Authorization: `Bearer ${await getToken(request)}` },
      },
    );
    expect(resp.status()).toBe(400);
  });

  test("GET /tables/{tid} 详情里 view_count=1 且 views[0] 就是「全部」", async ({ request }) => {
    if (!tid) tid = await createTable(request, WID, "E2E-详情视图测试表");

    const resp: APIResponse = await request.get(
      `/api/v1/workspaces/${WID}/tables/${tid}`,
      { headers: { Authorization: `Bearer ${await getToken(request)}` } },
    );
    expect(resp.status()).toBe(200);
    const d = (await resp.json()) as any;
    expect(d.view_count).toBe(1);
    expect(d.views.length).toBe(1);
    expect(d.views[0].name).toBe("全部");
    expect(d.views[0].view_type).toBe("grid");
    expect(d.views[0].is_default).toBe(true);
  });
});

test.describe("复制表 → 副本同样自带默认视图", () => {
  let srcTid: number;
  let dstTid: number;

  test.afterAll(async ({ request }) => {
    if (srcTid) await deleteTable(request, WID, srcTid);
    if (dstTid) await deleteTable(request, WID, dstTid);
  });

  test("copy_table(mode=structure) → 新表也有默认视图「全部」", async ({ request }) => {
    srcTid = await createTable(request, WID, "E2E-复制源表");

    // 给源表加一个非默认视图（确保副本只带默认视图）
    const resp1: APIResponse = await request.post(
      `/api/v1/workspaces/${WID}/tables/${srcTid}/views`,
      {
        data: { name: "另一个视图", view_type: "grid" },
        headers: { Authorization: `Bearer ${await getToken(request)}` },
      },
    );
    expect(resp1.status()).toBe(201);

    // 复制表
    const resp2: APIResponse = await request.post(
      `/api/v1/workspaces/${WID}/tables/${srcTid}/copy?mode=structure`,
      {
        data: {},
        headers: { Authorization: `Bearer ${await getToken(request)}` },
      },
    );
    expect(resp2.status()).toBe(201);
    dstTid = (await resp2.json()).id;

    // 查副本 views
    const views = await listViews(request, WID, dstTid);
    expect(views.length).toBe(1);
    expect(views[0].name).toBe("全部");
    expect(views[0].view_type).toBe("grid");
    expect(views[0].is_default).toBe(true);
  });
});
