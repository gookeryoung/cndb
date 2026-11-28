/**
 * Critical — 工作区列表的响应式信息优先级（需求 0157 列表优化）。
 *
 * 回归背景：宽度不足时 `.cn-ws-row-meta`（含长日期）不可收缩，名称被压成 0，
 * 出现「名称消失、时间完整」的错误优先级。
 *
 * 断言口径：
 * 1) 1440 / 1280 / 1024 / 768 / 390 下名称始终可见且有可读宽度；
 * 2) 收藏（操作列）始终可见；
 * 3) <1200（antd xl）模块徽标收起；<1024 时间整体收起；<768 meta 不渲染；
 */
import { expect, test } from "../fixtures/auth"
import { getWorkspaceId } from "../helpers/api"

const WIDTHS = [1440, 1280, 1024, 768, 390]

test.describe("工作区列表响应式", () => {
  test("名称优先：各宽度下名称可读，次要信息按断点让位", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过")

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto("/w")
      await expect(page.getByTestId("workspace-list")).toBeVisible({ timeout: 20_000 })

      const row = page.locator('[data-testid^="workspace-row-"]').first()
      await expect(row).toBeVisible()
      const name = row.locator(".cn-ws-row-name")
      await expect(name).toBeVisible()
      const box = await name.boundingBox()
      expect(box, `width=${width} 名称应有布局盒`).not.toBeNull()
      expect(box!.width, `width=${width} 名称宽度不应被压没`).toBeGreaterThan(60)

      // 操作列（收藏）始终可见
      await expect(row.locator('[data-testid^="star-btn-"]')).toBeVisible()

      const moduleTag = row.locator(".cn-ws-row-tag--module").first()
      const time = row.locator(".cn-ws-row-time").first()
      const meta = row.locator(".cn-ws-row-meta")

      if (width < 1280) {
        await expect(moduleTag, `width=${width} 模块徽标应收起`).toBeHidden()
      } else {
        await expect(moduleTag).toBeVisible()
      }

      if (width < 1024) {
        await expect(time, `width=${width} 时间应收起`).toBeHidden()
      } else {
        await expect(time).toBeVisible()
      }

      if (width < 768) {
        // 移动端 meta 不渲染（组件侧结构收敛）
        await expect(meta).toHaveCount(0)
      } else {
        await expect(meta).toHaveCount(1)
      }
    }
  })
})

test.describe("顶栏与外部链接入口的响应式", () => {
  test("顶栏窄宽度进入紧凑档且不横向溢出", async ({ page, request }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过")
    const wid = await getWorkspaceId(request)

    for (const width of [1440, 1200, 1100, 1024, 800]) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/w/${wid}/tables`)
      await expect(page.getByTestId("ws-module-nav")).toBeVisible({ timeout: 20_000 })

      const headerFits = await page.evaluate(() => {
        const el = document.querySelector(".cn-app-header") as HTMLElement | null
        return !!el && el.scrollWidth <= el.clientWidth + 1
      })
      expect(headerFits, `width=${width} 顶栏不应横向溢出`).toBe(true)

      if (width < 1280) {
        // 紧凑档（需求 0190 C6）：降级改由 CSS 媒体查询驱动，元素仍在 DOM 里（不再整块消失），
        // 断言的是「不可见」而非「不存在」。这是判据迁移而非放宽：可见性仍被硬断言。
        await expect(page.locator(".cn-brand-word")).not.toBeVisible()
        await expect(page.getByTestId("ws-nav-tables").locator(".cn-header-nav-label")).not.toBeVisible()
        await expect(page.getByTestId("llm-settings-btn")).not.toBeVisible()
        await expect(page.getByTestId("help-btn")).not.toBeVisible()
        // 可访问名不受收起影响（窄屏只剩图标，仍能被读屏与 title 识别）
        await expect(page.getByTestId("ws-nav-tables")).toHaveAttribute("aria-label", "数据表")
        await expect(page.getByTestId("ws-nav-tables")).toHaveAttribute("title", "数据表")
      } else {
        await expect(page.locator(".cn-brand-word")).toBeVisible()
        await expect(page.getByTestId("ws-nav-tables").locator(".cn-header-nav-label")).toBeVisible()
        await expect(page.getByTestId("llm-settings-btn")).toBeVisible()
      }
    }
  })

  test("外部链接不再常驻列表顶部：入口打开抽屉", async ({ page, request }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过")
    const wid = await getWorkspaceId(request)
    await page.goto(`/w/${wid}/tables`)
    await expect(page.getByTestId("workspace-links-entry")).toBeVisible({ timeout: 20_000 })
    // 列表顶部不再渲染链接面板
    await expect(page.getByTestId("workspace-links-panel")).toHaveCount(0)

    await page.getByTestId("workspace-links-entry").click()
    await expect(page.getByTestId("workspace-links-panel")).toBeVisible()
    await expect(page.getByRole("dialog")).toContainText("外部链接")
  })
})
