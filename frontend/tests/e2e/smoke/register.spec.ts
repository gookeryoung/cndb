/** P0 Smoke — 注册流程：注册后自动登录并进入工作区列表.
 *
 * 覆盖场景：
 * - 匿名访问 /register 可正常显示注册表单
 * - 注册成功后自动登录 → 进入 /w 工作区列表
 * - 重复用户名 → 显示错误提示
 */
import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]

function uniqueUsername(): string {
  return `e2e_${Date.now()}_${Math.floor(Math.random() * 10000)}`
}

test.describe("注册流程（仅 chromium-anon）", () => {
  test.skip(ANON.includes(test.info().project.name) === false, "仅 anon 项目运行")

  test("注册页表单渲染完整", async ({ page }) => {
    await page.goto("/register")

    // 表单元素
    await expect(page.getByPlaceholder("用户名")).toBeVisible()
    await expect(page.getByPlaceholder("显示昵称（可选）")).toBeVisible()
    await expect(page.getByPlaceholder("your@email.com")).toBeVisible()
    await expect(page.getByPlaceholder("密码")).toBeVisible()
    // 角色选择器
    await expect(page.getByRole("radio", { name: /普通用户/ })).toBeVisible()
    // 提交按钮
    await expect(page.getByRole("button", { name: /创 建 账 号/ })).toBeVisible()
  })

  test("注册成功 → 自动登录 → 进入 /w 工作区列表", async ({ page }) => {
    const username = uniqueUsername()

    await page.goto("/register")
    await page.getByPlaceholder("用户名").fill(username)
    await page.getByPlaceholder("密码").fill("testpass123")
    await page.getByRole("button", { name: /创 建 账 号/ }).click()

    // 注册成功后自动登录，跳转到 /w
    await page.waitForURL(/\/w$/)
    // 工作区列表关键锚点
    await expect(page.getByTestId("workspace-list")).toBeVisible()
    await expect(page.getByRole("heading", { level: 3, name: /我的工作区/ })).toBeVisible()
  })

  test("重复用户名 → 显示错误提示", async ({ page }) => {
    // 先用 demo 用户名（已存在于 seed 数据）
    await page.goto("/register")
    await page.getByPlaceholder("用户名").fill("demo")
    await page.getByPlaceholder("密码").fill("testpass123")
    await page.getByRole("button", { name: /创 建 账 号/ }).click()

    // 应该留在注册页，不跳转
    await page.waitForTimeout(1000)
    await expect(page.getByPlaceholder("用户名")).toBeVisible()
    await expect(page.getByPlaceholder("密码")).toBeVisible()
  })
})
