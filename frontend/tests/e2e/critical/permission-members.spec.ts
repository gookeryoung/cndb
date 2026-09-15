/** P1 — 权限与成员 E2E：数据表权限成员管理 + 工作区权限 Tab.
 *
 * 测试覆盖：
 * - 数据表权限 Tab：展示表拥有者、表成员列表、添加成员（候选来自工作区成员）
 * - 变更表成员角色（read ↔ write）、移除表成员
 * - 工作区权限 Tab：展示所有者卡片、编辑权限开关、成员列表
 */

import { test, expect } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]

// seed 数据：工作区 1 = 某企业销售管理（含 sec_admin/audit_admin/demo 成员），表 1 = 产品开发
const WID = 1
const TID = 1

test.describe("数据表权限 — 成员管理", () => {
  /** 打开表设置 Modal 并切到「权限」Tab，返回 Modal 定位器（用于后续作用域限定）. */
  async function openTablePermModal(page: any) {
    await page.goto(`/w/${WID}/tables/${TID}`)
    await page.waitForURL(/\/tables\/\d+$/)
    // 点击"表设置"按钮打开设置 Modal
    await page.getByTestId("table-settings-btn").click()
    // 表设置 Modal（页面上第一个 ant-modal-wrap）
    const settingsModal = page.locator(".ant-modal-wrap").first()
    await expect(settingsModal).toBeVisible()
    // 切到"权限"Tab
    const tab = (name: string) => settingsModal.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)
    // 等待工作区成员加载完成（"添加成员"按钮出现且可点击）
    await expect(settingsModal.getByRole("button", { name: /添加成员/ })).toBeVisible({ timeout: 10000 })
    // 额外等待确保 workspace members 查询完成（候选列表依赖此数据）
    await page.waitForTimeout(1500)
    return settingsModal
  }

  test("权限 Tab 展示表拥有者卡片和成员列表", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const modal = await openTablePermModal(page)

    // 表拥有者卡片
    await expect(modal.getByText("表拥有者")).toBeVisible()
    await expect(modal.locator(".ant-card").filter({ hasText: "表拥有者" }).getByText("admin")).toBeVisible()

    // 表成员列表（初始为空，显示"暂无显式成员"）
    await expect(modal.getByText("暂无显式成员")).toBeVisible()

    // 添加成员按钮
    await expect(modal.getByRole("button", { name: /添加成员/ })).toBeVisible()
  })

  test("添加表成员 — 候选列表展示工作区其他成员", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const modal = await openTablePermModal(page)

    // 点击"添加成员"
    await modal.getByRole("button", { name: /添加成员/ }).click()

    // 添加成员 Modal 打开（最上层的 modal，即最后一个 ant-modal-wrap）
    const addModal = page.locator(".ant-modal-wrap").last()
    await expect(addModal).toBeVisible()
    await expect(addModal.getByText("添加表成员")).toBeVisible()

    // 候选用户下拉框 — 应展示工作区其他成员（sec_admin / audit_admin / demo）
    const select = addModal.locator(".ant-select-selector").first()
    await select.click()

    // 下拉选项中应包含工作区其他成员
    const options = page.locator(".ant-select-item-option")
    await expect(options.first()).toBeVisible({ timeout: 5000 })

    // 至少有 sec_admin 或 audit_admin 或 demo 作为候选
    const optionTexts = await options.allTextContents()
    const hasCandidate = optionTexts.some(t =>
      t.includes("sec_admin") || t.includes("audit_admin") || t.includes("demo")
    )
    expect(hasCandidate).toBe(true)

    // 先按 Escape 关闭下拉选项，避免选项遮罩拦截取消按钮
    await page.keyboard.press("Escape")
    // 关闭 Modal（点击取消按钮）
    await addModal.locator(".ant-modal-footer .ant-btn-default").click()
    // 验证添加成员 Modal 已关闭（通过标题消失判断，因为表设置 Modal 仍在）
    await expect(page.getByText("添加表成员")).not.toBeVisible({ timeout: 5000 })
  })

  test("添加表成员并验证出现在列表中", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const modal = await openTablePermModal(page)

    // 记录添加前的成员数（限定在 Modal 内"表成员"卡片下的表格）
    const memberCard = modal.locator(".ant-card").filter({ hasText: "表成员" })
    const beforeCount = await memberCard.locator(".ant-table-row").count()

    // 点击"添加成员"
    await modal.getByRole("button", { name: /添加成员/ }).click()
    const addModal = page.locator(".ant-modal-wrap").last()
    await expect(addModal).toBeVisible()

    // 选择第一个候选用户
    const select = addModal.locator(".ant-select-selector").first()
    await select.click()
    await page.locator(".ant-select-item-option").first().click()

    // 点击 Modal footer 的"添加"按钮（primary 按钮）
    await addModal.locator(".ant-modal-footer .ant-btn-primary").click()

    // 等待成功提示
    await expect(page.getByText(/已添加成员/)).toBeVisible({ timeout: 5000 })

    // 成员列表中应多出一行
    await expect(memberCard.locator(".ant-table-row")).toHaveCount(beforeCount + 1, { timeout: 5000 })
  })

  test("变更表成员角色 read ↔ write", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const modal = await openTablePermModal(page)

    // 先添加一个成员
    await modal.getByRole("button", { name: /添加成员/ }).click()
    const addModal = page.locator(".ant-modal-wrap").last()
    await expect(addModal).toBeVisible()
    const select = addModal.locator(".ant-select-selector").first()
    await select.click()
    await page.locator(".ant-select-item-option").first().click()
    await addModal.locator(".ant-modal-footer .ant-btn-primary").click()
    await expect(page.getByText(/已添加成员/)).toBeVisible({ timeout: 5000 })

    // 成员行的角色 Select — 切换为 write（限定在 Modal 内成员表）
    const memberCard = modal.locator(".ant-card").filter({ hasText: "表成员" })
    const roleSelect = memberCard.locator(".ant-table-row .ant-select-selector").first()
    await roleSelect.click()
    await page.locator(".ant-select-item-option").filter({ hasText: "write" }).click()

    // 等待成功提示
    await expect(page.getByText(/已更新授权/)).toBeVisible({ timeout: 5000 })
  })

  test("移除表成员", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    const modal = await openTablePermModal(page)

    // 先添加一个成员
    await modal.getByRole("button", { name: /添加成员/ }).click()
    const addModal = page.locator(".ant-modal-wrap").last()
    await expect(addModal).toBeVisible()
    const select = addModal.locator(".ant-select-selector").first()
    await select.click()
    await page.locator(".ant-select-item-option").first().click()
    await addModal.locator(".ant-modal-footer .ant-btn-primary").click()
    await expect(page.getByText(/已添加成员/)).toBeVisible({ timeout: 5000 })

    // 限定在 Modal 内成员表，点击某一行的移除按钮
    const memberCard = modal.locator(".ant-card").filter({ hasText: "表成员" })
    const removeBtn = memberCard.locator(".ant-table-row").first().getByRole("button", { name: "移除" })
    await removeBtn.click()

    // 等待 Popconfirm 出现并点击确认（最后一个按钮为确认）
    const popconfirm = page.locator(".ant-popover").last()
    await expect(popconfirm).toBeVisible({ timeout: 5000 })
    await popconfirm.locator("button").last().click()

    // 等待成功提示
    await expect(page.getByText(/已移除成员/)).toBeVisible({ timeout: 5000 })
  })
})

