/** P1 — 工作区和数据表设置独立页面 E2E.
 *
 * 测试覆盖：
 * - /w/:wid/settings 工作区设置独立页面
 * - /w/:wid/tables/:tid/settings 数据表设置独立页面
 * - 从各入口导航到设置页面
 * - 面包屑和返回按钮
 * - Tab 切换
 *
 * Tab 定位策略：使用 .ant-tabs-tab（外层包装器） + filter({ hasText }) 子串匹配。
 * 原因：
 * - antd Tabs 内部 role="tab" 元素的 id 计数器会随 Suspense lazy load / 数据拉取递增
 * - getByRole('tab') 的 accessible name 会混入 icon 的 aria-label 导致匹配失败
 * - .ant-tabs-tab 包装器在同一页面中始终稳定存在，hasText 子串匹配 +
 *   .toHaveClass(/ant-tabs-tab-active/) 是最可靠的组合
 */

import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]

// seed 数据：工作区 1 = 某企业销售管理，表 1 = 产品开发
const WID = 1
const TID = 1

test.describe("工作区设置独立页面 /w/:wid/settings", () => {
  test("直接访问独立页面 — 面包屑 + 返回按钮 + 三个 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    // 面包屑
    const breadcrumb = page.locator(".ant-breadcrumb")
    await expect(breadcrumb).toBeVisible()
    await expect(breadcrumb).toContainText("工作区")
    await expect(breadcrumb).toContainText("设置")

    // 返回按钮
    const backBtn = page.locator("[data-testid='settings-back-btn']")
    await expect(backBtn).toBeVisible()

    // 三个 Tab
    const tabs = page.locator(".ant-tabs-tab")
    await expect(tabs).toHaveCount(3)
    await expect(tabs.filter({ hasText: "基本设置" })).toBeVisible()
    await expect(tabs.filter({ hasText: "权限" })).toBeVisible()
    await expect(tabs.filter({ hasText: "统计信息" })).toBeVisible()
  })

  test("Tab 切换 — 基本设置 → 权限 → 统计信息", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    // 工作区设置 Tab 顺序：基本设置 / 权限 / 统计信息
    // 用 .ant-tabs-tab（外层包装器）+ hasText 子串匹配最稳定，
    // 不受内部 role=tab 元素 id 计数器或 aria-selected 变化影响
    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await expect(page.locator(".ant-tabs-tab")).toHaveCount(3, { timeout: 10000 })

    // 默认在基本设置
    await expect(tab("基本设置")).toHaveClass(/ant-tabs-tab-active/)

    // 切到权限
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)
    // 权限 Tab 内：成员列表有"用户"和"角色"两列表头
    await expect(page.getByRole("columnheader", { name: "用户" })).toBeVisible()
    await expect(page.getByRole("columnheader", { name: "角色" })).toBeVisible()

    // 切到统计信息
    await tab("统计信息").click()
    await expect(tab("统计信息")).toHaveClass(/ant-tabs-tab-active/)
    // 统计信息 Tab 内：统计卡片有"数据表"label + descs 块
    await expect(page.getByText("数据表", { exact: true })).toBeVisible()
    await expect(page.locator(".ant-descriptions").first()).toBeVisible()
  })

  test("返回按钮 → 表列表页", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    await page.locator("[data-testid='settings-back-btn']").click()
    await page.waitForURL(`/w/${WID}/tables`)
  })

  test("MainLayout Header 工作区设置按钮导航", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    const settingsNav = page.locator("[data-testid='workspace-settings-nav']")
    await expect(settingsNav).toBeVisible()
    await settingsNav.click()

    await page.waitForURL(`/w/${WID}/settings`)
    await expect(page.locator(".ant-tabs-tab").filter({ hasText: "基本设置" })).toBeVisible()
  })

  test("TablesList 头部工作区设置按钮导航", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    const link = page.locator("[data-testid='workspace-settings-link']")
    await expect(link).toBeVisible()
    await link.click()

    await page.waitForURL(`/w/${WID}/settings`)
  })
})

