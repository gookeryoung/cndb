/** MainLayout Header 导航 E2E.
 *
 * 覆盖：工作区级 Tab 顺序（数据表 → 文档 → 工作区设置）、
 * Header 导航按钮可达性 — 文档、工作区设置.
 * 以及表列表 owner 列展示 + 筛选器.
 */

import { test, expect } from "../fixtures/auth"
import { apiCall, getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

let adminToken = ""

test.beforeAll(async ({ request }: { request: any }) => {
  adminToken = await getAdminToken(request)
})

test.describe("MainLayout Header 导航按钮", () => {
  // 起点：工作区表列表页，保证所有 Header 按钮都能看到
  const start = async (page: any) => {
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)
  }

  // 原 forms.spec.ts 的「导航 Tab 顺序」用例随表单功能移除而失效，此处按当前
  // 工作区级 Tab 集重写：顺序即 wsTabItems 的声明顺序，回归导航被误调序的问题。
  test("工作区 Tab 顺序为 数据表 → 文档 → 数据分析 → 工作区设置", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 收敛到工作区级 Tabs 的 tablist：表级页签（role=tab）在表上下文下才会出现，
    // 但 /w/:wid/tables（表列表）无 tid，故此处 first() 即工作区级 Tabs
    const tabs = page.getByRole("tablist").first().getByRole("tab")
    // allTextContents() 不做自动等待，须先等 Tabs 挂载完成再读文本，否则会读到空标签集
    await expect(tabs.filter({ hasText: "数据表" })).toBeVisible()
    await expect(tabs.filter({ hasText: "工作区设置" })).toBeVisible()

    const names = (await tabs.allTextContents()).map((t) => t.trim())
    // Tab 标签内含数量徽标（如「数据表 8」），故用子串匹配而非全等
    const idxAssets = names.findIndex((n) => n.includes("数据表"))
    const idxDocs = names.findIndex((n) => n.includes("文档"))
    const idxAnalytics = names.findIndex((n) => n.includes("数据分析"))
    const idxSettings = names.findIndex((n) => n.includes("工作区设置"))

    expect(idxAssets).toBeGreaterThanOrEqual(0)
    expect(idxDocs).toBeGreaterThanOrEqual(0)
    expect(idxAnalytics).toBeGreaterThanOrEqual(0)
    expect(idxSettings).toBeGreaterThanOrEqual(0)
    expect(idxAssets).toBeLessThan(idxDocs)
    expect(idxDocs).toBeLessThan(idxAnalytics)
    expect(idxAnalytics).toBeLessThan(idxSettings)
  })

  test("Content 分页导航可见 文档 / 数据分析 / 工作区设置 Tab", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // MainLayout 重构后，文档 / 工作区设置从 Header 按钮迁移为 Content 上方的 Tabs
    await expect(page.getByRole("tab", { name: /文档/ })).toBeVisible()
    await expect(page.getByRole("tab", { name: /数据分析/ })).toBeVisible()
    await expect(page.getByRole("tab", { name: /工作区设置/ })).toBeVisible()
  })

  test("文档 Tab → /w/:wid/documents", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await page.getByRole("tab", { name: /文档/ }).click()
    await page.waitForURL(/\/documents$/)
    await expect(page.getByTestId("documents-layout")).toBeVisible({ timeout: 5000 })
  })

  test("数据分析 Tab → /w/:wid/analytics（独立于文档的模块）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    await page.getByRole("tab", { name: /数据分析/ }).click()
    await page.waitForURL(/\/analytics$/)
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 5000 })
    // 页签激活态落在「数据分析」，与文档模块互不影响
    await expect(page.getByRole("tab", { name: /数据分析/ })).toHaveAttribute("aria-selected", "true")
  })

  // ── 需求 0065：侧边栏随工作区功能段切换 ──

  test("切到文档段：侧栏由数据表列表切换为文档列表，进入文档后显示文档结构", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    // API 建一篇带两级标题的文档，不依赖 seed 文档数据
    const docTitle = `侧栏结构 ${Date.now()}`
    const created = await apiCall(page.request, adminToken, "post", `/workspaces/${WID}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n## 背景\n\n正文\n`,
      status: "draft",
    })
    expect(created.status, JSON.stringify(created.body)).toBe(201)
    const docId = (created.body as { id: number }).id

    try {
      await page.goto(`/w/${WID}/tables`)
      await page.waitForURL(/\/tables$/)
      // 表段：数据表导航侧栏
      await expect(page.getByTestId("sider-tables")).toBeVisible({ timeout: 10_000 })

      // 切到文档：表导航消失，文档列表侧栏出现
      await page.getByRole("tab", { name: /文档/ }).click()
      await page.waitForURL(/\/documents$/)
      await expect(page.getByTestId("sider-documents")).toBeVisible()
      await expect(page.getByTestId("sider-tables")).toHaveCount(0)

      // 侧栏点文档 → 编辑器，侧栏切换为文档结构（含两级标题）
      await page
        .locator('[data-testid="sider-documents"] .ant-menu-item', { hasText: docTitle })
        .click()
      await page.waitForURL(new RegExp(`/documents/${docId}`))
      const outline = page.getByTestId("sider-doc-outline")
      await expect(outline).toBeVisible({ timeout: 10_000 })
      await expect(outline).toContainText(docTitle)
      await expect(outline).toContainText("背景")
    } finally {
      await apiCall(page.request, adminToken, "delete", `/workspaces/${WID}/documents/${docId}`).catch(() => {})
    }
  })

  test("数据分析段不渲染侧栏，内容区占满宽度", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/analytics`)
    await page.waitForURL(/\/analytics$/)
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 5000 })
    await expect(page.locator(".ant-layout-sider")).toHaveCount(0)
  })
})

test.describe("表列表 owner 列 + 访问级筛选器", () => {
  const start = async (page: any) => {
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)
    // 等待表列表渲染（含新增的「产品批次」表，至少 9 张）；
    // 并行用例可能临时向 WID=1 增表，与 grid.spec 同口径不锁死精确行数
    const rows = page.locator(".ant-table-tbody tr.ant-table-row")
    await expect.poll(() => rows.count(), { timeout: 10000 }).toBeGreaterThanOrEqual(9)
  }

  test("访问级筛选器：「我拥有的」可筛选出全部表（admin 是所有 seed 表的 owner）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 点击「我拥有的」筛选器
    const seg = page.locator(".ant-segmented-item", { hasText: "我拥有的" })
    await seg.click()
    await expect(seg).toHaveClass(/ant-segmented-item-selected/)

    // seed 所有 9 张表的 owner 都是 admin（当前用户），筛选后至少仍应显示 9 张
    await expect
      .poll(() => page.locator(".ant-table-tbody tr.ant-table-row").count(), { timeout: 5000 })
      .toBeGreaterThanOrEqual(9)
  })
})
