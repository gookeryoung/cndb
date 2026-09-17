/** P0 — 工作区新功能 E2E：列表卡片 / 设置对话框 / 备份对话框. */

import { test, expect } from "../fixtures/auth";

const ANON = ["setup", "chromium-anon"];

test.describe("工作区列表卡片展示", () => {
  test("卡片显示公开性标签", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);
    // seed 的工作区至少有 2 个
    const cards = page.locator(".ant-card");
    await expect(cards.first()).toBeVisible();

    // 每张卡片应该有公开性 Tag（公开/成员可见/私有）
    const visibilityTag = page.locator(".ant-tag").filter({ hasText: /公开|成员可见|私有/ }).first();
    await expect(visibilityTag).toBeVisible();
  });

  test("卡片有统计信息（表数 / 成员数）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    // 至少一个卡片显示了表数和成员数
    const tableCountText = page.getByText(/\d+\s*表/);
    const memberCountText = page.getByText(/\d+\s*成员/);
    await expect(tableCountText.first()).toBeVisible();
    await expect(memberCountText.first()).toBeVisible();
  });

  test("卡片有四项功能按钮（置顶 / 备份 / 设置 / 完整页面）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    const backupBtn = page.getByText(/备份/).first();
    const settingsBtn = page.locator("[data-testid='settings-btn-1']");
    const fullPageBtn = page.locator("[data-testid='settings-page-btn-1']");
    const pinBtn = page.getByText(/置顶|取消置顶/).first();

    await expect(backupBtn).toBeVisible();
    await expect(settingsBtn).toBeVisible();
    await expect(fullPageBtn).toBeVisible();
    await expect(pinBtn).toBeVisible();
  });
});

test.describe("工作区设置对话框", () => {
  test("打开设置 → 基本设置 Tab → 改名称保存", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    // 点击第一张卡片的"设置"按钮（data-testid 精确定位卡片内设置入口）
    await page.locator("[data-testid='settings-btn-1']").click();

    // 设置对话框标题（Ant Design Modal title 是 div，不是 heading）
    await expect(page.locator(".ant-modal-title")).toContainText("工作区设置");

    // 默认在"基本设置" Tab
    await expect(page.getByRole("tab", { name: /基本设置/ })).toBeVisible();

    // 修改名称
    const nameInput = page.getByLabel("工作区名称");
    await expect(nameInput).toBeVisible();
    await nameInput.fill(`E2E 测试工作区-${Date.now()}`);

    // 保存
    await page.getByRole("button", { name: /保存设置/ }).click();

    // 等待成功提示
    await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 5000 });
  });

  test("设置对话框切换到权限 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    await page.locator("[data-testid='settings-btn-1']").click();
    await page.getByRole("tab", { name: /权限/ }).click();

    // 权限 Tab 显示"用户"和"角色"表头
    await expect(page.getByText(/用户/).first()).toBeVisible();
    await expect(page.getByText(/角色/).first()).toBeVisible();
  });

  test("设置对话框切换到统计信息 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    await page.locator("[data-testid='settings-btn-1']").click();
    await page.getByRole("tab", { name: /统计信息/ }).click();

    // 统计 Tab 显示统计卡片和工作区信息
    await expect(page.getByText(/数据表/).first()).toBeVisible();
    await expect(page.getByText(/成员/).first()).toBeVisible();
  });
});

test.describe("工作区备份对话框", () => {
  test("打开备份对话框 → 默认在导出 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    await page.getByText(/备份/).first().click();

    // Ant Design Modal title
    await expect(page.locator(".ant-modal-title")).toContainText(/工作区.*导入.*导出/);

    // 默认显示"导出工作区"内容
    await expect(page.getByText(/导出整个工作区/)).toBeVisible();
  });

  test("备份对话框切换到导入 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    await page.getByText(/备份/).first().click();
    await page.getByRole("tab", { name: /导入到工作区/ }).click();

    // 导入 Tab 有文件上传区域
    await expect(page.getByText(/点击或拖拽.*JSON/)).toBeVisible();
  });
});
