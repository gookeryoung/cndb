/** P0 — 排序功能 E2E：工作区表列表 + Grid 视图 Tab.
 *
 * 覆盖链路：
 *   1. API 调用 reorder 改变后端 order
 *   2. 前端列表正确按新顺序渲染
 *   3. 排序后的数据持久化（刷新后不变）
 *
 * 说明：dnd-kit 拖拽交互由组件库自身测试覆盖，
 *       本文件聚焦排序的业务逻辑正确性（后端存储 + 前端展示 + 持久化）.
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"

const ANON = ["setup", "chromium-anon"]
const WID = 1

/** 登录获取 token. */
async function getToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  })
  const body = await resp.json()
  return body.access_token
}

/** 通过 API 创建 N 张表，返回 id 数组（按创建顺序）. */
async function createTables(request: APIRequestContext, names: string[]): Promise<number[]> {
  const token = await getToken(request)
  const ids: number[] = []
  for (const name of names) {
    const resp = await request.post(`/api/v1/workspaces/${WID}/tables`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { name },
    })
    const body = await resp.json()
    ids.push(body.id)
  }
  return ids
}

/** 通过 API 删除表. */
async function deleteTables(request: APIRequestContext, ids: number[]) {
  const token = await getToken(request)
  for (const id of ids) {
    await request.delete(`/api/v1/workspaces/${WID}/tables/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  }
}

/** 通过 API 创建 N 个视图，返回 id 数组. */
async function createViews(
  request: APIRequestContext,
  tid: number,
  names: string[],
): Promise<number[]> {
  const token = await getToken(request)
  const ids: number[] = []
  for (const name of names) {
    const resp = await request.post(`/api/v1/workspaces/${WID}/tables/${tid}/views`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { name, view_type: "grid" },
    })
    const body = await resp.json()
    ids.push(body.id)
  }
  return ids
}

/** 查询当前工作区的表顺序. */
async function listTableOrder(request: APIRequestContext): Promise<number[]> {
  const token = await getToken(request)
  const resp = await request.get(`/api/v1/workspaces/${WID}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const tables = await resp.json()
  return tables.map((t: { id: number }) => t.id)
}

/** 查询指定表的视图顺序. */
async function listViewOrder(request: APIRequestContext, tid: number): Promise<number[]> {
  const token = await getToken(request)
  const resp = await request.get(`/api/v1/workspaces/${WID}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const views = await resp.json()
  return views.map((v: { id: number }) => v.id)
}

/** 调用 reorder API 改变表顺序 —— ids 为新的完整 id 列表. */
async function reorderTables(request: APIRequestContext, ids: (number | string)[]) {
  const token = await getToken(request)
  const resp = await request.post(`/api/v1/workspaces/${WID}/tables/reorder`, {
    headers: { Authorization: `Bearer ${token}` },
    data: ids,
  })
  if (!resp.ok()) {
    throw new Error(`reorder 失败: ${resp.status()} ${await resp.text()}`)
  }
}

/** 调用 reorder API 改变视图顺序. */
async function reorderViews(
  request: APIRequestContext,
  tid: number,
  ids: (number | string)[],
) {
  const token = await getToken(request)
  const resp = await request.post(`/api/v1/workspaces/${WID}/tables/${tid}/views/reorder`, {
    headers: { Authorization: `Bearer ${token}` },
    data: ids,
  })
  if (!resp.ok()) {
    throw new Error(`view reorder 失败: ${resp.status()} ${await resp.text()}`)
  }
}

// ── 测试：表排序 ──

test.describe("工作区表排序（reorder API + UI 同步）", () => {
  const NEW_TABLES = ["E2E 排序表-A", "E2E 排序表-B", "E2E 排序表-C"]
  let createdIds: number[] = []

  test.beforeAll(async ({ request }) => {
    createdIds = await createTables(request, NEW_TABLES)
  })

  test.afterAll(async ({ request }) => {
    await deleteTables(request, createdIds)
  })

  test("reorder API 改变表顺序后，后端持久化且前端列表同步", async ({
    page,
    request,
  }) => {
    // 1. 确认初始顺序
    const beforeOrder = await listTableOrder(request)
    const beforeIdx = createdIds.map((id) => beforeOrder.indexOf(id))
    expect(beforeIdx.every((i) => i >= 0)).toBeTruthy()

    // 2. 调用 reorder API：把 C 移到 A 前面
    //    构造新列表：在完整 beforeOrder 中，先移走 C，再插到 A 前
    const reordered = [...beforeOrder]
    const cId = createdIds[2] // C
    const aId = createdIds[0] // A
    reordered.splice(reordered.indexOf(cId), 1)
    reordered.splice(reordered.indexOf(aId), 0, cId)
    await reorderTables(request, reordered)

    // 3. 验证后端顺序已更新
    const afterOrder = await listTableOrder(request)
    const afterIdx = createdIds.map((id) => afterOrder.indexOf(id))
    expect(afterIdx[2]).toBeLessThan(afterIdx[0]) // C 在 A 前
    expect(afterIdx.every((i) => i >= 0)).toBeTruthy()

    // 4. 打开前端页面，验证列表渲染顺序正确
    await page.goto(`/w/${WID}/tables`)
    await page.waitForURL(/\/w\/\d+\/tables/)
    await expect(page.getByText(/E2E 排序表/).first()).toBeVisible()

    // 取表名在页面上出现的顺序
    // 第一列是拖拽图标（空文字），第二列才是表名，用 td:nth-child(2) 取
    const visibleNames = await page
      .locator("tr.ant-table-row")
      .filter({ hasText: /E2E 排序表/ })
      .evaluateAll((rows) =>
        rows.map((r) => {
          const tds = r.querySelectorAll("td")
          return (tds[1]?.textContent || "").trim()
        }),
      )
    // C 应该在 A 前
    const cPos = visibleNames.findIndex((n) => n.includes("C"))
    const aPos = visibleNames.findIndex((n) => n.includes("A"))
    expect(cPos).toBeGreaterThanOrEqual(0)
    expect(aPos).toBeGreaterThanOrEqual(0)
    expect(cPos).toBeLessThan(aPos)

    // 5. 刷新页面 — 验证排序持久化
    await page.reload()
    await page.waitForLoadState("networkidle")
    const namesAfterReload = await page
      .locator("tr.ant-table-row")
      .filter({ hasText: /E2E 排序表/ })
      .evaluateAll((rows) =>
        rows.map((r) => {
          const tds = r.querySelectorAll("td")
          return (tds[1]?.textContent || "").trim()
        }),
      )
    expect(namesAfterReload.findIndex((n) => n.includes("C"))).toBeLessThan(
      namesAfterReload.findIndex((n) => n.includes("A")),
    )
  })
})

// ── 测试：视图排序 ──

test.describe("Grid 视图排序（reorder API + UI 同步）", () => {
  const TABLE_NAME = "E2E 视图排序表"
  const NEW_VIEWS = ["Alpha 视图", "Beta 视图", "Gamma 视图"]
  let tableId: number | null = null
  let viewIds: number[] = []

  test.beforeAll(async ({ request }) => {
    const ids = await createTables(request, [TABLE_NAME])
    tableId = ids[0]
    viewIds = await createViews(request, tableId, NEW_VIEWS)
  })

  test.afterAll(async ({ request }) => {
    if (tableId != null) await deleteTables(request, [tableId])
  })

  test("reorder API 改变视图顺序后，后端持久化且前端 Segmented 同步", async ({
    page,
    request,
  }) => {
    if (tableId == null) throw new Error("表未创建")

    // 1. 先拿到初始顺序
    const beforeOrder = await listViewOrder(request, tableId)

    // 2. Gamma 移到 Alpha 前面
    const reordered = [...beforeOrder]
    const gammaId = viewIds[2]
    const alphaId = viewIds[0]
    reordered.splice(reordered.indexOf(gammaId), 1)
    reordered.splice(reordered.indexOf(alphaId), 0, gammaId)
    await reorderViews(request, tableId, reordered)

    // 3. 验证后端顺序
    const afterOrder = await listViewOrder(request, tableId)
    expect(afterOrder.indexOf(gammaId)).toBeLessThan(
      afterOrder.indexOf(alphaId),
    )

    // 4. 打开 Grid 页面，验证 Segmented Tab 渲染顺序
    await page.goto(`/w/${WID}/tables/${tableId}`)
    await page.waitForURL(/\/tables\/\d+/)
    await expect(page.getByText(/Alpha 视图|Gamma 视图/).first()).toBeVisible({
      timeout: 5000,
    })

    const tabTexts = await page
      .locator(".ant-segmented-item-label")
      .evaluateAll((labels) => labels.map((l) => (l.textContent || "").trim()))

    const gammaPos = tabTexts.findIndex((t) => t.includes("Gamma"))
    const alphaPos = tabTexts.findIndex((t) => t.includes("Alpha"))
    // 两个视图都在（可能有默认视图 "全部"）
    expect(gammaPos).toBeGreaterThanOrEqual(0)
    expect(alphaPos).toBeGreaterThanOrEqual(0)
    // Gamma 应该在 Alpha 前
    expect(gammaPos).toBeLessThan(alphaPos)
  })
})
