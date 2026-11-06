/** 文档查看态按需加载（ADR 0116 C6 / D7）—— @perf 观察期.
 *
 * 查看态不得请求含 CodeMirror / lezer 的 chunk，也不得出现编辑器 DOM；
 * 点击「编辑」后才下载编辑器并渲染 `.cm-editor`。
 *
 * chunk 归属从 `dist/.vite/chunk-modules.json` 读取（构建期产物），
 * hash 改名不影响断言。
 */

import { test, expect } from "../fixtures/auth"
import type { Page } from "@playwright/test"
import { existsSync, readFileSync } from "node:fs"
import path from "node:path"
import { publishedDocUrl } from "./docFixtures"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 含 CodeMirror / lezer 模块的 JS 资源文件名（不含 assets/ 前缀） */
function codeMirrorAssets(): string[] {
  const attribution = path.resolve(process.cwd(), "dist/.vite/chunk-modules.json")
  if (!existsSync(attribution)) return []
  const table = JSON.parse(readFileSync(attribution, "utf8")) as Record<
    string,
    Array<{ id: string; bytes: number }>
  >
  return Object.entries(table)
    .filter(([file]) => file.endsWith(".js"))
    .filter(([, modules]) =>
      modules.some((m) => m.id.includes("@codemirror/") || m.id.includes("@lezer/")),
    )
    .map(([file]) => file.replace(/^assets\//, ""))
}

async function openDoc(page: Page): Promise<void> {
  await page.goto(`/w/${WID}/documents`)
  const url = await publishedDocUrl(page, WID)
  await page.goto(url)

  // 已发布文档（草稿默认进编辑态，会在打开时就加载编辑器 chunk）
  const published = page
    .locator('.cn-list-item:has([data-testid^="doc-list-format-"])')
    .first()
  await expect(published, "未找到已发布文档，无法验证查看态").toBeVisible({ timeout: 15000 })
  await published.click()
  await page.waitForURL(/\/documents\/\d+/)
  await expect(page.getByTestId("doc-mode-switch")).toBeVisible({ timeout: 15000 })
}

test.describe("性能：文档查看态不加载编辑器（ADR 0116 C6）", () => {
  test("查看态无 CodeMirror chunk / 无编辑器 DOM，点击编辑后才加载", { tag: "@perf" }, async ({ page }, testInfo) => {
    test.skip(ANON.includes(testInfo.project.name), "anon 项目跳过")
    const assets = codeMirrorAssets()
    test.skip(assets.length === 0, "dist/.vite/chunk-modules.json 缺失或无 CodeMirror chunk，跳过网络断言")

    const loaded: string[] = []
    page.on("request", (request) => {
      const name = new URL(request.url()).pathname.split("/").pop() ?? ""
      if (assets.includes(name)) loaded.push(name)
    })

    await openDoc(page)
    expect(await page.locator(".cm-editor").count(), "查看态不应出现编辑器 DOM").toBe(0)
    expect(loaded, `查看态请求了编辑器 chunk：${loaded.join(", ")}`).toHaveLength(0)

    // 编辑入口：hover 预取 / 点击后必须能加载编辑器
    await page.getByRole("button", { name: "编辑" }).first().click()
    await expect(page.locator(".cm-editor").first()).toBeVisible({ timeout: 15000 })
    expect(loaded.length, "编辑态应请求 CodeMirror chunk").toBeGreaterThan(0)
  })
})
