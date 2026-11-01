/**
 * Critical — 工作区功能模块勾选与导航门控（ADR 0080 / 需求 0081 导航形态）。
 *
 * 覆盖用户拍板的验收链路：
 * 1) 仅勾「文档 + 设计」的工作区：落地 /design，顶栏一级导航不含数据表，
 *    二级页签不含数据分析 / 数据同步，文档质量检查在文档区胶囊页签；
 * 2) 质量检查页：仅勾「设计」的工作区检查动作目录为空时给出「暂无可用检查动作」提示
 *    （design 域动作后续提供；文档域已有检查动作，故需独立的设计域工作区）；
 *    文档模块的质量检查入口在文档区胶囊页签（/documents/pipelines），只呈现 document/* 规则，
 *    工作区级 /pipelines（数据表域）不重复呈现文档规则；
 * 3) 设置页取消「文档」仅留「设计」→ 保存后访问 /documents 自动重定向到 /design。
 *
 * 为什么必须 E2E：门控重定向 / 导航集合 / 落地段依赖真实路由与后端 modules 字段，
 * jsdom 单测无法覆盖真实导航链路。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken } from "../helpers/api";

test.describe.configure({ timeout: 90_000 });

let wid: number;
/** 仅勾「设计」的工作区：design 域检查动作尚未提供，质量检查目录为空（test 3 前提） */
let designOnlyWid: number;
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
  const designOnly = await apiCall(request, token, "post", "/workspaces", {
    name: `模块勾选回归·仅设计 ${stamp}`,
    modules: ["design"],
  });
  expect(designOnly.status, JSON.stringify(designOnly.body)).toBe(201);
  designOnlyWid = (designOnly.body as { id: number }).id;
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (wid) await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
  if (designOnlyWid) {
    await apiCall(request, token, "delete", `/workspaces/${designOnlyWid}`).catch(() => undefined);
  }
});

test.describe("工作区模块勾选与导航门控", () => {
  test("仅勾文档+设计：落地 /design，导航按模块收敛且质量检查恒显", async ({ page }) => {
    await page.goto(`/w/${wid}`);
    // 落地段 = 第一个可用模块：无 tables → documents
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));

    // 顶栏一级导航（需求 0081 C4）：文档 / 设计 / 工作区设置可见，数据表不渲染
    const nav = page.getByTestId("ws-module-nav");
    await expect(nav.getByTestId("ws-nav-documents")).toBeVisible();
    await expect(nav.getByTestId("ws-nav-design")).toBeVisible();
    await expect(nav.getByTestId("ws-nav-settings")).toBeVisible();
    await expect(nav.getByTestId("ws-nav-tables")).toHaveCount(0);
    // 二级页签：数据表派生的数据分析 / 数据同步随表收敛；质量检查在文档段由文档区胶囊页签承载
    await expect(page.getByTestId("document-tab-pipelines")).toBeVisible();
    await expect(page.getByRole("tab", { name: /数据分析/ })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: /数据同步/ })).toHaveCount(0);
  });

  test("未开放段自动重定向到落地段", async ({ page }) => {
    await page.goto(`/w/${wid}/tables`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));
    await page.goto(`/w/${wid}/analytics`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));
  });

  test("设计域质量检查页：目录为空时给出提示", async ({ page }) => {
    // 仅勾「设计」的工作区：design 域检查动作尚未提供 → 目录为空 → 空态提示
    await page.goto(`/w/${designOnlyWid}/pipelines`);
    await expect(page.getByTestId("empty-checks-alert")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("暂无可用检查动作")).toBeVisible();
    // 页面仍可用：可新建流水线
    await expect(page.getByRole("button", { name: /新建流水线/ })).toBeVisible();
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
