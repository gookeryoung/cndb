/** 全站字体口径 E2E（ADR 0031）.
 *
 * 覆盖：
 *  1. 默认不加粗：body 计算字重 400，表格正文单元格 400
 *  2. 全局加粗开关可切到 600 并在刷新后保持（localStorage 持久化），随后复原
 *  3. 展示字体 Outfit 已加载并作用于顶栏品牌字
 *  4. 等宽字体 JetBrains Mono 已加载
 */

import { test, expect } from "../fixtures/auth"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 打开个人设置 → 主题分页 */
const openThemeTab = async (page: any) => {
  await page.getByTestId("user-menu-trigger").click()
  await page.getByRole("menuitem", { name: "个人设置" }).click()
  await page.getByRole("tab", { name: "主题" }).click()
}

test.describe("字体口径", () => {
  test("默认正文为 400 且全站不加粗", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    expect(
      await page.evaluate(() => getComputedStyle(document.body).fontWeight),
    ).toBe("400")

    // 表格正文单元格同为 400，未被 body 继承抬重
    const cellWeight = await page.evaluate(() => {
      const cell = document.querySelector(".ant-table-tbody td")
      return cell ? getComputedStyle(cell).fontWeight : null
    })
    if (cellWeight) expect(cellWeight).toBe("400")
  })

  test("全局加粗开关切换后刷新仍保持", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    await openThemeTab(page)
    const boldSwitch = page.getByTestId("font-bold-switch")
    await expect(boldSwitch).not.toBeChecked()
    await boldSwitch.click()
    await expect
      .poll(() => page.evaluate(() => getComputedStyle(document.body).fontWeight))
      .toBe("600")

    await page.reload()
    await page.waitForURL(/\/tables$/)
    expect(
      await page.evaluate(() => getComputedStyle(document.body).fontWeight),
    ).toBe("600")

    // 复原，避免污染后续用例与本地存储
    await openThemeTab(page)
    await page.getByTestId("font-bold-switch").click()
    await expect
      .poll(() => page.evaluate(() => getComputedStyle(document.body).fontWeight))
      .toBe("400")
  })

  test("展示字体 Outfit 已加载并作用于品牌字", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    const brandFamily = await page.evaluate(() => {
      const el = document.querySelector(".cn-brand-word")
      return el ? getComputedStyle(el).fontFamily : null
    })
    // 窄视口隐藏品牌字，此时只校验字体可用性
    if (brandFamily) expect(brandFamily).toContain("Outfit")

    // 字体按需加载，先显式 load 再 check（未加载时 check 恒为 false）
    const outfitReady = await page.evaluate(async () => {
      await document.fonts.load("700 16px Outfit")
      return document.fonts.check("700 16px Outfit")
    })
    expect(outfitReady).toBe(true)
  })

  test("等宽字体 JetBrains Mono 已加载", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/tables$/)

    const monoReady = await page.evaluate(async () => {
      await document.fonts.load("400 13px 'JetBrains Mono'")
      return document.fonts.check("400 13px 'JetBrains Mono'")
    })
    expect(monoReady).toBe(true)
  })
})
