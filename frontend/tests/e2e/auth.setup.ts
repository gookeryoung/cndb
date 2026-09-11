/** 登录 setup：一次表单登录 → 持久化 StorageState 到 .auth/state.json.
 *
 * 所有 `chromium-authed` 项目用例自动复用此 state，避免每用例重复登录.
 * 重新跑 auth.setup.ts 即可刷新（当密码/权限变更后）.
 */
import { test, expect } from "@playwright/test";

const DEMO_USER = "demo";
const DEMO_PASS = "demo1234";
const STATE_PATH = ".auth/state.json";

test("登录并持久化 StorageState", async ({ page }) => {
  // 未登录访问根 → 重定向到 /login
  await page.goto("/");
  await page.waitForURL(/\/login/);

  // 表单定位：Ant Design Form — input#username / input#password
  // Antd 使用 Form.Item name 属性，内部 input 可通过 placeholder 定位
  const usernameInput = page.getByPlaceholder("用户名或邮箱");
  const passwordInput = page.getByPlaceholder("密码");
  const loginButton = page.getByRole("button", { name: /登 录/ });

  await expect(usernameInput).toBeVisible();
  await expect(passwordInput).toBeVisible();
  await expect(loginButton).toBeVisible();

  await usernameInput.fill(DEMO_USER);
  await passwordInput.fill(DEMO_PASS);
  await loginButton.click();

  // 登录成功 → 重定向到 /w（工作区列表，然后自动 Navigate 到 /w/{wid}/tables）
  await page.waitForURL(/\/w\/\d+/);
  // 主应用关键元素 — h3 标题 "演示工作区 · 表"
  await expect(page.getByRole("heading", { level: 3, name: /演示工作区/ })).toBeVisible();

  // 持久化 cookie + localStorage
  await page.context().storageState({ path: STATE_PATH });
});
