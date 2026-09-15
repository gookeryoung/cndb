/* eslint-disable react-hooks/rules-of-hooks */
/** Playwright fixture：手动注入已登录 storage state + 辅助清理函数.
 *
 * 根因：Playwright 1.63.0 的 `projects[].storageState` 在 Puppeteer Chrome
 * 组合下不生效（localStorage 始终为空，AuthProvider 的 auth/me 调用失败后清
 * 空 token，ProtectedRoute 重定向到 /login）。
 *
 * 方案：通过 fixture 手动调用 browser.newContext({ storageState }) 注入登录态，
 * 彻底绕过 config 层 storageState 不生效的问题。
 *
 * 使用：
 *   import { test, expect } from "@/e2e/fixtures/auth"
 *   test("my test", async ({ page }) => { ... })
 */

import { test as base, expect } from "@playwright/test"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { existsSync, readFileSync } from "node:fs"

const _fixtureDir = path.dirname(fileURLToPath(import.meta.url))
// fixtures/auth.ts → e2e → tests → frontend/.auth/state.json（向上 3 级）
const AUTH_STATE_PATH = path.resolve(_fixtureDir, "../../../.auth/state.json")

/** 从 storageState 文件中提取 access token，用于直接调 API 做清理. */
function _readAuthToken(): string | null {
  if (!existsSync(AUTH_STATE_PATH)) return null
  try {
    const raw = readFileSync(AUTH_STATE_PATH, "utf-8")
    const state = JSON.parse(raw)
    return state?.origins?.[0]?.localStorage?.find(
      (it: { name: string }) => it.name === "cndb_access_token",
    )?.value ?? null
  } catch {
    return null
  }
}

/** 清空指定表的所有成员（除 owner 外），用于 E2E 测试间隔离. */
async function cleanTableMembers(wid: number, tid: number, baseURL = "http://127.0.0.1:8000") {
  const token = _readAuthToken()
  if (!token) return
  const res = await fetch(`${baseURL}/api/v1/workspaces/${wid}/tables/${tid}/members`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const members: Array<{ user_id: number }> = await res.json()
  for (const m of members) {
    await fetch(`${baseURL}/api/v1/workspaces/${wid}/tables/${tid}/members/${m.user_id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    })
  }
}

export const test = base.extend({
  page: async ({ browser }, use) => {
    const context = await browser.newContext({ storageState: AUTH_STATE_PATH })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },
})

/** 在 test 内部调用，等价于 beforeEach。 */
export const beforeEachCleanTable = (wid: number, tid: number) => {
  test.beforeEach(async () => {
    await cleanTableMembers(wid, tid)
  })
}

export { expect, cleanTableMembers }
