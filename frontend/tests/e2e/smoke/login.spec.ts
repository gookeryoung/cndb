/** P0 Smoke — 登录流程：匿名重定向 / 表单登录 / 错误密码. */
import { test, expect } from "../fixtures/auth";

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
    await expect(page.getByPlaceholder("用户名或邮箱")).toBeVisible();
    await expect(page.getByPlaceholder("密码")).toBeVisible();
    await expect(page.getByRole("button", { name: /^登\s*录$/ })).toBeVisible();
  });

  test("动态背景可见且不拦截表单点击", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator(".auth-bg-canvas")).toBeVisible();
    await expect(page.locator(".auth-bg-layer")).toHaveAttribute("aria-hidden", "true");
    await expect(page.locator(".auth-bg-layer")).toHaveAttribute("data-effect", "flowfield");
    await expect(page.locator(".auth-bg-layer")).toHaveCSS("pointer-events", "none");

    await page.getByPlaceholder("用户名或邮箱").click();
    await expect(page.getByPlaceholder("用户名或邮箱")).toBeFocused();
  });

  test("表单登录成功 → 进入工作区列表 /w", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("用户名或邮箱").fill("demo");
    await page.getByPlaceholder("密码").fill("demo1234");
    await page.getByRole("button", { name: /^登\s*录$/ }).click();
    await page.waitForURL(/\/w$/);
    await expect(page.getByTestId("workspace-list")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /我的工作区/ })).toBeVisible();
  });

  test("错误密码 → 保留在登录页并显示错误", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("用户名或邮箱").fill("demo");
    await page.getByPlaceholder("密码").fill("wrong-password");
    await page.getByRole("button", { name: /^登\s*录$/ }).click();
    // 错误密码应保留在登录页，不跳转（toHaveURL 自动等待确认未重定向 /w）
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByPlaceholder("用户名或邮箱")).toBeVisible();
    await expect(page.getByPlaceholder("密码")).toBeVisible();
    await expect(page.getByText("用户名或密码错误")).toBeVisible();
  });

  test("错误密码后立即改对提交 → 正常登录（会话过期竞态回归，见 client.ts 401 分支）", async ({ page }) => {
    // 修复前：登录接口的 401 也会走 clearToken + auth:expired（500ms 防抖），
    // 随后立刻登录成功的会话会被延迟触发的 notifyExpired 清掉，用户被弹回 /login。
    await page.goto("/login");
    await page.getByPlaceholder("用户名或邮箱").fill("demo");
    await page.getByPlaceholder("密码").fill("wrong-password");
    await page.getByRole("button", { name: /^登\s*录$/ }).click();
    await expect(page.getByText("用户名或密码错误")).toBeVisible();

    await page.getByPlaceholder("密码").fill("demo1234");
    await page.getByRole("button", { name: /^登\s*录$/ }).click();
    await expect(page).toHaveURL(/\/w$/, { timeout: 15_000 });
    await expect(page.getByTestId("workspace-list")).toBeVisible();
  });
});

// ── 已登录场景：仅 chromium-authed ──────────────────────

test.describe("已登录会话（chromium-authed only）", () => {
  test.skip(isAnon, "anon 项目无 StorageState，跳过");

  test("已登录访问根 / → 自动重定向到 /w 工作区列表", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/w$/);
    await expect(page.getByTestId("workspace-list")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /我的工作区/ })).toBeVisible();
  });
});
