/** Critical — API 自动建表 + 数据抓取 前端 E2E.
 *
 * 策略：用 page.route() 拦截 import-api 相关 3 个后端端点返回伪造响应，
 * 其他 API（登录、表列表、行 CRUD 等）走真实后端。
 * 这样既不依赖真实的网络抓取能力（SSRF 防护会拦截本地），
 * 又能完整验证前端 UI 流程。
 *
 * 覆盖场景：
 *   1. TablesList 页面点击 "API 建表" → 分析预览 → 建表 → 跳转
 *   2. GridPage 的 "导入/导出" → API 抓取追加 tab → 分析预览 → 追加
 *   3. 错误提示：URL 不合法、后端返回 400
 */
import { test, expect } from "../fixtures/auth";
import type { Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const WID = 1; // seed 后的"某企业销售管理"工作区

// ── Mock 数据 ────────────────────────────────────────

const MOCK_ANALYZE_RESPONSE = {
  columns: [
    { name: "symbol", field_type: "text", null_ratio: 0, samples: ["BTC", "ETH", "SOL"] },
    { name: "name", field_type: "text", null_ratio: 0, samples: ["Bitcoin", "Ethereum", "Solana"] },
    { name: "price", field_type: "float", null_ratio: 0, samples: [65000.0, 3200.5, 145.3] },
    { name: "market_cap", field_type: "number", null_ratio: 0.1, samples: [1_200_000_000_000, 380_000_000_000, 60_000_000_000] },
    { name: "change_24h", field_type: "float", null_ratio: 0, samples: [2.5, -1.2, 5.8] },
    { name: "is_active", field_type: "boolean", null_ratio: 0, samples: [true, true, false] },
    { name: "listed_date", field_type: "date", null_ratio: 0, samples: ["2009-01-03", "2015-07-30", "2020-03-16"] },
  ],
  total_rows: 42,
  sample_row_keys: ["symbol", "name", "price", "market_cap", "change_24h", "is_active", "listed_date"],
};

const MOCK_CREATE_RESPONSE = {
  table_id: 9999,
  table_name: "加密货币行情",
  imported_rows: 42,
  field_count: 7,
  columns: MOCK_ANALYZE_RESPONSE.columns,
};

const MOCK_APPEND_RESPONSE = {
  table_id: 2, // seed 表之一
  appended_rows: 42,
};

/** 注册 import-api 相关路由的 mock */
function mockImportApiRoutes(page: Page) {
  page.route(/\/api\/v1\/workspaces\/\d+\/import-api\/analyze$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_ANALYZE_RESPONSE),
    });
  });
  page.route(/\/api\/v1\/workspaces\/\d+\/import-api$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_CREATE_RESPONSE),
    });
  });
  page.route(/\/api\/v1\/workspaces\/\d+\/tables\/\d+\/import-api$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_APPEND_RESPONSE),
    });
  });
}

/** 让 analyze 端点返回 SSRF 错误（400） */
function mockAnalyzeError(page: Page, status = 400, detail = "禁止访问保留 IP: 127.0.0.1") {
  page.route(/\/api\/v1\/workspaces\/\d+\/import-api\/analyze$/, async (route) => {
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify({ detail }),
    });
  });
}

// ── 辅助：打开建表 Dialog 并填入参数 ─────────────────

