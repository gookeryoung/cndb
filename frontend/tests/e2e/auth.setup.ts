import { test, expect } from "@playwright/test";

const DEMO_USER = "demo";
const DEMO_PASS = "demo1234";
const STATE_PATH = ".auth/state.json";

test("登录并持久化 StorageState", async ({ page }) => {
  await page.goto("/");
  await page.waitForURL(/\/login/);

  const usernameInput = page.getByPlaceholder("用户名或邮箱");
  const passwordInput = page.getByPlaceholder("密码");
  const loginButton = page.getByRole("button", { name: /登 录/ });

  await expect(usernameInput).toBeVisible();
  await expect(passwordInput).toBeVisible();
  await expect(loginButton).toBeVisible();

  await usernameInput.fill(DEMO_USER);
  await passwordInput.fill(DEMO_PASS);
  await loginButton.click();

  await page.waitForURL(/\/w$/);
  await page.waitForTimeout(500);
  await page.context().storageState({ path: STATE_PATH });
});
