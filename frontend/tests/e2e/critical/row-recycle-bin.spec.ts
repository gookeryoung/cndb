/** Critical — 行回收站（ADR 0139）：删除 → 回收站可见 → 恢复 → 彻底删除（仅 chromium-authed）.
 *
 * 策略与 row-crud.spec.ts 一致：行数据用 API 造，前端只验证入口、列表与操作结果，
 * 最终以 API 的 total 作为真值断言（虚拟滚动下行数文本不稳定）。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId } from "../helpers/api";
import type { APIResponse } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1;
const TABLE_NAME = "员工表";

async function createRow(request: any, tid: number, values: Record<string, unknown>): Promise<number> {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.post(`/api/v1/workspaces/${WID}/tables/${tid}/records`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { values },
  });
  expect(resp.ok()).toBe(true);
  return (await resp.json()).id;
}

async function deleteRowSoft(request: any, tid: number, rowId: number) {
  const token = await getAdminToken(request);
  const resp = await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/records/${rowId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(resp.status()).toBe(204);
}

/** 回收站中的行 id 集合（只认行 id，避免与其他并发用例共享员工表时全局 total 抖动）。 */
async function trashedIds(request: any, tid: number): Promise<number[]> {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?trashed=only&limit=200`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(resp.ok()).toBe(true);
  const items: Array<{ id: number }> = (await resp.json()).items ?? [];
  return items.map(r => r.id);
}

/** 彻底清掉上一次（重试）遗留的同名回收站行，保证「回收站清空」断言不被历史残留干扰。 */
async function purgeLeftoverTrash(request: any, tid: number) {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?trashed=only&limit=200`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(resp.ok()).toBe(true);
  const items: Array<{ id: number; 姓名?: string }> = (await resp.json()).items ?? [];
  const ids = items.filter(r => r["姓名"] === "E2E-回收站行").map(r => r.id);
  if (!ids.length) return;
  const purge = await request.post(
    `/api/v1/workspaces/${WID}/tables/${tid}/records/purge`,
    { headers: { Authorization: `Bearer ${token}` }, data: { row_ids: ids } },
  );
  expect(purge.ok()).toBe(true);
}

/** 活动行（非回收站）id 集合。 */
async function activeIds(request: any, tid: number): Promise<number[]> {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?limit=500`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(resp.ok()).toBe(true);
  const items: Array<{ id: number }> = (await resp.json()).items ?? [];
  return items.map(r => r.id);
}

/** 打开员工表 Grid 并等待骨架完成 */
async function openEmployeeGrid(page: any) {
  await page.goto(`/w/${WID}/tables`);
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

test.describe("行回收站", () => {
  test("删除 → 回收站可见 → 恢复回网格 → 彻底删除", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await purgeLeftoverTrash(request, tid);

    const rowId = await createRow(request, tid, {
      姓名: "E2E-回收站行",
      工号: "E2E-TRASH-001",
      入职日期: "2024-01-01",
      薪资: 100,
      是否在职: "是",
    });
    expect(await activeIds(request, tid)).toContain(rowId);

    await deleteRowSoft(request, tid, rowId);
    // 默认列表看不到，回收站能看到
    expect(await activeIds(request, tid)).not.toContain(rowId);
    expect(await trashedIds(request, tid)).toContain(rowId);

    await openEmployeeGrid(page);
    await page.getByTestId("grid-more-menu").click();
    await page.locator(".ant-dropdown-menu-item", { hasText: "回收站" }).click();

    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("E2E-回收站行").first()).toBeVisible();

    // 恢复：回到活动行（定位到自己刚删除的那一行，避免同名残留行干扰）
    await drawer.locator("tr", { hasText: "#" + rowId }).getByRole("button", { name: /恢复/ }).click();
    await expect.poll(() => activeIds(request, tid)).toContain(rowId);

    // 点击右上角关闭按钮（恢复后原焦点按钮已卸载，Esc 不再命中弹窗键盘处理）
    await page.locator(".ant-modal-close").click();
    await expect(page.getByRole("dialog")).toBeHidden();

    // 再次删除并彻底删除（删除走 API 旁路，需重载页面让回收站查询不吃 10s staleTime 缓存）
    await deleteRowSoft(request, tid, rowId);
    await openEmployeeGrid(page);
    await page.getByTestId("grid-more-menu").click();
    await page.locator(".ant-dropdown-menu-item", { hasText: "回收站" }).click();
    const drawer2 = page.getByRole("dialog");
    const row = drawer2.locator("tr", { hasText: "#" + rowId });
    await row.getByRole("button", { name: /彻底删除/ }).click();
    await page.locator(".ant-popconfirm").getByRole("button", { name: /彻底删除/ }).click();

    await expect.poll(() => trashedIds(request, tid)).not.toContain(rowId);
    expect(await activeIds(request, tid)).not.toContain(rowId);
  });
});
