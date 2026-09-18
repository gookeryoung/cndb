import { test, expect } from "@playwright/test";

const DEMO_USER = "admin";
const DEMO_PASS = "admin1234";
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

  // 登录后进入 /w（工作区列表视图）
  await page.waitForURL(/\/w$/);
  // token 写入 localStorage 后才落盘 state，避免保存到空态
  await page.waitForFunction(
    () => !!window.localStorage.getItem("cndb_access_token"),
  );
  await page.context().storageState({ path: STATE_PATH });
});
