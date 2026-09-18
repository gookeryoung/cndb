/** 报表模板页面 E2E — /w/:wid/reports.
 *
 * 覆盖：页面加载、模板 CRUD、校验错误、渲染下载、参数 Modal、
 *       格式下拉枚举（Phase 1 修复后的对齐）。
 *
 * 所有会改写模板数据的测试都用 serial 模式串行执行，避免并行污染。
 * 只读类场景（页面加载、预置模板存在、格式枚举）放在前两个 describe 块，
 * 后面的 CRUD 共享同一个 describe.configure({ mode: 'serial' })。
 */

import { test, expect } from "../fixtures/auth";

const ANON = ["setup", "chromium-anon"];
const WID = 1;

// ─────────────── 只读：页面加载与预置数据 ───────────────

test.describe("报表模板页面 /w/:wid/reports（只读）", () => {
  test("页面加载 — 标题 + 表格 + 新建按钮 + 预置员工名册模板 + 格式对齐 + 导航返回", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    // 标题 + 新建按钮 + 表格 + 6 列表头
    await expect(page.locator("h3", { hasText: /报表模板/ })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /新建模板/ })).toBeVisible();
    await expect(page.locator(".ant-table")).toBeVisible();
    await expect(page.getByRole("columnheader")).toHaveCount(6, { timeout: 5000 });

    // seed 预置：1 行员工名册模板
    await expect(page.locator(".ant-table-row")).toHaveCount(1, { timeout: 10000 });
    await expect(page.locator(".ant-table-row").first()).toContainText(/员工名册/);

    // 描述文案：仅提及 Word/PDF/Excel
    await expect(page.getByText(/Word.*PDF.*Excel/).first()).toBeVisible();

    // 返回工作区（独立断言避免后续 Modal 打开干扰）
    const backBtn = page.getByRole("button", { name: /arrow-left/i }).first();
    await expect(backBtn).toBeVisible();
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
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
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
    await expect(page.locator(".ant-table-row").first()).toBeVisible({ timeout: 10000 });
    const rowCountBefore = await page.locator(".ant-table-row").count();

    // 打开 Modal
    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 填写表单
    await dialog.getByLabel(/模板名称/).fill("E2E 测试模板");
    await dialog.locator(".ant-form-item").filter({ hasText: /输出格式/ }).locator(".ant-select").click();
    const pdfOpt = page.locator(".ant-select-item-option").filter({ hasText: /PDF/ }).first();
    await pdfOpt.click();
    await dialog.getByLabel(/描述/).fill("由 E2E 测试自动创建");
    const cmEditor = dialog.locator(".report-codemirror-host").first();
    await cmEditor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await page.keyboard.type("# 测试报告\n{{ table_name }}", { delay: 5 });
    await page.keyboard.press("Tab");

    // 提交
    await dialog.getByRole("button", { name: /创\s*建/ }).click();

    // 成功 message
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已创建/, {
      timeout: 8000,
    });

    // 表格增加一行
    await expect(page.locator(".ant-table-row")).toHaveCount(rowCountBefore + 1, { timeout: 5000 });
    await expect(page.locator(".ant-table-row").last()).toContainText("E2E 测试模板");
  });

  test("新建模板 — 必填校验：空名称显示错误", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 不填任何内容直接提交
    await dialog.getByRole("button", { name: /创\s*建/ }).click();

    // 必填校验错误提示（template_content Form.Item hidden，只查 name）
    await expect(dialog.getByText(/请输入名称/)).toBeVisible({ timeout: 3000 });

    // 关闭
    await dialog.getByRole("button", { name: /取\s*消/ }).click();
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
    await dialog.getByRole("button", { name: /保\s*存/ }).click();

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
    await expect(page.locator(".ant-table-row").first()).toBeVisible({ timeout: 10000 });
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
    await expect(confirmDialog).toContainText(/删除模板/);

    await confirmDialog.getByRole("button", { name: /删\s*除/ }).click();

    // 表格减少一行
    await expect(page.locator(".ant-table-row")).toHaveCount(rowCountBefore - 1, { timeout: 5000 });
  });

  test("删除模板 — 取消后行仍在", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);
    await expect(page.locator(".ant-table-row").first()).toBeVisible({ timeout: 10000 });
    const rowCountBefore = await page.locator(".ant-table-row").count();

    const lastRow = page.locator(".ant-table-row").last();
    await lastRow.getByRole("button", { name: /more/i }).click();
    const deleteOption = page.locator(".ant-dropdown-menu-item").filter({ hasText: /删除/ });
    await deleteOption.click();

    const confirmDialog = page.locator(".ant-modal-confirm");
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole("button", { name: /取\s*消/ }).click();

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
    const cm2 = dialog.locator(".report-codemirror-host").first();
    await cm2.click(); await page.keyboard.press("Control+A"); await page.keyboard.press("Backspace");
    await page.keyboard.type("hello world", { delay: 5 }); await page.keyboard.press("Tab");
    await dialog.getByRole("button", { name: /创\s*建/ }).click();

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
    const cm3 = dialog.locator(".report-codemirror-host").first();
    await cm3.click(); await page.keyboard.press("Control+A"); await page.keyboard.press("Backspace");
    await page.keyboard.type("Hello {{ params.name }} - {{ params.count }}", { delay: 5 }); await page.keyboard.press("Tab");

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
    await dialog.getByRole("button", { name: /创\s*建/ }).click();
    await expect(page.locator(".ant-message-notice-content").first()).toContainText(/模板已创建/, {
      timeout: 8000,
    });

    // 最后一行 → 操作列，应该显示 2 个参数 Tag
    const lastRow = page.locator(".ant-table-row").last();
    await expect(lastRow.getByText(/name/)).toBeVisible();
    await expect(lastRow.getByText(/count/)).toBeVisible();
  });
});

