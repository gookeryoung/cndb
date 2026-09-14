/** 报表模板页面 E2E — /w/:wid/reports.
 *
 * 覆盖：页面加载、模板 CRUD、校验错误、渲染下载、参数 Modal、
 *       格式下拉枚举（Phase 1 修复后的对齐）。
 *
 * 所有会改写模板数据的测试都用 serial 模式串行执行，避免并行污染。
 * 只读类场景（页面加载、预置模板存在、格式枚举）放在前两个 describe 块，
 * 后面的 CRUD 共享同一个 describe.configure({ mode: 'serial' })。
 */

import { test, expect } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1;

// ─────────────── 只读：页面加载与预置数据 ───────────────

test.describe("报表模板页面 /w/:wid/reports", () => {
  test("直接访问 — 标题 + 表格 + 新建按钮 + 6 列表头", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await expect(page.locator("h3", { hasText: /报表模板/ })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /新建模板/ })).toBeVisible();
    await expect(page.locator(".ant-table")).toBeVisible();

    // 表头：模板名称/输出格式/关联表/描述/参数/操作
    const headers = page.getByRole("columnheader");
    await expect(headers).toHaveCount(6, { timeout: 5000 });
  });

  test("seed 预置 — 存在员工名册模板", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await expect(page.locator(".ant-table-row")).toHaveCount(1, { timeout: 10000 });
    const firstRow = page.locator(".ant-table-row").first();
    await expect(firstRow.getByText(/员工名册/)).toBeVisible();
  });

  test("格式下拉 — 仅有 docx / pdf / xlsx 三种选项（Phase 1 对齐后）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // 打开新建模板 Modal
    await page.getByRole("button", { name: /新建模板/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // 点击输出格式 Select，检查下拉项
    const formatSelect = page.locator(".ant-form-item").filter({ hasText: /输出格式/ }).locator(".ant-select");
    await formatSelect.click();

    const options = page.locator(".ant-select-item-option");
    await expect(options).toHaveCount(3, { timeout: 3000 });
    await expect(options.filter({ hasText: /Word/ })).toBeVisible();
    await expect(options.filter({ hasText: /PDF/ })).toBeVisible();
    await expect(options.filter({ hasText: /Excel/ })).toBeVisible();
    // 关闭 Modal
    await page.getByRole("button", { name: /取消/ }).click();
  });

  test("描述文案正确 — 仅提及 Word/PDF/Excel", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await expect(page.locator("h3").first().locator("..")).toContainText(/Word.*PDF.*Excel/);
  });

  test("返回工作区 — 点击左箭头回到 /w/:wid", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /arrow-left/i }).first().click();
    await page.waitForURL(/\/w\/\d+$/);
  });
});

// ─────────────── CRUD + 渲染：串行执行，避免数据污染 ───────────────

