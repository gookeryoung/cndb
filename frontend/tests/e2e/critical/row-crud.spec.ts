/** Critical — 行 CRUD 全链路（仅 chromium-authed）.
 *
 * 策略：通过 API 直接管理测试行，前端只验证 Grid 渲染结果。
 * 避免 inline 编辑在 Antd 组件中的复杂选择器。
 */
import { test, expect, APIResponse } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1;
const TABLE_NAME = "员工表";
const SEED_NAMES = new Set(["张三", "李四", "王五", "赵六", "钱七"]);

/** 获取员工表 ID */
async function getTableId(request: any): Promise<number> {
  const token = await getToken(request);
  const resp: APIResponse = await request.get(`/api/v1/workspaces/${WID}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const tables = await resp.json();
  const emp = tables.find((t: any) => t.name === TABLE_NAME);
  return emp.id;
}

/** 登录获取 token */
async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  const body = await resp.json();
  return body.access_token;
}

/** 确保 Grid 显示 N 条记录 */
async function gotoGridAndCheckCount(page: any, expectedCount: number) {
  // 直接导航到指定工作区，绕过 WorkspaceList 多工作区场景
  await page.goto(`/w/${WID}/tables`);

  // 侧栏 Menu 点击 "员工表"
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);

  // 等待数据渲染
  await page.waitForTimeout(800);

  const rows = page.locator(".ant-table-tbody tr.ant-table-row");
  await expect(rows).toHaveCount(expectedCount);
}

/** 清理非 seed 行 */
async function cleanupExtraRows(request: any, tid: number) {
  const token = await getToken(request);
  const resp: APIResponse = await request.get(`/api/v1/workspaces/${WID}/tables/${tid}/records`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await resp.json();
  const items = body.items || body.results || [];
  const extras = items.filter((r: any) => !SEED_NAMES.has(r["姓名"] ?? ""));
  for (const r of extras) {
    await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/records/${r.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  }
}

/** 通过 API 创建一行 */
async function createRow(request: any, tid: number, values: Record<string, unknown>): Promise<number> {
  const token = await getToken(request);
  const resp: APIResponse = await request.post(
    `/api/v1/workspaces/${WID}/tables/${tid}/records`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: { values },
    },
  );
  const body = await resp.json();
  return body.id;
}

/** 通过 API 删除一行 */
async function deleteRow(request: any, tid: number, rowId: number) {
  const token = await getToken(request);
  await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/records/${rowId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ─────────────── 测试 ───────────────

test.describe("行 CRUD", () => {
  test("添加行 → Grid +1 行 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request);
    await cleanupExtraRows(request, tid);

    // 创建测试行
    const newId = await createRow(request, tid, {
      姓名: "E2E-测试行",
      入职日期: "2024-01-01",
      薪资: 9999,
      是否在职: "是",
    });

    // Grid 验证
    await gotoGridAndCheckCount(page, 6);
    await expect(page.getByText("E2E-测试行")).toBeVisible();

    // 清理
    await deleteRow(request, tid, newId);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, 5);
  });

  test("删除行 → Grid -1 行 → 重建 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request);
    await cleanupExtraRows(request, tid);

    // 先通过 API 创建一个临时行
    const tmpId = await createRow(request, tid, {
      姓名: "E2E-临时",
      入职日期: "2024-06-01",
      薪资: 1000,
      是否在职: "否",
    });

    // 确认 Grid 有 6 行
    await gotoGridAndCheckCount(page, 6);

    // 删除临时行
    await deleteRow(request, tid, tmpId);

    // 确认回到 5 行
    await gotoGridAndCheckCount(page, 5);
    await expect(page.getByText("E2E-临时")).not.toBeVisible();
  });
});
