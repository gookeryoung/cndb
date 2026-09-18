/** Critical — 行 CRUD 全链路（仅 chromium-authed）.
 *
 * 策略：通过 API 直接管理测试行，前端只验证 Grid 渲染结果。
 * 避免 inline 编辑在 Antd 组件中的复杂选择器。
 *
 * 选择器说明（2026-09）：Grid 已启用 Antd virtual 虚拟滚动，行 DOM 为 div 而非
 * tr.ant-table-row —— 行数断言一律用分页「共 N 条」文本（showTotal，服务端真值）；
 * 行定位用 tag 无关的 [data-row-key] 属性。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId } from "../helpers/api";
import type { APIResponse } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1;
const TABLE_NAME = "员工表";
const SEED_NAMES = new Set(["张三", "李四", "王五", "赵六", "钱七"]);

/** 导航到员工表 Grid 并等待数据渲染. */
async function openEmployeeGrid(page: any) {
  // 直接导航到指定工作区，绕过 WorkspaceList 多工作区场景
  await page.goto(`/w/${WID}/tables`);

  // 侧栏 Menu 点击 "员工表"
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);

  // Grid 骨架渲染完成信号：新增行按钮可见
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

/** 确保 Grid 分页显示共 N 条（服务端真值，不受虚拟滚动 DOM 影响） */
async function gotoGridAndCheckCount(page: any, expectedCount: number) {
  await openEmployeeGrid(page);
  await expect(page.getByText(`共 ${expectedCount} 条`)).toBeVisible();
}

/** 清理非 seed 行 */
async function cleanupExtraRows(request: any, tid: number) {
  const token = await getAdminToken(request);
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
  const token = await getAdminToken(request);
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
  const token = await getAdminToken(request);
  await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/records/${rowId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ─────────────── 测试 ───────────────

test.describe("行 CRUD", () => {
  test("添加行 → Grid +1 行 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
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
    await expect(page.getByText("E2E-测试行")).not.toBeVisible();
  });

  test("删除行 → Grid -1 行 → 重建 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
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

  test("新增行按钮 → 行内新增 → 必填校验 → 填写 → Grid +1 行 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, 5);

    // 点击 "新增行" → 底部出现空白可编辑行（虚拟滚动下行是 div，用 data-row-key 定位）
    await page.getByTestId("add-row-btn").click();
    const newRow = page.locator('[data-row-key="__new__"]');
    await expect(newRow).toHaveCount(1);

    // 必填字段缺失直接保存 → 阻止并提示
    await newRow.getByTestId("row-save-btn").click();
    await expect(page.getByText(/请填写必填字段/)).toBeVisible();

    // 填写必填字段 "姓名" 后保存
    await newRow.locator("input.ant-input").first().fill("E2E-按钮新增");
    await newRow.getByTestId("row-save-btn").click();

    // Grid +1 行且新行可见（虚拟新增行消失，回落到 DB 行）
    await expect(page.getByText("E2E-按钮新增")).toBeVisible();
    await expect(page.getByText("共 6 条")).toBeVisible();

    // 清理
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, 5);
    await expect(page.getByText("E2E-按钮新增")).not.toBeVisible();
  });

  test("新增行 — 必填字段缺失时阻止提交，取消后行数不变", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, 5);

    // 打开行内新增行，直接保存
    await page.getByTestId("add-row-btn").click();
    const newRow = page.locator('[data-row-key="__new__"]');
    await expect(newRow).toHaveCount(1);
    await newRow.getByTestId("row-save-btn").click();

    // 校验错误提示出现，且未产生新行
    await expect(page.getByText(/请填写必填字段/)).toBeVisible();
    await expect(newRow).toHaveCount(1);

    // 取消放弃本次新增，新增行消失，Grid 回到 5 条
    await newRow.getByTestId("row-cancel-btn").click();
    await expect(newRow).toHaveCount(0);
    await expect(page.getByText("共 5 条")).toBeVisible();
  });

  test("整行编辑 → 修改字段 → 保存 → Grid 更新 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, 5);

    // 定位 "张三" 行，进入整行编辑（虚拟滚动行是 div，用 data-row-key 过滤）
    const zhangRow = page.locator("[data-row-key]").filter({ hasText: "张三" }).first();
    await zhangRow.getByTestId("row-edit-btn").click();

    // 编辑态重渲染后行内容不再嵌套在 [data-row-key] 容器内，
    // 且编辑态下仅当前行有保存按钮 —— 用全局 testid 定位
    const saveBtn = page.getByTestId("row-save-btn");
    await expect(saveBtn).toBeVisible();

    // 确认 "姓名" 字段回填正确（表格内第一个文本输入框）
    const nameInput = page.locator(".ant-table").getByRole("textbox").first();
    await expect(nameInput).toHaveValue("张三");

    // 提交保存 → 整行编辑退出，行数据仍可见
    await saveBtn.click();
    await expect(saveBtn).not.toBeVisible();
    await expect(page.getByText("张三")).toBeVisible();
  });
});
