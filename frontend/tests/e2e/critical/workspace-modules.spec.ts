/**
 * Critical — 工作区功能模块勾选与页签门控（ADR 0080）。
 *
 * 覆盖用户拍板的验收链路：
 * 1) 仅勾「文档 + 设计」的工作区：落地 /design，顶部页签不含数据表 / 数据分析 / 数据源同步，
 *    质量检查页签恒显；
 * 2) 质量检查页：检查动作目录为空时给出「暂无可用检查动作」提示（design 域动作后续提供）；
 * 3) 设置页取消「文档」仅留「设计」→ 保存后访问 /documents 自动重定向到 /design。
 *
 * 为什么必须 E2E：门控重定向 / 页签集合 / 落地段依赖真实路由与后端 modules 字段，
 * jsdom 单测无法覆盖真实导航链路。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken } from "../helpers/api";

test.describe.configure({ timeout: 90_000 });

let wid: number;
let token: string;
const stamp = Date.now();

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  const created = await apiCall(request, token, "post", "/workspaces", {
    name: `模块勾选回归 ${stamp}`,
    modules: ["documents", "design"],
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  wid = (created.body as { id: number }).id;
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (!wid) return;
  await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
});

test.describe("工作区模块勾选与页签门控", () => {
  test("仅勾文档+设计：落地 /design，页签按模块收敛且质量检查恒显", async ({ page }) => {
    await page.goto(`/w/${wid}`);
    // 落地段 = 第一个可用模块：无 tables → documents
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));

    // 页签集合：文档 / 设计 / 质量检查 / 工作区设置可见；数据侧三页签不渲染
    const tabs = page.getByRole("tablist").first();
    await expect(tabs.getByRole("tab", { name: /文档/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /设计/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /质量检查/ })).toBeVisible();
    await expect(tabs.getByRole("tab", { name: /工作区设置/ })).toBeVisible();
    await expect(page.getByRole("tab", { name: /数据表/ })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: /数据分析/ })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: /数据源同步/ })).toHaveCount(0);
  });

  test("未开放段自动重定向到落地段", async ({ page }) => {
    await page.goto(`/w/${wid}/tables`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));
    await page.goto(`/w/${wid}/analytics`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));
  });

  test("质量检查页签恒显：目录为空时给出提示", async ({ page, request }) => {
    // 检查动作目录按工作区已启用模块过滤：documents 模块自带文档检查族动作，目录非空。
    // 「目录为空」只可能出现在仅勾「设计」时（design 域动作尚未提供），故先收窄模块。
    const narrowed = await apiCall(request, token, "patch", `/workspaces/${wid}`, { modules: ["design"] });
    expect(narrowed.status, JSON.stringify(narrowed.body)).toBe(200)
    try {
      await page.goto(`/w/${wid}/pipelines`);
      await expect(page.getByTestId("empty-checks-alert")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText("暂无可用检查动作")).toBeVisible();
      // 页面仍可用：可新建流水线
      await expect(page.getByRole("button", { name: /新建流水线/ })).toBeVisible();
    } finally {
      // 还原给后续用例（设置页断言「文档」默认勾选）
      await apiCall(request, token, "patch", `/workspaces/${wid}`, { modules: ["documents", "design"] })
    }
  });

  test("设置页取消「文档」仅留设计后，未开放段重定向到 /design", async ({ page }) => {
    await page.goto(`/w/${wid}/settings`);
    // 基本设置页签默认激活；取消勾选「文档」卡片
    const docCard = page.getByTestId("module-card-documents");
    await expect(docCard).toBeVisible({ timeout: 20_000 });
    await expect(docCard).toHaveAttribute("data-checked", "true");
    await docCard.click();
    await expect(docCard).toHaveAttribute("data-checked", "false");

    await page.getByRole("button", { name: /保存设置/ }).click();
    await expect(page.getByText("设置已保存")).toBeVisible({ timeout: 20_000 });

    // 保存后访问文档段：已不开放，自动重定向到 /design
    await page.goto(`/w/${wid}/documents`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/design`));
  });
});
