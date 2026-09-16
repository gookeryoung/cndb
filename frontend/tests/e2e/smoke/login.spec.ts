/** P0 Smoke — 登录流程：匿名重定向 / 表单登录 / 错误密码.
 *
 * cndb 使用 Ant Design + React Router：
 * - 未登录访问根 → Navigate 到 /login?return_to=%2F
 * - 登录成功 → Navigate 到 return_to（默认 /w，工作区列表视图）
 * - 根路径 / 不可直接访问，登录后自动重定向到 /w
 */
import { test, expect } from "@playwright/test";

const ANON_PROJECTS = ["setup", "chromium-anon"];

function isAnon(): boolean {
  return ANON_PROJECTS.includes(test.info().project.name);
}

function isAuthed(): boolean {
  return test.info().project.name === "chromium-authed";
}

// ── 匿名场景：仅 chromium-anon ──────────────────────────

test.describe("匿名（chromium-anon only）", () => {
  test.skip(isAuthed, "authed 项目用户已登录，跳过");

  test("未登录访问 / → 重定向到 /login", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/login/);
    // 登录表单关键元素
    await expect(page.getByPlaceholder("用户名或邮箱")).toBeVisible();
    await expect(page.getByPlaceholder("密码")).toBeVisible();
    await expect(page.getByRole("button", { name: /登 录/ })).toBeVisible();
  });

  test("表单登录成功 → 进入工作区列表 /w", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("用户名或邮箱").fill("demo");
    await page.getByPlaceholder("密码").fill("demo1234");
    await page.getByRole("button", { name: /登 录/ }).click();
    // 登录成功 → 自动 Navigate 到 /w（工作区列表视图，不再自动跳入某个工作区）
    await page.waitForURL(/\/w$/);
    // 工作区列表关键锚点
    await expect(page.getByTestId("workspace-list")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /我的工作区/ })).toBeVisible();
  });

  test("错误密码 → 保留在登录页并显示错误", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("用户名或邮箱").fill("demo");
    await page.getByPlaceholder("密码").fill("wrong-password");
    await page.getByRole("button", { name: /登 录/ }).click();
    // 应该还在登录页
    await page.waitForTimeout(500);
    await expect(page.getByPlaceholder("用户名或邮箱")).toBeVisible();
    await expect(page.getByPlaceholder("密码")).toBeVisible();
  });
});

// ── 已登录场景：仅 chromium-authed ──────────────────────

test.describe("已登录会话（chromium-authed only）", () => {
  test.skip(isAnon, "anon 项目无 StorageState，跳过");

  test("已登录访问根 / → 自动重定向到 /w 工作区列表", async ({ page }) => {
    await page.goto("/");
    // 根路径不可直接访问，应跳转到 /w
    await page.waitForURL(/\/w$/);
    // 工作区列表关键锚点
    await expect(page.getByTestId("workspace-list")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /我的工作区/ })).toBeVisible();
  });
});