test.describe("数据表设置独立页面 /w/:wid/tables/:tid/settings", () => {
  test("直接访问独立页面 — 面包屑 + 返回按钮 + 四个 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables/${TID}/settings`)
    await page.waitForURL(/\/tables\/\d+\/settings$/)

    // 面包屑
    const breadcrumb = page.locator(".ant-breadcrumb")
    await expect(breadcrumb).toBeVisible()
    await expect(breadcrumb).toContainText("工作区")

    // 返回按钮
    const backBtn = page.locator("[data-testid='settings-back-btn']")
    await expect(backBtn).toBeVisible()

    // 四个 Tab
    const tabs = page.locator(".ant-tabs-tab")
    await expect(tabs).toHaveCount(4)
    await expect(tabs.filter({ hasText: "基本信息" })).toBeVisible()
    await expect(tabs.filter({ hasText: "字段" })).toBeVisible()
    await expect(tabs.filter({ hasText: "视图" })).toBeVisible()
    await expect(tabs.filter({ hasText: "权限" })).toBeVisible()
  })

  test("Tab 切换 — 基本信息 → 字段 → 视图 → 权限", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables/${TID}/settings`)
    await page.waitForURL(/\/tables\/\d+\/settings$/)

    // 数据表设置 Tab：基本信息 / 字段 / 视图 / 权限
    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await expect(page.locator(".ant-tabs-tab")).toHaveCount(4, { timeout: 10000 })

    // 默认在基本信息
    await expect(tab("基本信息")).toHaveClass(/ant-tabs-tab-active/)

    // 切到字段 — embedded FieldManager 触发 Suspense
    await tab("字段").click()
    await expect(tab("字段")).toHaveClass(/ant-tabs-tab-active/)

    // 切到视图 — 视图列表拉取数据
    await tab("视图").click()
    await expect(tab("视图")).toHaveClass(/ant-tabs-tab-active/)
    await expect(page.getByText(/共 \d+ 个视图/)).toBeVisible()

    // 切到权限
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)
  })

  test("返回按钮 → Grid 页面", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables/${TID}/settings`)
    await page.waitForURL(/\/tables\/\d+\/settings$/)

    await page.locator("[data-testid='settings-back-btn']").click()
    await page.waitForURL(`/w/${WID}/tables/${TID}`)

    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible()
  })

  test("GridPage Dropdown 导航到表设置页面", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/tables/${TID}`)
    await page.waitForURL(`/w/${WID}/tables/${TID}`)

    await page.locator("[data-testid='grid-more-menu']").click()
    await expect(page.getByRole("menuitem", { name: /表设置页面/ })).toBeVisible()
    await page.getByRole("menuitem", { name: /表设置页面/ }).click()

    await page.waitForURL(`/w/${WID}/tables/${TID}/settings`)
  })
})

test.describe("工作区列表页卡片导航入口", () => {
  test("WorkspaceList 卡片有「完整页面」按钮并能导航", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto("/w")
    await page.waitForURL(/\/w$/)

    const pageBtn = page.locator("[data-testid='settings-page-btn-1']")
    await expect(pageBtn).toBeVisible()
    await pageBtn.click()

    await page.waitForURL(`/w/${WID}/settings`)
  })
})

test.describe("GridPage 表设置 Modal — 字段 Tab embedded 模式", () => {
  async function gotoGrid(page: any) {
    await page.goto("/")
    await page.waitForURL(/\/w/)
    if (page.url().match(/\/w\/?$/)) {
      const cards = page.locator(".ant-card")
      await expect(cards.first()).toBeVisible({ timeout: 10000 })
      await cards.first().click()
    }
    await page.waitForURL(/\/w\/\d+/)
    await page.getByRole("menuitem", { name: /员工表|产品开发|客户/ }).first().click()
    await page.waitForURL(/\/tables\/\d+/)
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible()
  }

  test("表设置 Modal 打开 — 四个 Tab 正常显示", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await gotoGrid(page)

    // 点击表设置按钮
    await page.locator("[data-testid='table-settings-btn']").click()

    // Modal 标题
    const modalTitle = page.locator(".ant-modal-title").filter({ hasText: "表设置" })
    await expect(modalTitle).toBeVisible()

    // 四个 Tab
    const tabs = page.locator(".ant-tabs-tab")
    await expect(tabs).toHaveCount(4, { timeout: 10000 })
    await expect(tabs.filter({ hasText: "基本信息" })).toBeVisible()
    await expect(tabs.filter({ hasText: "字段" })).toBeVisible()
    await expect(tabs.filter({ hasText: "视图" })).toBeVisible()
    await expect(tabs.filter({ hasText: "权限" })).toBeVisible()
  })

  test("字段 Tab 不包含嵌套 Modal（embedded 模式）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await gotoGrid(page)

    // 打开表设置 Modal
    await page.locator("[data-testid='table-settings-btn']").click()
    await expect(page.locator(".ant-modal-title").filter({ hasText: "表设置" })).toBeVisible()

    // 切到字段 Tab
    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("字段").click()
    await expect(tab("字段")).toHaveClass(/ant-tabs-tab-active/)

    // 关键断言：不应该出现标题为"字段管理"的嵌套 Modal
    // 之前 FieldManager 独立 Modal 会有 title="字段管理"，embedded 模式下去掉了外层 Modal
    const nestedFieldMgrModal = page.locator(".ant-modal-title").filter({ hasText: "字段管理" })
    await expect(nestedFieldMgrModal).not.toBeVisible()

    // 应该直接能看到字段表格和"新建字段"按钮（在表设置 Modal body 内）
    const settingsModalBody = page.getByRole("dialog", { name: /表设置/ }).locator(".ant-modal-body")
    await expect(settingsModalBody.getByRole("button", { name: /新建字段/ })).toBeVisible()
    // 字段 Tab 里唯一的 small table 就是字段列表
    await expect(settingsModalBody.locator(".ant-table-small")).toBeVisible()
  })

  test("字段 Tab 内新建字段对话框正常打开并可关闭", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await gotoGrid(page)

    // 打开表设置 Modal → 切到字段 Tab
    await page.locator("[data-testid='table-settings-btn']").click()
    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("字段").click()
    await expect(tab("字段")).toHaveClass(/ant-tabs-tab-active/)

    // 点"新建字段" → 内部编辑对话框打开（用 role=dialog + name 精确定位）
    await page.getByRole("button", { name: /新建字段/ }).first().click()

    const editModal = page.getByRole("dialog", { name: /新建字段/ })
    await expect(editModal).toBeVisible()

    // 点取消 → 对话框关闭（antd 按钮文本可能含空格，用 regex 匹配）
    await editModal.getByRole("button", { name: /取\s*消/ }).click()
    await expect(editModal).not.toBeVisible()

    // 关闭后仍在字段 Tab，字段表格还在
    await expect(page.getByRole("button", { name: /新建字段/ }).first()).toBeVisible()
  })

  test("关闭表设置 Modal 后内部编辑对话框不泄漏", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await gotoGrid(page)

    // 打开表设置 Modal → 切到字段 Tab → 点新建字段
    await page.locator("[data-testid='table-settings-btn']").click()
    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("字段").click()
    await page.getByRole("button", { name: /新建字段/ }).first().click()

    const editModal = page.getByRole("dialog", { name: /新建字段/ })
    await expect(editModal).toBeVisible()

    // 现在有 2 个 role="dialog"：外层表设置 + 内层新建字段
    const dialogs = page.getByRole("dialog")
    await expect(dialogs).toHaveCount(2)

    // 先关内层（点取消）
    await editModal.getByRole("button", { name: /取\s*消/ }).click()
    await expect(dialogs).toHaveCount(1)

    // 关外层表设置 Modal（点 X）
    await page.getByRole("dialog", { name: /表设置/ }).locator(".ant-modal-close").click()
    await expect(page.locator(".ant-modal-title").filter({ hasText: "表设置" })).not.toBeVisible()

    // 确认回到 Grid
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible()
  })
})
