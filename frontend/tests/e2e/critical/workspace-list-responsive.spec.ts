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