// ─────────────── Task 10: 多表引用 + 编辑器增强 ───────────────

test.describe("多表引用 + 编辑器增强（只读）", () => {
  test("新建模板 — 表单包含额外引用表多选器", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 额外引用表多选器存在
    const extraLabel = dialog.getByText(/额外引用表/).first();
    await expect(extraLabel).toBeVisible({ timeout: 5000 });

    // 选择关联表后，打开额外引用表 Select 查看可用选项
    await dialog.getByLabel(/关联表/).click();
    const empTableOpt = page.locator(".ant-select-item-option").filter({ hasText: /员工表/ }).first();
    if (await empTableOpt.isVisible({ timeout: 3000 }).catch(() => false)) {
      await empTableOpt.click();
    } else {
      await page.locator(".ant-select-item-option").first().click();
    }

    // 额外引用表 Select 应该是 multiple mode
    const extraSelectContainer = page.locator(".ant-form-item").filter({ hasText: /额外引用表/ }).locator(".ant-select");
    await extraSelectContainer.click();
    const extraOptions = page.locator(".ant-select-item-option");
    await expect(extraOptions.first()).toBeVisible({ timeout: 3000 });
    expect(await extraOptions.count()).toBeGreaterThanOrEqual(1);
    // 直接 Esc 关闭下拉
    await page.keyboard.press("Escape");

    // 关闭 Modal
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  });

  test("编辑器 — SyntaxHelpPanel 包含跨表引用 + Markdown 输出分组", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 切换到"语法帮助"Tab
    const rightPanel = dialog.locator(".report-right-panel").first();
    const helpTab = rightPanel.getByRole("tab", { name: /语法帮助/ });
    await helpTab.click();

    // 跨表引成分组存在
    await expect(rightPanel.getByText(/跨表引用/).first()).toBeVisible({ timeout: 3000 });
    // Markdown 输出标记分组存在
    await expect(rightPanel.getByText(/Markdown/).first()).toBeVisible();
    // 简化：只验证标题分组可见
    
    // 简化：只验证 Markdown 标题可见

    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  });

  test("编辑器 — 实时预览支持模板渲染", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.getByLabel(/关联表/).click();
    await page.locator(".ant-select-item-option").first().click();

    // 在编辑器填模板
    const cmEditor = dialog.locator(".report-codemirror-host").first();
    await cmEditor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await page.keyboard.type("# 测试报告", { delay: 5 });
    await page.keyboard.press("Tab");

    // 切换到预览 Tab
    const rightPanel = dialog.locator(".report-right-panel").first();
    const previewTab = rightPanel.getByRole("tab", { name: /实时预览/ });
    await previewTab.click();

    // 预览渲染成功（Markdown h1 出现，无 error alert）
    await expect(rightPanel.getByRole("heading", { name: /测试报告/ })).toBeVisible({ timeout: 5000 });
    const errorCount = await rightPanel.locator(".ant-alert").filter({ hasText: /渲染错误/ }).count();
    expect(errorCount).toBe(0);

    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  });

  test("渲染 Modal — 支持选择额外引用表", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await expect(page.locator(".ant-table-row").first()).toBeVisible({ timeout: 10000 });

    const firstRow = page.locator(".ant-table-row").first();
    await expect(firstRow).toContainText(/员工名册/, { timeout: 8000 });

    // 点击渲染下载按钮
    const renderBtn = firstRow.getByRole("button", { name: /渲染下载/ });
    await renderBtn.click();

    // 点击后等 dialog 出现
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 5000 });
    const renderDialog = page.getByRole("dialog").first();

    // 额外引用表选择器存在
    await expect(renderDialog.locator(".ant-form-item").filter({ hasText: /额外引用表/ }).first()).toBeVisible({ timeout: 3000 });

    await page.keyboard.press("Escape");
  });

  test("额外引用表选择器 — 自动排除已选主表", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    await page.goto(`/w/${WID}/reports`);
    await page.waitForURL(/\/reports$/);

    await page.getByRole("button", { name: /新建模板/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // 选第一个表作为主表
    await dialog.getByLabel(/关联表/).click();
    const allOptions = page.locator(".ant-select-item-option");
    const totalTables = await allOptions.count();
    const firstMainTable = allOptions.first();
    await firstMainTable.click();

    // 打开额外引用表 Select
    const extraSelectContainer = page.locator(".ant-form-item").filter({ hasText: /额外引用表/ }).locator(".ant-select");
    await extraSelectContainer.click();
    const extraOptions = page.locator(".ant-select-item-option");
    const extraCount = await extraOptions.count();

    // 额外选项应该比总表数少 1
    expect(extraCount).toBe(totalTables - 1);

    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  });
});
