import { test, expect } from "@playwright/test"

const WID = 1, TID = 1

test("approach: use click on .ant-tabs-tab wrapper directly", async ({ page }) => {
  await page.goto(`/w/${WID}/tables/${TID}/settings`)
  await page.waitForURL(/\/settings$/)

  // Use the outer .ant-tabs-tab wrapper directly (it's clickable)
  const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
  
  await expect(page.locator(".ant-tabs-tab")).toHaveCount(4, { timeout: 10000 })

  // Default
  await expect(tab("基本信息")).toHaveClass(/ant-tabs-tab-active/)

  // Fields
  await tab("字段").click()
  await expect(tab("字段")).toHaveClass(/ant-tabs-tab-active/)

  // Views
  await tab("视图").click()
  await expect(tab("视图")).toHaveClass(/ant-tabs-tab-active/)
  await expect(page.getByText(/共 \d+ 个视图/)).toBeVisible()

  // Perms
  await tab("权限").click()
  await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)
  
  console.log("ALL OK")
})
