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

async function trashTotal(request: any, tid: number): Promise<number> {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?trashed=only&limit=1`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(resp.ok()).toBe(true);
  return (await resp.json()).total ?? 0;
}

async function activeTotal(request: any, tid: number): Promise<number> {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?limit=1`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  return (await resp.json()).total ?? 0;
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
    const beforeActive = await activeTotal(request, tid);

    const rowId = await createRow(request, tid, {
      姓名: "E2E-回收站行",
      工号: "E2E-TRASH-001",
      入职日期: "2024-01-01",
      薪资: 100,
      是否在职: "是",
    });
    const afterCreate = await activeTotal(request, tid);
    expect(afterCreate).toBe(beforeActive + 1);

    await deleteRowSoft(request, tid, rowId);
    // 默认列表看不到，回收站能看到
    expect(await activeTotal(request, tid)).toBe(beforeActive);
    expect(await trashTotal(request, tid)).toBeGreaterThanOrEqual(1);

    await openEmployeeGrid(page);
    await page.getByTestId("grid-more-menu").click();
    await page.locator(".ant-dropdown-menu-item", { hasText: "回收站" }).click();

    const drawer = page.getByTestId("row-recycle-bin");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("E2E-回收站行")).toBeVisible();

    // 恢复：回到活动行
    await drawer.getByRole("button", { name: /恢复/ }).first().click();
    await expect.poll(() => activeTotal(request, tid)).toBe(beforeActive + 1);

    await page.keyboard.press("Escape");

    // 再次删除并彻底删除
    await deleteRowSoft(request, tid, rowId);
    await page.getByTestId("grid-more-menu").click();
    await page.locator(".ant-dropdown-menu-item", { hasText: "回收站" }).click();
    const drawer2 = page.getByTestId("row-recycle-bin");
    const row = drawer2.locator("tr", { hasText: "#" + rowId });
    await row.getByRole("button", { name: /彻底删除/ }).click();
    await page.locator(".ant-popconfirm").getByRole("button", { name: /彻底删除/ }).click();

    await expect.poll(() => trashTotal(request, tid)).toBe(0);
    expect(await activeTotal(request, tid)).toBe(beforeActive);
  });
});