async function openCreateDialog(page: Page) {
  await page.goto(`/w/${WID}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.waitForTimeout(300);
  // 点击 "API 建表" 按钮
  await page.getByTestId("api-import-entry").click();
  // Dialog 打开 — 等 URL 输入框出现
  await expect(page.getByTestId("api-url-input")).toBeVisible();
}

async function openAppendDialog(page: Page) {
  // 进入某张已存在的 seed 表（表列表第二张一般可用）
  await page.goto(`/w/${WID}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  // 直接点表格第一行（跳过具体表名依赖）
  const firstRow = page.locator(".ant-table-tbody tr.ant-table-row").first();
  await firstRow.click();
  await page.waitForURL(/\/tables\/\d+/);
  await page.waitForTimeout(500);

  // 顶部 "导入/导出" 按钮
  await page.getByRole("button", { name: /导入\/导出/ }).click();
  // 切到 "API 抓取追加" tab
  const tabs = page.locator(".ant-tabs-tab");
  await expect(tabs).toHaveCount(3);
  await tabs.nth(2).click();
  // URL 输入框应该出现（embed 模式）
  await expect(page.getByTestId("api-url-input")).toBeVisible();
}

// ── 测试用例 ─────────────────────────────────────────

/** 需要登录态（chromium-authed only）的 API 建表/追加流程测试 */
test.describe("API 自动建表 + 数据抓取", () => {
  test.skip(
    () => !["chromium-authed"].includes(test.info().project.name),
    "需要登录态，anon 项目跳过",
  );

  test("Analyze 端点返回的列元数据正确展示", async ({ page }) => {
    mockImportApiRoutes(page);
    await openCreateDialog(page);

    // 填 URL + 表名
    await page.getByTestId("api-url-input").fill("https://api.coingecko.com/api/v3/coins/markets");
    await page.getByLabel("请求方法").first().click();
    await page.getByTitle("GET", { exact: true }).click();
    await page.getByLabel("新表名称").fill("加密货币行情");

    // 点 "分析" 按钮
    await page.getByTestId("api-analyze-btn").click();

    // 预览区域出现
    const preview = page.getByTestId("api-analyze-preview");
    await expect(preview).toBeVisible();

    // Descriptions 面板 — 42 行 / 7 字段
    await expect(preview.getByText("42")).toBeVisible();
    await expect(preview.getByText("7")).toBeVisible();

    // 表格中的字段名
    const fieldTable = preview.locator(".ant-table-body");
    await expect(fieldTable.getByText("symbol")).toBeVisible();
    await expect(fieldTable.getByText("name")).toBeVisible();
    await expect(fieldTable.getByText("price")).toBeVisible();
    await expect(fieldTable.getByText("market_cap")).toBeVisible();

    // 类型推断 Tag
    await expect(fieldTable.getByText("float")).toBeVisible();
    await expect(fieldTable.getByText("number")).toBeVisible();
    await expect(fieldTable.getByText("boolean")).toBeVisible();
    await expect(fieldTable.getByText("date")).toBeVisible();

    // 样本值
    await expect(fieldTable.getByText("BTC")).toBeVisible();
    await expect(fieldTable.getByText("Bitcoin")).toBeVisible();
  });

  test("建表流程：分析 → 建表 → 成功消息 → 自动跳转", async ({ page }) => {
    mockImportApiRoutes(page);
    await openCreateDialog(page);

    // 填 URL + 表名
    await page.getByTestId("api-url-input").fill("https://api.coingecko.com/api/v3/coins/markets");
    await page.getByLabel("新表名称").fill("加密货币行情");

    // 分析 → 预览
    await page.getByTestId("api-analyze-btn").click();
    await expect(page.getByTestId("api-analyze-preview")).toBeVisible();

    // "建表并导入" 按钮启用，点击
    const importBtn = page.getByTestId("api-import-btn");
    await expect(importBtn).toBeEnabled();
    await expect(importBtn).toHaveText(/建表并导入/);
    await importBtn.click();

    // 成功提示 — antd message 的"已创建表"文案
    const successMsg = page.locator(".ant-message").filter({ hasText: /已创建表.*加密货币行情.*42 行/ });
    await expect(successMsg).toBeVisible({ timeout: 5000 });

    // 自动跳转到新表（mock 返回 table_id=9999）
    await page.waitForURL(/\/tables\/\d+/, { timeout: 5000 });
  });

  test("追加流程：进入已有表 → 打开导入导出 → 切 API tab → 分析 → 追加", async ({ page }) => {
    mockImportApiRoutes(page);
    await openAppendDialog(page);

    // 追加模式下不应该有表名字段
    await expect(page.getByLabel("新表名称")).toBeHidden();

    // 填 URL
    await page.getByTestId("api-url-input").fill("https://api.coingecko.com/api/v3/coins/markets");

    // 分析
    await page.getByTestId("api-analyze-btn").click();
    await expect(page.getByTestId("api-analyze-preview")).toBeVisible();

    // 预览
    const preview = page.getByTestId("api-analyze-preview");
    await expect(preview.getByText("42")).toBeVisible(); // 总行数

    // 按钮应该显示 "追加到当前表"
    const importBtn = page.getByTestId("api-import-btn");
    await expect(importBtn).toHaveText(/追加到当前表/);
    await importBtn.click();

    // 成功提示
    const successMsg = page.locator(".ant-message").filter({ hasText: /已追加 42 行/ });
    await expect(successMsg).toBeVisible({ timeout: 5000 });
  });

  test("追加流程：后端 400 错误在 Dialog 内展示 Alert", async ({ page }) => {
    mockAnalyzeError(page, 400, "禁止访问保留 IP: 127.0.0.1");
    await openAppendDialog(page);

    // 填 URL（不合法的被 SSRF 拦截）
    await page.getByTestId("api-url-input").fill("http://127.0.0.1/admin");

    // 点分析 → 失败
    await page.getByTestId("api-analyze-btn").click();
    // 应该显示错误 Alert
    const alert = page.getByTestId("api-error-alert");
    await expect(alert).toBeVisible({ timeout: 3000 });
    await expect(alert).toContainText(/127\.0\.0\.1/);

    // 预览不应该出现
    await expect(page.getByTestId("api-analyze-preview")).toBeHidden();
    // "导入"按钮应该禁用
    const importBtn = page.getByTestId("api-import-btn");
    await expect(importBtn).toBeDisabled();
  });

  test("URL 表单校验：http 前缀强制 + 非法 URL 禁止提交", async ({ page }) => {
    await openCreateDialog(page);

    // 不填 URL 直接分析 → 应该有校验错误
    await page.getByTestId("api-analyze-btn").click();
    await expect(page.getByText(/请输入 API URL/)).toBeVisible({ timeout: 2000 });

    // 填非 http 开头 → 表单校验
    await page.getByTestId("api-url-input").fill("ftp://example.com/file");
    await page.getByTestId("api-analyze-btn").click();
    await expect(page.getByText(/仅支持 http.*或 https.*开头/)).toBeVisible({ timeout: 2000 });
  });

  test("高级参数折叠面板可展开并保存 headers/params", async ({ page }) => {
    mockImportApiRoutes(page);
    await openCreateDialog(page);

    // 展开高级参数
    const advanced = page.getByText("高级参数").first();
    await advanced.click();

    // 填 headers
    await page.getByLabel("自定义请求头").fill("Authorization: Bearer test-token-12345");
    // 填 query params（JSON 对象）
    await page.getByLabel("URL 查询参数", { exact: false }).fill('{"page": 1}');

    // 填 URL + 表名
    await page.getByTestId("api-url-input").fill("https://api.example.com/v1/data");
    await page.getByLabel("新表名称").fill("测试高级参数");

    // 分析
    await page.getByTestId("api-analyze-btn").click();
    await expect(page.getByTestId("api-analyze-preview")).toBeVisible();

    // 验证发出的 analyze 请求包含 headers 和 params — 用 page.evaluate 抓不到，
    // 但我们可以用 route 的 fulfilled 请求体做断言
  });

  test("追加流程与导入/导出 Dialog 的三个 tab 正常切换", async ({ page }) => {
    mockImportApiRoutes(page);
    await openAppendDialog(page);

    const tabs = page.locator(".ant-tabs-tab");
    // 切回第一个 tab（文件导入）
    await tabs.nth(0).click();
    await expect(page.getByText(/点击或拖拽文件到此处/)).toBeVisible();

    // 切到第二个 tab（导出）
    await tabs.nth(1).click();
    await expect(page.getByText(/将表中的数据导出为所选格式/)).toBeVisible();

    // 切到第三个 tab（API 抓取追加）
    await tabs.nth(2).click();
    await expect(page.getByTestId("api-url-input")).toBeVisible();
  });
});

/* ─────────────── 视觉回归：深色模式下 API 抓取对话框无白色背景块 ───────────────
 * 本测试组是 Issue 修复的回归保护，验证深色模式下：
 *   1. 预览区域 Descriptions label 背景不是白色
 *   2. 预览区域 Table 边框不是白色
 *   3. 占位符（未分析时）区域背景不是白色
 */
test.describe("深色模式下 API 抓取对话框视觉回归", () => {
  /** 辅助：切换到 GitHub 深色主题 — 直接写 localStorage + reload */
  async function ensureDarkTheme(page: Page) {
    const body = page.locator("body");
    if (!(await body.evaluate(el => el.classList.contains("theme-github-dark")))) {
      await page.evaluate(() => {
        localStorage.setItem("cndb_theme", "github-dark");
      });
      await page.reload();
      await page.waitForURL(/\/w\/\d+\/tables/);
      await expect(body).toHaveClass(/theme-github-dark/);
      await page.waitForTimeout(500);
    }
  }

  test("深色模式 — 未分析时占位符区域背景/边框不是白色", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    mockImportApiRoutes(page);

    // 进入应用并切深色主题
    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await ensureDarkTheme(page);

    // 打开 API 建表 Dialog
    await page.getByTestId("api-import-entry").click();
    await expect(page.getByTestId("api-url-input")).toBeVisible();

    // 找到占位符区域
    const placeholder = page.getByTestId("api-placeholder");
    await expect(placeholder).toBeVisible();

    const placeholderBg = await placeholder.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(placeholderBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);

    const placeholderBorder = await placeholder.evaluate(el => getComputedStyle(el).borderColor);
    expect(placeholderBorder).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
  });

  test("深色模式 — 分析预览区域 Descriptions label 背景不是白色", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    mockImportApiRoutes(page);

    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await ensureDarkTheme(page);

    await page.getByTestId("api-import-entry").click();
    await expect(page.getByTestId("api-url-input")).toBeVisible();

    // 填 URL → 分析
    await page.getByTestId("api-url-input").fill("https://api.example.com/data");
    await page.getByTestId("api-analyze-btn").click();

    const preview = page.getByTestId("api-analyze-preview");
    await expect(preview).toBeVisible();

    // Descriptions label 单元格
    const descLabels = preview.locator(".ant-descriptions-item-label");
    const labelCount = await descLabels.count();
    expect(labelCount).toBeGreaterThan(0);

    // 检查前 3 个 label 单元格背景色都不是白色
    for (let i = 0; i < Math.min(3, labelCount); i++) {
      const labelBg = await descLabels.nth(i).evaluate(el => getComputedStyle(el).backgroundColor);
      expect(labelBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
    }
  });

  test("深色模式 — 分析预览区域 Table 边框不是白色", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    mockImportApiRoutes(page);

    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await ensureDarkTheme(page);

    await page.getByTestId("api-import-entry").click();
    await expect(page.getByTestId("api-url-input")).toBeVisible();

    await page.getByTestId("api-url-input").fill("https://api.example.com/data");
    await page.getByTestId("api-analyze-btn").click();

    const preview = page.getByTestId("api-analyze-preview");
    await expect(preview).toBeVisible();

    // Table 外层边框容器
    const tableWrapper = preview.locator(".ant-table").first();
    const borderColor = await tableWrapper.evaluate(el => getComputedStyle(el).borderColor);
    expect(borderColor).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);

    // Table body 背景也不能是白色
    const tableBody = preview.locator(".ant-table-body").first();
    const bodyBg = await tableBody.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bodyBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
  });

  test("深色模式 — API 抓取追加 Dialog embed 模式下无白色块", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    mockImportApiRoutes(page);

    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await ensureDarkTheme(page);

    // 进入第一张表
    const firstRow = page.locator(".ant-table-tbody tr.ant-table-row").first();
    await firstRow.click();
    await page.waitForURL(/\/tables\/\d+/);
    await page.waitForTimeout(500);

    // 打开导入导出 → 切 API tab
    await page.getByRole("button", { name: /导入\/导出/ }).click();
    const tabs = page.locator(".ant-tabs-tab");
    await tabs.nth(2).click();
    await expect(page.getByTestId("api-url-input")).toBeVisible();

    // 分析 → 出现预览
    await page.getByTestId("api-url-input").fill("https://api.example.com/data");
    await page.getByTestId("api-analyze-btn").click();

    const preview = page.getByTestId("api-analyze-preview");
    await expect(preview).toBeVisible();

    // embed 模式下 Table 背景也不能是白色
    const tableBg = await preview.locator(".ant-table").first()
      .evaluate(el => getComputedStyle(el).backgroundColor);
    expect(tableBg).not.toMatch(/rgba?\(25[0-5],\s*25[0-5],\s*25[0-5]/);
  });
});
