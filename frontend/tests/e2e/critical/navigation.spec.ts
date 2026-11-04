/** MainLayout Header 导航 E2E.
 *
 * 覆盖（需求 0081 后的导航形态）：
 * 顶栏一级导航顺序（数据表 → 文档 → 设计 → 工作区设置）+ 三区划分、
 * 二级页签（数据列表 / 数据分析 / 数据同步 / 质量检查 / 修改申请 / 问题清单）维持在内容区上方、
 * 文档模块的质量检查由文档区胶囊页签承载（/documents/pipelines，不跳数据表段）、
 * Header 导航按钮可达性 — 文档、数据分析。
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

  // 需求 0081：四个一级模块上移顶栏（桌面端），回归导航被误调序的问题；
  // 二级模块（数据分析等）维持在内容区上方页签行（C5）。
  test("顶栏一级导航顺序为 数据表 → 文档 → 设计 → 工作区设置，二级页签仅承载二级模块", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 一级导航落在顶栏左区（ws-module-nav），顺序即 headerNavItems 声明顺序；
    // 布局挂载前页面处于「加载中」，须先等导航渲染完成再读 DOM
    await expect(page.getByTestId("ws-nav-tables")).toBeVisible()
    const navNames = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll('[data-testid="ws-module-nav"] button'),
      ).map(b => (b.textContent ?? "").trim()),
    )
    // 导航标签内含数量徽标（如「数据表8」），故用子串匹配而非全等
    const idx = (kw: string) => navNames.findIndex(n => n.includes(kw))
    expect(idx("数据表")).toBe(0)
    expect(idx("文档")).toBe(1)
    expect(idx("设计")).toBe(2)
    expect(idx("工作区设置")).toBe(3)

    // 二级页签顺序（2026-11-03 用户口径）：
    // 数据列表 → 数据分析 → 数据同步 → 质量检查 → 修改申请 → 问题清单
    const tabs = page.getByRole("tablist").first().getByRole("tab")
    const expectedOrder = ["数据列表", "数据分析", "数据同步", "质量检查", "修改申请", "问题清单"]
    for (const label of expectedOrder) {
      await expect(tabs.filter({ hasText: label })).toHaveCount(1)
    }
    const labels = (await tabs.allTextContents()).map(t => t.trim())
    const pos = (kw: string) => labels.findIndex(n => n.includes(kw))
    for (let i = 1; i < expectedOrder.length; i += 1) {
      expect(pos(expectedOrder[i - 1]!)).toBeGreaterThanOrEqual(0)
      expect(pos(expectedOrder[i - 1]!)).toBeLessThan(pos(expectedOrder[i]!))
    }
    for (const primary of ["数据表", "文档", "设计", "工作区设置"]) {
      await expect(tabs.filter({ hasText: primary })).toHaveCount(0)
    }
  })

  test("顶栏布局：搜索框位于右侧操作按钮左侧（主页 / 工作区位置一致）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 需求 0081 C1（2026-11-03 调整）：左区（品牌 + 工作区 + 一级导航）在前，
    // 搜索框收进右区首位、位于操作按钮左侧；先等布局挂载完成再读 DOM
    await expect(page.getByTestId("ws-nav-tables")).toBeVisible()
    const order = await page.evaluate(() => {
      const left = document.querySelector(".cn-header-left")
      const right = document.querySelector(".cn-header-right")
      const search = right?.querySelector(".cn-header-search")
      const llm = right?.querySelector('[data-testid="llm-settings-btn"]')
      if (!left || !right || !search || !llm) return null
      const before = (a: Element, b: Element) =>
        (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
      return {
        leftBeforeRight: before(left, right),
        searchInRight: !left.querySelector(".cn-header-search"),
        searchBeforeActions: before(search, llm),
      }
    })
    expect(order).toEqual({ leftBeforeRight: true, searchInRight: true, searchBeforeActions: true })
    // 左区承载一级导航，右区承载搜索框
    await expect(page.locator(".cn-header-left").locator('[data-testid="ws-module-nav"]')).toBeVisible()
    await expect(page.locator(".cn-header-right").locator(".cn-header-search").getByTestId("global-search-input"))
      .toBeVisible()
  })

  test("文档导航 → /w/:wid/documents", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await start(page)

    // 需求 0081 C4：文档是一级模块，入口在顶栏导航
    await page.getByTestId("ws-nav-documents").click()
    await page.waitForURL(/\/documents$/)
    await expect(page.getByTestId("documents-layout")).toBeVisible({ timeout: 5000 })
  })

  test("切到文档模块：数据分析/数据同步/质量检查页签隐藏", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/documents`)
    await page.waitForURL(/\/documents$/)
    await expect(page.getByTestId("documents-layout")).toBeVisible({ timeout: 5000 })
    // 数据分析 / 数据同步为数据表派生二级功能，仅数据表模块上下文显示
    const tabs = page.getByRole("tablist").first().getByRole("tab")
    await expect(tabs.filter({ hasText: "数据分析" })).toHaveCount(0)
    await expect(tabs.filter({ hasText: "数据同步" })).toHaveCount(0)
    // 文档上下文由文档区胶囊页签承载质量检查（避免同名页签重复，页签行隐藏）
    await expect(tabs.filter({ hasText: "质量检查" })).toHaveCount(0)
    await expect(page.getByTestId("document-tab-pipelines")).toBeVisible()
  })

  // 需求 0082 C3：文档区二级页签新增「文档结构」，指向文档总览列表页本体
  test("文档区二级页签含「文档结构」：落在文档总览时激活，点击回到总览", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/documents`)
    await page.waitForURL(/\/documents$/)
    await expect(page.getByTestId("documents-crumb")).toBeVisible({ timeout: 5000 })
    const structureTab = page.getByTestId("document-tab-structure")
    await expect(structureTab).toBeVisible()
    await expect(structureTab).toHaveAttribute("aria-selected", "true")

    // 修改申请 / 问题清单两个子页签仍在同一行
    await expect(page.getByTestId("document-tab-change-requests")).toBeVisible()
    await expect(page.getByTestId("document-tab-issues")).toBeVisible()
  })

  test("设计区「设计结构」为默认页：页签可见且激活", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/design`)
    await page.waitForURL(/\/design$/)
    await expect(page.getByTestId("design-crumb")).toBeVisible({ timeout: 10_000 })
    await expect(page.getByTestId("design-tab-structure")).toBeVisible()
    await expect(page.getByTestId("design-tab-structure")).toHaveAttribute("aria-selected", "true")
    await expect(page.getByText("设计结构").first()).toBeVisible()
  })

  test("文档区「质量检查」页签留在文档上下文（/documents/pipelines），不跳数据表段", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/documents`)
    await page.waitForURL(/\/documents$/)
    await expect(page.getByTestId("documents-crumb")).toBeVisible({ timeout: 5000 })

    await page.getByTestId("document-tab-pipelines").click()
    // 文档质量检查不跳到工作区级 /pipelines（数据表域）
    await page.waitForURL(/\/documents\/pipelines$/)
    await expect(page.getByTestId("document-tab-pipelines")).toHaveAttribute("aria-selected", "true")
    await expect(page.getByTestId("pipelines-page")).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/仅文档检查动作与规则/)).toBeVisible()
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

  test("切到文档段：侧栏由数据表列表切换为文档树，进入文档后侧栏保持文档树并高亮当前文档", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    // API 建一篇文档（根目录），不依赖 seed 文档数据
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

      // 切到文档（顶栏一级导航）：表导航消失，文档树侧栏出现且包含新建文档
      await page.getByTestId("ws-nav-documents").click()
      await page.waitForURL(/\/documents$/)
      const sider = page.getByTestId("sider-documents")
      await expect(sider).toBeVisible()
      await expect(page.getByTestId("sider-tables")).toHaveCount(0)
      await expect(sider.getByTitle(docTitle)).toBeVisible()

      // 侧栏点文档 → 编辑器：侧栏仍是同一棵文档树，高亮当前文档；不再有大纲侧栏
      await sider.getByTitle(docTitle).click()
      await page.waitForURL(new RegExp(`/documents/${docId}`))
      await expect(page.getByTestId("sider-documents")).toBeVisible()
      await expect(page.locator(".ant-tree-treenode-selected")).toContainText(docTitle)
      await expect(page.getByTestId("sider-doc-outline")).toHaveCount(0)
    } finally {
      await apiCall(page.request, adminToken, "delete", `/workspaces/${WID}/documents/${docId}`).catch(() => {})
    }
  })

  test("数据分析段侧栏保持展开（Sider 不卸载且不折叠）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")

    await page.goto(`/w/${WID}/analytics`)
    await page.waitForURL(/\/analytics$/)
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 5000 })
    const sider = page.locator(".ant-layout-sider")
    await expect(sider).toHaveCount(1)
    await expect(sider).not.toHaveClass(/ant-layout-sider-collapsed/)
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
