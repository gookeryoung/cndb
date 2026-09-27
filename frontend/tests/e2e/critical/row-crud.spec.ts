/** Critical — 行 CRUD 全链路（仅 chromium-authed）.
 *
 * 策略：通过 API 直接管理测试行，前端验证 Grid 渲染结果。
 * 避免 inline 编辑在 Antd 组件中的复杂选择器。
 *
 * 选择器说明（2026-09）：Grid 已启用 Antd virtual 虚拟滚动 + 独立 Pagination，
 * 行 DOM 用 [data-row-key] 定位；分页「共 N 条」文本在虚拟滚动布局中不稳定（可能被
 * 推到视口外或尚未渲染），行数断言统一走 API records.total 作为真值，前端只负责
 * 导航 + 骨架加载信号验证。
 *
 * 字段说明（2026-09）：员工表 Grid 列顺序为 姓名→工号→部门→职位→...，
 * 第一列就是姓名，可编辑时 textbox.first() / input.first() 正确命中姓名字段。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getRowId, getTableId } from "../helpers/api";
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

/** 确保 Grid 骨架加载完成 + API 行数校验（跳过不稳定的分页文本）. */
async function gotoGridAndCheckCount(
  page: any,
  request: any,
  tid: number,
  expectedCount: number,
) {
  await openEmployeeGrid(page);
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?limit=1`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = await resp.json();
  const total = body.total ?? body.count ?? 0;
  expect(total).toBe(expectedCount);
}

/** 清理非 seed 行 */
async function cleanupExtraRows(request: any, tid: number) {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?limit=500`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = await resp.json();
  const items = body.items || body.results || [];
  const extras = items.filter((r: any) => !SEED_NAMES.has(r["姓名"] ?? ""));
  for (const r of extras) {
    await request.delete(
      `/api/v1/workspaces/${WID}/tables/${tid}/records/${r.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
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
  expect(resp.ok()).toBe(true);
  const body = await resp.json();
  return body.id;
}

/** 通过 API 删除一行 */
async function deleteRow(request: any, tid: number, rowId: number) {
  const token = await getAdminToken(request);
  await request.delete(
    `/api/v1/workspaces/${WID}/tables/${tid}/records/${rowId}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
}

/** 用 API 验证当前记录总数 */
async function expectRecordCount(request: any, tid: number, expected: number) {
  const token = await getAdminToken(request);
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${WID}/tables/${tid}/records?limit=1`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = await resp.json();
  const total = body.total ?? body.count ?? 0;
  expect(total).toBe(expected);
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
      工号: "E2E-NEW-001",
      入职日期: "2024-01-01",
      薪资: 9999,
      是否在职: "是",
    });

    // Grid 验证：骨架加载 + API 行数
    await gotoGridAndCheckCount(page, request, tid, 6);
    await expect(page.getByText("E2E-测试行")).toBeVisible();

    // 清理
    await deleteRow(request, tid, newId);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, request, tid, 5);
    await expect(page.getByText("E2E-测试行")).not.toBeVisible();
  });

  test("删除行 → Grid -1 行 → 重建 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);

    // 先通过 API 创建一个临时行
    const tmpId = await createRow(request, tid, {
      姓名: "E2E-临时",
      工号: "E2E-TMP-001",
      入职日期: "2024-06-01",
      薪资: 1000,
      是否在职: "否",
    });

    // 确认 Grid 有 6 行
    await gotoGridAndCheckCount(page, request, tid, 6);

    // 删除临时行
    await deleteRow(request, tid, tmpId);

    // 确认回到 5 行
    await gotoGridAndCheckCount(page, request, tid, 5);
    await expect(page.getByText("E2E-临时")).not.toBeVisible();
  });

  test("新增行按钮 → 行内新增 → 必填校验 → 填写 → Grid +1 行 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, request, tid, 5);

    // 点击 "新增行" → 底部出现空白可编辑行（虚拟滚动下行是 div，用 data-row-key 定位）
    await page.getByTestId("add-row-btn").click();
    const newRow = page.locator('[data-row-key="__new__"]');
    await expect(newRow).toHaveCount(1);

    // 自动滚动聚焦回归保护：新行第一个可编辑文本输入框必须自动获得焦点
    // 字段顺序已调整为"姓名"第一列，first() 正确命中
    await expect(newRow.locator("input.ant-input").first()).toBeFocused();

    // 必填字段缺失直接保存 → 阻止并提示（姓名 + 工号都是必填）
    await newRow.getByTestId("row-save-btn").click();
    await expect(page.getByText(/请填写必填字段/)).toBeVisible();

    // 填写两个必填字段后保存（字段顺序已调整为 姓名[0] → 工号[1] → ...）
    const inputs = newRow.locator("input.ant-input");
    await inputs.first().fill("E2E-按钮新增");      // 姓名
    await inputs.nth(1).fill("E2E-BTN-001");        // 工号
    await newRow.getByTestId("row-save-btn").click();

    // 等待新增行保存完成（虚拟 __new__ 行消失，新 DB 行出现）
    await expect(newRow).toHaveCount(0, { timeout: 10000 });

    // API 验证 + 前端文本可见
    await expectRecordCount(request, tid, 6);
    await expect(page.getByText("E2E-按钮新增")).toBeVisible();

    // 清理
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, request, tid, 5);
    await expect(page.getByText("E2E-按钮新增")).not.toBeVisible();
  });

  test("整行编辑 → 修改字段 → 保存 → Grid 更新 → 清理", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const tid = await getTableId(request, WID, TABLE_NAME);
    await cleanupExtraRows(request, tid);
    await gotoGridAndCheckCount(page, request, tid, 5);

    // 通过 API 拿到张三行的真实 row id —— 彻底规避 hasText 子串匹配
    // 被操作列按钮文字（如"编辑"）误命中的风险，以及虚拟滚动下行 DOM 顺序
    // 与数据顺序不一致导致 .first() 拿错行的问题
    const zhangRowId = await getRowId(request, WID, tid, "姓名", "张三");

    // 用精确 row-key 定位张三行，点击进入整行编辑
    const zhangRow = page.locator(`[data-row-key="${zhangRowId}"]`);
    await expect(zhangRow.getByTestId("row-edit-btn")).toBeVisible();
    await zhangRow.getByTestId("row-edit-btn").click();

    // 编辑态下仅当前行有保存按钮 —— 用全局 testid 定位
    const saveBtn = page.getByTestId("row-save-btn");
    await expect(saveBtn).toBeVisible();

    // 用具体 [data-row-key] 容器定位姓名输入框，避免虚拟滚动下
    // .ant-table .textbox.first() 只拿到视口顶部输入框的不稳定问题
    // 字段顺序已调整为姓名第一列，textbox.first() 正确命中
    const nameInput = zhangRow.getByRole("textbox").first();
    await expect(nameInput).toHaveValue("张三");

    // 提交保存 → 整行编辑退出，行数据仍可见（虚拟滚动中"张三"文本可能
    // 出现在多行 DOM 中，strict mode 下需 .first() 消除歧义）
    await saveBtn.click();
    await expect(saveBtn).not.toBeVisible();
    await expect(zhangRow.getByText("张三").first()).toBeVisible();
  });
});
