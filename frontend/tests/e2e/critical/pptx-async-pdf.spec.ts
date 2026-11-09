/**
 * Critical — PPTX 服务端 PDF 衍生预览（ADR 0129 P2）.
 *
 * 覆盖阅读器的两条降级口径 + 一次成功切换：
 * 1) 转换器未配置（真实后端 409）：客户端预览容器保留，不出现「原件缺失」错误页；
 * 2) 路由拦截 202 → 200：先出现「正在生成高清预览」，就绪后原位替换为 PDF iframe；
 * 3) 路由拦截 422：保留客户端预览，出现「重试高清预览」，点击后 POST 重试并重新 GET。
 *
 * 为什么必须 E2E：渐进式替换依赖真实网络时序（202 轮询 → 200 原子替换）与
 * objectURL + iframe 挂载，jsdom 单测只能断言 mock 调用，覆盖不到真实渲染分支。
 *
 * 说明：用例导入的是按扩展名识别的占位 .pptx（真实转换在 e2e 环境不部署 worker），
 * 因此客户端渲染器自身可能提示「无法在线渲染」——本用例只断言阅读器容器存在、
 * 页面级错误页不出现，以及 PDF 链路的状态切换符合 ADR D10。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";
const PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
/** 占位原件：后端只按后缀识别原件族，不做 zip 解析 */
const PPTX_BYTES = Buffer.from("PK\x03\x04e2e-pptx-placeholder", "utf-8");
const PDF_BYTES = Buffer.from(
  "%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n",
  "utf-8",
);

let wid: number;
let token: string;
/** 本轮用例的标题都带时间戳，避免与历史数据同名 */
const stamp = Date.now();

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

/** 经真实导入接口落一份 .pptx 原件文档，返回 doc id（收尾由调用方删除） */
async function importPptx(page: Page, title: string): Promise<number> {
  const resp = await page.request.post(`/api/v1/workspaces/${wid}/documents/import/files`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      files: { name: `${title}.pptx`, mimeType: PPTX_MIME, buffer: PPTX_BYTES },
      status: "draft",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  const tree = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/tree`);
  expect(tree.status).toBe(200);
  const doc = flatten(tree.body as { items: TreeNode[] }).find((n) => !n.is_folder && n.title === title);
  expect(doc, "PPTX 导入后未落库").toBeTruthy();
  return doc!.id;
}

/** 拦截 PDF 端点：按调用顺序回放状态码，POST 单独计数 */
async function mockPdfRoute(
  page: Page,
  docId: number,
  plan: { gets: number[]; postStatus?: number },
) {
  const gets: number[] = [];
  const posts: number[] = [];
  await page.route(`**/api/v1/workspaces/${wid}/documents/${docId}/asset/pdf`, async (route) => {
    if (route.request().method() === "POST") {
      posts.push(1);
      await route.fulfill({
        status: plan.postStatus ?? 202,
        contentType: "application/json",
        body: JSON.stringify({ status: "queued", retry_after: 2 }),
      });
      return;
    }
    const index = gets.length;
    gets.push(index);
    const status = plan.gets[Math.min(index, plan.gets.length - 1)] ?? 200;
    if (status === 200) {
      await route.fulfill({ status, contentType: "application/pdf", body: PDF_BYTES });
      return;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      headers: { "Retry-After": "2" },
      body: JSON.stringify({ status: "queued", retry_after: 2 }),
    });
  });
  return { gets, posts };
}

test.describe("PPTX 服务端 PDF 预览", () => {
  test("转换器未配置：保留客户端预览，不出现原件错误页", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    const docId = await importPptx(page, `pdf 未配置 ${stamp}`);
    try {
      await page.goto(`/w/${wid}/documents/${docId}`);
      await expect(page.getByTestId("doc-asset-pptx")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("doc-asset-error")).toHaveCount(0);
      // 409（未启用）是静默降级：不弹重试按钮、不显示生成中提示
      await expect(page.getByTestId("doc-pptx-pdf-retry")).toHaveCount(0);
      await expect(page.getByTestId("doc-pptx-pdf-pending")).toHaveCount(0);
      await expect(page.getByTestId("doc-asset-pptx-pdf")).toHaveCount(0);
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(
        () => undefined,
      );
    }
  });

  test("202 → 200：先提示生成中，就绪后原位切换为 PDF iframe", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    const docId = await importPptx(page, `pdf 渐进 ${stamp}`);
    const mock = await mockPdfRoute(page, docId, { gets: [202, 200] });
    try {
      await page.goto(`/w/${wid}/documents/${docId}`);

      // 202 期间：客户端预览容器 + 右下角轻量提示，不阻断阅读
      await expect(page.getByTestId("doc-pptx-pdf-pending")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("doc-asset-pptx")).toBeVisible();

      // 下一轮轮询命中 200：原位替换为 PDF iframe
      await expect(page.getByTestId("doc-asset-pptx-pdf")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("doc-asset-pptx")).toHaveCount(0);
      await expect(page.getByTestId("doc-pptx-pdf-pending")).toHaveCount(0);
      await expect(page.getByTestId("doc-asset-error")).toHaveCount(0);
      expect(mock.gets.length).toBeGreaterThanOrEqual(2);
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(
        () => undefined,
      );
    }
  });

  test("422：保留客户端预览，点击重试后重新转换并切换 PDF", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    const docId = await importPptx(page, `pdf 重试 ${stamp}`);
    // 首次读取失败 → POST 重试 → 重新读取成功
    const mock = await mockPdfRoute(page, docId, { gets: [422, 200], postStatus: 202 });
    try {
      await page.goto(`/w/${wid}/documents/${docId}`);

      const retry = page.getByTestId("doc-pptx-pdf-retry");
      await expect(retry).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("doc-asset-pptx")).toBeVisible();
      await expect(page.getByTestId("doc-asset-error")).toHaveCount(0);

      await retry.click();
      // 重试后重新 GET：成功即切换 PDF，重试入口消失
      await expect(page.getByTestId("doc-asset-pptx-pdf")).toBeVisible({ timeout: 30_000 });
      await expect(retry).toHaveCount(0);
      expect(mock.posts.length).toBe(1);
      expect(mock.gets.length).toBeGreaterThanOrEqual(2);
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(
        () => undefined,
      );
    }
  });
});

interface TreeNode {
  id: number;
  title: string;
  is_folder: boolean;
  children?: TreeNode[];
}

function flatten(nodes: { items: TreeNode[] }): TreeNode[] {
  const out: TreeNode[] = [];
  const walk = (list: TreeNode[]) => {
    for (const node of list) {
      out.push(node);
      if (node.children?.length) walk(node.children);
    }
  };
  walk(nodes.items ?? []);
  return out;
}
