/** 数据源同步 E2E —— 工作区级「数据源同步」页签主链路.
 *
 * 覆盖：
 * - 页签进入 /w/:wid/datasource，任务列表渲染（可为空态）
 * - 新建同步任务 → 保存 → 列表出现该任务，且后端已落库
 * - 编辑抽屉回填已保存配置；删除清理
 *
 * 不在 E2E 里点「立即运行」：那会请求真实外部数据源（CI 不可控），
 * 运行链路（抓取 → 失效 → 落表 → 游标 → 留痕）由后端单测与接口测试覆盖。
 */

import { test, expect } from "../fixtures/auth"
import type { APIRequestContext } from "@playwright/test"
import { getAdminToken } from "../helpers/api"

const ANON = ["setup", "chromium-anon"]
const WID = 1

async function listJobs(request: APIRequestContext) {
  const token = await getAdminToken(request)
  const resp = await request.get(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(resp.ok()).toBeTruthy()
  return (await resp.json()) as { total: number; jobs: Array<{ id: number; name: string }> }
}

async function deleteJob(request: APIRequestContext, id: number) {
  const token = await getAdminToken(request)
  await request.delete(`/api/v1/workspaces/${WID}/datasource/sync-jobs/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

async function gotoDatasource(page: any) {
  await page.goto(`/w/${WID}/datasource`)
  await expect(page.getByTestId("datasource-page")).toBeVisible({ timeout: 10_000 })
}

test.describe("数据源同步", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过")
    void page
  })

  test("工作区页签可进入数据源同步页", async ({ page }) => {
    await gotoDatasource(page)
    await expect(page.getByRole("heading", { name: "数据源同步" })).toBeVisible()
    await expect(page.getByTestId("datasource-create-btn")).toBeVisible()
  })

  test("新建同步任务 → 保存 → 列表出现且落库", async ({ page, request }) => {
    const name = `E2E 同步任务 ${Date.now()}`
    await gotoDatasource(page)

    await page.getByTestId("datasource-create-btn").click()
    const drawer = page.locator(".ant-drawer-section")
    await expect(drawer.getByTestId("datasource-name-input")).toBeVisible()

    await drawer.getByTestId("datasource-name-input").fill(name)
    await drawer.getByTestId("datasource-url-template").fill("https://api.example.com/weather?city=北京")
    await drawer.getByTestId("datasource-save-btn").click()

    // 保存成功提示里也会出现任务名，列表断言取首个可见匹配
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 15_000 })

    const listing = await listJobs(request)
    const created = listing.jobs.find(job => job.name === name)
    expect(created, "新建的任务应出现在后端列表中").toBeTruthy()

    if (created) await deleteJob(request, created.id)
  })

  test("编辑抽屉回填已保存配置", async ({ page, request }) => {
    const name = `E2E 回填 ${Date.now()}`
    const token = await getAdminToken(request)
    const created = await request.post(`/api/v1/workspaces/${WID}/datasource/sync-jobs`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        name,
        provider: "http_json",
        request_spec: { url_template: "https://api.example.com/news?page={page}", paging: { mode: "page", page_size: 20 } },
        entrant_keys: [],
        match_keys: [],
        cursor: { strategy: "none" },
        schedule: { mode: "manual" },
        enabled: true,
      },
    })
    expect(created.ok()).toBeTruthy()
    const job = (await created.json()) as { id: number }

    try {
      await gotoDatasource(page)
      await page.getByRole("button", { name: `编辑 ${name}` }).click()
      const drawer = page.locator(".ant-drawer-section")
      await expect(drawer.getByTestId("datasource-name-input")).toHaveValue(name)
      await expect(drawer.getByTestId("datasource-url-template")).toHaveValue(
        "https://api.example.com/news?page={page}",
      )
    } finally {
      await deleteJob(request, job.id)
    }
  })

  test("空 URL 模板不可保存（前端校验拦截）", async ({ page }) => {
    await gotoDatasource(page)
    await page.getByTestId("datasource-create-btn").click()
    const drawer = page.locator(".ant-drawer-section")

    await drawer.getByTestId("datasource-name-input").fill("E2E 校验")
    await drawer.getByTestId("datasource-save-btn").click()

    await expect(drawer.getByText("请输入 http/https URL 模板")).toBeVisible()
  })
})