test.describe.configure({ mode: "serial" });
test.describe("报表模板 CRUD + 渲染（串行）", () => {
  test("新建模板 — 完整表单 → 表格新增行 + 成功提示", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);
    const rowCountBefore = await page.locator(".ant-table-row").count();

    // 打开 Modal
    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 填写表单
    await dialog.getByLabel(/模板名称/).fill("E2E 测试模板");
    await dialog.getByLabel(/输出格式/).click();
    const pdfOpt = page.locator(".ant-select-item-option").filter({ hasText: /PDF/ }).first();
    await pdfOpt.click();
    await dialog.getByLabel(/描述/).fill("由 E2E 测试自动创建");
    await dialog.getByLabel(/模板内容/).fill("# 测试报告\n{{ table_name }}");

    // 提交
    await dialog.getByRole("button", { name: /创建/ }).click();

    // 成功 message
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已创建/, {
      timeout: 8000,
    });

    // 表格增加一行
    await expect(page.locator(".ant-table-row")).toHaveCount(rowCountBefore + 1, { timeout: 5000 });
    await expect(page.locator(".ant-table-row").last()).toContainText("E2E 测试模板");
  });

  test("新建模板 — 必填校验：空名称 + 空模板内容显示错误", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 不填任何内容直接提交
    await dialog.getByRole("button", { name: /创建/ }).click();

    // 必填校验错误提示
    await expect(dialog.getByText(/请输入名称/)).toBeVisible({ timeout: 3000 });
    await expect(dialog.getByText(/请输入模板内容/)).toBeVisible();

    // 关闭
    await dialog.getByRole("button", { name: /取消/ }).click();
  });

  test("编辑模板 — 回填后修改名称 → 保存成功", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // 操作列的 MoreOutlined 下拉 → 编辑
    const lastRow = page.locator(".ant-table-row").last();
    await lastRow.getByRole("button", { name: /more/i }).click();

    // Antd Dropdown 的 edit 选项
    const editOption = page.locator(".ant-dropdown-menu-item").filter({ hasText: /编辑/ });
    await expect(editOption).toBeVisible();
    await editOption.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 名称输入框应已有值（回填）
    const nameInput = dialog.getByLabel(/模板名称/);
    await expect(nameInput).toHaveValue(/E2E 测试模板/, { timeout: 8000 });

    // 修改名称
    await nameInput.fill("E2E 模板-已编辑");
    await dialog.getByRole("button", { name: /保存/ }).click();

    // 成功 message
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已更新/, {
      timeout: 8000,
    });

    // 表格最后一行名称更新
    await expect(page.locator(".ant-table-row").last()).toContainText("E2E 模板-已编辑", { timeout: 5000 });
  });

  test("删除模板 — 确认后行消失", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);
    const rowCountBefore = await page.locator(".ant-table-row").count();

    // 最后一行 → More → 删除
    const lastRow = page.locator(".ant-table-row").last();
    await lastRow.getByRole("button", { name: /more/i }).click();

    const deleteOption = page.locator(".ant-dropdown-menu-item").filter({ hasText: /删除/ });
    await expect(deleteOption).toBeVisible();
    await deleteOption.click();

    // confirm dialog
    const confirmDialog = page.locator(".ant-modal-confirm");
    await expect(confirmDialog).toBeVisible({ timeout: 3000 });
    await expect(confirmDialog).toContainText(/确认删除/);

    await confirmDialog.getByRole("button", { name: /删除/ }).click();

    // 表格减少一行
    await expect(page.locator(".ant-table-row")).toHaveCount(rowCountBefore - 1, { timeout: 5000 });
  });

  test("删除模板 — 取消后行仍在", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);
    const rowCountBefore = await page.locator(".ant-table-row").count();

    const lastRow = page.locator(".ant-table-row").last();
    await lastRow.getByRole("button", { name: /more/i }).click();
    const deleteOption = page.locator(".ant-dropdown-menu-item").filter({ hasText: /删除/ });
    await deleteOption.click();

    const confirmDialog = page.locator(".ant-modal-confirm");
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole("button", { name: /取消/ }).click();

    // 行数不变
    await expect(page.locator(".ant-table-row")).toHaveCount(rowCountBefore);
  });

  test("渲染已关联表的模板 — 触发浏览器下载 + 成功提示", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // seed 的第一个模板是"员工名册"，绑定了员工表
    const firstRow = page.locator(".ant-table-row").first();

    // 等待模板列表加载
    await expect(firstRow).toContainText(/员工名册/, { timeout: 8000 });

    // 期望下载事件
    const downloadPromise = page.waitForEvent("download", { timeout: 15000 });

    // 点击渲染下载按钮
    const renderBtn = firstRow.getByRole("button", { name: /渲染下载/ });
    await expect(renderBtn).toBeEnabled();
    await renderBtn.click();

    const download = await downloadPromise;
    const filename = download.suggestedFilename() || "";
    // seed 模板是 docx 格式
    expect(filename).toMatch(/员工名册.*\.(docx|pdf|xlsx)/i);

    // 成功 message
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/报告已生成/, {
      timeout: 5000,
    });
  });

  test("渲染未关联表的模板 — 按钮 disabled", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // 先创建一个 table_id=null 的模板
    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.getByLabel(/模板名称/).fill("无关联表模板");
    // table_id 不选（为空）
    await dialog.getByLabel(/模板内容/).fill("hello world");
    await dialog.getByRole("button", { name: /创建/ }).click();

    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已创建/, {
      timeout: 8000,
    });

    // 最后一行 → 渲染下载按钮应为 disabled
    const lastRow = page.locator(".ant-table-row").last();
    const renderBtn = lastRow.getByRole("button", { name: /渲染下载/ });
    await expect(renderBtn).toBeDisabled({ timeout: 3000 });
  });

  test("带参数的模板 — 定义参数后渲染弹参数 Modal", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // 打开新建 Modal
    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.getByLabel(/模板名称/).fill("带参数模板");
    await dialog.getByLabel(/模板内容/).fill("Hello {{ params.name }} - {{ params.count }}");

    // 添加参数
    await dialog.getByRole("button", { name: /添加参数/ }).click();

    // 参数行：名称=name，类型=string，必填=false
    const paramRows = dialog.locator(".ant-space").filter({ has: page.locator("input[placeholder='参数名']") });
    await expect(paramRows.first()).toBeVisible();
    await paramRows.first().locator("input").first().fill("name");

    // 添加第二个参数
    await dialog.getByRole("button", { name: /添加参数/ }).click();
    const paramRows2 = dialog.locator(".ant-space").filter({ has: page.locator("input[placeholder='参数名']") });
    await expect(paramRows2).toHaveCount(2);
    await paramRows2.nth(1).locator("input").first().fill("count");

    // 提交
    await dialog.getByRole("button", { name: /创建/ }).click();
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已创建/, {
      timeout: 8000,
    });

    // 最后一行 → 操作列，应该显示 2 个参数 Tag
    const lastRow = page.locator(".ant-table-row").last();
    await expect(lastRow.getByText(/name/)).toBeVisible();
    await expect(lastRow.getByText(/count/)).toBeVisible();
  });
});
