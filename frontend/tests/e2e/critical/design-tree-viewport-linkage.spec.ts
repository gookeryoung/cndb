/** 树↔视口联动 E2E（ADR 0103 P2：C7 / D7 / D8）—— 点击侧栏大纲节点 → 视口高亮实体并渐隐.
 *
 * 链路：经 API 建一份带模块 / 布尔分组的设计 → 侧栏展开装配树 → 点击零件节点
 * → 编辑器带 `?line=` 定位源行 + 视口按大纲归属收集 node_index 集合高亮 3s 渐隐。
 * 高亮态在 canvas 内部无法外部观测，故 PreviewCanvas 把当前高亮实体数写到宿主
 * `data-highlight-nodes` 属性上（真实渲染 + 真实联动，只是断言通道换成 DOM）。
 *
 * IR v4 旧快照的降级路径（无 node_index 不高亮）由 `designOutline.test.ts` 与
 * `DesignEditorPage.test.tsx` 覆盖：e2e 无法在无数据库写权限下构造 v4 快照。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext, Page } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 源行：param 1 / module 2 / difference 3 / box 4 / translate 5 / cyl 6 / 闭合 7-9 / 实例 10 */
const CONTENT = [
  "param width = 80",
  "module plate(w, t) {",
  "  difference {",
  "    box(size = [w, 40, t])",
  "    translate([w / 2, 20, -1]) {",
  "      cyl(d = 8, h = t + 2)",
  "    }",
  "  }",
  "}",
  "plate(width, 12)",
].join("\n")

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request)
  return { Authorization: `Bearer ${token}` }
}

async function createDesign(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post(`/api/v1/workspaces/${WID}/designs`, {
    headers: await authHeaders(request),
    data: { title, description: "E2E 树视口联动", content: CONTENT },
  })
  expect(resp.status()).toBe(201)
  return ((await resp.json()) as { id: number }).id
}

async function safeDeleteDesign(request: APIRequestContext, designId: number) {
  await request
    .delete(`/api/v1/workspaces/${WID}/designs/${designId}`, {
      headers: await authHeaders(request),
    })
    .catch(() => undefined)
}

/** 点击树节点所在行的展开箭头（testid 在标题内，需回溯到 treenode） */
async function expandNode(page: Page, testId: string) {
  await page
    .locator(".ant-tree-treenode")
    .filter({ has: page.getByTestId(testId) })
    .locator(".ant-tree-switcher")
    .click()
  await page.waitForTimeout(650)
}

test.describe("树↔视口联动（0103 P2）", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("点击侧栏零件节点 → 编辑器定位源行 + 视口高亮并渐隐", async ({ page, request }) => {
    test.setTimeout(120_000)
    const title = `E2E 联动 ${Date.now()}`
    let designId = 0

    try {
      designId = await createDesign(request, title)

      // 1) 侧栏展开装配树：设计 → 组件 → 布尔分组 → 零件
      await page.goto(`/w/${WID}/design`)
      await expect(page.getByTestId(`design-node-${designId}`)).toBeVisible({ timeout: 15_000 })
      await expandNode(page, `design-node-${designId}`)
      await expandNode(page, `design-outline-node-design-${designId}-0`)
      await expandNode(page, `design-outline-node-design-${designId}-0-0`)
      await expect(page.getByText("零件 · 第 4 行")).toBeVisible({ timeout: 15_000 })

      // 2) 点击零件节点 → 编辑器带 ?line=4，视口就绪
      await page.getByText("零件 · 第 4 行").click()
      await page.waitForURL(new RegExp(`/w/1/design/${designId}\\?line=4`))
      const host = page.getByTestId("design-preview-host")
      await expect(host).toBeVisible({ timeout: 30_000 })

      // 3) 高亮出现（IR v5 的 node_index → 顶层节点下标集合）
      await expect(host).toHaveAttribute("data-highlight-nodes", /\d+/, { timeout: 20_000 })

      // 4) 3s 渐隐后高亮属性清除（D8：2.4s 常亮 + 0.6s 淡出）
      await expect(host).not.toHaveAttribute("data-highlight-nodes", /\d+/, { timeout: 20_000 })

      // 5) 反向定位：侧栏同步选中该零件节点（C1② / D9）
      const selected = page.locator(".ant-tree-treenode-selected")
      await expect(selected).toContainText("立方体", { timeout: 15_000 })
    } finally {
      if (designId) await safeDeleteDesign(request, designId)
    }
  })
})
