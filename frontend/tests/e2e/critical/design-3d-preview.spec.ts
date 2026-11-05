/** 设计模块 3D 预览 E2E（ADR 0079 P2）—— 新建设计 → 画布渲染 → 诊断回显 → 导出 STL.
 *
 * 走完整 UI 链路：列表页新建设计（法兰板模板）自动进入编辑器，headless Chromium
 * 经 SwiftShader 提供 WebGL2，真实渲染 PreviewCanvas 并断言画布挂载；输入坏 DSL
 * 验证诊断回显，修正后导出 STL 并校验二进制头（'cndb design stl'）。
 * 清理统一走 API，避免失败用例残留设计。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { readFileSync } from "node:fs"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

/** 删除失败不阻断用例结果（超时后 request context 可能已关闭） */
async function safeDeleteDesign(request: APIRequestContext, designId: number) {
  await request
    .delete(`/api/v1/workspaces/${WID}/designs/${designId}`, {
      headers: await authHeaders(request),
    })
    .catch(() => undefined)
}

test.describe("设计模块（结构 DSL）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("新建设计 → 画布渲染 → 诊断回显 → 导出 STL", async ({ page, request }) => {
    test.setTimeout(90_000)
    const stamp = Date.now()
    const title = `E2E 法兰板 ${stamp}`
    let designId = 0

    try {
      // 1) 列表页新建设计（示例模板）→ 创建后自动进入编辑器
      await page.goto(`/w/${WID}/design`)
      await page.getByRole("button", { name: /新建设计/ }).click()
      const modal = page.locator(".ant-modal")
      await modal.getByLabel("名称").fill(title)
      await modal.getByRole("button", { name: /创\s*建/ }).click()

      await expect(page.getByText(title).first()).toBeVisible({ timeout: 15_000 })
      await page.waitForURL(/\/w\/1\/design\/\d+/)
      designId = Number(page.url().match(/\/design\/(\d+)/)?.[1] ?? 0)

      // 2) 预览画布真实挂载（three WebGL2 + SwiftShader），模板编译通过
      await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 3) 输入坏 DSL → 防抖重编译 → 诊断回显行号与消息
      const editor = page.locator(".cm-content")
      await editor.click()
      await page.keyboard.press("ControlOrMeta+a")
      await page.keyboard.type("param width = 80\nbogus(size = [1, 2, 3])\n")
      await expect(page.getByText("第2行").first()).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText(/未知模块 'bogus'/)).toBeVisible()

      // 4) 修正为合法 DSL → 诊断消失、编译恢复通过
      await page.keyboard.press("ControlOrMeta+a")
      await page.keyboard.type("param width = 80\nbox(size = [width, 40, 12])\n")
      await expect(page.getByText("第2行").first()).toBeHidden({ timeout: 15_000 })
      await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 15_000 })

      // 5) 导出 STL：导出收进「更多」菜单（ADR 0103 D6）→ 二进制头为 'cndb design stl'
      // 文件名含中文设计名，Chromium suggestedFilename 不稳定（同 workspace-backup 用例），以内容为准则
      const downloadPromise = page.waitForEvent("download", { timeout: 30_000 })
      await page.getByRole("button", { name: "更多" }).click()
      await page.getByText("STL（二进制，3D 打印）").click()
      const download = await downloadPromise
      const buf = readFileSync(await download.path())
      expect(buf.subarray(0, 15).toString("latin1")).toBe("cndb design stl")
      // 80 字节头 + uint32 三角形数 + 每三角形 50 字节，非空模型三角形数 > 0
      expect(buf.length).toBeGreaterThan(84)
      expect(buf.readUInt32LE(80)).toBeGreaterThan(0)
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