test.describe("工作区权限 Tab", () => {
  test("权限 Tab 展示所有者卡片和编辑权限开关", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)

    // 工作区所有者卡片
    await expect(page.getByText("工作区所有者")).toBeVisible()
    await expect(page.locator(".ant-card").filter({ hasText: "工作区所有者" }).getByText("admin")).toBeVisible()

    // 编辑权限开关
    await expect(page.getByText("编辑权限")).toBeVisible()
    const allowEditSwitch = page.locator(".ant-switch").first()
    await expect(allowEditSwitch).toBeVisible()
  })

  test("权限 Tab 展示成员列表（含多个成员）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)

    // 成员列表应包含多行（admin + sec_admin + audit_admin + demo）
    const rows = page.locator(".ant-table-row")
    await expect(rows).toHaveCount(4, { timeout: 10000 })
  })

  test("切换编辑权限开关", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/settings`)
    await page.waitForURL(/\/settings$/)

    const tab = (name: string) => page.locator(".ant-tabs-tab").filter({ hasText: name }).first()
    await tab("权限").click()
    await expect(tab("权限")).toHaveClass(/ant-tabs-tab-active/)

    // 点击编辑权限开关
    const allowEditSwitch = page.locator(".ant-switch").first()
    await allowEditSwitch.click()

    // 等待成功提示
    await expect(page.getByText(/编辑权限已更新/)).toBeVisible({ timeout: 5000 })
  })
})
